from pathlib import Path
import tempfile
from datetime import datetime
import pytest
import reminders as reminders_mod
from reminders import sync_reminders_from_notes, list_reminders


@pytest.fixture(autouse=True)
def _no_real_schtasks(monkeypatch):
    # WS-4: sync_reminders_from_notes now requests delivery="os". On the Windows test runner that
    # would otherwise fire a REAL schtasks subprocess per reminder (create_reminder -> _create_schtask).
    # Stub it so every test in this file stays hermetic regardless of the runner OS.
    monkeypatch.setattr(reminders_mod, "_create_schtask", lambda *a, **k: None)


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


def test_schtasks_date_format_is_locale_unambiguous():
    from reminders import _SCHTASKS_DATE_FMT
    # 2026-01-09 reads as Sept 1 under %d/%m and Jan 9 under %m/%d if ambiguous -- the chosen format
    # must round-trip unambiguously regardless of the interpreting locale.
    when = datetime(2026, 1, 9)
    assert when.strftime(_SCHTASKS_DATE_FMT) == "2026/01/09"


def test_sync_reminders_from_notes_prefers_os_delivery_on_windows(monkeypatch):
    # Force the Windows branch deterministically regardless of the test-runner's actual OS (the
    # autouse fixture already stubs the real schtasks subprocess).
    monkeypatch.setattr(reminders_mod, "_IS_WINDOWS", True)

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "captures.db"
        sync_reminders_from_notes(db, [_note("a", "2026-07-30T09:00:00Z")])
        rows = list_reminders(db)
        assert rows[0]["delivery"] == "os"
