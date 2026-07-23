"""
test_api_surface.py
-------------------
§3.7 API/server abuse-handling audit. Table-driven sweep of the whole localhost
FastAPI surface (server.py) + the separate LAN listener (lan_sync.py, B-11).

Scope: this file asserts ABUSE handling, not happy paths -- those already live in
test_server.py / test_capture_idempotency.py / test_lan_sync.py. Per route:
missing secret, wrong secret, malformed JSON, wrong content-type, oversized
payload, concurrent double-submit. Per LAN route: nonce replay/expiry, oversized
blob, garbage ciphertext.

Oracle for every case (see `_assert_clean_4xx`): never a 500-with-traceback,
never a leak of the secret / a filesystem path / internal exception text, and
never a partial vault write.

Fixtures reuse the established patterns rather than inventing a competing fake:
  * GUI  -- `TestClient(server.app)` + tmp config/vault, mirroring
            test_server.py:_client_config. `_GUI_SECRET` is patched on the module
            (not the env) because `_require_secret` reads that global at call
            time -- no importlib.reload needed, and monkeypatch restores it so the
            rest of the suite still runs with the guard disabled as it expects.
  * LAN  -- `_lan_client` is test_lan_sync.py:_client verbatim in shape (same
            monkeypatched seams, same per-test `_nonces.clear()`).
Every test runs against tmp_path; nothing touches the real vault or config.toml.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent))
# SRV-01: server._require_secret now fails CLOSED, so an empty OMNI_GUI_SECRET
# 403s every route instead of disabling auth. Every server test module uses this
# SAME literal on purpose: the env var is process-global and pytest imports all
# modules before running any test, so differing values would make the suite
# order-dependent.
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET
_AUTH = {"X-Omni-Secret": GUI_SECRET}


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import lan_crypto
import lan_sync
import provisional_store as ps
import server

SECRET = "surface-audit-secret-1234567890"
WRONG_SECRET = "surface-audit-WRONG-0987654321"
GOOD_HEADERS = {"X-Omni-Secret": SECRET}
WRONG_HEADERS = {"X-Omni-Secret": WRONG_SECRET}

# /health is the ONE deliberately-unauthenticated route. Documented in-line at
# server.py:935 ("Unauthenticated liveness probe: used by launch.ps1 to detect
# readiness. Returns only booleans, so it leaks nothing sensitive even with a
# secret set.") and in the module header at server.py:66-67. Any OTHER route
# reaching a handler without the guard is a HIGH finding.
UNAUTH_BY_DESIGN = {"/health"}


# ============================================================================
# Oracles
# ============================================================================

# Substrings that must never reach a client: Python traceback furniture and
# interpreter/library paths. A response carrying any of these means an unhandled
# exception was rendered into the body instead of a clean, modelled error.
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last)",
    'File "',
    ", line ",
    "site-packages",
    "  File ",
)


def _assert_no_leak(resp, vault: Path | None = None) -> None:
    """No traceback, no secret, no server-side filesystem path in the body."""
    text = resp.text
    for marker in _TRACEBACK_MARKERS:
        assert marker not in text, f"traceback/path marker {marker!r} leaked in body: {text[:400]!r}"
    assert SECRET not in text, f"X-Omni-Secret leaked in body: {text[:400]!r}"
    assert WRONG_SECRET not in text, f"submitted secret echoed in body: {text[:400]!r}"
    if vault is not None:
        # The vault root is a server-side absolute path -- a client that failed
        # auth or sent garbage must never learn it.
        assert str(vault) not in text, f"vault path leaked in body: {text[:400]!r}"
        assert str(vault).replace("\\", "/") not in text


def _assert_clean_4xx(resp, vault: Path | None = None) -> None:
    """The core oracle: a modelled 4xx, never a 5xx, never a leak."""
    assert 400 <= resp.status_code < 500, (
        f"expected a clean 4xx, got {resp.status_code}: {resp.text[:400]!r}"
    )
    _assert_no_leak(resp, vault)


def _assert_no_crash(resp, vault: Path | None = None) -> None:
    """Weaker oracle for oversized payloads: any non-5xx outcome is acceptable
    (a local editor legitimately accepts large bodies) -- it must simply not
    fall over or leak."""
    assert resp.status_code < 500, (
        f"server crashed with {resp.status_code}: {resp.text[:400]!r}"
    )
    _assert_no_leak(resp, vault)


def _vault_notes(vault: Path) -> set[str]:
    """Every file under the vault -- the partial-write oracle.

    Strict on purpose: used where the handler must not run at all (rejected auth,
    malformed body), so not even a derived index may be touched.
    """
    return {str(p.relative_to(vault)) for p in vault.rglob("*") if p.is_file()}


def _vault_md_notes(vault: Path) -> set[str]:
    """Vault NOTES only -- for handlers that legitimately run and may touch a
    derived index (.omni_capture/captures.db et al) while still being forbidden
    from writing a note. Derived caches are rebuildable and never authoritative
    over the .md files (CLAUDE.md: "files are the source of truth")."""
    return {str(p.relative_to(vault)) for p in vault.rglob("*.md") if p.is_file()}


# ============================================================================
# GUI fixture -- tmp vault + tmp config, guard ENABLED
# ============================================================================

@pytest.fixture
def gui(tmp_path, monkeypatch):
    """(client, vault) with the secret enforced and every filesystem seam in tmp_path.

    `_GUI_SECRET`, `CONFIG_PATH` and `_get_vault_root` are the three module
    globals the routes read at call time; patching them is sufficient to keep the
    real `~/second-thought-storage` vault and the repo's config.toml untouched.
    """
    vault = tmp_path / "vault"
    (vault / "Notes").mkdir(parents=True)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[vault]\nroot = "' + str(vault).replace("\\", "/") + '"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(server, "reload_config", lambda *a, **k: None)
    # Module-global caches are process-wide; isolate them per test.
    server._capture_results.clear()
    server._recent_request_hashes.clear()
    return TestClient(server.app), vault


# ============================================================================
# The route table -- (method, path, request kwargs)
#
# Bodies/params are minimal-but-schema-valid so that an auth rejection is
# unambiguously the guard talking (403) and not a 422 from body validation
# shadowing it. For the auth cases the handler never runs, so these never
# touch the vault regardless.
# ============================================================================

GUI_ROUTES: list[tuple[str, str, dict]] = [
    ("POST",   "/capture",                        {"json": {"content_type": "text", "content": "x"}}),
    ("POST",   "/share",                          {"json": {"url": "https://example.com/a"}}),
    ("GET",    "/ollama/reachable",               {}),
    ("GET",    "/sync/status",                    {}),
    ("POST",   "/sync/run",                       {}),
    ("GET",    "/drive/auth/status",              {}),
    ("POST",   "/drive/auth/connect",             {}),
    ("POST",   "/drive/auth/disconnect",          {}),
    ("GET",    "/lan/device-id",                  {}),
    ("GET",    "/config",                         {}),
    ("PATCH",  "/config",                         {"json": {"llm_scrutiny": "strict"}}),
    ("POST",   "/look/chat",                      {"json": {"question": "q"}}),
    ("POST",   "/vault/sync-index",               {}),
    ("GET",    "/provisional",                    {}),
    ("GET",    "/inbox",                          {}),
    ("POST",   "/inbox/n1/approve",               {"json": {"target_category": "Notes"}}),
    ("GET",    "/inbox/n1/suggest-categories",    {}),
    ("DELETE", "/inbox/n1",                       {}),
    ("GET",    "/reminders",                      {}),
    ("POST",   "/reminders",                      {"json": {"note_path": "Notes/a.md", "label": "l",
                                                            "when_iso": "2030-01-01T00:00:00"}}),
    ("DELETE", "/reminders/1",                    {}),
    ("GET",    "/note",                           {"params": {"path": "Notes/a.md"}}),
    ("PUT",    "/note",                           {"json": {"path": "Notes/a.md", "body": "b",
                                                            "expected_mtime": 0.0}}),
    ("POST",   "/note/attachment",                {"json": {"path": "Notes/a.md", "filename": "f.png",
                                                            "data_b64": "AA==", "expected_mtime": 0.0}}),
    ("GET",    "/note/attachment",                {"params": {"path": "Notes/a.md", "filename": "f.png"}}),
    ("GET",    "/note/history",                   {"params": {"path": "Notes/a.md"}}),
    ("GET",    "/note/history/revision",          {"params": {"path": "Notes/a.md", "revision_id": "r1"}}),
    ("GET",    "/note/conflict",                  {"params": {"path": "Notes/a.md"}}),
    ("POST",   "/note/conflict/resolve",          {"json": {"path": "Notes/a.md",
                                                            "conflict_path": "Notes/a (conflict).md",
                                                            "action": "both"}}),
]

# The subset that accepts a JSON body -- malformed-JSON / content-type abuse only
# applies where a body is parsed at all.
BODY_ROUTES = [(m, p, kw) for m, p, kw in GUI_ROUTES if "json" in kw]

_ID = lambda m, p: f"{m} {p}"


# ============================================================================
# 1. Auth coverage -- the guard must be on EVERY route
# ============================================================================

def _dependency_calls(dependant) -> set:
    """Flatten a route's dependency tree to the set of callables it will run.

    Router-level `dependencies=[Depends(_require_secret)]` (how jobs.router and
    vault_admin.router are mounted at server.py:409-410) is merged by FastAPI
    into each route's own dependant, so this sees both mounting styles.
    """
    calls = set()
    for dep in dependant.dependencies:
        if dep.call is not None:
            calls.add(dep.call)
        calls |= _dependency_calls(dep)
    return calls


def test_every_route_depends_on_require_secret():
    """Reflection over the live app: the strongest form of the check -- it also
    catches any route added later that forgets the guard, including the
    split-out jobs.py / vault_admin.py routers."""
    unguarded = []
    for route in server.app.routes:
        if not isinstance(route, APIRoute):
            continue          # Starlette's /openapi.json, /docs, /redoc
        if route.path in UNAUTH_BY_DESIGN:
            continue
        if server._require_secret not in _dependency_calls(route.dependant):
            unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert unguarded == [], (
        "routes reachable without X-Omni-Secret (HIGH -- localhost API auth lock): "
        + ", ".join(unguarded)
    )


def test_route_table_matches_live_app():
    """Guards this file against drift: if a route is added/renamed in server.py
    and not mirrored into GUI_ROUTES, the abuse sweep below would silently stop
    covering it."""
    live = {
        (method, route.path)
        for route in server.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method != "HEAD" and route.path not in UNAUTH_BY_DESIGN
    }
    # Normalise the table's concrete ids back to their path templates.
    tabled = set()
    for method, path, _ in GUI_ROUTES:
        path = path.replace("/n1", "/{note_id}").replace("/reminders/1", "/reminders/{reminder_id}")
        tabled.add((method, path))
    missing = live - tabled
    # jobs.py / vault_admin.py routers are covered by the reflection test above,
    # not by this hand table -- exclude them here rather than duplicating them.
    router_paths = {p for _, p in live if p.startswith(("/jobs", "/vault/"))} - {"/vault/sync-index"}
    missing = {(m, p) for m, p in missing if p not in router_paths}
    assert missing == set(), f"routes in server.app not covered by GUI_ROUTES: {sorted(missing)}"


@pytest.mark.parametrize("method,path,kwargs", GUI_ROUTES, ids=[_ID(m, p) for m, p, _ in GUI_ROUTES])
def test_missing_secret_is_rejected(gui, method, path, kwargs):
    """Abuse case 1: no X-Omni-Secret header at all -> 401/403, handler never runs."""
    client, vault = gui
    before = _vault_notes(vault)
    resp = client.request(method, path, **kwargs)
    assert resp.status_code in (401, 403), (
        f"{method} {path} reached a handler without X-Omni-Secret "
        f"(got {resp.status_code}) -- HIGH, violates the localhost-auth lock"
    )
    _assert_clean_4xx(resp, vault)
    assert _vault_notes(vault) == before, "unauthenticated request wrote to the vault"


@pytest.mark.parametrize("method,path,kwargs", GUI_ROUTES, ids=[_ID(m, p) for m, p, _ in GUI_ROUTES])
def test_wrong_secret_is_rejected(gui, method, path, kwargs):
    """Abuse case 2: a wrong X-Omni-Secret -> 401/403, handler never runs."""
    client, vault = gui
    before = _vault_notes(vault)
    resp = client.request(method, path, headers=WRONG_HEADERS, **kwargs)
    assert resp.status_code in (401, 403), (
        f"{method} {path} accepted a WRONG X-Omni-Secret (got {resp.status_code}) -- HIGH"
    )
    _assert_clean_4xx(resp, vault)
    assert _vault_notes(vault) == before, "wrong-secret request wrote to the vault"


def test_empty_secret_header_is_rejected(gui):
    """`hmac.compare_digest(x_omni_secret or "", _GUI_SECRET)` -- an empty header
    must not degrade to a match (the same class of bug lan_sync guards against
    explicitly at lan_sync.py:119-128)."""
    client, vault = gui
    resp = client.get("/config", headers={"X-Omni-Secret": ""})
    assert resp.status_code in (401, 403)
    _assert_clean_4xx(resp, vault)


# ============================================================================
# 2. /health -- unauthenticated by design; must leak ONLY booleans
# ============================================================================

def test_health_is_unauthenticated_by_design(gui):
    """Documented at server.py:935. Reachable with the guard ENABLED and no header."""
    client, _ = gui
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers=WRONG_HEADERS).status_code == 200


def test_health_leaks_only_booleans(gui):
    """The justification for /health being unauthenticated is 'returns only
    booleans, so it leaks nothing sensitive'. Assert that literally: every leaf
    value in the payload must be a bool or None -- no paths, no counts, no
    strings, no error text."""
    client, vault = gui
    body = client.get("/health").json()

    leaves: list[tuple[str, object]] = []

    def _walk(node, trail: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{trail}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{trail}[{i}]")
        else:
            leaves.append((trail, node))

    _walk(body, "health")
    non_bool = [(t, v) for t, v in leaves if not isinstance(v, bool) and v is not None]
    assert non_bool == [], (
        "/health is unauthenticated on the documented grounds that it returns "
        f"only booleans -- these leaves are not booleans: {non_bool}"
    )
    _assert_no_leak(client.get("/health"), vault)


# ============================================================================
# 3. Malformed JSON -> clean 4xx, no stack trace
# ============================================================================

@pytest.mark.parametrize("method,path,kwargs", BODY_ROUTES, ids=[_ID(m, p) for m, p, _ in BODY_ROUTES])
def test_malformed_json_is_clean_4xx(gui, method, path, kwargs):
    """Abuse case 3. Sent WITH a valid secret so the guard isn't what rejects it --
    this exercises the body parser. Truncated JSON must never reach a handler."""
    client, vault = gui
    before = _vault_notes(vault)
    resp = client.request(
        method, path,
        headers={**GOOD_HEADERS, "Content-Type": "application/json"},
        content=b'{"content_type": "text", "content": "unterminated',
    )
    _assert_clean_4xx(resp, vault)
    assert _vault_notes(vault) == before, "malformed JSON produced a partial vault write"


@pytest.mark.parametrize("method,path,kwargs", BODY_ROUTES, ids=[_ID(m, p) for m, p, _ in BODY_ROUTES])
def test_wrong_content_type_is_clean_4xx(gui, method, path, kwargs):
    """Abuse case 4. A non-JSON content-type carrying a non-JSON body.

    (FastAPI parses on body shape rather than strictly on the header, so a
    text/plain body containing valid JSON is deliberately NOT the test here --
    that would exercise the handler, not the rejection path.)
    """
    client, vault = gui
    before = _vault_notes(vault)
    resp = client.request(
        method, path,
        headers={**GOOD_HEADERS, "Content-Type": "text/plain"},
        content=b"this is not json at all",
    )
    _assert_clean_4xx(resp, vault)
    assert _vault_notes(vault) == before


@pytest.mark.parametrize("method,path,kwargs", BODY_ROUTES, ids=[_ID(m, p) for m, p, _ in BODY_ROUTES])
def test_wrong_types_in_json_are_clean_4xx(gui, method, path, kwargs):
    """Schema-valid JSON shape, wrong value types -> pydantic 422, never a 500
    from the handler dereferencing a str as an int etc."""
    client, vault = gui
    before = _vault_notes(vault)
    resp = client.request(
        method, path,
        headers=GOOD_HEADERS,
        json={k: [{"nested": ["wrong", "types"]}] for k in kwargs["json"]},
    )
    _assert_clean_4xx(resp, vault)
    assert _vault_notes(vault) == before


# ============================================================================
# 4. Oversized payloads -> no crash, no unbounded buffering
# ============================================================================

_BIG = "A" * (5 * 1024 * 1024)   # 5 MB


def _fake_pipeline(counter: dict):
    """Stand-in for _run_pipeline_blocking, same queue protocol as
    test_capture_idempotency.py:_fake_pipeline_factory -- no LLM, no vault write."""
    def _fake(content_type, content, q, loop, run_id=None):
        counter["n"] += 1
        counter.setdefault("sizes", []).append(len(content))
        loop.call_soon_threadsafe(q.put_nowait, {"event": "done", "path": "V/x.md", "category": "Notes"})
        loop.call_soon_threadsafe(q.put_nowait, None)
    return _fake


def test_oversized_capture_does_not_crash(gui):
    """Abuse case 5 on the highest-volume route."""
    client, vault = gui
    counter = {"n": 0}
    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline(counter)):
        resp = client.post("/capture", headers=GOOD_HEADERS,
                           json={"content_type": "text", "content": _BIG})
    _assert_no_crash(resp, vault)


def test_oversized_share_does_not_crash(gui):
    client, vault = gui
    counter = {"n": 0}
    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline(counter)):
        resp = client.post("/share", headers=GOOD_HEADERS,
                           json={"url": "https://example.com/a", "selection": _BIG})
    _assert_no_crash(resp, vault)


def test_oversized_note_body_does_not_crash(gui):
    """PUT /note against a real (tmp) note -- either it writes or it cleanly
    refuses, but it must not 500 and must not leave a half-written file."""
    client, vault = gui
    note = vault / "Notes" / "big.md"
    note.write_text("---\nid: big\norigin: note\n---\nsmall\n", encoding="utf-8", newline="")
    mtime = note.stat().st_mtime
    resp = client.put("/note", headers=GOOD_HEADERS,
                      json={"path": "Notes/big.md", "body": _BIG, "expected_mtime": mtime})
    _assert_no_crash(resp, vault)
    # Frontmatter survives whatever the outcome was (body-sacred inverse: the
    # machine-owned header must never be truncated by an oversized body write).
    assert note.read_text(encoding="utf-8").startswith("---\nid: big\n")


def test_oversized_config_patch_does_not_crash(gui):
    client, vault = gui
    resp = client.patch("/config", headers=GOOD_HEADERS, json={"chat_system_prompt": _BIG})
    _assert_no_crash(resp, vault)


def test_oversized_query_param_does_not_crash(gui):
    """Oversized data on a GET's query string rather than a body.

    Capped at 50k: httpx refuses to build a URL over MAX_URL_LENGTH (65536)
    client-side, so anything larger never leaves the test client and would
    assert nothing about the server.
    """
    client, vault = gui
    resp = client.get("/note", headers=GOOD_HEADERS, params={"path": "A" * 50_000})
    _assert_no_crash(resp, vault)


# ============================================================================
# 5. Concurrent double-submit -> dedup must hold (exactly one note written)
# ============================================================================

def test_concurrent_double_submit_of_same_capture_dedups(gui):
    """Abuse case 6: two identical /capture POSTs racing in parallel threads.

    `_is_duplicate_request` (server.py:362) is the gate: it must admit exactly
    one of them and answer the other with `event: duplicate`. Anything else means
    two pipeline runs -> two vault writes for one logical capture.
    """
    client, _ = gui
    counter = {"n": 0}
    results: list = []
    barrier = threading.Barrier(2)

    def _submit():
        barrier.wait()          # maximise the overlap
        r = client.post("/capture", headers=GOOD_HEADERS,
                        json={"content_type": "text", "content": "racing capture payload"})
        results.append(r)

    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline(counter)):
        threads = [threading.Thread(target=_submit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert len(results) == 2 and all(r.status_code == 200 for r in results)
    duplicates = [r for r in results if "event: duplicate" in r.text]
    assert counter["n"] == 1, (
        f"concurrent double-submit ran the pipeline {counter['n']}x -- dedup did not hold; "
        "one logical capture would be written to the vault twice"
    )
    assert len(duplicates) == 1, "exactly one of the two racing submits must be told 'duplicate'"


def test_concurrent_double_submit_with_same_run_id_dedups(gui):
    """The other dedup axis: the same X-Capture-Run-Id (a GUI retry after a lost
    SSE connection) while the first attempt is STILL RUNNING.

    Deterministic by construction rather than timing-dependent: the fake pipeline
    blocks on `release` so attempt #1 provably cannot record its terminal event
    before attempt #2 performs its idempotency check. That is precisely the
    window the real retry path sits in.
    """
    client, _ = gui
    counter = {"n": 0}
    results: list = []
    started = threading.Event()
    release = threading.Event()

    def _blocking_pipeline(content_type, content, q, loop, run_id=None):
        counter["n"] += 1
        started.set()
        release.wait(timeout=10)      # hold the run open across #2's check
        loop.call_soon_threadsafe(q.put_nowait, {"event": "done", "path": "V/x.md", "category": "Notes"})
        loop.call_soon_threadsafe(q.put_nowait, None)

    def _submit(content):
        results.append(client.post(
            "/capture",
            headers={**GOOD_HEADERS, "X-Capture-Run-Id": "race-run-id"},
            json={"content_type": "text", "content": content},
        ))

    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_blocking_pipeline):
        # Distinct content so the 0.5s content-hash gate can't be what saves us --
        # this isolates the run_id idempotency path.
        t1 = threading.Thread(target=_submit, args=("run id race one",))
        t1.start()
        assert started.wait(timeout=10), "first pipeline never started"
        t2 = threading.Thread(target=_submit, args=("run id race two",))
        t2.start()
        # #2 has now claimed its role (waiter -- #1 owns the in-flight run_id). Let #1
        # finish; #1 releases the claim on completion, which wakes #2 to replay.
        time.sleep(0.2)
        release.set()
        t1.join(timeout=30)
        t2.join(timeout=30)

    assert len(results) == 2 and all(r.status_code == 200 for r in results)
    assert counter["n"] == 1, (
        f"a retry sharing X-Capture-Run-Id, issued while the first attempt was still "
        f"in flight, ran the pipeline {counter['n']}x -- two notes for one capture"
    )
    assert all("event: done" in r.text for r in results), (
        "the in-flight retry must WAIT and replay the first attempt's terminal 'done' "
        "-- not run a second pipeline and not fall back to an error"
    )


def test_distinct_captures_sharing_a_2000_char_prefix_are_not_conflated(gui):
    """Regression lock: `_request_hash` used to hash only `content[:2000]`, so two
    DIFFERENT captures whose first 2000 chars matched collided and the second was
    silently dropped as a duplicate inside the 0.5s window -- silent data loss.
    It now hashes the full content. Submitted serially, well inside
    `_DEDUP_WINDOW_S`."""
    client, _ = gui
    counter = {"n": 0}
    prefix = "P" * 2500
    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline(counter)):
        r1 = client.post("/capture", headers=GOOD_HEADERS,
                         json={"content_type": "text", "content": prefix + "FIRST DISTINCT TAIL"})
        r2 = client.post("/capture", headers=GOOD_HEADERS,
                         json={"content_type": "text", "content": prefix + "SECOND DISTINCT TAIL"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert "event: duplicate" not in r2.text, (
        "two DIFFERENT captures sharing a 2000-char prefix were conflated: the "
        "second was dropped as a duplicate and never written to the vault"
    )
    assert counter["n"] == 2


# ============================================================================
# 6. CORS -- allow_methods vs. the live route table
# ============================================================================

def _cors_allow_methods() -> set:
    """The verbs CORSMiddleware was actually configured with, read off the live
    app -- so this locks the real config, not a copy of it that can drift."""
    for mw in server.app.user_middleware:
        if mw.cls is CORSMiddleware:
            return set(mw.kwargs["allow_methods"])
    raise AssertionError("CORSMiddleware is not installed on server.app")


def test_cors_allow_methods_covers_every_route_method(gui):
    """Every method the app actually routes must be in CORSMiddleware's
    allow_methods, or the browser preflight for it fails and the route is
    unreachable from the GUI/extension. Regression lock for the PUT /note gap:
    allow_methods omitted PUT while `PUT /note` was routed, so `saveNoteContent`
    (gui/src/lib/api.ts) was answered 400 'Disallowed CORS method' -- note-editor
    save was dead in the packaged build."""
    allowed = _cors_allow_methods() | {"HEAD", "OPTIONS"}
    live_methods = {
        m for route in server.app.routes if isinstance(route, APIRoute) for m in route.methods
    }
    assert live_methods <= allowed, (
        f"routed method(s) {sorted(live_methods - allowed)} are not in CORSMiddleware's "
        "allow_methods -- a cross-origin preflight for them is rejected"
    )


def test_cors_preflight_succeeds_for_every_route_method(gui):
    """Behavioural form of the check above: drive an actual OPTIONS preflight per
    routed verb and require both a 200 and the verb echoed in the response's
    access-control-allow-methods."""
    client, _ = gui
    origin = server._ALLOWED_ORIGINS[0]
    failed = []
    for method in sorted({m for r in server.app.routes if isinstance(r, APIRoute) for m in r.methods}
                         - {"HEAD", "OPTIONS"}):
        resp = client.options("/note", headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "x-omni-secret",
        })
        echoed = resp.headers.get("access-control-allow-methods", "")
        if resp.status_code != 200 or method not in echoed:
            failed.append((method, resp.status_code, echoed or resp.text[:80]))
    assert failed == [], f"CORS preflight rejected routed method(s): {failed}"


# ============================================================================
# 8. LAN listener (B-11) -- lan_sync.py
#
# s23 already verified nonce replay/expiry/cap/403 + B-12 traversal; the tests
# below re-confirm those still hold and add the oversized-blob / garbage-
# ciphertext / no-partial-write cases this audit is responsible for.
# ============================================================================

def _lan_client(tmp_path, monkeypatch):
    """Shape-identical to test_lan_sync.py:_client -- same seams, same isolation."""
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "S3CRET")
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    lan_sync._nonces.clear()
    app = FastAPI()
    app.include_router(lan_sync.router)
    return TestClient(app), key, str(tmp_path / ".sync")


def _fetch_nonce(c, key) -> str:
    r = c.get("/lan/nonce")
    assert r.status_code == 200
    return json.loads(lan_crypto.open_envelope(r.json(), key))["nonce"]


def _seal_changes(key, nonce, since=0, lan_secret="S3CRET") -> dict:
    """LAN-11: the sealed {lan_secret, nonce, since} envelope is the POST /lan/changes BODY now."""
    return lan_crypto.seal(json.dumps({"lan_secret": lan_secret, "nonce": nonce, "since": since}), key)


def _push_env(key, nonce, lan_secret="S3CRET", **fields):
    """Seal a /lan/push plaintext with lan_secret + a redeemed nonce (LAN-02/17/20)."""
    plain = {"lan_secret": lan_secret, "nonce": nonce, "op_id": "op1", "note_id": "n",
             "base_rev": None, "device": "d", "modified": "", "body": "x"}
    plain.update(fields)
    return lan_crypto.seal(json.dumps(plain), key)


def test_lan_changes_replayed_nonce_rejected_cleanly(tmp_path, monkeypatch):
    """Re-confirms s23's replay finding AND applies this audit's leak oracle."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    (tmp_path / "n.md").write_text("---\nid: n\norigin: note\n---\nx\n", encoding="utf-8", newline="")
    env = _seal_changes(key, _fetch_nonce(c, key))
    assert c.post("/lan/changes", json=env).status_code == 200
    replay = c.post("/lan/changes", json=env)
    assert replay.status_code == 403
    _assert_clean_4xx(replay, tmp_path)
    assert ps.list_provisional(sync_dir) == []


def test_lan_changes_expired_nonce_rejected_cleanly(tmp_path, monkeypatch):
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    nonce = _fetch_nonce(c, key)
    lan_sync._nonces[nonce] = time.time() - 1        # force-expire
    resp = c.post("/lan/changes", json=_seal_changes(key, nonce))
    assert resp.status_code == 403
    _assert_clean_4xx(resp, tmp_path)
    assert ps.list_provisional(sync_dir) == []


def test_lan_changes_never_minted_nonce_rejected_cleanly(tmp_path, monkeypatch):
    """A nonce the server never issued (attacker-chosen) must not redeem."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    resp = c.post("/lan/changes", json=_seal_changes(key, "deadbeef" * 4))
    assert resp.status_code == 403
    _assert_clean_4xx(resp, tmp_path)


def test_lan_changes_get_method_is_gone(tmp_path, monkeypatch):
    """LAN-11: the old GET /lan/changes route (with ?auth=) is removed — an old phone's GET poll now
    gets a clean 405 and falls back to Drive, never a half-authenticated scan."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    assert c.get("/lan/changes").status_code == 405


def test_lan_push_garbage_ciphertext_rejected_cleanly(tmp_path, monkeypatch):
    """Well-shaped envelope, wrong key -> 400, and nothing staged."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    other_key = lan_crypto.gen_key_b64()
    env = lan_crypto.seal(json.dumps({"lan_secret": "S3CRET", "op_id": "op1", "note_id": "n",
                                      "base_rev": None, "device": "d", "modified": "",
                                      "body": "x"}), other_key)
    resp = c.post("/lan/push", json=env)
    assert resp.status_code == 400
    _assert_clean_4xx(resp, tmp_path)
    assert ps.list_provisional(sync_dir) == [], "garbage ciphertext produced a partial write"


@pytest.mark.parametrize("payload", [
    {},
    {"n": "not-base64!!", "box": "also-not-base64!!"},
    {"n": None, "box": None},
    {"box": "AAAA"},                       # missing nonce field
    [1, 2, 3],                             # not even an object
    "a bare string",
], ids=["empty", "non-b64", "nulls", "missing-n", "list", "string"])
def test_lan_push_malformed_envelope_rejected_cleanly(tmp_path, monkeypatch, payload):
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    resp = c.post("/lan/push", json=payload)
    _assert_clean_4xx(resp, tmp_path)
    assert ps.list_provisional(sync_dir) == []


def test_lan_push_oversized_blob_rejected_cleanly(tmp_path, monkeypatch):
    """A 5 MB undecryptable box: must be refused without staging anything."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    resp = c.post("/lan/push", json={"n": "A" * 32, "box": "B" * (5 * 1024 * 1024)})
    assert resp.status_code == 400
    _assert_clean_4xx(resp, tmp_path)
    assert ps.list_provisional(sync_dir) == [], "oversized blob produced a partial write"


def test_lan_push_oversized_valid_envelope_does_not_crash(tmp_path, monkeypatch):
    """A correctly-sealed but very large body: decryption succeeds, so this
    exercises the staging path's size handling rather than the reject path."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    env = _push_env(key, _fetch_nonce(c, key), op_id="big", note_id="bignote", device="phone",
                    body="Z" * (2 * 1024 * 1024))
    resp = c.post("/lan/push", json=env)
    _assert_no_crash(resp, tmp_path)


def test_lan_changes_oversized_body_rejected_cleanly(tmp_path, monkeypatch):
    """LAN-11 moved the auth envelope into the POST body, so the old ?auth= URL-length hazard is gone.
    A large non-envelope POST body must still be refused cleanly (400) with no scan and no leak."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    resp = c.post("/lan/changes", content=b"X" * 50_000)
    assert resp.status_code == 400
    _assert_clean_4xx(resp, tmp_path)


def test_lan_push_wrong_secret_stages_nothing(tmp_path, monkeypatch):
    """Re-confirms the s23 403 AND the no-partial-write oracle for this audit."""
    c, key, sync_dir = _lan_client(tmp_path, monkeypatch)
    env = _push_env(key, _fetch_nonce(c, key), lan_secret="WRONG")
    resp = c.post("/lan/push", json=env)
    assert resp.status_code == 403
    _assert_clean_4xx(resp, tmp_path)
    assert ps.list_provisional(sync_dir) == []


def test_lan_nonce_cap_is_bounded(tmp_path, monkeypatch):
    """Re-confirms s23's cap finding: /lan/nonce is unauthenticated by design, so
    an attacker must not be able to grow the store past _NONCE_CAP."""
    c, key, _ = _lan_client(tmp_path, monkeypatch)
    for _ in range(lan_sync._NONCE_CAP + 40):
        assert c.get("/lan/nonce").status_code == 200
    assert len(lan_sync._nonces) <= lan_sync._NONCE_CAP


def test_lan_nonce_response_leaks_nothing_in_the_clear(tmp_path, monkeypatch):
    """The nonce endpoint is unauthenticated -- its plaintext response envelope
    must carry no secret and no filesystem path."""
    c, key, _ = _lan_client(tmp_path, monkeypatch)
    resp = c.get("/lan/nonce")
    assert "S3CRET" not in resp.text
    assert str(tmp_path) not in resp.text
    assert str(tmp_path).replace("\\", "/") not in resp.text
