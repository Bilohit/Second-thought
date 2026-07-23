"""LAN-02/11/17/20 hardening (contract §11.3/§11.4/§11.9). Security-critical, test-first.

New wire vs the pre-hardening one:
  - the in-envelope credential field is `lan_secret` (NOT the GUI `secret`), read from `[lan] secret`;
  - `POST /lan/push` now redeems a server-issued single-use nonce, AFTER the lan_secret check;
  - `/lan/changes` is `POST` with the sealed `{lan_secret, nonce, since}` in the BODY (no `?auth=`,
    no `GET`).
Each failure path must fall through to "LAN silently off, Drive carries everything".
"""
from fastapi.testclient import TestClient
from fastapi import FastAPI
import json, time
import lan_sync, lan_crypto


def _client(tmp_path, monkeypatch, secret="S3CRET"):
    key = lan_crypto.gen_key_b64()
    monkeypatch.setattr(lan_sync, "_lan_key", lambda: key)
    monkeypatch.setattr(lan_sync, "_lan_secret", lambda: secret)
    monkeypatch.setattr(lan_sync, "_sync_dir", lambda: str(tmp_path / ".sync"))
    monkeypatch.setattr(lan_sync, "_vault_path", lambda: str(tmp_path))
    lan_sync._nonces.clear()
    app = FastAPI(); app.include_router(lan_sync.router)
    return TestClient(app), key


def _issue_nonce(c, key) -> str:
    r = c.get("/lan/nonce")
    assert r.status_code == 200
    return json.loads(lan_crypto.open_envelope(r.json(), key))["nonce"]


def _push(c, key, *, lan_secret="S3CRET", nonce=None, op_id="op1", note_id="noteA",
          body="---\n---\nhi\n", include_nonce=True):
    plain = {"lan_secret": lan_secret, "op_id": op_id, "note_id": note_id,
             "base_rev": None, "device": "phone", "modified": "2026-07-11T00:00:00Z", "body": body}
    if include_nonce:
        plain["nonce"] = nonce
    return c.post("/lan/push", json=lan_crypto.seal(json.dumps(plain), key))


def _changes(c, key, *, lan_secret="S3CRET", nonce=None, since=0, include_nonce=True):
    plain = {"lan_secret": lan_secret, "since": since}
    if include_nonce:
        plain["nonce"] = nonce
    return c.post("/lan/changes", json=lan_crypto.seal(json.dumps(plain), key))


# (a) a push without a valid nonce is 403; the same push WITH a valid nonce is 200.
def test_push_requires_nonce(tmp_path, monkeypatch):
    import provisional_store as ps
    c, key = _client(tmp_path, monkeypatch)
    # positive control: correct lan_secret + a freshly-issued nonce → staged, 200.
    n = _issue_nonce(c, key)
    assert _push(c, key, nonce=n).status_code == 200
    assert len(ps.list_provisional(str(tmp_path / ".sync"))) == 1
    # negative: no nonce field at all → 403, nothing staged beyond the one above.
    assert _push(c, key, include_nonce=False, op_id="op2", note_id="noteB").status_code == 403
    # negative: a never-issued nonce → 403.
    assert _push(c, key, nonce="deadbeef" * 4, op_id="op3", note_id="noteC").status_code == 403
    assert len(ps.list_provisional(str(tmp_path / ".sync"))) == 1


# (b) nonce redemption happens AFTER the lan_secret check: a wrong lan_secret 403s WITHOUT
#     consuming the nonce; only a correct lan_secret consumes it.
def test_nonce_consumed_only_after_secret_check(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    n = _issue_nonce(c, key)
    assert n in lan_sync._nonces
    # wrong lan_secret + a valid nonce → 403 and the nonce is STILL in the pool (not burned).
    assert _push(c, key, lan_secret="WRONG", nonce=n).status_code == 403
    assert n in lan_sync._nonces, "wrong lan_secret must not burn a nonce"
    # correct lan_secret + same nonce → 200 and NOW the nonce is consumed.
    assert _push(c, key, lan_secret="S3CRET", nonce=n).status_code == 200
    assert n not in lan_sync._nonces


# (c) an empty configured server lan_secret is always 403 — never key-only auth — on both writes.
def test_empty_server_secret_always_403(tmp_path, monkeypatch):
    import provisional_store as ps
    c, key = _client(tmp_path, monkeypatch, secret="")
    n = _issue_nonce(c, key)
    assert _push(c, key, lan_secret="", nonce=n).status_code == 403
    assert ps.list_provisional(str(tmp_path / ".sync")) == []
    n2 = _issue_nonce(c, key)
    assert _changes(c, key, lan_secret="", nonce=n2).status_code == 403


# (d) GET /lan/changes is gone (405); POST with the sealed body envelope works.
def test_changes_is_post_only(tmp_path, monkeypatch):
    (tmp_path / "nA.md").write_text("---\nid: nA\norigin: note\n---\nd\n", encoding="utf-8", newline="")
    c, key = _client(tmp_path, monkeypatch)
    assert c.get("/lan/changes").status_code == 405          # the old GET route is gone
    n = _issue_nonce(c, key)
    r = _changes(c, key, nonce=n, since=0)
    assert r.status_code == 200
    plain = json.loads(lan_crypto.open_envelope(r.json(), key))
    assert [ch["note_id"] for ch in plain["changes"]] == ["nA"]
    # the server never echoes lan_secret or nonce back in the feed.
    assert "lan_secret" not in plain and "nonce" not in plain
    for ch in plain["changes"]:
        assert "lan_secret" not in ch and "nonce" not in ch


# replay guard on /lan/changes too: same nonce twice → 403 on the second.
def test_changes_rejects_replayed_nonce(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    n = _issue_nonce(c, key)
    assert _changes(c, key, nonce=n).status_code == 200
    assert _changes(c, key, nonce=n).status_code == 403


# Cross-side agreement backstop: the desktop's PushPlain fields (names + presence of lan_secret,
# nonce) must match the phone's sealed push plaintext exactly. The phone seals
# { ...op, lan_secret, nonce } where op = {op_id, note_id, base_rev, device, modified, body}
# (see phone/src/lib/lanSync.ts pushOp + sync.ts pushEnqueuedOp). Assert the desktop accepts
# exactly that field set and rejects a push missing lan_secret.
PHONE_PUSH_PLAIN_FIELDS = {
    "op_id", "note_id", "base_rev", "device", "modified", "body", "lan_secret", "nonce",
}


def test_push_plain_shape_matches_phone(tmp_path, monkeypatch):
    c, key = _client(tmp_path, monkeypatch)
    n = _issue_nonce(c, key)
    plain = {"op_id": "o", "note_id": "nX", "base_rev": None, "device": "phone",
             "modified": "2026-07-11T00:00:00Z", "body": "---\n---\nz\n",
             "lan_secret": "S3CRET", "nonce": n}
    assert set(plain.keys()) == PHONE_PUSH_PLAIN_FIELDS
    assert c.post("/lan/push", json=lan_crypto.seal(json.dumps(plain), key)).status_code == 200
    # lan_secret is load-bearing: drop it and the same otherwise-valid push is 403.
    n2 = _issue_nonce(c, key)
    plain2 = dict(plain); plain2.pop("lan_secret"); plain2["nonce"] = n2
    assert c.post("/lan/push", json=lan_crypto.seal(json.dumps(plain2), key)).status_code == 403
