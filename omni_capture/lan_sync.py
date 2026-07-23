"""LAN accelerator endpoints (contract §11). Served on the LAN-IP listener ONLY (lan_server.py).

Auth is the `lan_secret` field INSIDE the NaCl envelope (LAN-17: a distinct credential from the GUI
X-Omni-Secret, read from `[lan] secret` in config) plus a server-issued single-use `nonce`, not an HTTP
header -- this listener has no header middleware; the encrypted envelope both authenticates and encrypts.
Both POST writes check in the normative order lan_secret -> nonce -> fields (contract §11.3)."""
import hmac
import json
import math
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

# Nonce challenge store (contract §11.9): authenticates + de-replays BOTH LAN writes
# (POST /lan/push and POST /lan/changes). One pool, endpoint-agnostic, single-use.
# {nonce_hex: expiry_epoch}. In-memory, single-process, thread-locked (uvicorn serves polls
# concurrently), single-use (consumed on redeem), size-capped so an unauthenticated /lan/nonce
# caller can't grow it unboundedly.
# ponytail: in-memory dict is right for one LAN listener — nonces are volatile op-state, lost on
# restart (phone just re-fetches). Only revisit if the LAN server ever goes multi-process.
_NONCE_TTL = 30.0          # seconds
# LAN-10: the cap was 256 and eviction is min-by-expiry, which -- since every nonce is minted with
# the same TTL -- is the OLDEST outstanding nonce. /lan/nonce is unauthenticated by design, so 256
# quick requests could evict a legitimate phone's in-flight challenge before it redeemed it, turning
# a working poll into a 403 (LAN degrades to Drive-only; correctness is never at risk, which is why
# this is the low-severity end of the batch). Raising the cap moves the flood threshold far above any
# real poll rate at trivial cost: an entry is a 32-char hex key plus a float, so 4096 outstanding
# nonces is well under a megabyte and they all expire within _NONCE_TTL anyway.
# ponytail: a bigger dict, not a rate limiter. The ceiling is a sustained flood of >4096 nonce
# requests inside 30s from someone already on the LAN; add per-peer throttling only if that is ever
# observed.
_NONCE_CAP = 4096          # max outstanding; oldest-by-expiry evicted when full
_nonces: dict = {}
_nonce_lock = threading.Lock()

# LAN-06: `await request.json()` buffers an unbounded body BEFORE any auth runs, and this listener
# faces the LAN. Same ceiling as server.py's `_MAX_B64_LEN` for the loopback app; defined here rather
# than imported because importing `server` would drag the whole GUI FastAPI app (and its startup
# hooks) into the LAN listener's import graph and into every LAN unit test.
MAX_ENVELOPE_LEN = 64 * 1024 * 1024


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
    # LAN-17: the LAN-plane credential lives in `[lan] secret`, read per request via get_config()
    # exactly as `[lan] key` is -- NOT the GUI X-Omni-Secret (OMNI_GUI_SECRET), which never reaches
    # this network-facing listener. An empty value is always rejected by _check_secret (never key-only).
    return get_config().lan.secret


def _sync_dir() -> str:
    return get_config().vault_sync_dir()


def _vault_path() -> str:
    return str(get_config().vault.root)


def _check_secret(plain: dict) -> None:
    """Step 4 of the normative check order (contract §11.3): the shared LAN-secret gate for both LAN
    endpoints. Raises 403 on failure. An empty server secret must never degrade to key-only auth: this
    listener is network-exposed, and hmac.compare_digest("", "") would otherwise accept lan_secret:""
    from anyone holding the shared key but not the secret.

    LAN-17: the credential field is `lan_secret` (the LAN-plane credential from `[lan] secret`), NOT the
    GUI `secret`. LAN-19: it comes out of an attacker-shaped JSON object and may be any type;
    `hmac.compare_digest` accepts str/str only and raises TypeError on anything else -- which surfaced
    as a 500 instead of the 403 this gate exists to return. Type-check before comparing."""
    lan_secret = _lan_secret()
    if not lan_secret:
        raise HTTPException(status_code=403, detail="lan secret not configured")
    supplied = plain.get("lan_secret", "")
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, lan_secret):
        raise HTTPException(status_code=403, detail="bad secret")


def _check_nonce(plain: dict) -> None:
    """Step 5 of the normative check order (contract §11.3/§11.9): redeem a server-issued single-use
    nonce, consuming it. Called STRICTLY AFTER _check_secret so an attacker without the LAN secret can
    never burn a nonce out of the pool. Unknown/expired/reused/non-str -> 403 with no state change past
    the consume. `nonce` is attacker-shaped, so type-check before touching the pool (LAN-19 shape)."""
    nonce = plain.get("nonce", "")
    if not isinstance(nonce, str) or not _consume_nonce(nonce):
        raise HTTPException(status_code=403, detail="bad or expired nonce")


async def _read_capped_body(request: Request) -> bytes:
    """LAN-06: read the request body with a hard ceiling instead of `await request.json()`, which
    buffers whatever the peer sends. Streamed rather than trusting Content-Length, because that
    header can be absent (chunked) or simply lie."""
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_ENVELOPE_LEN:
            raise HTTPException(status_code=413, detail="envelope too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _open_plain(env) -> dict:
    """Decrypt an envelope into the JSON OBJECT the contract says it carries.

    LAN-18: the old `try` ended at the `json.loads` and every field access sat outside it, so a
    forged-but-decryptable envelope carrying a list, a bare string, or a missing key raised
    AttributeError/KeyError and became a 500. Everything a hostile peer controls belongs inside the
    guard, and every failure here is a client error."""
    try:
        plain = json.loads(lan_crypto.open_envelope(env, _lan_key()))
    except Exception:
        raise HTTPException(status_code=400, detail="undecryptable envelope")
    if not isinstance(plain, dict):
        raise HTTPException(status_code=400, detail="envelope is not an object")
    return plain


def _push_fields(plain: dict) -> tuple:
    """LAN-18: the three required `/lan/push` fields, read defensively. `body` may legitimately be
    empty; `op_id` and `note_id` may not (they key the staging file and the supersede compare)."""
    values = []
    for name, allow_empty in (("op_id", False), ("note_id", False), ("body", True)):
        value = plain.get(name)
        if not isinstance(value, str) or (not value and not allow_empty):
            raise HTTPException(status_code=400, detail=f"missing or invalid {name}")
        values.append(value)
    return tuple(values)


@router.post("/lan/push")
async def lan_push(request: Request):
    raw = await _read_capped_body(request)               # LAN-06: bounded before anything parses it
    try:
        env = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="malformed request body")
    plain = _open_plain(env)                             # LAN-18: 400, never 500, on a forged shape
    _check_secret(plain)                                 # step 4: lan_secret (403; empty -> always 403)
    _check_nonce(plain)                                  # step 5: single-use nonce, AFTER the secret
    op_id, note_id, body = _push_fields(plain)           # step 6: field validation (LAN-02/LAN-20)
    # LAN-14: stage() indexes into captures.db best-effort and used to swallow the failure entirely,
    # so a push that staged but never became chat/search-visible answered an unqualified {"ok": true}.
    # `status` carries that back so the degraded case is visible on the wire. `ok` still means
    # "staged durably" -- the phone treats HTTP status as the signal, so this is additive only.
    status: dict = {}
    try:
        ps.stage(_sync_dir(), op_id, note_id, body,
                 {"device": str(plain.get("device", "")), "modified": str(plain.get("modified", "")),
                  "staged_at": time.time()},             # epoch seconds -> TTL sweep
                 status=status)
    except ValueError as e:
        # provisional_store's op_id/note_id allowlists (B-12, LAN-07) raise ValueError on a forged
        # value. That escaped as a 500 before; it is a client error.
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "indexed": bool(status.get("indexed", False))}


@router.get("/lan/nonce")
async def lan_nonce():
    # First handshake step (contract §11.9): mint a single-use, short-TTL challenge the phone must seal
    # back into POST /lan/push or POST /lan/changes. Unauthenticated by design — a nonce is useless
    # without the shared key + lan_secret. Sealed for wire consistency (every LAN body is an envelope).
    nonce, exp = _issue_nonce()
    return lan_crypto.seal(json.dumps({"nonce": nonce, "exp": exp}), _lan_key())


@router.post("/lan/changes")
async def lan_changes(request: Request):
    # LAN-11: the sealed {lan_secret, nonce, since} auth envelope is now the POST BODY, not a ?auth=
    # query value (which leaked the replayable ciphertext into proxy/access logs and URL history). The
    # method changed GET -> POST so an old phone's GET poll gets a clean 405 -> Drive fallback, and both
    # LAN writes share one request shape. AUTH BEFORE SCAN (contract §11.3/§11.9): verify lan_secret then
    # a server-issued single-use nonce BEFORE touching the vault. Any failure 413/400/403s with no scan.
    raw = await _read_capped_body(request)               # LAN-06: bounded before anything parses it
    try:
        env = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="malformed request body")
    req = _open_plain(env)                               # LAN-18/19: 400 on a non-object envelope
    _check_secret(req)                                   # step 4: lan_secret (403; empty -> always 403)
    _check_nonce(req)                                    # step 5: single-use nonce, AFTER the secret
    # step 6: field validation, then the scan.
    try:
        since_ts = float(req.get("since", 0))
    except (TypeError, ValueError):
        since_ts = 0.0
    # LAN-09: float("nan") and float("inf") both PARSE. NaN is the dangerous one -- `mtime <= nan`
    # is False for every note, so the cursor filter at refresh_outbound() skips nothing and the
    # ENTIRE vault is served on what looks like an incremental poll. Reject rather than coerce to
    # 0.0: that coercion has the same "send everything" effect while hiding the malformed cursor.
    if not math.isfinite(since_ts):
        raise HTTPException(status_code=400, detail="since cursor must be finite")
    # LAN-24: mint the cursor BEFORE the scan. Minting it afterwards means a note touched while the
    # scan was running is newer than the cursor the phone stores, yet was not in this response
    # either -- so the next poll's `since` skips it and it is excluded permanently. An early cursor
    # can only ever re-serve a note, which the phone already handles idempotently.
    cursor = str(int(time.time()))
    # Populate the outbound feed in THIS (serving) process (refresh_outbound's other caller is the
    # single-shot mobile_sync_agent in a separate process). Scan for notes changed since the
    # phone's cursor (best-effort; Drive stays the sole canonical/version authority).
    # ponytail: re-scans the vault per poll (5s while the phone is foregrounded). Fine for a
    # same-WiFi accelerator; add an mtime-keyed cache if a vault ever holds thousands of notes.
    refresh_outbound(_vault_path(), since_ts=since_ts)
    payload = json.dumps({"cursor": cursor, "changes": _outbound})
    return lan_crypto.seal(payload, _lan_key())
