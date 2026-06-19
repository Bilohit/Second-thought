"""
capture_log.py
--------------
Dual-write audit trail for every Second Thought run.

Each successful capture:
  1. Appends one JSON line to captures.jsonl  (legacy, transition period)
  2. Upserts one row in captures.db           (new SQLite index)

The log path is configured in config.toml → [log] path.
The DB lives at <vault_root>/.omni_capture/captures.db (managed by index_writer).

Log entry schema
  timestamp   ISO-8601 datetime of the capture
  category    CRM | Tech_Notes | Finance | …
  filename    suggested_filename (without .md)
  filepath    absolute path written to
  input_type  text | url_web | url_github | url_youtube | image | audio
  source_url  original URL (null for plain text/image)
  model       Ollama model used
  confidence  LLM confidence score (0-1)
  new_category  true when content needs review in scratchpad, else null

CLI usage
  python capture_log.py          # print last 20 entries
  python capture_log.py --n 50   # print last 50 entries
  python capture_log.py --stats  # category breakdown
  python capture_log.py --migrate  # one-shot JSONL → SQLite import
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import get_config
from models import CaptureOutput, EnrichedPayload


# ── Write ─────────────────────────────────────────────────────────────────────

def log_capture(
    output: CaptureOutput,
    enriched: EnrichedPayload,
    filepath: str,
    model: str,
) -> None:
    """
    Dual-write: append to captures.jsonl AND upsert into captures.db.
    Fails silently — a logging error must never break the capture pipeline.
    """
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

    # 1 — JSONL (legacy transition)
    if cfg.log.path:
        try:
            cfg.log.path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg.log.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            print(f"[CaptureLog] JSONL write error: {exc}", file=sys.stderr)

    # 2 — SQLite index (new)
    try:
        from index_writer import log_capture_db
        log_capture_db(entry, cfg.vault.root)
    except Exception as exc:
        print(f"[CaptureLog] SQLite write error: {exc}", file=sys.stderr)


# ── Read / stats ──────────────────────────────────────────────────────────────

def read_log(n: int = 20) -> list[dict]:
    """Return the last n log entries, newest first."""
    cfg = get_config()
    if not cfg.log.path or not cfg.log.path.exists():
        return []

    lines = cfg.log.path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return list(reversed(entries[-n:]))


def print_recent(n: int = 20) -> None:
    entries = read_log(n)
    if not entries:
        print("No captures logged yet.")
        return

    print(f"\n{'Timestamp':<22}  {'Category':<20}  {'Filename':<35}  Source")
    print("─" * 100)
    for e in entries:
        ts   = e.get("timestamp", "")[:19]
        cat  = e.get("category", "")[:19]
        fn   = (e.get("filename", "") + ".md")[:34]
        src  = (e.get("source_url") or e.get("input_type", ""))[:40]
        print(f"{ts:<22}  {cat:<20}  {fn:<35}  {src}")


def print_stats() -> None:
    all_entries = read_log(n=10_000)
    if not all_entries:
        print("No captures logged yet.")
        return

    from collections import Counter
    counts = Counter(e.get("category", "unknown") for e in all_entries)
    total  = sum(counts.values())

    print(f"\nTotal captures: {total}")
    print(f"\n{'Category':<25}  {'Count':>6}  {'%':>6}")
    print("─" * 45)
    for cat, count in counts.most_common():
        pct = count / total * 100
        print(f"{cat:<25}  {count:>6}  {pct:>5.1f}%")


