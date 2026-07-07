"""
test_dedup.py
--------------
P0: file-locking for the dedup-index read-modify-write cycle in dedup.py.

Relocated from test_dedup_merge_lock.py when storage_engine.py was split into
dedup.py / merge.py / scratchpad.py (see docs/ROADMAP.md). Patches dedup's own
module attributes directly -- patching storage_engine.py's re-exported name
would NOT reach register_in_dedup_index's internal call, since that function
now lives in dedup.py and resolves _load_dedup_index against dedup.py's own
module globals, not storage_engine's.

Covers:
  * register_in_dedup_index holds its FileLock across the WHOLE cycle
    (load -> mutate -> save), not just the save call.
  * Two concurrent register_in_dedup_index calls (different content hashes)
    both survive -- no last-write-wins loss of the other's index entry.

Run:
    python -m pytest test_dedup.py -q
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from filelock import Timeout

sys.path.insert(0, str(Path(__file__).parent))

import dedup


def test_dedup_lock_spans_load_not_just_save(tmp_path, monkeypatch):
    """Prove the lock is held during _load_dedup_index (the read half of the
    cycle), not acquired only around _save_dedup_index. If a second locker
    can grab the same lock file while a register call is mid-load, the lock
    does not actually scope the whole read-modify-write cycle."""
    vault = tmp_path
    entered = threading.Event()
    release = threading.Event()

    orig_load = dedup._load_dedup_index

    def slow_load(vault_root):
        entered.set()
        assert release.wait(timeout=5), "test setup deadlocked"
        return orig_load(vault_root)

    monkeypatch.setattr(dedup, "_load_dedup_index", slow_load)

    note_dir = vault / "Journal"
    note_dir.mkdir()
    note = note_dir / "a.md"
    note.write_text("hello", encoding="utf-8")

    t = threading.Thread(
        target=dedup.register_in_dedup_index,
        args=("some content", None, vault, note),
    )
    t.start()
    assert entered.wait(timeout=5), "register_in_dedup_index never reached the load"

    # Writer thread is now inside the lock, blocked in the (patched) load.
    # A second acquire of the same lock file must NOT succeed immediately.
    contender = dedup._vault_lock(dedup._dedup_lock_path(vault), timeout=0.3)
    with pytest.raises(Timeout):
        with contender:
            pass

    release.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_two_concurrent_dedup_registrations_both_persist(tmp_path, monkeypatch):
    """Without the lock spanning the whole cycle, two concurrent registrations
    of DIFFERENT content (different hash keys) racing on load->mutate->save
    can silently lose one entry (last writer's save overwrites the other's).
    Inject an artificial delay into every load so the two threads' cycles
    would overlap if unsynchronized, then assert BOTH entries survive."""
    vault = tmp_path
    note_dir = vault / "Journal"
    note_dir.mkdir()
    note_a = note_dir / "a.md"
    note_a.write_text("a", encoding="utf-8")
    note_b = note_dir / "b.md"
    note_b.write_text("b", encoding="utf-8")

    orig_load = dedup._load_dedup_index

    def slow_load(vault_root):
        time.sleep(0.05)
        return orig_load(vault_root)

    monkeypatch.setattr(dedup, "_load_dedup_index", slow_load)

    def worker(text, path):
        dedup.register_in_dedup_index(text, None, vault, path)

    t1 = threading.Thread(target=worker, args=("alpha content", note_a))
    t2 = threading.Thread(target=worker, args=("beta content", note_b))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()

    idx = dedup._load_dedup_index(vault)
    h1 = dedup._content_hash("alpha content", None)
    h2 = dedup._content_hash("beta content", None)
    assert h1 in idx, "first registration's entry was lost to a race"
    assert h2 in idx, "second registration's entry was lost to a race"
    assert idx[h1] == str(note_a.relative_to(vault))
    assert idx[h2] == str(note_b.relative_to(vault))


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
