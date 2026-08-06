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


def test_default_delivery_param_is_honored_on_fresh_row():
    """REM-1: server.py's POST /reminders passes the request's own delivery (or the user's
    configured default) as `default_delivery` so a fresh row from the EDITOR isn't forced to 'os'
    the way a fresh row from the periodic background scan intentionally is (WS-4)."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "captures.db"
        r = sync_reminders_from_notes(
            db, [_note("a", "2026-07-20T09:00:00Z")], default_delivery="app"
        )
        assert r == {"created": 1, "updated": 0, "removed": 0}
        assert list_reminders(db)[0]["delivery"] == "app"


def test_delivery_preserved_across_sync_pass_on_recreate():
    """REM-1 point 3: a user who chose delivery='app' must not be silently flipped to 'os' when a
    later sync pass recreates the row for a genuine fire_at change. Before the fix, the recreate
    branch hardcoded delivery='os' unconditionally."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "captures.db"
        sync_reminders_from_notes(db, [_note("a", "2026-07-20T09:00:00Z")], default_delivery="app")
        first = list_reminders(db)[0]
        assert first["delivery"] == "app"

        # A genuinely different fire_at -> exercises the recreate (delete+create) branch.
        r = sync_reminders_from_notes(db, [_note("a", "2026-07-21T10:00:00Z")])
        assert r == {"created": 0, "updated": 1, "removed": 0}
        rows = list_reminders(db)
        assert len(rows) == 1
        assert rows[0]["id"] != first["id"], "test did not actually exercise the recreate path"
        assert rows[0]["delivery"] == "app", "delivery was flipped to 'os' on recreate"


def test_fire_at_format_noise_does_not_churn():
    """REM-1: _normalize_fire_at's actual defensive value. The SAME naive instant, spelled two
    cosmetically different ways (seconds present vs the datetime-local shape's seconds omitted),
    must NOT look like a change -- this is the case a raw `cur["fire_at"] != want` string compare
    gets wrong, and is what would make sync_reminders_from_notes recreate the row on every pass if
    a note's remind_at spelling ever drifted between two equivalent ISO forms."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "captures.db"
        sync_reminders_from_notes(db, [_note("a", "2026-07-20T09:00:00")])
        first = list_reminders(db)[0]

        # Same instant, cosmetically different spelling (no seconds -- the datetime-local shape).
        r = sync_reminders_from_notes(db, [_note("a", "2026-07-20T09:00")])
        assert r == {"created": 0, "updated": 0, "removed": 0}, (
            "a cosmetically different spelling of the SAME instant was treated as a real change"
        )
        assert list_reminders(db)[0]["id"] == first["id"]


def test_churn_regression_datetime_local_shape_is_idempotent(tmp_path):
    """REM-1 -- THE churn regression test. NoteEditor.tsx's <input type="datetime-local">
    (NoteEditor.tsx:1145) produces an ISO shape with no seconds and no offset (e.g.
    "2026-08-10T08:00"). That value goes: wire request -> note_editor.set_note_remind_at ->
    note_model parse/serialize -> back out as frontmatter -> reminders.sync_reminders_from_notes.
    A second sync pass over the note UNCHANGED must be a pure no-op -- before the
    _normalize_fire_at fix, any format drift here made `cur["fire_at"] != want` true forever,
    deleting and recreating the row (new id, re-registered Windows scheduled task) on every pass."""
    from note_editor import set_note_remind_at

    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "call_mom.md"
    note.write_text(
        "---\nid: r1\norigin: note\ntitle: Call mom\n---\n# Call mom\n\nDon't forget.\n",
        encoding="utf-8", newline="",
    )
    db = tmp_path / "captures.db"

    write = set_note_remind_at(vault, str(note), "2026-08-10T08:00")
    r1 = sync_reminders_from_notes(db, [(str(note), write["content"])])
    assert r1 == {"created": 1, "updated": 0, "removed": 0}
    first_id = list_reminders(db)[0]["id"]

    # Re-read from DISK -- the exact bytes a later periodic full-vault pass would see.
    on_disk = note.read_text(encoding="utf-8", newline="")
    r2 = sync_reminders_from_notes(db, [(str(note), on_disk)])
    assert r2 == {"created": 0, "updated": 0, "removed": 0}, (
        "churn regression: a second sync pass over the SAME unchanged note re-created the row"
    )
    rows = list_reminders(db)
    assert len(rows) == 1 and rows[0]["id"] == first_id, "row id changed -- a delete+recreate happened"

    # A third pass, for good measure -- "forever" means it doesn't self-correct after one retry.
    r3 = sync_reminders_from_notes(db, [(str(note), note.read_text(encoding="utf-8", newline=""))])
    assert r3 == {"created": 0, "updated": 0, "removed": 0}
