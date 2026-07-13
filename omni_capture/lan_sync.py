"""LAN accelerator endpoints (contract §11). Served on the LAN-IP listener ONLY (lan_server.py).

Auth is the `secret` field INSIDE the NaCl envelope (== the GUI X-Omni-Secret), not an HTTP header --
this listener has no header middleware; the encrypted envelope both authenticates and encrypts."""
import hmac
import json
import os
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


@router.post("/lan/push")
async def lan_push(request: Request):
    env = await request.json()
    try:
        plain = json.loads(lan_crypto.open_envelope(env, _lan_key()))
    except Exception:
        raise HTTPException(status_code=400, detail="undecryptable envelope")
    lan_secret = _lan_secret()
    if not lan_secret:
        # An empty server secret must never degrade to key-only auth: unlike the
        # loopback dev server, this listener is network-exposed, and
        # hmac.compare_digest("", "") would otherwise accept secret:"" from anyone.
        raise HTTPException(status_code=403, detail="lan secret not configured")
    if not hmac.compare_digest(plain.get("secret", ""), lan_secret):
        raise HTTPException(status_code=403, detail="bad secret")
    ps.stage(_sync_dir(), plain["op_id"], plain["note_id"], plain["body"],
             {"device": plain.get("device", ""), "modified": plain.get("modified", ""),
              "staged_at": time.time()})               # epoch seconds -> TTL sweep
    return {"ok": True}


@router.get("/lan/changes")
async def lan_changes(since: str = "0"):
    # Populate the outbound feed in THIS (serving) process. refresh_outbound's only other
    # caller is the single-shot mobile_sync_agent, whose _outbound lives in a separate
    # process and never reaches the running LAN server -- so without this the desktop->phone
    # accelerator (contract §11.3) always served an empty feed. Scan for notes changed since
    # the phone's cursor so we serve only this peer's recent edits (best-effort; Drive stays
    # the sole canonical/version authority).
    try:
        since_ts = float(since)
    except (TypeError, ValueError):
        since_ts = 0.0
    # ponytail: re-scans the vault per poll (5s while the phone is foregrounded). Fine for a
    # same-WiFi accelerator; add an mtime-keyed cache if a vault ever holds thousands of notes.
    refresh_outbound(_vault_path(), since_ts=since_ts)
    payload = json.dumps({"cursor": str(int(time.time())), "changes": _outbound})
    return lan_crypto.seal(payload, _lan_key())
