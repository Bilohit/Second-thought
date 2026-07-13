"""LAN provisional staging (contract §11) — a display/index overlay. NEVER writes canonical state.

Layout under <sync_dir>:
  provisional/<op_id>.md          exact received note bytes (body sacred)
  provisional_state.json          [{op_id, note_id, body_hash, staged_at, device, modified}]
"""
import json
import os
from note_hash import body_hash

_STATE = "provisional_state.json"
_DIR = "provisional"


def _dir(sync_dir: str) -> str:
    d = os.path.join(sync_dir, _DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _state_path(sync_dir: str) -> str:
    return os.path.join(sync_dir, _STATE)


def _load_state(sync_dir: str) -> list:
    try:
        with open(_state_path(sync_dir), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_state(sync_dir: str, rows: list) -> None:
    os.makedirs(sync_dir, exist_ok=True)
    tmp = _state_path(sync_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    os.replace(tmp, _state_path(sync_dir))   # atomic


def stage(sync_dir: str, op_id: str, note_id: str, body: str, meta: dict):
    bh = body_hash(body)
    rows = _load_state(sync_dir)
    if any(r["note_id"] == note_id and r["body_hash"] == bh for r in rows):
        return None                                   # idempotent: same note_id+body-hash already staged
    path = os.path.join(_dir(sync_dir), f"{op_id}.md")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)                                 # exact bytes; body sacred
    rows.append({
        "op_id": op_id, "note_id": note_id, "body_hash": bh,
        # staged_at is epoch seconds (numeric); the LAN endpoint passes time.time()
        "staged_at": float(meta.get("staged_at", 0.0)),
        "device": meta.get("device", ""), "modified": meta.get("modified", ""),
    })
    _save_state(sync_dir, rows)
    return path


def list_provisional(sync_dir: str) -> list:
    out = []
    for r in _load_state(sync_dir):
        r = dict(r)
        r["path"] = os.path.join(_dir(sync_dir), f"{r['op_id']}.md")
        out.append(r)
    return out


def read_body(sync_dir: str, op_id: str) -> str:
    with open(os.path.join(_dir(sync_dir), f"{op_id}.md"), encoding="utf-8", newline="") as f:
        return f.read()


def _drop(sync_dir: str, keep_pred) -> list:
    rows = _load_state(sync_dir)
    dropped, kept = [], []
    for r in rows:
        if keep_pred(r):
            kept.append(r)
        else:
            dropped.append(r["op_id"])
            try:
                os.remove(os.path.join(_dir(sync_dir), f"{r['op_id']}.md"))
            except FileNotFoundError:
                pass
    _save_state(sync_dir, kept)
    return dropped


def supersede(sync_dir: str, note_id: str) -> list:
    """Drive canonical for note_id arrived → drop every provisional for it (contract §11.2)."""
    return _drop(sync_dir, lambda r: r["note_id"] != note_id)


def sweep(sync_dir: str, now_ts: float, ttl_seconds: float) -> list:
    """Discard orphan provisionals older than the TTL (contract §11.6)."""
    cutoff = now_ts - ttl_seconds
    return _drop(sync_dir, lambda r: float(r.get("staged_at") or 0) > cutoff)
