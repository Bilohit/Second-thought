"""
test_reminders.py
------------------
Tests for reminders.py: create/list/due/mark_fired/delete.

Run:  pytest omni_capture/test_reminders.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from reminders import (
    create_reminder,
    list_reminders,
    due_reminders,
    mark_fired,
    delete_reminder,
)


def test_create_and_list_pending(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(
        db, note_path="a.md", label="follow up", fire_at_iso="2030-01-01T00:00"
    )
    assert isinstance(rid, int)

    rows = list_reminders(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == rid
    assert row["note_path"] == "a.md"
    assert row["label"] == "follow up"
    assert row["fire_at"] == "2030-01-01T00:00"
    assert row["status"] == "pending"
    assert row["delivery"] == "app"
    assert row["created_at"]


def test_due_reminders_past_vs_future(tmp_path):
    db = tmp_path / "captures.db"
    create_reminder(db, note_path="past.md", label="past", fire_at_iso="2020-01-01T00:00")
    create_reminder(db, note_path="future.md", label="future", fire_at_iso="2099-01-01T00:00")

    due_now = due_reminders(db, now_iso="2025-01-01T00:00")
    assert len(due_now) == 1
    assert due_now[0]["note_path"] == "past.md"

    due_early = due_reminders(db, now_iso="2019-01-01T00:00")
    assert due_early == []


def test_mark_fired_flips_status_and_removes_from_due(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(db, note_path="a.md", label="due", fire_at_iso="2020-01-01T00:00")

    assert len(due_reminders(db, now_iso="2025-01-01T00:00")) == 1

    mark_fired(db, rid)

    assert due_reminders(db, now_iso="2025-01-01T00:00") == []
    rows = list_reminders(db, include_done=True)
    assert rows[0]["status"] == "fired"


def test_delete_reminder_removes_from_list(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(db, note_path="a.md", label="gone", fire_at_iso="2030-01-01T00:00")
    assert len(list_reminders(db)) == 1

    delete_reminder(db, rid)

    assert list_reminders(db) == []


def test_fire_due_notifies_and_marks(tmp_path):
    from reminders import create_reminder, list_reminders
    from server import _fire_due
    db = tmp_path / "captures.db"
    create_reminder(db, note_path="a.md", label="due now", fire_at_iso="2020-01-01T00:00", delivery="app")
    create_reminder(db, note_path="b.md", label="future", fire_at_iso="2099-01-01T00:00", delivery="app")
    fired = []
    _fire_due(db, notify_fn=lambda title, msg: fired.append(title))
    assert fired == ["⏰ due now"]
    statuses = {r["label"]: r["status"] for r in list_reminders(db, include_done=True)}
    assert statuses == {"due now": "fired", "future": "pending"}


def test_create_reminder_os_delivery_calls_schtasks_create_on_windows():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert args[0] == "schtasks"
            assert "/Create" in args
            assert "/SC" in args
            sc_idx = args.index("/SC")
            assert args[sc_idx + 1] == "ONCE"
            tn_idx = args.index("/TN")
            assert args[tn_idx + 1] == f"SecondThought\\reminder-{rid}"


def test_create_reminder_app_delivery_runs_no_subprocess():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="app",
            )
            assert not mock_run.called


def test_create_reminder_os_delivery_on_non_windows_falls_back_to_app():
    with patch("reminders._IS_WINDOWS", False), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            assert not mock_run.called
            row = list_reminders(db)[0]
            assert row["id"] == rid
            assert row["delivery"] == "app"


def test_delete_reminder_os_delivery_calls_schtasks_delete_on_windows():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            mock_run.reset_mock()
            delete_reminder(db, rid)
            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert args[0] == "schtasks"
            assert "/Delete" in args
            tn_idx = args.index("/TN")
            assert args[tn_idx + 1] == f"SecondThought\\reminder-{rid}"
            assert mock_run.call_args[1].get("check") is not True


def test_delete_reminder_app_delivery_runs_no_subprocess():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="app",
            )
            mock_run.reset_mock()
            delete_reminder(db, rid)
            assert not mock_run.called


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-v"]))
