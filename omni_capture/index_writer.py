"""
index_writer.py
---------------
SQLite index for every Second Thought note.

Database file:  <vault_root>/.omni_capture/captures.db

Schema
------
captures
  id            INTEGER PRIMARY KEY AUTOINCREMENT
  timestamp     TEXT NOT NULL          -- ISO-8601 seconds
  category      TEXT NOT NULL
  path          TEXT NOT NULL UNIQUE
  hash          TEXT                   -- SHA-256 of written note content
  tags          TEXT DEFAULT '[]'      -- JSON array of strings
  confidence    REAL DEFAULT 0.9
  source_url    TEXT
  input_type    TEXT
  model         TEXT
  filename      TEXT
  body_excerpt  TEXT                   -- note body, frontmatter stripped, capped ~65536 chars
  provisional   INTEGER DEFAULT 0      -- 1 = LAN provisional overlay row (contract §11); search/RAG
                                        -- display ONLY, never dedup/merge/link authority (files are
                                        -- the source of truth)
  note_id       TEXT                   -- set only on provisional rows (LAN PushPlain.note_id)

captures_fts   (FTS5 virtual table)
  rowid -> captures.id
  body  -> category || ' ' || filename || ' ' || source_url || ' ' || tags || ' ' || body_excerpt
  (stored internally — not content=captures, which requires a captures.body column)

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
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from frontmatter import strip_frontmatter
from tag_index import parse_tags, resolve_paths
import index_health

# ponytail: 64k cap; raise or chunk FTS if vault notes routinely exceed this
_BODY_EXCERPT_MAX_CHARS = 65536

_INITIALIZED: set[str] = set()  # db paths whose schema has been set up this process
_BODY_INDEX_META_KEY = f"body_indexed_v{_BODY_EXCERPT_MAX_CHARS}"


# ── Path helpers ──────────────────────────────────────────────────────────────

def get_db_path(vault_root: Path) -> Path:
    return vault_root / ".omni_capture" / "captures.db"


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS captures (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    path          TEXT    NOT NULL UNIQUE,
    hash          TEXT,
    tags          TEXT    DEFAULT '[]',
    confidence    REAL    DEFAULT 0.9,
    source_url    TEXT,
    input_type    TEXT,
    model         TEXT,
    filename      TEXT,
    body_excerpt  TEXT,
    provisional   INTEGER NOT NULL DEFAULT 0,
    note_id       TEXT
);

CREATE INDEX IF NOT EXISTS idx_captures_timestamp ON captures(timestamp);
CREATE INDEX IF NOT EXISTS idx_captures_category  ON captures(category);

CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
    body
);

CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Trigger bodies must stay in sync with the captures_fts concatenation used
# by _row_fts_body() below. captures_fts is a standard (internal-storage)
# FTS5 table, so row removal uses a plain DELETE -- NOT the external-content
# 'delete' command, which raises "SQL logic error" on an internal table.
# Re-CREATE'd unconditionally (not IF NOT EXISTS) because existing databases
# already have older trigger versions installed under these names.
_TRIGGERS_DDL = """
DROP TRIGGER IF EXISTS captures_ai;
DROP TRIGGER IF EXISTS captures_ad;
DROP TRIGGER IF EXISTS captures_au;

CREATE TRIGGER captures_ai AFTER INSERT ON captures BEGIN
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'') || ' ' ||
        COALESCE(new.body_excerpt,'')
    );
END;

CREATE TRIGGER captures_ad AFTER DELETE ON captures BEGIN
    DELETE FROM captures_fts WHERE rowid = old.id;
END;

CREATE TRIGGER captures_au AFTER UPDATE ON captures BEGIN
    DELETE FROM captures_fts WHERE rowid = old.id;
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'') || ' ' ||
        COALESCE(new.body_excerpt,'')
    );
END;
"""


def _row_fts_body(
    category: str | None,
    filename: str | None,
    source_url: str | None,
    tags: str | None,
    body_excerpt: str | None,
) -> str:
    return (
        f"{category or ''} "
        f"{filename or ''} "
        f"{source_url or ''} "
        f"{tags or ''} "
        f"{body_excerpt or ''}"
    )


def _migrate_fts_internal(conn: sqlite3.Connection) -> None:
    """Rebuild FTS without external content= — old schema pointed at captures.body which does not exist."""
    flag = conn.execute(
        "SELECT value FROM _meta WHERE key = 'fts_internal_storage'"
    ).fetchone()
    if flag and flag[0] == "1":
        return

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='captures_fts'"
    ).fetchone()
    if not row or not row[0] or "content=" not in row[0].lower():
        conn.execute(
            "INSERT INTO _meta (key, value) VALUES ('fts_internal_storage', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        return

    rows = conn.execute(
        "SELECT id, category, filename, source_url, tags, body_excerpt FROM captures"
    ).fetchall()

    conn.executescript(
        """
        DROP TRIGGER IF EXISTS captures_ai;
        DROP TRIGGER IF EXISTS captures_ad;
        DROP TRIGGER IF EXISTS captures_au;
        DROP TABLE IF EXISTS captures_fts;
        CREATE VIRTUAL TABLE captures_fts USING fts5(body);
        """
    )

    for r in rows:
        body = _row_fts_body(
            r["category"], r["filename"], r["source_url"], r["tags"], r["body_excerpt"],
        )
        conn.execute(
            "INSERT INTO captures_fts(rowid, body) VALUES (?, ?)",
            (r["id"], body),
        )

    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('fts_internal_storage', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = '1'"
    )
    print("[IndexWriter] migrated captures_fts to internal storage", flush=True)


def _rebuild_fts_once(conn: sqlite3.Connection) -> None:
    """Heal existing FTS rows that went stale while the AFTER UPDATE/DELETE
    triggers were broken (see H7). Runs exactly once per vault, gated by a
    _meta flag. Safe to call on every init.

    ponytail: full DELETE + re-INSERT of every row. Fine for the small vaults
    this app targets; if a vault ever holds 100k+ notes, switch to a
    diff-based rebuild keyed on captures.hash.
    """
    flag = conn.execute(
        "SELECT value FROM _meta WHERE key = 'fts_rebuilt_trigger_fix_v1'"
    ).fetchone()
    if flag and flag[0] == "1":
        return

    rows = conn.execute(
        "SELECT id, category, filename, source_url, tags, body_excerpt FROM captures"
    ).fetchall()
    conn.execute("DELETE FROM captures_fts")
    for r in rows:
        body = _row_fts_body(
            r["category"], r["filename"], r["source_url"], r["tags"], r["body_excerpt"],
        )
        conn.execute(
            "INSERT INTO captures_fts(rowid, body) VALUES (?, ?)",
            (r["id"], body),
        )
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('fts_rebuilt_trigger_fix_v1', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = '1'"
    )
    print(f"[IndexWriter] rebuilt captures_fts ({len(rows)} rows) after trigger fix", flush=True)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema upgrade for databases created before body_excerpt
    existed: adds the column if missing and unconditionally re-installs the
    FTS triggers so they pick up the new concatenation (CREATE TRIGGER IF NOT
    EXISTS in _DDL would silently keep the stale ones).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(captures)").fetchall()}
    if "body_excerpt" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN body_excerpt TEXT")
    if "provisional" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0")
    if "note_id" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN note_id TEXT")
    _migrate_fts_internal(conn)
    conn.commit()
    conn.executescript(_TRIGGERS_DDL)
    conn.commit()
    _rebuild_fts_once(conn)
    conn.commit()


def init_db(vault_root: Path) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at the canonical path.
    Applies the schema on first call per vault path (within the process);
    subsequent calls skip the DDL/migration overhead.
    Returns the open connection — caller is responsible for closing it.
    """
    db_path = get_db_path(vault_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    key = str(db_path)
    if key not in _INITIALIZED:
        conn.executescript(_DDL)
        _migrate_schema(conn)
        _INITIALIZED.add(key)

    return conn


def heal_corrupt_db(vault_root: Path) -> bool:
    """Discard captures.db if it is unreadable, so the caller can re-create it.

    captures.db is a derived cache — every byte of it is reconstructible from the
    vault .md files — so deleting an unreadable one is the sanctioned recovery, not
    data loss. A truncated/half-flushed/bad-sector file raises
    sqlite3.DatabaseError("file is not a database") on the first real read; that used
    to land in vault_sync.sync_vault_indexes' blanket `except Exception`, which
    printed and returned a success-shaped {"added": 0}, leaving the index dead until
    a human deleted the file by hand.

    Returns True if a corrupt db was discarded. Detection must run BEFORE init_db.

    OperationalError is deliberately caught FIRST and never heals. It is a subclass
    of DatabaseError, but it is what a HEALTHY db raises when it is merely
    unavailable -- SQLITE_BUSY/SQLITE_LOCKED under a concurrent writer, a
    permissions fault, an unwritable temp dir. Corruption (SQLITE_NOTADB "file is
    not a database", SQLITE_CORRUPT "database disk image is malformed") surfaces as
    a plain DatabaseError, so the split is exact. Without it, "unreadable" meant
    "unlink it" and a busy-but-intact index could be destroyed: today WAL
    (init_db's journal_mode) keeps readers from ever blocking and the unlink's
    OSError branch catches the rest, but both are incidental -- deleting a healthy
    user index must not rest on an unstated invariant holding.
    """
    db_path = get_db_path(vault_root)
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            # Touches the schema pages -- connect() alone does not read the file.
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
        return False
    except sqlite3.OperationalError as exc:
        # Unavailable, not corrupt -- stay fail-soft and leave the file alone. The
        # caller proceeds to init_db, which surfaces the same condition honestly.
        print(f"[IndexWriter] captures.db unavailable ({exc}) -- leaving it intact; "
              "this is not corruption", file=sys.stderr, flush=True)
        index_health.record_failure("captures", exc)
        return False
    except sqlite3.DatabaseError as exc:
        print(f"[IndexWriter] captures.db unreadable ({exc}) -- discarding the corrupt "
              "derived cache; it rebuilds from the vault files", file=sys.stderr, flush=True)
        try:
            db_path.unlink()
            # A stale -wal/-shm can resurrect the pages we just destroyed.
            for extra in db_path.parent.glob(db_path.name + "-*"):
                extra.unlink()
        except OSError as unlink_exc:   # locked by another process -- stay fail-soft
            print(f"[IndexWriter] could not discard corrupt captures.db: {unlink_exc}",
                  file=sys.stderr, flush=True)
            index_health.record_failure("captures", exc)
            return False
        _INITIALIZED.discard(str(db_path))   # force init_db to re-apply the DDL
        return True


# ── Content hash ──────────────────────────────────────────────────────────────

def _file_hash(path: str) -> Optional[str]:
    """SHA-256 of the note file at *path*, or None if the file doesn't exist."""
    try:
        data = Path(path).read_bytes()
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


def _read_body_excerpt(path: str) -> Optional[str]:
    """
    Read the note at *path*, strip leading YAML frontmatter, collapse
    whitespace, and cap to _BODY_EXCERPT_MAX_CHARS. Returns None on any
    read error -- this must never raise (callers index it best-effort).
    """
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    text = re.sub(r"\s+", " ", strip_frontmatter(text)).strip()
    return text[:_BODY_EXCERPT_MAX_CHARS] if text else None


def _read_file_tags(path: Path) -> list[str]:
    """The note's frontmatter tags, or [] on any read error -- like
    _read_body_excerpt, this must never raise (callers index best-effort)."""
    try:
        return parse_tags(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


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
        body = _read_body_excerpt(entry.get("filepath", ""))

        conn.execute(
            """
            INSERT INTO captures
                (timestamp, category, path, hash, tags, confidence,
                 source_url, input_type, model, filename, body_excerpt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash         = excluded.hash,
                tags         = excluded.tags,
                confidence   = excluded.confidence,
                model        = excluded.model,
                timestamp    = excluded.timestamp,
                body_excerpt = excluded.body_excerpt
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
                body,
            ),
        )
        conn.commit()
        conn.close()
        index_health.record_ok("captures")
    except Exception as exc:
        print(f"[IndexWriter] Non-fatal DB error: {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)


# ── One-time body reindex ───────────────────────────────────────────────────

def reindex_bodies(vault_root: Path) -> int:
    """
    One-time backfill of body_excerpt for rows written before this column
    existed. Gated by a _meta flag so it only does real work once per vault;
    safe to call repeatedly (e.g. best-effort on every server startup).

    Returns the number of rows updated (0 if already indexed or on error).
    """
    try:
        conn = init_db(vault_root)
        cursor = conn.cursor()

        flag = cursor.execute(
            "SELECT value FROM _meta WHERE key = ?", (_BODY_INDEX_META_KEY,)
        ).fetchone()
        if flag and flag[0] == "1":
            conn.close()
            return 0

        rows = cursor.execute("SELECT id, path FROM captures WHERE provisional = 0").fetchall()
        updated = 0
        for row in rows:
            body = _read_body_excerpt(row["path"])
            cursor.execute(
                "UPDATE captures SET body_excerpt = ? WHERE id = ?",
                (body, row["id"]),
            )
            updated += 1

        cursor.execute(
            "INSERT INTO _meta (key, value) VALUES (?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'",
            (_BODY_INDEX_META_KEY,),
        )
        conn.commit()
        conn.close()
        index_health.record_ok("captures")
        return updated
    except Exception as exc:
        print(f"[IndexWriter] Non-fatal reindex error: {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)
        return 0


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


# ── Remove / upsert helpers ───────────────────────────────────────────────────

def remove_capture_by_path(vault_root: Path, abs_path: Path) -> None:
    """Delete a captures row (and FTS shadow via trigger) by absolute path. Fails silently."""
    try:
        conn = init_db(vault_root)
        conn.execute("DELETE FROM captures WHERE path = ?", (str(abs_path),))
        conn.commit()
        conn.close()
        print(f"[IndexWriter] removed: {abs_path}", flush=True)
        index_health.record_ok("captures")
    except Exception as exc:
        print(f"[IndexWriter] remove_capture_by_path error: {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)


def upsert_capture_from_file(vault_root: Path, abs_path: Path) -> None:
    """Insert or update a captures row from the file on disk. Fails silently."""
    try:
        p = abs_path
        if not p.exists():
            return
        category   = p.parent.name
        body       = _read_body_excerpt(str(p))
        h          = _file_hash(str(p))
        # Tags come from the FILE's frontmatter -- the source of truth. This
        # column used to be left unset here, so every row this path wrote (i.e.
        # every `origin: note` file, and every row after a rebuild) had tags='[]'
        # even though the tags were sitting in the frontmatter. tag_vocab reads
        # this column as the vault's tag vocabulary, so a rebuild silently decayed
        # it and the LLM re-forked tags it should have reused. parse_tags reads
        # both frontmatter shapes (inline notes + the pipeline's block list).
        tags = json.dumps(_read_file_tags(p))
        # File mtime, not wall-clock now: a bulk vault sync must not stamp
        # every pre-existing note as captured-today (it poisons Recent
        # activity and the 30-day by_day stats).
        timestamp  = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        conn = init_db(vault_root)
        conn.execute(
            """
            INSERT INTO captures (timestamp, category, path, hash, filename, body_excerpt, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash         = excluded.hash,
                body_excerpt = excluded.body_excerpt,
                timestamp    = excluded.timestamp,
                tags         = excluded.tags
            """,
            (timestamp, category, str(p), h, p.name, body, tags),
        )
        conn.commit()
        conn.close()
        print(f"[IndexWriter] upserted: {p}", flush=True)
        index_health.record_ok("captures")
    except Exception as exc:
        print(f"[IndexWriter] upsert_capture_from_file error: {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)


# ── LAN provisional overlay (contract §11) ─────────────────────────────────────
# ponytail: provisional rows indexed for search/RAG only; never authoritative — files remain source of truth
#
# Provisional rows live in the SAME captures table (so search/RAG sees them for
# free) but are keyed by a synthetic `__lan_provisional__/<op_id>` path instead
# of a real vault path, and flagged provisional=1. Every dedup/merge/link
# authority query in this codebase (dedup.py's JSON index, merge.py's
# find_merge_target -> vector_store.best_match) must exclude provisional=1 --
# see vector_store.py's best_match() for the enforced exclusion. Plain
# index_writer.search() intentionally does NOT exclude provisional -- that is
# precisely where the LAN overlay is meant to surface. stats()/reindex_bodies()
# DO exclude provisional=1: dashboard/digest counts and the FTS body backfill
# are canonical-only (contract §11) -- provisional rows have no real vault
# path to read a body from, and must not inflate stats.

def _provisional_path(op_id: str) -> str:
    return f"__lan_provisional__/{op_id}"


def upsert_provisional(db: sqlite3.Connection, op_id: str, note_id: str, body: str, meta: dict) -> None:
    """Index one LAN-provisional note body for search/RAG (contract §11).

    *db* is an already-open connection (from init_db) -- the caller controls
    its lifetime, unlike the other write helpers here which open/close their
    own. Idempotent per op_id (ON CONFLICT upserts the same synthetic path).
    """
    body_excerpt = re.sub(r"\s+", " ", strip_frontmatter(body)).strip()[:_BODY_EXCERPT_MAX_CHARS]
    timestamp = meta.get("modified") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO captures
            (timestamp, category, path, tags, confidence,
             input_type, filename, body_excerpt, provisional, note_id)
        VALUES (?, ?, ?, '[]', 0.0, 'lan_provisional', ?, ?, 1, ?)
        ON CONFLICT(path) DO UPDATE SET
            body_excerpt = excluded.body_excerpt,
            timestamp    = excluded.timestamp,
            provisional  = 1,
            note_id      = excluded.note_id
        """,
        (
            timestamp,
            meta.get("category", ""),
            _provisional_path(op_id),
            op_id,
            body_excerpt,
            note_id,
        ),
    )
    db.commit()


def clear_provisional(db: sqlite3.Connection, op_id: str) -> None:
    """Drop a provisional row (and its FTS shadow via the existing AFTER DELETE
    trigger) once the Drive canonical version of its note supersedes it."""
    db.execute(
        "DELETE FROM captures WHERE path = ? AND provisional = 1",
        (_provisional_path(op_id),),
    )
    db.commit()


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    query: str,
    vault_root: Path,
    category: Optional[str] = None,
    since: Optional[str]    = None,
    limit: int              = 25,
    tag: Optional[str]      = None,
) -> list[dict]:
    """
    Full-text search over captures.  Returns up to *limit* rows, newest first.

    Parameters
    ----------
    query     FTS5 query string (supports prefix/phrase matching).
    category  Optional category filter.
    since     ISO-8601 timestamp lower-bound (inclusive).
    limit     Max rows to return.
    tag       F-4: tag filter -- the Library tags browser's "jump to filtered
              search" hand-off. Membership is resolved from the vault FILES
              (tag_index.resolve_paths), never from the `tags` column. The column
              is a derived cache that lags every frontmatter edit made since the
              note's last index pass, so a `tags LIKE` filter can disagree with
              the counts the Tags view scanned off disk. (It used to be strictly
              worse: the column was written only by log_capture_db, leaving every
              `origin: note` file empty and the filter listing nothing at all.
              upsert_capture_from_file now populates it from the file too, but the
              files stay authoritative regardless.) Rows are then filtered by
              path, keeping captures.db a cache in front of the files rather than
              an authority over them. A namespace tag (`project/`) resolves by
              prefix. See tag_index.py.
    """
    # Resolved before the DB is touched: no path on disk carries the tag -> no
    # row can legitimately match it, whatever captures.db still remembers.
    tag_paths = resolve_paths(vault_root, tag) if tag else None
    if tag and not tag_paths:
        return []

    # init_db is INSIDE the try: opening a corrupt db raises sqlite3.DatabaseError
    # here, before any query runs. Reads mirror the write path (log_capture_db) and
    # fail soft -- files are the source of truth and index_health is purely
    # observational, so a corrupt cache must degrade to empty, never 500 /search.
    try:
        conn = init_db(vault_root)
    except sqlite3.DatabaseError as exc:
        print(f"[IndexWriter] Non-fatal DB error (search): {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)
        return []
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
        if tag_paths:
            sql    += f" AND c.path IN ({_binds(tag_paths)})"
            params.extend(sorted(tag_paths))
    else:
        sql    = "SELECT * FROM captures WHERE 1=1"
        params = []
        if category:
            sql    += " AND category = ?"
            params.append(category)
        if since:
            sql    += " AND timestamp >= ?"
            params.append(since)
        if tag_paths:
            sql    += f" AND path IN ({_binds(tag_paths)})"
            params.extend(sorted(tag_paths))

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        rows = cursor.execute(sql, params).fetchall()
    except sqlite3.DatabaseError:
        # DatabaseError, not OperationalError: it is the shared base of both the
        # OperationalError the _binds ceiling below relies on AND the
        # DatabaseError("file is not a database") a corrupt file raises.
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def _binds(values) -> str:
    """`?,?,?` for an IN (...) clause.

    ponytail: the tag filter binds one variable per matching path. SQLite's
    variable cap (999 on builds older than 3.32) would reject a tag carried by
    more notes than that -- search() already swallows the OperationalError and
    returns [], so it degrades to empty rather than crashing. Chunk the IN list
    or stage the paths in a temp table if a single tag ever spans that many.
    """
    return ",".join("?" * len(values))


def _sanitize_fts_query(query: str) -> str:
    """
    Turn free-text user input into a safe FTS5 query: each whitespace-separated
    token uses prefix matching (``token*``) so singular queries match plurals
    (e.g. ``dinosaur`` → ``dinosaurs``). Tokens with FTS metacharacters are
    wrapped in double quotes (embedded quotes doubled) instead.
    """
    tokens = query.split()
    parts: list[str] = []
    for t in tokens:
        escaped = t.replace('"', '""')
        if re.fullmatch(r"[\w\-]+", t, flags=re.ASCII):
            parts.append(f"{escaped}*")
        else:
            parts.append(f'"{escaped}"')
    return " ".join(parts)


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
    # Fail-soft like search()/log_capture_db: a corrupt captures.db degrades to an
    # empty dashboard rather than 500ing /stats. The vault files are unaffected, and
    # index_health is purely observational -- it records, it does not gate. init_db is
    # INSIDE the try (a corrupt file raises there, before any query) and so are the
    # queries (init_db raises only while the per-process schema memo is cold).
    try:
        conn   = init_db(vault_root)
        cursor = conn.cursor()

        total_row = cursor.execute("SELECT COUNT(*) FROM captures WHERE provisional = 0").fetchone()
        total     = total_row[0] if total_row else 0

        cat_rows = cursor.execute(
            "SELECT category, COUNT(*) AS cnt FROM captures WHERE provisional = 0 GROUP BY category ORDER BY cnt DESC"
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
            WHERE timestamp >= date('now','-30 days') AND provisional = 0
            GROUP BY date
            ORDER BY date DESC
            """
        ).fetchall()
        by_day = [{"date": r["date"], "count": r["cnt"]} for r in day_rows]

        recent_rows = cursor.execute(
            "SELECT * FROM captures WHERE provisional = 0 ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()
        recent = [dict(r) for r in recent_rows]

        conn.close()
    except sqlite3.DatabaseError as exc:
        print(f"[IndexWriter] Non-fatal DB error (stats): {exc}", file=sys.stderr)
        index_health.record_failure("captures", exc)
        return {"total": 0, "by_category": [], "by_day": [], "recent": []}
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
