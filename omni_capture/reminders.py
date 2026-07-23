"""
reminders.py
------------
Plain sqlite3-backed store for user-set reminders on vault notes.

Lives in the same SQLite file as captures.db (path via
index_writer.get_db_path(vault_root)) but in its own table.

Authority carve-out: Reminders are operational state, not note content.
This table is authoritative for scheduling only -- never for anything
about the notes themselves (see CLAUDE.md: files are the source of truth).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import sqlite3

_IS_WINDOWS = sys.platform.startswith("win")

# ponytail: /SD format is locale-dependent (dd/mm here); verified on this
# machine only -- switch to schtasks /XML if another locale breaks it.
_SCHTASKS_DATE_FMT = "%d/%m/%Y"

# SRV-09: characters that let a note title break out of the quoted /TR command line
# that schtasks re-parses. `"` closes the argument; the rest are cmd metacharacters
# that would then be interpreted rather than passed to notifier.py.
_SCHTASKS_UNSAFE = '"&|<>^%\r\n'


def _sanitize_schtasks_label(label: str) -> str:
    """Strip characters that would escape the quoted /TR string, and cap the length.

    The label is display text passed straight to notifier.py as an argv element, so
    dropping these characters costs nothing a user would notice. schtasks also rejects
    an over-long /TR outright, which would make the reminder silently fail to schedule.
    """
    cleaned = "".join(ch for ch in label if ch not in _SCHTASKS_UNSAFE)
    cleaned = " ".join(cleaned.split())  # collapse any remaining control whitespace
    return cleaned[:120] or "Reminder"

_DDL = """
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path  TEXT NOT NULL,
    label      TEXT NOT NULL,
    fire_at    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    delivery   TEXT NOT NULL DEFAULT 'app',
    created_at TEXT NOT NULL
);
"""

_COLUMNS = ("id", "note_path", "label", "fire_at", "status", "delivery", "created_at")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL)


def _connect(db_path: Path) -> sqlite3.Connection:
    # The DB is a derived, rebuildable cache — create its dir if a sync reaches
    # reminders before any capture/enrich has made it (note with remind_at, empty vault).
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    return conn


def _row_to_dict(row: tuple) -> dict:
    # strict=: every SELECT uses `', '.join(_COLUMNS)`, so a row always has len(_COLUMNS)
    # columns today; strict= turns a future schema/SELECT drift into a loud error instead
    # of a silent field misalignment (OF-22 / ruff B905).
    return dict(zip(_COLUMNS, row, strict=True))


def create_reminder(
    db_path: Path,
    *,
    note_path: str,
    label: str,
    fire_at_iso: str,
    delivery: str = "app",
) -> int:
    from datetime import datetime, timezone

    if delivery == "os" and not _IS_WINDOWS:
        print("reminders: OS-level delivery requires Windows; storing as 'app' instead.")
        delivery = "app"

    conn = _connect(db_path)
    try:
        created_at = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO reminders (note_path, label, fire_at, status, delivery, created_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (note_path, label, fire_at_iso, delivery, created_at),
        )
        rid = int(cur.lastrowid)   # assigned by the INSERT; readable before the commit
        # SRV-10: the OS task is created BEFORE the commit, inside the same try. The row
        # id is already allocated (schtasks needs it for the task name), but nothing is
        # durable until schtasks has succeeded -- so a schtasks failure rolls the row back
        # instead of leaving an orphan 'pending' reminder no scheduled task will ever fire.
        if delivery == "os" and _IS_WINDOWS:
            _create_schtask(rid, note_path=note_path, label=label, fire_at_iso=fire_at_iso)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return rid


def _create_schtask(rid: int, *, note_path: str, label: str, fire_at_iso: str) -> None:
    """Register the Windows Task Scheduler entry that fires reminder *rid*.
    Raises (CalledProcessError / ValueError) if the task could not be created --
    create_reminder relies on that to roll its uncommitted row back."""
    from datetime import datetime

    when = datetime.fromisoformat(fire_at_iso)
    # SRV-09: subprocess.run is already argv-based (no shell=True), so PYTHON is not
    # the injection surface -- schtasks is. It re-parses the /TR string as a command
    # line, so a `"` inside `label` closes the quoted argument and everything after it
    # becomes new tokens. `label` is the note TITLE, which arrives from note
    # frontmatter via sync_reminders_from_notes -- i.e. from the Drive hub.
    safe_label = _sanitize_schtasks_label(label)
    subprocess.run(
        [
            "schtasks", "/Create", "/F",
            "/TN", f"SecondThought\\reminder-{rid}",
            "/SC", "ONCE",
            "/SD", when.strftime(_SCHTASKS_DATE_FMT),
            "/ST", when.strftime("%H:%M"),
            "/TR",
            f'"{sys.executable}" "{Path(__file__).parent / "notifier.py"}" "{safe_label}" "{Path(note_path).name}"',
        ],
        check=True,
        capture_output=True,
    )


def list_reminders(db_path: Path, include_done: bool = False) -> list[dict]:
    conn = _connect(db_path)
    try:
        if include_done:
            cur = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM reminders ORDER BY id")
        else:
            cur = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM reminders WHERE status = 'pending' ORDER BY id"
            )
        return [_row_to_dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def due_reminders(db_path: Path, now_iso: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM reminders "
            "WHERE status = 'pending' AND delivery = 'app' AND fire_at <= ? "
            "ORDER BY fire_at",
            (now_iso,),
        )
        return [_row_to_dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def mark_fired(db_path: Path, reminder_id: int) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE reminders SET status = 'fired' WHERE id = ?", (reminder_id,)
        )
        conn.commit()
    finally:
        conn.close()


def delete_reminder(db_path: Path, reminder_id: int) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT delivery FROM reminders WHERE id = ?", (reminder_id,)
        )
        row = cur.fetchone()
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
    finally:
        conn.close()

    if row is not None and row[0] == "os" and _IS_WINDOWS:
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", f"SecondThought\\reminder-{reminder_id}"],
            capture_output=True,
        )


def sync_reminders_from_notes(db_path: Path, notes: list[tuple[str, str]]) -> dict:
    """Reconcile the reminders table against note `remind_at` frontmatter.

    Files are the source of truth; this table is scheduling state only. For each
    (note_path, raw_text): if the note has a remind_at, ensure exactly one pending
    reminder with that fire_at (label from the note title); if not, drop any
    pending reminder for that note. Idempotent. Never writes note files.
    """
    from note_model import parse_note

    created = updated = removed = 0
    existing = {r["note_path"]: r for r in list_reminders(db_path) if r["status"] == "pending"}

    for note_path, raw in notes:
        note = parse_note(raw)
        want = note.remind_at
        cur = existing.get(note_path)
        if want:
            label = note.title or Path(note_path).stem
            if cur is None:
                create_reminder(db_path, note_path=note_path, label=label, fire_at_iso=want)
                created += 1
            elif cur["fire_at"] != want:
                delete_reminder(db_path, cur["id"])
                create_reminder(db_path, note_path=note_path, label=label, fire_at_iso=want)
                updated += 1
        elif cur is not None:
            delete_reminder(db_path, cur["id"])
            removed += 1

    return {"created": created, "updated": updated, "removed": removed}


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "captures.db"
        rid = create_reminder(db, note_path="a.md", label="test", fire_at_iso="2020-01-01T00:00")
        assert list_reminders(db)[0]["id"] == rid
        assert due_reminders(db, now_iso="2025-01-01T00:00")
        mark_fired(db, rid)
        assert not due_reminders(db, now_iso="2025-01-01T00:00")
        delete_reminder(db, rid)
        assert list_reminders(db, include_done=True) == []
        print("reminders.py smoke check OK")
