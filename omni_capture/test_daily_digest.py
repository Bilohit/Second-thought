"""F-14 digest-stats: the 4 counts the ephemeral daily-digest pop-in renders (mock 06-daily-digest-v2).
Ephemeral by contract — digest_stats returns counts and never writes to the vault."""
import os
from datetime import date, datetime, time, timedelta

import index_writer
import reminders as rem
from daily_digest import digest_stats


def _write_note(vault, name, note_id, mtime_epoch):
    p = vault / f"{name}.md"
    p.write_text(f"---\nid: {note_id}\norigin: note\n---\nbody\n", encoding="utf-8")
    os.utime(p, (mtime_epoch, mtime_epoch))
    return p


def _insert_capture(vault, path, ts_iso, provisional=0):
    conn = index_writer.init_db(vault)
    conn.execute(
        "INSERT INTO captures (timestamp, category, path, hash, filename, body_excerpt, provisional) "
        "VALUES (?, 'Notes', ?, ?, ?, 'x', ?)",
        (ts_iso, path, f"h-{path}", path, provisional),
    )
    conn.commit()
    conn.close()


def test_digest_stats_counts_all_four(tmp_path):
    today = date.today()
    day_epoch = datetime.combine(today, time(12, 0)).timestamp()
    old_epoch = day_epoch - 40 * 86400            # >30d ago -> unrevisited

    # notes: one touched today, one stale (also counts as unrevisited)
    _write_note(tmp_path, "fresh", "n-fresh", day_epoch)
    _write_note(tmp_path, "stale", "n-stale", old_epoch)

    # captures: one today (counted), one provisional today (excluded), one yesterday (excluded)
    _insert_capture(tmp_path, "cap-today", datetime.combine(today, time(9, 0)).isoformat())
    _insert_capture(tmp_path, "cap-prov", datetime.combine(today, time(9, 0)).isoformat(), provisional=1)
    _insert_capture(tmp_path, "cap-yest", datetime.combine(today - timedelta(days=1), time(9, 0)).isoformat())

    # reminders: one due by end of today (counted), one next week (excluded)
    db = index_writer.get_db_path(tmp_path)
    rem.create_reminder(db, note_path="fresh.md", label="due",
                        fire_at_iso=datetime.combine(today, time(18, 0)).isoformat(timespec="seconds"))
    rem.create_reminder(db, note_path="fresh.md", label="later",
                        fire_at_iso=datetime.combine(today + timedelta(days=7), time(9, 0)).isoformat(timespec="seconds"))

    stats = digest_stats(today, tmp_path)
    assert stats == {"captured": 1, "touched": 1, "reminders_due": 1, "unrevisited": 1}


def test_digest_stats_empty_vault(tmp_path):
    stats = digest_stats(date.today(), tmp_path)
    assert stats == {"captured": 0, "touched": 0, "reminders_due": 0, "unrevisited": 0}
