"""
test_merge.py
-------------
P0: file-locking for the merge-append read-modify-write cycle in merge.py.

Relocated from test_dedup_merge_lock.py when storage_engine.py was split into
dedup.py / merge.py / scratchpad.py (see docs/ROADMAP.md). Patches merge's own
module attribute (_append_general) directly, since that function now lives in
merge.py.

Covers:
  * _append_general holds its FileLock across the whole read-then-write.
  * Two concurrent _append_general calls against the same target file both
    land in the final content -- no last-write-wins loss of the other's
    appended text.

Run:
    python -m pytest test_merge.py -q
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from filelock import Timeout

sys.path.insert(0, str(Path(__file__).parent))

import merge


def test_merge_lock_spans_read_not_just_write(tmp_path, monkeypatch):
    """Prove the lock is held during the read (Path.read_text), not acquired
    only around the write -- a second acquire of the same lock file must not
    succeed while _append_general is mid-read."""
    vault = tmp_path
    target = vault / "note.md"
    target.write_text("original body", encoding="utf-8")

    entered = threading.Event()
    release = threading.Event()

    orig_read_text = Path.read_text

    def slow_read_text(self, *args, **kwargs):
        if self == target:
            entered.set()
            assert release.wait(timeout=5), "test setup deadlocked"
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", slow_read_text)

    t = threading.Thread(target=merge._append_general, args=(target, "Appended A", vault))
    t.start()
    assert entered.wait(timeout=5), "_append_general never reached the read"

    contender = merge._vault_lock(merge._merge_lock_path(vault), timeout=0.3)
    with pytest.raises(Timeout):
        with contender:
            pass

    release.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_two_concurrent_appends_to_same_target_both_persist(tmp_path, monkeypatch):
    """Two captures deciding to merge-append into the SAME target file at
    nearly the same time must not have one overwrite the other. Inject a
    delay into the read half so both threads' cycles would overlap if
    unsynchronized, then assert both appended bodies survive in the file."""
    vault = tmp_path
    target = vault / "note.md"
    target.write_text("original body", encoding="utf-8")

    orig_read_text = Path.read_text

    def slow_read_text(self, *args, **kwargs):
        if self == target:
            time.sleep(0.05)
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", slow_read_text)

    def worker(text):
        merge._append_general(target, text, vault)

    t1 = threading.Thread(target=worker, args=("Appended A",))
    t2 = threading.Thread(target=worker, args=("Appended B",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()

    final = target.read_text(encoding="utf-8")
    assert "original body" in final
    assert "Appended A" in final, "first append was lost to a race"
    assert "Appended B" in final, "second append was lost to a race"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
