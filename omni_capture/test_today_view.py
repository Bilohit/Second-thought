"""Tests for today_view.py — the desktop TODAY/agenda aggregation (D-A)."""
from datetime import datetime
from pathlib import Path

from today_view import _bucket_reminders, _parse_local, build_today, create_daily_note, find_daily_note
from note_model import parse_note
from reminders import create_reminder


NOW = datetime(2026, 7, 26, 14, 0, 0)  # local wall-clock for every bucket test


def _rem(rid, fire_at, label="r"):
    return {"id": rid, "note_path": f"{label}.md", "label": label, "fire_at": fire_at}


def test_parse_local_naive_and_aware():
    assert _parse_local("2026-07-26T09:30") == datetime(2026, 7, 26, 9, 30)
    assert _parse_local("nonsense") is None
    assert _parse_local("") is None
    # offset-aware value is accepted (converted to local); we only assert it parses to *some* datetime
    assert _parse_local("2026-07-26T09:30:00+00:00") is not None


def test_bucket_overdue_due_future():
    rems = [
        _rem(1, "2026-07-25T09:00", "yesterday"),   # past day, passed  → overdue
        _rem(2, "2026-07-26T09:00", "earlier"),     # today, already passed → due_today
        _rem(3, "2026-07-26T20:00", "later"),       # today, not yet      → due_today
        _rem(4, "2026-07-27T09:00", "tomorrow"),    # future day          → excluded
    ]
    overdue, due_today = _bucket_reminders(rems, NOW)
    assert [r["id"] for r in overdue] == [1]
    assert {r["id"] for r in due_today} == {2, 3}


def test_bucket_sort_order():
    rems = [
        _rem(1, "2026-07-20T09:00"),   # older miss
        _rem(2, "2026-07-24T09:00"),   # newer miss
        _rem(3, "2026-07-26T18:00"),   # later today
        _rem(4, "2026-07-26T08:00"),   # earlier today
    ]
    overdue, due_today = _bucket_reminders(rems, NOW)
    assert [r["id"] for r in overdue] == [2, 1]     # most-recent miss first
    assert [r["id"] for r in due_today] == [4, 3]   # soonest first


def test_bucket_skips_unparseable():
    overdue, due_today = _bucket_reminders([_rem(1, "not-a-date")], NOW)
    assert overdue == [] and due_today == []


def _write_note(vault: Path, folder: str, nid: str, title: str, body: str = "body\n"):
    d = vault / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{nid}.md").write_text(
        f"---\nid: {nid}\ntitle: {title}\norigin: note\n---\n{body}",
        encoding="utf-8",
    )


def test_find_daily_note_title_match(tmp_path):
    _write_note(tmp_path, "personal", "n1", "2026-07-26")
    _write_note(tmp_path, "personal", "n2", "Some other note")
    hit = find_daily_note(tmp_path, "2026-07-26")
    assert hit is not None and hit["id"] == "n1"
    assert find_daily_note(tmp_path, "2026-07-25") is None


def test_build_today_integration(tmp_path):
    db = tmp_path / "captures.db"
    create_reminder(db, note_path="a.md", label="Yesterday task", fire_at_iso="2026-07-25T09:00")
    create_reminder(db, note_path="b.md", label="Today task", fire_at_iso="2026-07-26T18:00")
    create_reminder(db, note_path="c.md", label="Tomorrow task", fire_at_iso="2026-07-27T09:00")

    _write_note(tmp_path, "personal", "d1", "2026-07-26")          # today's daily note
    (tmp_path / "_scratchpad").mkdir()
    (tmp_path / "_scratchpad" / "s1.md").write_text("---\nid: s1\n---\nx\n", encoding="utf-8")

    view = build_today(tmp_path, db, "2026-07-26", NOW)
    assert view["date"] == "2026-07-26"
    assert [r["title"] for r in view["overdue"]] == ["Yesterday task"]
    assert [r["title"] for r in view["due_today"]] == ["Today task"]
    assert view["scratchpad_count"] == 1
    assert view["daily_note"]["id"] == "d1"


def test_build_today_no_daily_note(tmp_path):
    db = tmp_path / "captures.db"
    view = build_today(tmp_path, db, "2026-07-26", NOW)
    assert view["daily_note"] is None
    assert view["overdue"] == [] and view["due_today"] == []
    assert view["scratchpad_count"] == 0


def test_create_daily_note_mints_desktop_note(tmp_path):
    res = create_daily_note(tmp_path, "2026-07-26")
    p = Path(res["path"])
    assert p == tmp_path / "Daily" / "2026-07-26.md"   # lands in Daily/
    assert res["title"] == "2026-07-26"
    note = parse_note(p.read_text(encoding="utf-8", newline=""))
    assert note.origin == "note" and note.origin_device == "desktop" and note.device == "desktop"
    assert note.title == "2026-07-26" and note.id == res["id"]
    assert note.body == "# 2026-07-26\n\n## Intentions\n- [ ] \n\n## Log\n"   # phone-parity template
    # now discoverable by the same S1 title-match the view uses
    assert find_daily_note(tmp_path, "2026-07-26")["id"] == res["id"]


def test_create_daily_note_idempotent_body_sacred(tmp_path):
    first = create_daily_note(tmp_path, "2026-07-26")
    # user edits the body — a second call must NOT overwrite it, and must return the SAME note
    p = Path(first["path"])
    p.write_text(p.read_text(encoding="utf-8", newline="").replace("## Log\n", "## Log\nmine\n"),
                 encoding="utf-8", newline="")
    second = create_daily_note(tmp_path, "2026-07-26")
    assert second["id"] == first["id"]
    assert "mine" in p.read_text(encoding="utf-8", newline="")   # body untouched


def test_create_daily_note_matches_existing_elsewhere(tmp_path):
    # a daily note already exists in another folder (S1 title-match) → reuse it, don't make a dupe
    _write_note(tmp_path, "personal", "d1", "2026-07-26")
    res = create_daily_note(tmp_path, "2026-07-26")
    assert res["id"] == "d1"
    assert not (tmp_path / "Daily" / "2026-07-26.md").exists()   # no second file minted
