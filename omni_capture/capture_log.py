"""
capture_log.py
--------------
Audit trail for every Second Thought run.

Each successful capture upserts one row in captures.db (managed by index_writer).
The old captures.jsonl dual-write has been dropped; use `python index_writer.py
migrate --jsonl <path>` to import any existing JSONL history into the DB.

CLI usage
  python capture_log.py          # print last 20 entries
  python capture_log.py --n 50   # print last 50 entries
  python capture_log.py --stats  # category breakdown
"""

from __future__ import annotations

import sys
from datetime import datetime

from config import get_config
from models import CaptureOutput, EnrichedPayload


# ── Write ─────────────────────────────────────────────────────────────────────

def log_capture(
    output: CaptureOutput,
    enriched: EnrichedPayload,
    filepath: str,
    model: str,
) -> None:
    """Upsert one capture record into captures.db. Fails silently."""
    cfg = get_config()

    entry = {
        "timestamp":    datetime.now().isoformat(timespec="seconds"),
        "category":     output.category,
        "filename":     output.suggested_filename,
        "filepath":     filepath,
        "input_type":   enriched.input_type,
        "source_url":   enriched.source_url,
        "model":        model,
        "confidence":   round(output.confidence, 4),
        "tags":         [],
        "new_category": True if output.requires_new_category else None,
    }

    try:
        from index_writer import log_capture_db
        log_capture_db(entry, cfg.vault.root)
    except Exception as exc:
        print(f"[CaptureLog] SQLite write error: {exc}", file=sys.stderr)


# ── Read / stats ──────────────────────────────────────────────────────────────

def read_log(n: int = 20) -> list[dict]:
    """Return the last n log entries, newest first."""
    cfg = get_config()
    try:
        from index_writer import search
        return search("", cfg.vault.root, limit=n)
    except Exception as exc:
        print(f"[CaptureLog] read error: {exc}", file=sys.stderr)
        return []


def print_recent(n: int = 20) -> None:
    entries = read_log(n)
    if not entries:
        print("No captures logged yet.")
        return

    print(f"\n{'Timestamp':<22}  {'Category':<20}  {'Filename':<35}  Source")
    print("─" * 100)
    for e in entries:
        ts   = (e.get("timestamp") or "")[:19]
        cat  = (e.get("category") or "")[:19]
        fn   = ((e.get("filename") or "") + ".md")[:34]
        src  = (e.get("source_url") or e.get("input_type") or "")[:40]
        print(f"{ts:<22}  {cat:<20}  {fn:<35}  {src}")


def print_stats() -> None:
    cfg = get_config()
    try:
        from index_writer import stats
        s = stats(cfg.vault.root)
    except Exception as exc:
        print(f"[CaptureLog] stats error: {exc}", file=sys.stderr)
        return

    total = s.get("total", 0)
    if not total:
        print("No captures logged yet.")
        return

    print(f"\nTotal captures: {total}")
    print(f"\n{'Category':<25}  {'Count':>6}  {'%':>6}")
    print("─" * 45)
    for row in s.get("by_category", []):
        print(f"{row['category']:<25}  {row['count']:>6}  {row['pct']:>5.1f}%")
