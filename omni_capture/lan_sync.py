"""LAN accelerator endpoints (contract §11). Served on the LAN-IP listener ONLY (lan_server.py).

Auth is the `secret` field INSIDE the NaCl envelope (== the GUI X-Omni-Secret), not an HTTP header --
this listener has no header middleware; the encrypted envelope both authenticates and encrypts."""
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

import lan_crypto
import provisional_store as ps
from config import get_config

router = APIRouter()

# Outbound feed (desktop's own changed notes since a cursor). Filled by refresh_outbound() below.
_outbound: list = []

# Nonce challenge store (contract §11.9): authenticates + de-replays GET /lan/changes.
# {nonce_hex: expiry_epoch}. In-memory, single-process, thread-locked (uvicorn serves polls
# concurrently), single-use (consumed on redeem), size-capped so an unauthenticated /lan/nonce
# caller can't grow it unboundedly.
# ponytail: in-memory dict is right for one LAN listener — nonces are volatile op-state, lost on
# restart (phone just re-fetches). Only revisit if the LAN server ever goes multi-process.
_NONCE_TTL = 30.0          # seconds
_NONCE_CAP = 256           # max outstanding; oldest-by-expiry evicted when full
_nonces: dict = {}
_nonce_lock = threading.Lock()


def _issue_nonce() -> tuple:
    """Mint + record a single-use nonce, returning (nonce_hex, exp_epoch)."""
    now = time.time()
    nonce = secrets.token_hex(16)
    exp = now + _NONCE_TTL
    with _nonce_lock:
        # Drop expired first, then bound size (evict soonest-to-expire = oldest).
        for n in [n for n, e in _nonces.items() if e <= now]:
            _nonces.pop(n, None)
        while len(_nonces) >= _NONCE_CAP:
            _nonces.pop(min(_nonces, key=_nonces.get), None)
        _nonces[nonce] = exp
    return nonce, exp


def _consume_nonce(nonce: str) -> bool:
    """True iff nonce is known + unexpired; deletes it (single-use) either way it's found."""
    now = time.time()
    with _nonce_lock:
        exp = _nonces.pop(nonce, None)
    return exp is not None and exp > now


def set_outbound(changes: list) -> None:
    global _outbound
    _outbound = list(changes)


def refresh_outbound(vault_path: str, since_ts: float = 0.0) -> list:
    """Scan this desktop's own vault notes changed since since_ts and feed
    set_outbound, so GET /lan/changes serves this peer's own recent edits to
    the paired phone (contract §11.3, "phone POLLS /lan/changes").

    # ponytail: mtime-based "recently changed" -- good enough for a same-WiFi
    # accelerator (best-effort, never authoritative; Drive remains the sole
    # canonical/version source). If this ever needs to match Drive's
    # headRevisionId-based change detection exactly, switch to
    # mobile_sync_agent's sync_state.json (base_rev) bookkeeping instead of
    # file mtime. Reuses mobile_sync_agent.read_vault_notes rather than
    # re-walking the vault with a second implementation.
    """
    from datetime import datetime, timezone

    from mobile_sync_agent import read_vault_notes

    notes = read_vault_notes(vault_path)
    changes = []
    for note_id, note in notes.items():
        try:
            mtime = Path(note["path"]).stat().st_mtime
        except OSError:
            continue
        if mtime <= since_ts:
            continue
        changes.append({
            "op_id": note["hash"][:16],
            "note_id": note_id,
            "base_rev": None,
            "device": "desktop",
            "modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "body": note["content"],
        })
    set_outbound(changes)
    return changes


def _lan_key() -> str:
    return get_config().lan.key


def _lan_secret() -> str:
    return os.getenv("OMNI_GUI_SECRET", "")


def _sync_dir() -> str:
    return get_config().vault_sync_dir()


def _vault_path() -> str:
    return str(get_config().vault.root)


def _check_secret(plain: dict) -> None:
    """Shared auth gate for both LAN endpoints (contract §11.3). Raises 403 on failure.
    An empty server secret must never degrade to key-only auth: this listener is
    network-exposed, and hmac.compare_digest("", "") would otherwise accept secret:"" from
    anyone holding the shared key but not the secret."""
    lan_secret = _lan_secret()
    if not lan_secret:
        raise HTTPException(status_code=403, detail="lan secret not configured")
    if not hmac.compare_digest(plain.get("secret", ""), lan_secret):
        raise HTTPException(status_code=403, detail="bad secret")


@router.post("/lan/push")
async def lan_push(request: Request):
    env = await request.json()
    try:
        plain = json.loads(lan_crypto.open_envelope(env, _lan_key()))
    except Exception:
        raise HTTPException(status_code=400, detail="undecryptable envelope")
    _check_secret(plain)
    ps.stage(_sync_dir(), plain["op_id"], plain["note_id"], plain["body"],
             {"device": plain.get("device", ""), "modified": plain.get("modified", ""),
              "staged_at": time.time()})               # epoch seconds -> TTL sweep
    return {"ok": True}


@router.get("/lan/nonce")
async def lan_nonce():
    # First handshake step (contract §11.9): mint a single-use, short-TTL challenge the phone
    # must seal back into GET /lan/changes. Unauthenticated by design — a nonce is useless
    # without the shared key + secret. Sealed for wire consistency (every LAN body is an envelope).
    nonce, exp = _issue_nonce()
    return lan_crypto.seal(json.dumps({"nonce": nonce, "exp": exp}), _lan_key())


@router.get("/lan/changes")
async def lan_changes(auth: str = ""):
    # AUTH BEFORE SCAN (contract §11.3/§11.9): the fix for the pre-B11 gap where an
    # unauthenticated same-WiFi caller forced a full-vault refresh_outbound() and received the
    # key-sealed feed. `auth` is a sealed {secret, nonce, since} envelope; verify secret + a
    # server-issued single-use nonce BEFORE touching the vault. Any failure 403/400s with no scan.
    try:
        req = json.loads(lan_crypto.open_envelope(json.loads(auth), _lan_key()))
    except Exception:
        raise HTTPException(status_code=400, detail="undecryptable auth envelope")
    _check_secret(req)
    if not _consume_nonce(req.get("nonce", "")):
        raise HTTPException(status_code=403, detail="bad or expired nonce")
    try:
        since_ts = float(req.get("since", 0))
    except (TypeError, ValueError):
        since_ts = 0.0
    # Populate the outbound feed in THIS (serving) process (refresh_outbound's other caller is the
    # single-shot mobile_sync_agent in a separate process). Scan for notes changed since the
    # phone's cursor (best-effort; Drive stays the sole canonical/version authority).
    # ponytail: re-scans the vault per poll (5s while the phone is foregrounded). Fine for a
    # same-WiFi accelerator; add an mtime-keyed cache if a vault ever holds thousands of notes.
    refresh_outbound(_vault_path(), since_ts=since_ts)
    payload = json.dumps({"cursor": str(int(time.time())), "changes": _outbound})
    return lan_crypto.seal(payload, _lan_key())
