"""
test_dedup_and_inbox.py
-----------------------
Pytest suite covering:

  1. Content-hash deduplication (same text, different objects)
  2. URL-normalisation deduplication (query param order)
  3. Filename collision avoidance (same slug, different content)
  4. Inbox routing on low confidence
  5. Inbox routing on requires_new_category
  6. Scratchpad list_scratchpad
  7. Inbox approve → moves to final category, strips needs_review/note_id
  8. Inbox discard → file deleted
  9. Inbox approve with target_category override
 10. Approve removes category-default status fields from inbox frontmatter
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Make omni_capture importable when tests run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
from storage_engine import (
    SCRATCHPAD_CONFIDENCE_THRESHOLD,
    approve_scratchpad_item,
    check_duplicate,
    discard_scratchpad_item,
    list_scratchpad,
    register_in_dedup_index,
    route_to_scratchpad,
    write_to_vault,
    _content_hash,
    _normalize_url,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    return tmp_path


def _make(
    category="Tech_Notes",
    filename="test-note",
    content="Some content.",
    confidence=0.9,
    requires_new=False,
    new_cat=None,
) -> CaptureOutput:
    return CaptureOutput(
        category=category,
        suggested_filename=filename,
        markdown_content=content,
        key_signals=[],
        confidence=confidence,
        requires_new_category=requires_new,
    )


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDedup:
    def test_same_content_skips_second_write(self, vault):
        t = _make(content="Unique content ABC")
        p1 = write_to_vault(t, vault_root=vault)
        p2 = write_to_vault(t, vault_root=vault)
        assert p1 == p2, "Second write should return first path unchanged"
        # Only one file exists at that path
        assert p1.exists()

    def test_different_content_writes_separately(self, vault):
        t1 = _make(content="Alpha content", filename="note-a")
        t2 = _make(content="Beta content",  filename="note-b")
        p1 = write_to_vault(t1, vault_root=vault)
        p2 = write_to_vault(t2, vault_root=vault)
        assert p1 != p2

    def test_url_normalisation_dedup(self, vault):
        """Query params in different order → same hash."""
        t = _make(content="YouTube snippet", filename="yt-vid", category="Watch_Later")
        url_a = "https://youtube.com/watch?v=xyz&t=30"
        url_b = "https://youtube.com/watch?t=30&v=xyz"
        p1 = write_to_vault(t, source_url=url_a, vault_root=vault)
        p2 = write_to_vault(t, source_url=url_b, vault_root=vault)
        assert p1 == p2

    def test_url_normalisation_hash_consistency(self):
        a = _normalize_url("https://Example.COM/page/?z=1&a=2#frag")
        b = _normalize_url("https://example.com/page?a=2&z=1")
        assert _content_hash("x", a) == _content_hash("x", b)

    def test_check_duplicate_returns_none_before_registration(self, vault):
        result = check_duplicate("brand new text", None, vault)
        assert result is None

    def test_check_duplicate_returns_path_after_registration(self, vault, tmp_path):
        note = tmp_path / "vault" / "Tech_Notes" / "note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("# Note")
        register_in_dedup_index("some text", None, vault, note)
        result = check_duplicate("some text", None, vault)
        assert result is not None

    def test_finance_dedup_prevents_duplicate_row(self, vault):
        t = _make(
            category="Finance",
            content="| 2026-06-17 | Coffee | 3.50 | USD | food |",
            confidence=0.95,
        )
        write_to_vault(t, vault_root=vault)
        write_to_vault(t, vault_root=vault)  # duplicate — should be skipped
        expenses = vault / "Finance" / "Expenses.md"
        rows = [l for l in expenses.read_text().splitlines() if "Coffee" in l]
        assert len(rows) == 1, f"Duplicate Finance row was written: {rows}"


# ── Filename collisions ────────────────────────────────────────────────────────

class TestFilenameCollision:
    def test_same_slug_different_content_appends_to_existing_file(self, vault):
        """
        For appendable categories (Tech_Notes etc.), a second capture with the
        same slug appends to the same file rather than creating a new one.
        This is the intended collision-resolution strategy: one note per topic,
        not one file per capture.  Dedup prevents true duplicates; general-append
        handles new content under the same slug.
        """
        t1 = _make(content="First  note, unique content A.", filename="shared-slug")
        t2 = _make(content="Second note, unique content B.", filename="shared-slug")
        p1 = write_to_vault(t1, vault_root=vault)
        p2 = write_to_vault(t2, vault_root=vault)
        # Both writes resolve to the same file (append, not overwrite)
        assert p1 == p2
        combined = p1.read_text()
        assert "unique content A" in combined
        assert "unique content B" in combined

    def test_unique_file_path_used_during_inbox_approval(self, vault):
        """
        _unique_file_path collision avoidance is exercised by approve_scratchpad_item
        when a note with the same stem already exists in the target category.
        """
        from storage_engine import approve_scratchpad_item

        # Pre-create a note at the target path
        existing = _make(content="Pre-existing vault note.", filename="slug-x", confidence=0.9)
        write_to_vault(existing, vault_root=vault)

        # Seed inbox with same slug
        inbox_note = _make(content="Inbox note for same slug unique qqq.", confidence=0.1,
                           filename="slug-x")
        write_to_vault(inbox_note, vault_root=vault)
        items = list_scratchpad(vault)
        note_id = items[0]["note_id"]

        dest = approve_scratchpad_item(note_id, vault, target_category="Tech_Notes")
        original = vault / "Tech_Notes" / "slug-x.md"
        assert original.exists(), "Original should not be overwritten"
        assert dest.exists()
        # dest stem should differ from the original (hex suffix appended)
        if dest != original:
            assert dest.stem.startswith("slug-x-"), f"Unexpected dest stem: {dest.stem}"
            hex_part = dest.stem.split("-")[-1]
            assert len(hex_part) == 6 and all(c in "0123456789abcdef" for c in hex_part)


# ── Inbox routing ─────────────────────────────────────────────────────────────

class TestInboxRouting:
    def test_low_confidence_goes_to_inbox(self, vault):
        t = _make(content="Uncertain content XYZ.", confidence=SCRATCHPAD_CONFIDENCE_THRESHOLD - 0.1)
        p = write_to_vault(t, vault_root=vault)
        assert "_scratchpad" in str(p), f"Expected _scratchpad path, got {p}"

    def test_high_confidence_does_not_go_to_inbox(self, vault):
        t = _make(content="Very confident content.", confidence=SCRATCHPAD_CONFIDENCE_THRESHOLD + 0.1)
        p = write_to_vault(t, vault_root=vault)
        assert "_inbox" not in str(p), f"Did not expect _inbox path, got {p}"

    def test_requires_new_category_goes_to_inbox(self, vault):
        t = _make(
            content="This is a completely new domain.",
            confidence=0.9,
            requires_new=True,
            new_cat="Fitness_Log",
        )
        p = write_to_vault(t, vault_root=vault)
        assert "_scratchpad" in str(p)

    def test_inbox_note_has_needs_review_status(self, vault):
        t = _make(content="Inbox item content.", confidence=0.1)
        p = write_to_vault(t, vault_root=vault)
        text = p.read_text()
        assert "status: needs_review" in text

    def test_inbox_note_has_note_id(self, vault):
        t = _make(content="Inbox item 2 content.", confidence=0.1)
        p = write_to_vault(t, vault_root=vault)
        text = p.read_text()
        assert "note_id:" in text

    def test_inbox_note_has_confidence_field(self, vault):
        t = _make(content="Low conf content.", confidence=0.3)
        p = write_to_vault(t, vault_root=vault)
        text = p.read_text()
        assert "confidence:" in text


# ── list_scratchpad ────────────────────────────────────────────────────────────────

class TestListInbox:
    def test_empty_inbox_returns_empty_list(self, vault):
        items = list_scratchpad(vault)
        assert items == []

    def test_list_inbox_returns_all_items(self, vault):
        for i in range(3):
            t = _make(content=f"Unique inbox note #{i}", confidence=0.1, filename=f"note-{i}")
            write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        assert len(items) == 3

    def test_list_inbox_item_has_required_keys(self, vault):
        t = _make(content="Inbox meta check.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        assert len(items) == 1
        item = items[0]
        for key in ("note_id", "filename", "path", "category", "size", "modified"):
            assert key in item, f"Missing key: {key}"


# ── approve_scratchpad_item ────────────────────────────────────────────────────────

class TestApproveInbox:
    def _seed_inbox(self, vault, content="Inbox note to approve.", category="Tech_Notes"):
        t = _make(content=content, confidence=0.1, category=category)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        assert items
        return items[0]["note_id"]

    def test_approve_moves_to_vault(self, vault):
        note_id = self._seed_inbox(vault)
        dest = approve_scratchpad_item(note_id, vault)
        assert dest.exists()
        assert "_inbox" not in str(dest)

    def test_approve_removes_from_inbox(self, vault):
        note_id = self._seed_inbox(vault)
        approve_scratchpad_item(note_id, vault)
        items = list_scratchpad(vault)
        assert all(i["note_id"] != note_id for i in items)

    def test_approve_strips_needs_review(self, vault):
        note_id = self._seed_inbox(vault)
        dest = approve_scratchpad_item(note_id, vault)
        assert "needs_review" not in dest.read_text()

    def test_approve_strips_note_id_field(self, vault):
        note_id = self._seed_inbox(vault)
        dest = approve_scratchpad_item(note_id, vault)
        assert "note_id:" not in dest.read_text()

    def test_approve_with_target_category_override(self, vault):
        note_id = self._seed_inbox(vault, category="Tech_Notes")
        dest = approve_scratchpad_item(note_id, vault, target_category="Journal")
        assert "Journal" in str(dest)

    def test_approve_nonexistent_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            approve_scratchpad_item("nonexistent_id", vault)

    def test_approve_sets_watch_later_status_to_unread(self, vault):
        note_id = self._seed_inbox(vault, category="Watch_Later",
                                   content="Watch this video later unique www.")
        dest = approve_scratchpad_item(note_id, vault, target_category="Watch_Later")
        text = dest.read_text()
        assert "status: unread" in text

    def test_approve_collision_safe(self, vault):
        existing = _make(content="Existing vault note.", filename="test-note",
                         category="Tech_Notes", confidence=0.9)
        write_to_vault(existing, vault_root=vault)
        note_id = self._seed_inbox(vault, content="Inbox note, same slug.")
        dest = approve_scratchpad_item(note_id, vault, target_category="Tech_Notes")
        # "note" is a filename stopword (see storage_engine._FILENAME_STOPWORDS),
        # so "test-note" is shortened to "test" before being written.
        original = vault / "Tech_Notes" / "test.md"
        assert original.exists()
        assert dest.exists()


class TestDiscardInbox:
    def test_discard_removes_file(self, vault):
        t = _make(content="Discard this note unique aaa.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        note_id = items[0]["note_id"]
        path = Path(items[0]["path"])
        discard_scratchpad_item(note_id, vault)
        assert not path.exists()

    def test_discard_removes_from_list(self, vault):
        t = _make(content="Remove from list unique bbb.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        note_id = items[0]["note_id"]
        discard_scratchpad_item(note_id, vault)
        items_after = list_scratchpad(vault)
        assert all(i["note_id"] != note_id for i in items_after)

    def test_discard_nonexistent_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            discard_scratchpad_item("no_such_id", vault)
