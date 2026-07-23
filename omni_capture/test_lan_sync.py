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


def _push(c, key, lan_secret="S3CRET", **fields):
    """Full handshake: fetch a nonce, seal the push plaintext, POST /lan/push. LAN-02/20: /lan/push
    redeems a single-use nonce too, so `nonce` is part of every push (contract §11.3 step 5)."""
    nonce = _fetch_nonce(c, key)
    plain = {"lan_secret": lan_secret, "nonce": nonce, "op_id": "op1", "note_id": "noteA",
             "base_rev": None, "device": "phone", "modified": "2026-07-11T00:00:00Z",
             "body": "---\n---\nhi\n"}
    plain.update(fields)
    return c.post("/lan/push", json=lan_crypto.seal(json.dumps(plain), key))


def _poll(c, key, since=0, lan_secret="S3CRET"):
    """Full handshake: fetch a nonce, seal {lan_secret, nonce, since}, POST /lan/changes (LAN-11: the
    auth envelope is the POST BODY now, not a ?auth= query value)."""
    nonce = _fetch_nonce(c, key)
    env = lan_crypto.seal(json.dumps({"lan_secret": lan_secret, "nonce": nonce, "since": since}), key)
    return c.post("/lan/changes", json=env)


def test_push_stages_provisional(tmp_path, monkeypatch):
    import provisional_store as ps
    c, key = _client(tmp_path, monkeypatch)
    r = _push(c, key, op_id="op1", note_id="noteA", body="---\n---\nhi\n")
    assert r.status_code == 200
    assert len(ps.list_provisional(str(tmp_path / ".sync"))) == 1


def test_push_rejects_wrong_secret(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = _push(c, key, lan_secret="WRONG", note_id="n", body="x")
    assert r.status_code == 403


def test_push_rejects_empty_server_secret(tmp_path, monkeypatch):
    # An unconfigured (empty) server lan_secret must never degrade to key-only auth
    # — hmac.compare_digest("", "") would otherwise accept lan_secret:"" from any
    # LAN peer who has the shared key but not the secret.
    import provisional_store as ps
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "")
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    lan_sync._nonces.clear()
    app = FastAPI(); app.include_router(lan_sync.router)
    c = TestClient(app)
    r = _push(c, key, lan_secret="", note_id="n", body="x")
    assert r.status_code == 403
    assert ps.list_provisional(str(tmp_path / ".sync")) == []


def test_push_rejects_undecryptable(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = c.post("/lan/push", json={"n": "AAAA", "box": "BBBB"})   # garbage
    assert r.status_code == 400


def test_changes_returns_sealed_envelope(tmp_path, monkeypatch):
    # The handler now populates the feed IN-PROCESS by scanning the vault (the fix: the
    # single-shot mobile_sync_agent's set_outbound never reaches the running server). A note
    # with an id in the vault must be served on POST /lan/changes AFTER a valid nonce handshake.
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


def test_changes_get_is_gone_and_empty_post_is_400(tmp_path, monkeypatch):
    # LAN-11: /lan/changes is POST-only now — the old GET route (which carried ?auth=) is gone, so an
    # old phone's GET poll gets a clean 405 and falls back to Drive. An empty/malformed POST body 400s
    # before any vault scan — the whole point of B-11.
    (tmp_path / "nA.md").write_text("---\nid: nA\norigin: note\n---\nd\n", encoding="utf-8", newline="")
    c, key = _client(tmp_path, monkeypatch)
    assert c.get("/lan/changes").status_code == 405
    assert c.post("/lan/changes", content=b"").status_code == 400


def test_changes_rejects_bad_secret(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = _poll(c, key, lan_secret="WRONG")
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
    r = _poll(c, key, lan_secret="")
    assert r.status_code == 403


def test_changes_rejects_expired_nonce(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    nonce = _fetch_nonce(c, key)
    lan_sync._nonces[nonce] = time.time() - 1          # force-expire the issued nonce
    env = lan_crypto.seal(json.dumps({"lan_secret": "S3CRET", "nonce": nonce, "since": 0}), key)
    r = c.post("/lan/changes", json=env)
    assert r.status_code == 403


def test_changes_rejects_replayed_nonce(tmp_path, monkeypatch):
    # Single-use: the same sealed body envelope must fail on a second POST.
    c, key = _client(tmp_path, monkeypatch)
    nonce = _fetch_nonce(c, key)
    env = lan_crypto.seal(json.dumps({"lan_secret": "S3CRET", "nonce": nonce, "since": 0}), key)
    assert c.post("/lan/changes", json=env).status_code == 200
    assert c.post("/lan/changes", json=env).status_code == 403
