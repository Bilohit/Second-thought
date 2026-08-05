"""
sync_activity.py — Phase-1 Task 1.2: the SYNC panel's activity feed.

Read-only shaping over `capture_log.read_log(n)` (which is
`index_writer.search("", vault_root, limit=n)` — a blank query, so rows come
back `ORDER BY timestamp DESC, id DESC`, i.e. newest first). Nothing here
writes, and nothing here touches Drive.

What this feed deliberately is NOT: `sync_scheduler.status()["history"]` rows
are pass-level AGGREGATE COUNTS (uploaded/reconciled/conflicts/pulled/…) with
no note ids attached. Folding them in as if each were an event would invent
rows that never existed. The pass strip is a separate region of the panel and
reads `/sync/status` directly.

Two honest limits on what a captures.db row means, both surfaced rather than
smoothed over:

  * `kind` — captures.db is keyed by `path` and written by TWO paths.
    `capture_log.log_capture`/`log_capture_failure` write the pipeline-only
    columns (`input_type`, `model`, `source_url`, `confidence`); the vault
    reindexer `index_writer.upsert_capture_from_file` writes rows for plain
    `origin: note` files and never sets those columns (its ON CONFLICT clause
    updates only hash/body_excerpt/timestamp/tags/project). So a row with an
    `input_type` is a real capture EVENT; a row without one is a vault file the
    indexer saw. The feed labels which is which instead of calling both
    "activity".

  * `at` is not an immutable event time. A reindex overwrites a row's
    `timestamp` with the file's mtime (index_writer.py's "File mtime, not
    wall-clock now" comment). See the ponytail below.
"""
from __future__ import annotations

# The GUI asks for a page; the server decides the ceiling. A caller-supplied
# limit is clamped here so no client can turn this into a full-table dump.
DEFAULT_LIMIT = 25
MAX_LIMIT = 200


def _clamp_limit(limit: int) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if n < 1:
        return 1
    return min(n, MAX_LIMIT)


def _shape_row(row: dict) -> dict:
    """One captures.db row -> one activity event.

    `kind` is derived from the pipeline-only columns (see the module docstring),
    never guessed from the path. `status` marks the `log_capture_failure` shape
    (a capture that was logged with no resulting filename)."""
    input_type = row.get("input_type")
    kind = "capture" if input_type else "note"
    return {
        # ponytail: `at` is captures.db's `timestamp`, which a vault reindex
        # rewrites to the file's mtime — so an old capture that got re-indexed
        # can move in this feed. Ceiling accepted because captures.db is a
        # derived cache by the workspace lock and the files are the truth.
        # Upgrade path: give captures.db a separate append-only `event_at`
        # column that only log_capture writes, and order on that instead.
        "at":         row.get("timestamp"),
        "kind":       kind,
        "status":     "failed" if kind == "capture" and not row.get("filename") else "ok",
        "project":    row.get("project"),
        "path":       row.get("path"),
        "filename":   row.get("filename"),
        "input_type": input_type,
        "source_url": row.get("source_url"),
        "model":      row.get("model"),
        "confidence": row.get("confidence"),
    }


def read_activity(limit: int = DEFAULT_LIMIT) -> dict:
    """Newest-first activity events, bounded by a clamped `limit`.

    Resolves the vault through `capture_log.read_log`, which reads
    `get_config().vault.root` — the same single source of truth
    `server._get_vault_root()` returns. A corrupt/absent captures.db degrades to
    an empty list inside index_writer (files are the truth), never a 500."""
    n = _clamp_limit(limit)
    from capture_log import read_log
    rows = read_log(n)
    events = [_shape_row(r) for r in rows]
    return {"events": events, "count": len(events), "limit": n}


# ---------------------------------------------------------------------------
# Smoke test  (python sync_activity.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-5) == 1
    assert _clamp_limit(10_000) == MAX_LIMIT
    assert _clamp_limit("nope") == DEFAULT_LIMIT

    cap = _shape_row({"timestamp": "2026-08-06T10:00:00", "input_type": "url",
                      "filename": "a", "path": "/v/P/a.md", "model": "m"})
    assert cap["kind"] == "capture" and cap["status"] == "ok"

    fail = _shape_row({"timestamp": "2026-08-06T10:00:01", "input_type": "text",
                       "filename": None, "path": "/v/_scratchpad/x.md"})
    assert fail["kind"] == "capture" and fail["status"] == "failed"

    note = _shape_row({"timestamp": "2026-08-06T10:00:02", "path": "/v/P/n.md",
                       "filename": "n.md"})
    assert note["kind"] == "note" and note["status"] == "ok"

    print("All sync_activity.py smoke tests passed.")
