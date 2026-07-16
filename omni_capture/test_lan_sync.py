from fastapi.testclient import TestClient
from fastapi import FastAPI
import json, base64, time
import lan_sync, lan_crypto


def _client(tmp_path, monkeypatch):
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "S3CRET")
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    lan_sync._nonces.clear()                     # isolate the module-level nonce store per test
    app = FastAPI(); app.include_router(lan_sync.router)
    return TestClient(app), key


def _fetch_nonce(c, key) -> str:
    r = c.get("/lan/nonce")
    assert r.status_code == 200
    return json.loads(lan_crypto.open_envelope(r.json(), key))["nonce"]


def _seal_auth(key, nonce, since=0, secret="S3CRET"):
    """The ?auth= value: a sealed {secret, nonce, since} envelope, JSON-encoded for the query."""
    return json.dumps(lan_crypto.seal(json.dumps(
        {"secret": secret, "nonce": nonce, "since": since}), key))


def _poll(c, key, since=0, secret="S3CRET"):
    """Full handshake: fetch a nonce, seal auth, GET /lan/changes."""
    nonce = _fetch_nonce(c, key)
    return c.get("/lan/changes", params={"auth": _seal_auth(key, nonce, since, secret)})


def test_push_stages_provisional(tmp_path, monkeypatch):
    import provisional_store as ps
    c, key = _client(tmp_path, monkeypatch)
    plain = json.dumps({"secret": "S3CRET", "op_id": "op1", "note_id": "noteA",
                        "base_rev": None, "device": "phone", "modified": "2026-07-11T00:00:00Z",
                        "body": "---\n---\nhi\n"})
    r = c.post("/lan/push", json=lan_crypto.seal(plain, key))
    assert r.status_code == 200
    assert len(ps.list_provisional(str(tmp_path / ".sync"))) == 1


def test_push_rejects_wrong_secret(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    plain = json.dumps({"secret": "WRONG", "op_id": "op1", "note_id": "n", "base_rev": None,
                        "device": "d", "modified": "", "body": "x"})
    r = c.post("/lan/push", json=lan_crypto.seal(plain, key))
    assert r.status_code == 403


def test_push_rejects_empty_server_secret(tmp_path, monkeypatch):
    # An unconfigured (empty) server secret must never degrade to key-only auth
    # — hmac.compare_digest("", "") would otherwise accept secret:"" from any
    # LAN peer who has the shared key but not the secret.
    import provisional_store as ps
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "")
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    app = FastAPI(); app.include_router(lan_sync.router)
    c = TestClient(app)
    plain = json.dumps({"secret": "", "op_id": "op1", "note_id": "n", "base_rev": None,
                        "device": "d", "modified": "", "body": "x"})
    r = c.post("/lan/push", json=lan_crypto.seal(plain, key))
    assert r.status_code == 403
    assert ps.list_provisional(str(tmp_path / ".sync")) == []


def test_push_rejects_undecryptable(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = c.post("/lan/push", json={"n": "AAAA", "box": "BBBB"})   # garbage
    assert r.status_code == 400


def test_changes_returns_sealed_envelope(tmp_path, monkeypatch):
    # The handler now populates the feed IN-PROCESS by scanning the vault (the fix: the
    # single-shot mobile_sync_agent's set_outbound never reaches the running server). A note
    # with an id in the vault must be served on GET /lan/changes AFTER a valid nonce handshake.
    (tmp_path / "nA.md").write_text("---\nid: nA\norigin: note\n---\nd\n", encoding="utf-8", newline="")
    c, key = _client(tmp_path, monkeypatch)
    r = _poll(c, key, since=0)
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert [ch["note_id"] for ch in plain["changes"]] == ["nA"]
    assert plain["changes"][0]["body"] == "---\nid: nA\norigin: note\n---\nd\n"


def test_changes_filters_by_since_cursor(tmp_path, monkeypatch):
    # Only notes modified AFTER the phone's cursor are served, so a poll doesn't re-ship the
    # whole vault every 5s. Write an "old" note, capture the cursor, then a "new" note.
    import os
    (tmp_path / "old.md").write_text("---\nid: old\norigin: note\n---\nx\n", encoding="utf-8", newline="")
    old_mtime = (tmp_path / "old.md").stat().st_mtime
    c, key = _client(tmp_path, monkeypatch)
    (tmp_path / "new.md").write_text("---\nid: new\norigin: note\n---\ny\n", encoding="utf-8", newline="")
    os.utime(tmp_path / "new.md", (old_mtime + 10, old_mtime + 10))
    r = _poll(c, key, since=old_mtime + 5)
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert [ch["note_id"] for ch in plain["changes"]] == ["new"]


def test_changes_empty_vault_serves_empty_feed(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = _poll(c, key, since=0)
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert plain["changes"] == []


# --- B-11 auth-before-scan (contract §11.3/§11.9) ---

def test_nonce_endpoint_issues_sealed_nonce(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = c.get("/lan/nonce")
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert plain["nonce"] and plain["exp"] > time.time()
    assert plain["nonce"] in lan_sync._nonces          # recorded server-side


def test_changes_rejects_missing_auth(tmp_path, monkeypatch):
    # No ?auth= at all: 400 (undecryptable), never a served feed — the whole point of B-11.
    (tmp_path / "nA.md").write_text("---\nid: nA\norigin: note\n---\nd\n", encoding="utf-8", newline="")
    c, key = _client(tmp_path, monkeypatch)
    assert c.get("/lan/changes").status_code == 400


def test_changes_rejects_bad_secret(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = _poll(c, key, secret="WRONG")
    assert r.status_code == 403


def test_changes_rejects_empty_server_secret(tmp_path, monkeypatch):
    # Empty server secret must never degrade to key-only auth (mirrors the push test).
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "")
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    lan_sync._nonces.clear()
    app = FastAPI(); app.include_router(lan_sync.router)
    c = TestClient(app)
    nonce = _fetch_nonce(c, key)
    r = c.get("/lan/changes", params={"auth": _seal_auth(key, nonce, secret="")})
    assert r.status_code == 403


def test_changes_rejects_expired_nonce(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    nonce = _fetch_nonce(c, key)
    lan_sync._nonces[nonce] = time.time() - 1          # force-expire the issued nonce
    r = c.get("/lan/changes", params={"auth": _seal_auth(key, nonce)})
    assert r.status_code == 403


def test_changes_rejects_replayed_nonce(tmp_path, monkeypatch):
    # Single-use: the same sealed auth envelope must fail on a second GET.
    c, key = _client(tmp_path, monkeypatch)
    nonce = _fetch_nonce(c, key)
    auth = _seal_auth(key, nonce)
    assert c.get("/lan/changes", params={"auth": auth}).status_code == 200
    assert c.get("/lan/changes", params={"auth": auth}).status_code == 403
