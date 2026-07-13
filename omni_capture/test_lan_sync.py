from fastapi.testclient import TestClient
from fastapi import FastAPI
import json, base64
import lan_sync, lan_crypto


def _client(tmp_path, monkeypatch):
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: "S3CRET")
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    app = FastAPI(); app.include_router(lan_sync.router)
    return TestClient(app), key


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
    # with an id in the vault must be served on GET /lan/changes.
    (tmp_path / "nA.md").write_text("---\nid: nA\norigin: note\n---\nd\n", encoding="utf-8")
    c, key = _client(tmp_path, monkeypatch)
    r = c.get("/lan/changes?since=0")
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert [ch["note_id"] for ch in plain["changes"]] == ["nA"]
    assert plain["changes"][0]["body"] == "---\nid: nA\norigin: note\n---\nd\n"


def test_changes_filters_by_since_cursor(tmp_path, monkeypatch):
    # Only notes modified AFTER the phone's cursor are served, so a poll doesn't re-ship the
    # whole vault every 5s. Write an "old" note, capture the cursor, then a "new" note.
    import os, time
    (tmp_path / "old.md").write_text("---\nid: old\n---\nx\n", encoding="utf-8")
    old_mtime = (tmp_path / "old.md").stat().st_mtime
    c, key = _client(tmp_path, monkeypatch)
    (tmp_path / "new.md").write_text("---\nid: new\n---\ny\n", encoding="utf-8")
    os.utime(tmp_path / "new.md", (old_mtime + 10, old_mtime + 10))
    r = c.get(f"/lan/changes?since={old_mtime + 5}")
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert [ch["note_id"] for ch in plain["changes"]] == ["new"]


def test_changes_empty_vault_serves_empty_feed(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    r = c.get("/lan/changes?since=0")
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert plain["changes"] == []
