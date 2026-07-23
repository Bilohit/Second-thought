"""
test_conflict_and_trash.py — §3.4 cold-spot coverage for the F-1 conflict
resolver and the F-2 trash surface.

Both modules were at 0% under pytest despite being live behind three routes
(`server.py:/note/conflict`, `/note/conflict/resolve`, `vault_admin.py:/vault/
conflicts`, `/trash`, `/trash/restore`). Each module carries a `__main__` smoke
block covering the happy paths, but the gate never runs it — so the
*destructive* branches (trash collisions, stale-mtime refusal, reserved-folder
scanning) had no runnable check at all.

These tests encode the two workspace locks this code sits directly on top of:
  - "a note's body is sacred" — no path here may clobber a body the user
    edited, and a REFUSED resolve must leave both files byte-identical.
  - "field-aware, non-destructive conflicts" — a trash/restore move must never
    destroy a file it collides with by name.
"""
import os
import time
from pathlib import Path

import pytest

from conflict_resolver import (
    _trash_file,
    find_conflict_sibling,
    get_conflict,
    list_vault_conflicts,
    resolve_conflict,
)
from note_editor import NoteConflictError
from trash import list_trash, move_to_trash, restore_from_trash

_ORIGINAL = (
    "---\nid: 01ORIG\ntitle: Example note\ncategory: Tech_Notes\n---\n"
    "# Example note\n\nMy local body.\n"
)
_COPY = (
    "---\nid: 01COPY\ntitle: Example note (conflicted copy phone-9f3e 2026-07-11T19:27:00Z)\n"
    "category: Tech_Notes\ndevice: phone-9f3e\nmodified: 2026-07-11T19:27:00Z\n---\n"
    "# Example note\n\nTheir remote body.\n"
)


def _vault(tmp_path: Path):
    """Vault with Tech_Notes/example.md and one conflicted copy beside it."""
    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    original = cat / "example.md"
    original.write_text(_ORIGINAL, encoding="utf-8")
    copy_ = cat / "01COPY.md"
    copy_.write_text(_COPY, encoding="utf-8")
    return tmp_path, original, copy_


# -- conflict_resolver: refusal paths must never touch a body ---------------


def test_theirs_without_expected_mtime_is_refused(tmp_path):
    """"theirs" overwrites a body, so it must REFUSE to run without the
    optimistic-concurrency token rather than clobber blind."""
    vault, original, copy_ = _vault(tmp_path)
    with pytest.raises(ValueError, match="expected_mtime"):
        resolve_conflict(vault, str(original), str(copy_), "theirs")
    # Refusal is total: nothing moved, nothing rewritten.
    assert original.read_text(encoding="utf-8") == _ORIGINAL
    assert copy_.exists()


def test_theirs_with_stale_mtime_refuses_and_preserves_both(tmp_path):
    """If the note changed on disk since the diff was loaded, "theirs" must
    raise (route -> 409) and leave BOTH files intact — a silent clobber here
    would destroy a user edit the GUI never showed."""
    vault, original, copy_ = _vault(tmp_path)
    conflict = get_conflict(vault, str(original))
    stale = conflict["local_mtime"] - 5.0
    with pytest.raises(NoteConflictError):
        resolve_conflict(vault, str(original), str(copy_), "theirs", stale)
    assert original.read_text(encoding="utf-8") == _ORIGINAL
    assert copy_.read_text(encoding="utf-8") == _COPY
    assert not (vault / "_trash").exists() or not list(( vault / "_trash").glob("*.md"))


def test_unknown_action_raises_and_changes_nothing(tmp_path):
    """A typo'd/unsupported action must be a loud ValueError (route -> 400),
    never a silent no-op that the GUI reports as a successful resolve."""
    vault, original, copy_ = _vault(tmp_path)
    with pytest.raises(ValueError, match="unknown resolve action"):
        resolve_conflict(vault, str(original), str(copy_), "keep-both")
    assert original.read_text(encoding="utf-8") == _ORIGINAL
    assert copy_.exists()


def test_resolve_when_copy_already_gone_raises_before_any_write(tmp_path):
    """Concurrent resolve (other device already handled it): the missing copy
    must be detected BEFORE the body write, so "theirs" cannot half-apply."""
    vault, original, copy_ = _vault(tmp_path)
    conflict = get_conflict(vault, str(original))
    copy_.unlink()
    with pytest.raises(FileNotFoundError):
        resolve_conflict(vault, str(original), str(copy_), "theirs", conflict["local_mtime"])
    assert original.read_text(encoding="utf-8") == _ORIGINAL


def test_both_action_is_a_pure_no_op(tmp_path):
    """"both" keeps the copy as an independent note — it must perform no file
    operation at all (no trash, no body write)."""
    vault, original, copy_ = _vault(tmp_path)
    result = resolve_conflict(vault, str(original), str(copy_), "both")
    assert result == {"ok": True, "action": "both"}
    assert original.read_text(encoding="utf-8") == _ORIGINAL
    assert copy_.read_text(encoding="utf-8") == _COPY
    assert not (vault / "_trash").exists()


def test_mine_trashes_the_copy_and_leaves_the_original_verbatim(tmp_path):
    """"mine" discards the remote side. The original note must not be
    rewritten at all — not even reformatted — because the user chose the body
    that is already on disk."""
    vault, original, copy_ = _vault(tmp_path)
    result = resolve_conflict(vault, str(original), str(copy_), "mine")

    assert result == {"ok": True, "action": "mine"}
    assert original.read_text(encoding="utf-8") == _ORIGINAL
    assert not copy_.exists()
    assert (vault / "_trash" / copy_.name).is_file(), "copy must be recoverable from trash"


def test_theirs_swaps_the_body_but_preserves_the_original_frontmatter(tmp_path):
    """"theirs" takes the remote BODY only. The original note keeps its own
    frontmatter (its id/category are the ones the vault and hub already index)
    — importing the copy's frontmatter would fork the note's identity."""
    vault, original, copy_ = _vault(tmp_path)
    conflict = get_conflict(vault, str(original))

    result = resolve_conflict(vault, str(original), str(copy_), "theirs", conflict["local_mtime"])

    assert result == {"ok": True, "action": "theirs"}
    text = original.read_text(encoding="utf-8")
    assert "Their remote body." in text
    assert "My local body." not in text
    assert "id: 01ORIG" in text, "original frontmatter id must survive a 'theirs'"
    assert "01COPY" not in text, "copy's identity must not leak into the original"
    assert not copy_.exists()
    assert (vault / "_trash" / copy_.name).is_file()


def test_resolve_when_original_note_is_gone_raises(tmp_path):
    """Original deleted out from under the open diff -> FileNotFoundError
    (route -> 404) rather than resurrecting it from the copy."""
    vault, original, copy_ = _vault(tmp_path)
    original.unlink()
    with pytest.raises(FileNotFoundError):
        resolve_conflict(vault, str(original), str(copy_), "mine")
    assert copy_.exists(), "copy must not be trashed when the original is missing"


# -- _trash_file: the non-destructive move contract -------------------------


def test_trashing_same_named_files_does_not_overwrite(tmp_path):
    """Two conflicted copies from different categories can share a filename.
    Trashing the second must not destroy the first — both must survive."""
    (tmp_path / "Tech_Notes").mkdir()
    (tmp_path / "Personal").mkdir()
    a = tmp_path / "Tech_Notes" / "dup.md"
    b = tmp_path / "Personal" / "dup.md"
    a.write_text("---\ntitle: A\n---\nbody A\n", encoding="utf-8")
    b.write_text("---\ntitle: B\n---\nbody B\n", encoding="utf-8")

    _trash_file(tmp_path, a)
    _trash_file(tmp_path, b)

    trashed = sorted((tmp_path / "_trash").glob("*.md"))
    assert len(trashed) == 2, "second trash overwrote the first"
    bodies = {p.read_text(encoding="utf-8").strip().splitlines()[-1] for p in trashed}
    assert bodies == {"body A", "body B"}


def test_trash_bumps_mtime_to_deletion_time(tmp_path):
    """F-2: shutil.move preserves the source mtime, but the Trash view shows
    "deleted N days ago" from the trashed file's mtime — so the move MUST
    restamp it, or an old note reads as deleted years ago the moment it lands."""
    (tmp_path / "Tech_Notes").mkdir()
    f = tmp_path / "Tech_Notes" / "old.md"
    f.write_text("---\ntitle: Old\n---\nbody\n", encoding="utf-8")
    ancient = time.time() - (365 * 24 * 3600)
    os.utime(f, (ancient, ancient))

    dest = _trash_file(tmp_path, f)

    assert abs(dest.stat().st_mtime - time.time()) < 30, "mtime not restamped to trash time"
    assert dest.stat().st_mtime > ancient + 1000


# -- detection / scanning ---------------------------------------------------


def test_get_conflict_is_none_when_no_sibling(tmp_path):
    """A clean note must report no conflict — the GUI banner is driven off
    this None, so a false positive would badge every note."""
    vault, original, copy_ = _vault(tmp_path)
    copy_.unlink()
    assert get_conflict(vault, str(original)) is None
    assert find_conflict_sibling(vault, str(original)) is None


def test_find_conflict_sibling_missing_note_raises(tmp_path):
    """Missing note -> FileNotFoundError (route -> 404), not a silent None
    that would read as "no conflict"."""
    (tmp_path / "Tech_Notes").mkdir()
    with pytest.raises(FileNotFoundError):
        find_conflict_sibling(tmp_path, str(tmp_path / "Tech_Notes" / "ghost.md"))


def test_list_vault_conflicts_skips_reserved_folders(tmp_path):
    """A conflicted pair already sitting in _trash/ is resolved history, not a
    live conflict — badging it would make a resolved conflict un-dismissable."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    (trash_dir / "example.md").write_text(_ORIGINAL, encoding="utf-8")
    (trash_dir / "01COPY.md").write_text(_COPY, encoding="utf-8")
    assert list_vault_conflicts(tmp_path) == []


def test_list_vault_conflicts_requires_same_parent(tmp_path):
    """reconcile.py always writes the copy NEXT TO the original. A title-prefix
    match across two different category folders is a coincidence, not a
    conflict, and must not be reported."""
    (tmp_path / "Tech_Notes").mkdir()
    (tmp_path / "Personal").mkdir()
    (tmp_path / "Tech_Notes" / "example.md").write_text(_ORIGINAL, encoding="utf-8")
    (tmp_path / "Personal" / "01COPY.md").write_text(_COPY, encoding="utf-8")
    assert list_vault_conflicts(tmp_path) == []


def test_list_vault_conflicts_finds_same_parent_pair(tmp_path):
    """The positive case the two negatives above must not be masking."""
    vault, original, copy_ = _vault(tmp_path)
    found = list_vault_conflicts(vault)
    assert len(found) == 1
    assert found[0]["path"] == str(original)
    assert found[0]["conflict_path"] == str(copy_)
    assert found[0]["title"] == "Example note"


def test_list_vault_conflicts_missing_root_is_empty(tmp_path):
    """A misconfigured/unmounted vault root must degrade to "no conflicts",
    not crash the bulk-badge request for the whole Library view."""
    assert list_vault_conflicts(tmp_path / "nope") == []


def test_unreadable_sibling_does_not_break_conflict_detection(tmp_path, monkeypatch):
    """A vault file can be transiently unreadable (OneDrive/AV lock on
    Windows). One bad sibling must not fail the whole conflict lookup — the
    real conflicted copy still has to be found."""
    vault, original, copy_ = _vault(tmp_path)
    # Sorts ahead of 01COPY.md so the scan hits the unreadable file FIRST and
    # must recover from it before it can find the real conflicted copy.
    locked = original.parent / "00-locked.md"
    locked.write_text("---\ntitle: Locked\n---\nbody\n", encoding="utf-8")

    real_read_text = Path.read_text

    def flaky(self, *a, **kw):
        if self.name == "00-locked.md":
            raise OSError("file is locked by another process")
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert find_conflict_sibling(vault, str(original)) == copy_


def test_unreadable_note_does_not_break_the_bulk_conflict_scan(tmp_path, monkeypatch):
    """Same for the vault-wide scan behind /vault/conflicts: one locked file
    must not 500 the badge request for every other row."""
    vault, original, copy_ = _vault(tmp_path)
    locked = original.parent / "locked.md"
    locked.write_text("---\ntitle: Locked\n---\nbody\n", encoding="utf-8")

    real_read_text = Path.read_text

    def flaky(self, *a, **kw):
        if self.name == "locked.md":
            raise OSError("file is locked by another process")
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    found = list_vault_conflicts(vault)
    assert len(found) == 1
    assert found[0]["path"] == str(original)


# -- trash.py ---------------------------------------------------------------


def test_list_trash_without_trash_dir_is_empty(tmp_path):
    """A vault that never trashed anything has no _trash/ — the Trash view
    must render empty rather than 500."""
    assert list_trash(tmp_path) == []


def test_restore_does_not_overwrite_a_live_note(tmp_path):
    """If a note with the same filename was recreated while the old one sat in
    trash, restoring must not destroy the live note."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    (trash_dir / "dup.md").write_text(
        "---\ntitle: Trashed\ncategory: Personal\n---\ntrashed body\n", encoding="utf-8"
    )
    live_dir = tmp_path / "Personal"
    live_dir.mkdir()
    live = live_dir / "dup.md"
    live.write_text("---\ntitle: Live\ncategory: Personal\n---\nlive body\n", encoding="utf-8")

    result = restore_from_trash(tmp_path, "dup.md")

    assert live.read_text(encoding="utf-8").endswith("live body\n"), "restore clobbered live note"
    assert Path(result["path"]) != live
    assert Path(result["path"]).read_text(encoding="utf-8").endswith("trashed body\n")
    assert list_trash(tmp_path) == []


def test_restore_missing_file_raises(tmp_path):
    """Restoring an already-purged/never-existing file must 404, not create an
    empty note at the destination."""
    (tmp_path / "_trash").mkdir()
    with pytest.raises(FileNotFoundError):
        restore_from_trash(tmp_path, "ghost.md")


def test_restore_without_category_goes_to_uncategorized(tmp_path):
    """Frontmatter is the only source for the restore target; a note missing
    `category` must still be restorable, not stranded in trash forever."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    (trash_dir / "orphan.md").write_text("---\ntitle: Orphan\n---\nbody\n", encoding="utf-8")

    result = restore_from_trash(tmp_path, "orphan.md")

    assert result["category"] == "Uncategorized"
    assert (tmp_path / "Uncategorized" / "orphan.md").is_file()


def test_unreadable_trash_entry_is_skipped_not_fatal(tmp_path, monkeypatch):
    """One unreadable file in _trash/ must not blank the whole Trash view."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    (trash_dir / "good.md").write_text(
        "---\ntitle: Good\ncategory: Personal\n---\nbody\n", encoding="utf-8"
    )
    (trash_dir / "locked.md").write_text("---\ntitle: Locked\n---\nbody\n", encoding="utf-8")

    real_read_text = Path.read_text

    def flaky(self, *a, **kw):
        if self.name == "locked.md":
            raise OSError("file is locked by another process")
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    items = list_trash(tmp_path)
    assert [i["filename"] for i in items] == ["good.md"]


def test_move_to_trash_is_body_byte_identical(tmp_path):
    """ISS-005 A: a user delete is a soft MOVE — frontmatter + sacred body byte-identical
    after, and the file leaves its category folder for _trash/."""
    cat = tmp_path / "Personal"
    cat.mkdir()
    note = cat / "keep.md"
    # CRLF body + trailing spaces: a byte churn (newline translation, rstrip) would show here.
    raw = (
        b"---\ntitle: Keep\ncategory: Personal\norigin: note\n---\n"
        b"# Keep\r\n\r\nSacred body.   \n"
    )
    note.write_bytes(raw)

    result = move_to_trash(tmp_path, note)

    assert not note.exists(), "note must leave its category folder"
    trashed = tmp_path / "_trash" / result["filename"]
    assert trashed.read_bytes() == raw, "move_to_trash rewrote the note bytes"
    # Original category survives in frontmatter → restore puts it back where it was.
    listed = list_trash(tmp_path)
    assert listed and listed[0]["category"] == "Personal"


def test_move_to_trash_round_trips_with_restore(tmp_path):
    """A trashed note restores to its original category (the symmetric move, both directions)."""
    cat = tmp_path / "Work"
    cat.mkdir()
    note = cat / "task.md"
    note.write_text("---\ntitle: Task\ncategory: Work\norigin: note\n---\nbody\n", encoding="utf-8")

    moved = move_to_trash(tmp_path, note)
    assert not note.exists()
    restored = restore_from_trash(tmp_path, moved["filename"])
    assert restored["category"] == "Work"
    assert (cat / moved["filename"]).is_file()


def test_move_to_trash_missing_note_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        move_to_trash(tmp_path, tmp_path / "Personal" / "ghost.md")


def test_move_to_trash_does_not_overwrite_a_same_named_trash_entry(tmp_path):
    """Two notes sharing a filename, deleted in turn, must both survive in _trash/."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    (trash_dir / "dup.md").write_text("---\ntitle: First\n---\nfirst\n", encoding="utf-8")
    cat = tmp_path / "Personal"
    cat.mkdir()
    live = cat / "dup.md"
    live.write_text("---\ntitle: Second\n---\nsecond\n", encoding="utf-8")

    result = move_to_trash(tmp_path, live)
    assert result["filename"] != "dup.md", "must not clobber the existing trashed note"
    assert (trash_dir / "dup.md").read_text(encoding="utf-8").endswith("first\n")
    assert (trash_dir / result["filename"]).read_text(encoding="utf-8").endswith("second\n")


def test_list_trash_is_newest_deleted_first(tmp_path):
    """The Trash view shows a purge countdown; ordering must be by deletion
    time so the soonest-to-purge is not buried."""
    trash_dir = tmp_path / "_trash"
    trash_dir.mkdir()
    now = time.time()
    for name, age in (("old.md", 10_000), ("mid.md", 5_000), ("new.md", 10)):
        f = trash_dir / name
        f.write_text(f"---\ntitle: {name}\ncategory: Personal\n---\nbody\n", encoding="utf-8")
        os.utime(f, (now - age, now - age))

    items = list_trash(trash_dir.parent)

    assert [i["filename"] for i in items] == ["new.md", "mid.md", "old.md"]
    assert all(i["purge_at"] == i["deleted_at"] + 30 * 24 * 3600 for i in items)
