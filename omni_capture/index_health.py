"""
index_health.py
----------------
In-process "last outcome" flag for the derived search indexes (captures.db
FTS5 via index_writer.py, vectors.db embeddings via vector_store.py).

Files are the source of truth for this app; these two SQLite databases are
caches rebuilt from the vault's .md files (see CLAUDE.md "Files are the
source of truth" hard rule). A failed index write must never block a
capture, so every write already swallows its own exceptions at the call
site. This module only *observes* those existing swallow points -- record_ok
/ record_failure are called from inside the existing except blocks -- so a
silently-degraded index doesn't go unnoticed forever. It does not change
when, whether, or how any write happens, and it holds no authority over
anything: losing this state (e.g. process restart) is harmless.

Zero heavy imports (stdlib datetime only) so importing this module is
always free -- safe to import from --self-check or /health before anything
else (Ollama, sqlite3, numpy/torch) has loaded.

Public API
----------
  record_ok(index)         -> None   call from the success path of an index write
  record_failure(index, err) -> None call from the except block of an index write
  snapshot()               -> dict[str, dict]   {"captures": {...}, "vectors": {...}}
  degraded()                -> bool  True if any known index's last write failed
"""
from __future__ import annotations

from datetime import datetime, timezone

# Known indexes this module tracks. Not a hard allowlist -- record_ok/
# record_failure will happily track any string passed in -- just the set
# pre-seeded so snapshot() has a stable shape before any write has happened.
_KNOWN_INDEXES = ("captures", "vectors")

_state: dict[str, dict] = {
    name: {"ok": True, "error": None, "timestamp": None} for name in _KNOWN_INDEXES
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_ok(index: str) -> None:
    """Mark *index*'s most recent write as successful. Must never raise --
    this is called from hot capture-pipeline paths."""
    try:
        _state[index] = {"ok": True, "error": None, "timestamp": _now()}
    except Exception:
        pass


def record_failure(index: str, err: object) -> None:
    """Mark *index*'s most recent write as failed. Must never raise --
    this is called from inside existing swallow-the-exception blocks, so a
    bug here must not turn a soft failure into a hard one."""
    try:
        _state[index] = {"ok": False, "error": str(err), "timestamp": _now()}
    except Exception:
        pass


def snapshot() -> dict[str, dict]:
    """Shallow copy of current per-index state, safe to serialize to JSON."""
    try:
        return {k: dict(v) for k, v in _state.items()}
    except Exception:
        return {}


def degraded() -> bool:
    """True if any known index's last recorded write outcome was a failure."""
    try:
        return any(not v.get("ok", True) for v in _state.values())
    except Exception:
        return False


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # T1: fresh state is healthy
    assert degraded() is False, "fresh state should not be degraded"
    print("[T1] Fresh state healthy  PASS")

    # T2: record_failure flips degraded() and is visible in snapshot()
    record_failure("vectors", RuntimeError("disk full"))
    snap = snapshot()
    assert snap["vectors"]["ok"] is False
    assert snap["vectors"]["error"] == "disk full"
    assert degraded() is True
    print("[T2] record_failure reports degraded  PASS")

    # T3: the other index is unaffected
    assert snap["captures"]["ok"] is True
    print("[T3] Independent per-index state  PASS")

    # T4: record_ok clears the failure
    record_ok("vectors")
    assert degraded() is False
    assert snapshot()["vectors"]["error"] is None
    print("[T4] record_ok clears degraded  PASS")

    # T5: record_failure/record_ok never raise, even with odd input
    record_failure(None, object())      # type: ignore[arg-type]
    record_ok(123)                      # type: ignore[arg-type]
    print("[T5] Defensive against bad input  PASS")

    print("\nAll index_health.py smoke tests passed.")
