"""
index_writer.py
---------------
SQLite index for every Second Thought note.

Database file:  <vault_root>/.omni_capture/captures.db

Schema
------
captures
  id          INTEGER PRIMARY KEY AUTOINCREMENT
  timestamp   TEXT NOT NULL          -- ISO-8601 seconds
  category    TEXT NOT NULL
  path        TEXT NOT NULL UNIQUE
  hash        TEXT                   -- SHA-256 of written note content
  tags        TEXT DEFAULT '[]'      -- JSON array of strings
  confidence  REAL DEFAULT 0.9
  source_url  TEXT
  input_type  TEXT
  model       TEXT
  filename    TEXT

captures_fts   (FTS5 virtual table)
  rowid -> captures.id
  body  -> category || ' ' || filename || ' ' || source_url || ' ' || tags

Public API
----------
  get_db_path(vault_root)               -> Path
  init_db(vault_root)                   -> connection (creates schema if needed)
  log_capture_db(entry, vault_root)     -> None  (upsert one row)
  migrate_jsonl(jsonl_path, vault_root) -> int   (rows inserted)
  search(query, vault_root, ...)        -> list[dict]
  stats(vault_root)                     -> dict
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Path helpers ──────────────────────────────────────────────────────────────

def get_db_path(vault_root: Path) -> Path:
    return vault_root / ".omni_capture" / "captures.db"


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS captures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    path        TEXT    NOT NULL UNIQUE,
    hash        TEXT,
    tags        TEXT    DEFAULT '[]',
    confidence  REAL    DEFAULT 0.9,
    source_url  TEXT,
    input_type  TEXT,
    model       TEXT,
    filename    TEXT
);

CREATE INDEX IF NOT EXISTS idx_captures_timestamp ON captures(timestamp);
CREATE INDEX IF NOT EXISTS idx_captures_category  ON captures(category);

CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
    body,
    content=captures,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS captures_ai AFTER INSERT ON captures BEGIN
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'')
    );
END;

CREATE TRIGGER IF NOT EXISTS captures_ad AFTER DELETE ON captures BEGIN
    INSERT INTO captures_fts(captures_fts, rowid, body)
    VALUES ('delete', old.id,
        COALESCE(old.category,'') || ' ' ||
        COALESCE(old.filename,'') || ' ' ||
        COALESCE(old.source_url,'') || ' ' ||
        COALESCE(old.tags,'')
    );
END;

CREATE TRIGGER IF NOT EXISTS captures_au AFTER UPDATE ON captures BEGIN
    INSERT INTO captures_fts(captures_fts, rowid, body)
    VALUES ('delete', old.id,
        COALESCE(old.category,'') || ' ' ||
        COALESCE(old.filename,'') || ' ' ||
        COALESCE(old.source_url,'') || ' ' ||
        COALESCE(old.tags,'')
    );
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'')
    );
END;
"""


def init_db(vault_root: Path) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at the canonical path.
    Applies the schema if it is a fresh file.
    Returns the open connection — caller is responsible for closing it.
    """
    db_path = get_db_path(vault_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # executescript handles multi-statement DDL including trigger bodies
    conn.executescript(_DDL)
    return conn


# ── Content hash ──────────────────────────────────────────────────────────────

def _file_hash(path: str) -> Optional[str]:
    """SHA-256 of the note file at *path*, or None if the file doesn't exist."""
    try:
        data = Path(path).read_bytes()
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


# ── Write ─────────────────────────────────────────────────────────────────────

def log_capture_db(entry: dict, vault_root: Path) -> None:
    """
    Upsert one capture record.

    *entry* mirrors the JSONL schema produced by capture_log.py, plus optional
    ``tags`` (list[str]) and ``confidence`` (float) keys.

    Fails silently — a DB error must never break the capture pipeline.
    """
    try:
        conn = init_db(vault_root)
        tags = json.dumps(entry.get("tags") or [])
        h    = _file_hash(entry.get("filepath", ""))

        conn.execute(
            """
            INSERT INTO captures
                (timestamp, category, path, hash, tags, confidence,
                 source_url, input_type, model, filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash       = excluded.hash,
                tags       = excluded.tags,
                confidence = excluded.confidence,
                model      = excluded.model,
                timestamp  = excluded.timestamp
            """,
            (
                entry.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                entry.get("category", ""),
                entry.get("filepath", ""),
                h,
                tags,
                float(entry.get("confidence", 0.9)),
                entry.get("source_url"),
                entry.get("input_type"),
                entry.get("model"),
                entry.get("filename"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[IndexWriter] Non-fatal DB error: {exc}", file=sys.stderr)


# ── Migration ─────────────────────────────────────────────────────────────────

def migrate_jsonl(jsonl_path: Path, vault_root: Path) -> int:
    """
    One-shot import of an existing captures.jsonl into captures.db.
    Skips rows already present (by path).
    Returns the number of new rows inserted.
    """
    if not jsonl_path.exists():
        print(f"[IndexWriter] JSONL not found at {jsonl_path} — nothing to migrate.")
        return 0

    conn     = init_db(vault_root)
    cursor   = conn.cursor()
    inserted = 0

    with open(jsonl_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[IndexWriter] Skipping malformed line {line_no}: {exc}", file=sys.stderr)
                continue

            filepath = entry.get("filepath", "")
            if not filepath:
                continue

            row = cursor.execute(
                "SELECT id FROM captures WHERE path = ?", (filepath,)
            ).fetchone()
            if row:
                continue

            tags = json.dumps(entry.get("tags") or [])
            h    = _file_hash(filepath)

            cursor.execute(
                """
                INSERT OR IGNORE INTO captures
                    (timestamp, category, path, hash, tags, confidence,
                     source_url, input_type, model, filename)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.get("timestamp", ""),
                    entry.get("category", ""),
                    filepath,
                    h,
                    tags,
                    float(entry.get("confidence", 0.9)),
                    entry.get("source_url"),
                    entry.get("input_type"),
                    entry.get("model"),
                    entry.get("filename"),
                ),
            )
            inserted += cursor.rowcount

    conn.commit()
    conn.close()
    print(f"[IndexWriter] Migration complete — {inserted} rows inserted from {jsonl_path}.")
    return inserted


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    query: str,
    vault_root: Path,
    category: Optional[str] = None,
    since: Optional[str]    = None,
    limit: int              = 25,
) -> list[dict]:
    """
    Full-text search over captures.  Returns up to *limit* rows, newest first.

    Parameters
    ----------
    query     FTS5 query string (supports prefix/phrase matching).
    category  Optional category filter.
    since     ISO-8601 timestamp lower-bound (inclusive).
    limit     Max rows to return.
    """
    conn   = init_db(vault_root)
    cursor = conn.cursor()

    if query.strip():
        sql = """
            SELECT c.*
            FROM captures c
            JOIN captures_fts fts ON fts.rowid = c.id
            WHERE captures_fts MATCH ?
        """
        params: list = [_sanitize_fts_query(query)]
        if category:
            sql    += " AND c.category = ?"
            params.append(category)
        if since:
            sql    += " AND c.timestamp >= ?"
            params.append(since)
    else:
        sql    = "SELECT * FROM captures WHERE 1=1"
        params = []
        if category:
            sql    += " AND category = ?"
            params.append(category)
        if since:
            sql    += " AND timestamp >= ?"
            params.append(since)

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        rows = cursor.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def _sanitize_fts_query(query: str) -> str:
    """
    Turn free-text user input into a safe FTS5 query: each whitespace-separated
    token is wrapped in double quotes (embedded quotes doubled) so that FTS5
    metacharacters (``"`` ``*`` ``:`` ``(`` ``)`` ``AND``/``OR``/``NOT``, ``c++``,
    etc.) are treated as literal text rather than query syntax. Implicit AND
    joins the tokens.
    """
    tokens = query.split()
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


# ── Stats ─────────────────────────────────────────────────────────────────────

def stats(vault_root: Path) -> dict:
    """
    Return aggregated statistics for the dashboard.

    Shape
    -----
    {
      "total": int,
      "by_category": [{"category": str, "count": int, "pct": float}, ...],
      "by_day": [{"date": str, "count": int}, ...],   # last 30 days
      "recent": [<row dict>, ...]                      # last 10
    }
    """
    conn   = init_db(vault_root)
    cursor = conn.cursor()

    total_row = cursor.execute("SELECT COUNT(*) FROM captures").fetchone()
    total     = total_row[0] if total_row else 0

    cat_rows = cursor.execute(
        "SELECT category, COUNT(*) AS cnt FROM captures GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    by_category = [
        {
            "category": r["category"],
            "count":    r["cnt"],
            "pct":      round(r["cnt"] / total * 100, 1) if total else 0,
        }
        for r in cat_rows
    ]

    day_rows = cursor.execute(
        """
        SELECT substr(timestamp,1,10) AS date, COUNT(*) AS cnt
        FROM captures
        WHERE timestamp >= date('now','-30 days')
        GROUP BY date
        ORDER BY date DESC
        """
    ).fetchall()
    by_day = [{"date": r["date"], "count": r["cnt"]} for r in day_rows]

    recent_rows = cursor.execute(
        "SELECT * FROM captures ORDER BY timestamp DESC LIMIT 10"
    ).fetchall()
    recent = [dict(r) for r in recent_rows]

    conn.close()
    return {"total": total, "by_category": by_category, "by_day": by_day, "recent": recent}


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    from config import get_config

    p = argparse.ArgumentParser(description="Second Thought SQLite index tool.")
    sub = p.add_subparsers(dest="cmd")

    m = sub.add_parser("migrate", help="Import existing captures.jsonl into captures.db")
    m.add_argument("--jsonl", type=Path, help="Path to captures.jsonl (default: from config)")

    s = sub.add_parser("search", help="Full-text search")
    s.add_argument("query", help="FTS query")
    s.add_argument("--category", default=None)
    s.add_argument("--limit", type=int, default=20)

    sub.add_parser("stats", help="Print capture statistics")

    args = p.parse_args()
    cfg  = get_config()

    if args.cmd == "migrate":
        jsonl = args.jsonl or cfg.log.path
        if not jsonl:
            print("No JSONL path available.")
            sys.exit(1)
        migrate_jsonl(jsonl, cfg.vault.root)

    elif args.cmd == "search":
        results = search(args.query, cfg.vault.root, args.category, limit=args.limit)
        if not results:
            print("No results.")
        for r in results:
            print(f"{r['timestamp'][:19]}  [{r['category']:<20}]  {r['path']}")

    elif args.cmd == "stats":
        s = stats(cfg.vault.root)
        print(f"\nTotal captures: {s['total']}")
        print(f"\n{'Category':<25}  {'Count':>6}  {'%':>6}")
        print("-" * 45)
        for row in s["by_category"]:
            print(f"{row['category']:<25}  {row['count']:>6}  {row['pct']:>5.1f}%")
    else:
        p.print_help()
