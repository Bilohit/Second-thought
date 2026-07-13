from pathlib import Path
import tempfile
from reminders import sync_reminders_from_notes, list_reminders


def _note(nid, remind_at):
    ra = f"remind_at: {remind_at}\n" if remind_at else ""
    return (
        f"/vault/{nid}.md",
        f"---\nid: {nid}\norigin: note\ntitle: Note {nid}\n{ra}---\nbody text\n",
    )


def test_sync_creates_updates_removes():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "captures.db"

        # 1. one note with a reminder -> created
        r = sync_reminders_from_notes(db, [_note("a", "2026-07-20T09:00:00Z")])
        assert r == {"created": 1, "updated": 0, "removed": 0}
        rows = list_reminders(db)
        assert len(rows) == 1 and rows[0]["fire_at"] == "2026-07-20T09:00:00Z"

        # 2. same input again -> idempotent no-op
        r = sync_reminders_from_notes(db, [_note("a", "2026-07-20T09:00:00Z")])
        assert r == {"created": 0, "updated": 0, "removed": 0}
        assert len(list_reminders(db)) == 1

        # 3. remind_at changed -> updated, still one row
        r = sync_reminders_from_notes(db, [_note("a", "2026-07-21T10:00:00Z")])
        assert r == {"created": 0, "updated": 1, "removed": 0}
        rows = list_reminders(db)
        assert len(rows) == 1 and rows[0]["fire_at"] == "2026-07-21T10:00:00Z"

        # 4. remind_at removed -> removed
        r = sync_reminders_from_notes(db, [_note("a", None)])
        assert r == {"created": 0, "updated": 0, "removed": 1}
        assert list_reminders(db) == []
