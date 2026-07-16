"""LAN provisional staging (contract §11) — a display/index overlay. NEVER writes canonical state.

Layout under <sync_dir>:
  provisional/<op_id>.md          exact received note bytes (body sacred)
  provisional_state.json          [{op_id, note_id, body_hash, staged_at, device, modified}]
"""
import json
import os
import re
from note_hash import body_hash

_STATE = "provisional_state.json"
_DIR = "provisional"
# B-12: a LAN-supplied op_id becomes `<op_id>.md` on disk (stage() below). A forged push with an
# op_id like "../../evil" or an absolute path must never escape the staging dir — restrict to a
# safe basename before it ever touches the filesystem.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_op_id(op_id: str) -> str:
    if not isinstance(op_id, str) or not _SAFE_ID_RE.match(op_id):
        raise ValueError(f"unsafe op_id: {op_id!r}")
    return op_id


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
    op_id = _validate_op_id(op_id)                    # B-12: reject a path-traversal/forged op_id
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

    # B-10: index the provisional row into captures.db so a LAN-delivered note is chat/search
    # visible BEFORE Drive confirms it (contract §11). The production call site for
    # index_writer.upsert_provisional was missing (only the test fixture called it) — wire it in
    # here, the nearest module boundary both stage() callers (the /lan/push handler and any future
    # caller) share, rather than inside the POST/GET LAN handlers themselves. Best-effort: a
    # failure here must never fail the (already-durable) staging above.
    # sync_dir is `<vault_root>/.sync` (config.py:Config.vault_sync_dir()) — vault_root is its
    # parent, which is where captures.db lives (index_writer.get_db_path).
    try:
        from pathlib import Path

        import index_writer as iw

        vault_root = Path(sync_dir).parent
        db = iw.init_db(vault_root)
        try:
            iw.upsert_provisional(db, op_id, note_id, body, meta or {})
        finally:
            db.close()
    except Exception as e:
        print(f"[provisional_store] upsert_provisional failed for {op_id}: {e}")

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
