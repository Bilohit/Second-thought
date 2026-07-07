"""
test_storage_engine.py
----------------------
Consolidated storage_engine pytest suite, merged from:
  * test_dedup_and_inbox.py       (dedup, filename collisions, inbox routing)
  * test_routing_and_merge.py     (routing bug fix, smart merge, embedding fallback)
  * test_confidence_threshold.py  (configurable confidence threshold)
  * test_ocr_storage.py           (OCR fast-path vs vision transcription)
  * test_voice_unique.py          (voice recordings always create new files)

Test bodies are preserved verbatim from their originals. Same-name helpers with
differing bodies were renamed to keep both:
  * _make  -> _make_dedup / _make_routing
  * _out   -> _out_conf   / _out_voice
"""
from __future__ import annotations

import sys
import tempfile
import types
import urllib.error
import unittest.mock as mock
from pathlib import Path
from unittest import mock as _mock  # noqa: F401  (routing_and_merge used `from unittest import mock`)

import pytest

# Make omni_capture importable when tests run from repo root
sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
import storage_engine as se
import vector_store
from storage_engine import (
    SCRATCHPAD_CONFIDENCE_THRESHOLD,
    approve_scratchpad_item,
    check_duplicate,
    discard_scratchpad_item,
    find_merge_target,
    list_scratchpad,
    register_in_dedup_index,
    route_to_scratchpad,
    write_to_vault,
    _content_hash,
    _normalize_url,
)


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# From test_dedup_and_inbox.py
# ══════════════════════════════════════════════════════════════════════════════

def _make_dedup(
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
        t = _make_dedup(content="Unique content ABC")
        p1 = write_to_vault(t, vault_root=vault)
        p2 = write_to_vault(t, vault_root=vault)
        assert p1 == p2, "Second write should return first path unchanged"
        # Only one file exists at that path
        assert p1.exists()

    def test_different_content_writes_separately(self, vault):
        t1 = _make_dedup(content="Alpha content", filename="note-a")
        t2 = _make_dedup(content="Beta content",  filename="note-b")
        p1 = write_to_vault(t1, vault_root=vault)
        p2 = write_to_vault(t2, vault_root=vault)
        assert p1 != p2

    def test_url_normalisation_dedup(self, vault):
        """Query params in different order → same hash."""
        t = _make_dedup(content="YouTube snippet", filename="yt-vid", category="Watch_Later")
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
        t = _make_dedup(
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
        t1 = _make_dedup(content="First  note, unique content A.", filename="shared-slug")
        t2 = _make_dedup(content="Second note, unique content B.", filename="shared-slug")
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
        existing = _make_dedup(content="Pre-existing vault note.", filename="slug-x", confidence=0.9)
        write_to_vault(existing, vault_root=vault)

        # Seed inbox with same slug
        inbox_note = _make_dedup(content="Inbox note for same slug unique qqq.", confidence=0.1,
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
        t = _make_dedup(content="Uncertain content XYZ.", confidence=SCRATCHPAD_CONFIDENCE_THRESHOLD - 0.1)
        p = write_to_vault(t, vault_root=vault)
        assert "_scratchpad" in str(p), f"Expected _scratchpad path, got {p}"

    def test_high_confidence_does_not_go_to_inbox(self, vault):
        t = _make_dedup(content="Very confident content.", confidence=SCRATCHPAD_CONFIDENCE_THRESHOLD + 0.1)
        p = write_to_vault(t, vault_root=vault)
        assert "_inbox" not in str(p), f"Did not expect _inbox path, got {p}"

    def test_requires_new_category_goes_to_inbox(self, vault):
        t = _make_dedup(
            content="This is a completely new domain.",
            confidence=0.9,
            requires_new=True,
            new_cat="Fitness_Log",
        )
        p = write_to_vault(t, vault_root=vault)
        assert "_scratchpad" in str(p)

    def test_inbox_note_has_needs_review_status(self, vault):
        t = _make_dedup(content="Inbox item content.", confidence=0.1)
        p = write_to_vault(t, vault_root=vault)
        text = p.read_text()
        assert "status: needs_review" in text

    def test_inbox_note_has_note_id(self, vault):
        t = _make_dedup(content="Inbox item 2 content.", confidence=0.1)
        p = write_to_vault(t, vault_root=vault)
        text = p.read_text()
        assert "note_id:" in text

    def test_inbox_note_has_confidence_field(self, vault):
        t = _make_dedup(content="Low conf content.", confidence=0.3)
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
            t = _make_dedup(content=f"Unique inbox note #{i}", confidence=0.1, filename=f"note-{i}")
            write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        assert len(items) == 3

    def test_list_inbox_item_has_required_keys(self, vault):
        t = _make_dedup(content="Inbox meta check.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        assert len(items) == 1
        item = items[0]
        for key in ("note_id", "filename", "path", "category", "size", "modified"):
            assert key in item, f"Missing key: {key}"


# ── approve_scratchpad_item ────────────────────────────────────────────────────────

class TestApproveInbox:
    def _seed_inbox(self, vault, content="Inbox note to approve.", category="Tech_Notes"):
        t = _make_dedup(content=content, confidence=0.1, category=category)
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
        existing = _make_dedup(content="Existing vault note.", filename="test-note",
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
        t = _make_dedup(content="Discard this note unique aaa.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        note_id = items[0]["note_id"]
        path = Path(items[0]["path"])
        discard_scratchpad_item(note_id, vault)
        assert not path.exists()

    def test_discard_removes_from_list(self, vault):
        t = _make_dedup(content="Remove from list unique bbb.", confidence=0.1)
        write_to_vault(t, vault_root=vault)
        items = list_scratchpad(vault)
        note_id = items[0]["note_id"]
        discard_scratchpad_item(note_id, vault)
        items_after = list_scratchpad(vault)
        assert all(i["note_id"] != note_id for i in items_after)

    def test_discard_nonexistent_raises(self, vault):
        with pytest.raises(FileNotFoundError):
            discard_scratchpad_item("no_such_id", vault)


# ══════════════════════════════════════════════════════════════════════════════
# From test_routing_and_merge.py
# ══════════════════════════════════════════════════════════════════════════════

def _make_routing(category="Tech_Notes", filename="note", content="content",
          signals=None, confidence=0.9):
    return CaptureOutput(
        category=category,
        suggested_filename=filename,
        markdown_content=content,
        key_signals=signals or [],
        confidence=confidence,
        requires_new_category=False,
    )


# -- Bug fix: a URL must not collapse distinct content -----------------------

class TestRoutingBugFix:
    def test_same_url_different_content_not_deduped(self, vault):
        """The reported bug: two unrelated captures sharing a source URL were
        treated as duplicates.  They must now land in separate files."""
        url = "https://example.com/wiki/article"
        t1 = _make_routing(filename="mri-scans", content="MRI scans use magnetic fields.",
                   signals=["mri", "imaging"])
        t2 = _make_routing(filename="mouse-dongle", content="ATK mouse dongle sharing limitation.",
                   signals=["mouse", "usb"])
        p1 = write_to_vault(t1, source_url=url, vault_root=vault)
        p2 = write_to_vault(t2, source_url=url, vault_root=vault)
        assert p1 != p2, "Distinct content on same URL must not be deduped"
        assert p1.exists() and p2.exists()

    def test_same_url_same_content_is_deduped(self, vault):
        url = "https://example.com/page"
        t = _make_routing(content="identical body", signals=["x"])
        p1 = write_to_vault(t, source_url=url, vault_root=vault)
        p2 = write_to_vault(t, source_url=url, vault_root=vault)
        assert p1 == p2

    def test_hash_differs_for_different_content_same_url(self):
        url = "https://example.com/page"
        assert _content_hash("alpha text", url) != _content_hash("beta text", url)

    def test_dedup_hit_in_different_category_refiles_to_decided_category(self, vault):
        """The reported bug: a capture decided as CRM was silently short-circuited
        to a stale Tech_Notes copy because dedup ignored the category. A dedup
        hit in a different category must NOT win over the decided category."""
        body = "Notes about a historical matter."
        old = _make_routing(category="Tech_Notes", filename="tech-notes",
                    content=body, signals=["history"])
        p_old = write_to_vault(old, vault_root=vault)
        assert "Tech_Notes" in str(p_old)

        new = _make_routing(category="CRM", filename="historical-matter",
                    content=body, signals=["history"], confidence=0.95)
        p_new = write_to_vault(new, vault_root=vault)

        assert "CRM" in str(p_new), f"Expected CRM landing, got {p_new}"
        assert "Tech_Notes" not in str(p_new)
        assert p_new.exists()

    def test_dedup_skips_exact_duplicate_in_same_category(self, vault):
        """Genuine re-capture into the same decided category still dedups."""
        t = _make_routing(category="Tech_Notes", filename="asyncio", content="same body",
                  signals=["python"], confidence=0.95)
        p1 = write_to_vault(t, vault_root=vault)
        p2 = write_to_vault(t, vault_root=vault)
        assert p1 == p2

    def test_stale_index_entry_does_not_drop_capture(self, vault):
        """If the dedup index points to a note that no longer exists, a new
        capture with that hash must still be written, not silently skipped."""
        t = _make_routing(content="orphaned hash content", signals=["y"])
        register_in_dedup_index(t.markdown_content, None, vault,
                                vault / "Tech_Notes" / "ghost.md")
        assert check_duplicate(t.markdown_content, None, vault) is not None
        p = write_to_vault(t, vault_root=vault)
        assert p.exists(), "Capture must be written despite stale index entry"
        assert "ghost" not in p.name


# -- Feature: smart context-aware merging ------------------------------------

class TestSmartMerge:
    def test_confident_merge_same_topic_different_filename(self, vault):
        """Two gaming-mice captures with different filenames but strong shared
        tags should merge into one file."""
        day1 = _make_routing(filename="logitech-g502-review",
                     content="The G502 has great sensors.",
                     signals=["gaming-mice", "logitech", "hardware"])
        day2 = _make_routing(filename="razer-deathadder-notes",
                     content="The DeathAdder is comfortable.",
                     signals=["gaming-mice", "razer", "hardware"])
        p1 = write_to_vault(day1, vault_root=vault)
        p2 = write_to_vault(day2, vault_root=vault)
        assert p1 == p2, "Same-topic captures should merge into one file"
        body = p1.read_text()
        assert "G502" in body and "DeathAdder" in body

    def test_distinct_topics_stay_separate(self, vault):
        """No shared tags -> never merge, even in the same category."""
        a = _make_routing(filename="python-asyncio", content="asyncio event loop.",
                  signals=["python", "asyncio", "concurrency"])
        b = _make_routing(filename="docker-networking", content="docker bridge networks.",
                  signals=["docker", "networking", "containers"])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2

    def test_single_shared_tag_does_not_merge_without_semantics(self, vault):
        """A single shared tag is not enough confidence on its own."""
        a = _make_routing(filename="note-a", content="content a", signals=["hardware", "keyboards"])
        b = _make_routing(filename="note-b", content="content b", signals=["hardware", "monitors"])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2, "One shared tag should not trigger a merge"

    def test_no_tags_never_merges(self, vault):
        a = _make_routing(filename="note-a", content="alpha", signals=[])
        b = _make_routing(filename="note-b", content="beta", signals=[])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2

    def test_find_merge_target_returns_none_when_no_candidates(self, vault):
        out = _make_routing(signals=["gaming-mice", "hardware"])
        assert find_merge_target(out, vault) is None


# -- Embedding endpoint fallback ---------------------------------------------

class TestEmbeddingFallback:
    def test_falls_back_to_legacy_endpoint_on_404(self):
        calls = {}

        def fake_post(url, payload):
            calls["last"] = url
            if url.endswith("/api/embed"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            assert "prompt" in payload
            return {"embedding": [0.1, 0.2, 0.3]}

        with mock.patch.object(vector_store, "_post_json", side_effect=fake_post):
            vec = vector_store._embed("hello", "http://localhost:11434")
        assert vec == [0.1, 0.2, 0.3]
        assert calls["last"].endswith("/api/embeddings")

    def test_uses_modern_endpoint_when_available(self):
        def fake_post(url, payload):
            assert url.endswith("/api/embed")
            assert "input" in payload
            return {"embeddings": [[0.4, 0.5]]}

        with mock.patch.object(vector_store, "_post_json", side_effect=fake_post):
            vec = vector_store._embed("hi", "http://localhost:11434/v1")
        assert vec == [0.4, 0.5]

    def test_non_404_error_is_not_swallowed(self):
        def fake_post(url, payload):
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)

        with mock.patch.object(vector_store, "_post_json", side_effect=fake_post):
            with pytest.raises(RuntimeError):
                vector_store._embed("x", "http://localhost:11434")


# ══════════════════════════════════════════════════════════════════════════════
# From test_confidence_threshold.py
# ══════════════════════════════════════════════════════════════════════════════

def _out_conf(conf):
    return CaptureOutput(
        category="Tech_Notes", suggested_filename="topic-x",
        markdown_content="Some unique content " + str(conf),
        key_signals=["x"], confidence=conf, requires_new_category=False,
    )


def _cfg(threshold):
    return types.SimpleNamespace(capture=types.SimpleNamespace(
        confidence_threshold=threshold, filename_max_words=2,
        filename_max_chars=40, note_max_chars=0,
    ))


def test_high_threshold_routes_mid_confidence_to_scratchpad():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        with mock.patch("config.get_config", return_value=_cfg(0.8)):
            p = se.write_to_vault(_out_conf(0.7), vault_root=vault, scratchpad_folder="_scratchpad")
        assert "_scratchpad" in str(p)   # 0.7 < 0.8 -> inbox


def test_low_threshold_files_same_capture():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        with mock.patch("config.get_config", return_value=_cfg(0.5)):
            p = se.write_to_vault(_out_conf(0.7), vault_root=vault, scratchpad_folder="_scratchpad")
        assert "_scratchpad" not in str(p)  # 0.7 >= 0.5 -> filed
        assert "Tech_Notes" in str(p)


# ══════════════════════════════════════════════════════════════════════════════
# From test_ocr_storage.py
# ══════════════════════════════════════════════════════════════════════════════

def test_ocr_fastpath_note_has_extracted_text_and_source_type():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        out = CaptureOutput(
            category="Tech_Notes", suggested_filename="api-handler",
            markdown_content="Notes on a request handler from a screenshot.",
            key_signals=["python", "handler"], confidence=0.9,
            requires_new_category=False,
        )
        p = write_to_vault(
            out, vault_root=vault, scratchpad_folder="_scratchpad",
            source_metadata={
                "source_type": "image_ocr",
                "transcribed_text": "def handler(req): return 200",
                "image_embed": "![[img-x.png]]",
            },
        )
        text = p.read_text(encoding="utf-8")
        assert "source_type: image_ocr" in text          # frontmatter
        assert "## Extracted Text" in text                # OCR label
        assert "## Transcribed Text" not in text
        assert "def handler(req): return 200" in text
        assert "![[img-x.png]]" in text                   # image preserved


def test_vision_ocr_note_still_uses_transcribed_text():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        out = CaptureOutput(
            category="Tech_Notes", suggested_filename="cat-photo",
            markdown_content="A description.", key_signals=["cat"], confidence=0.9,
        )
        p = write_to_vault(
            out, vault_root=vault, scratchpad_folder="_scratchpad",
            source_metadata={"transcribed_text": "incidental ocr", "vision_model": "llava"},
        )
        text = p.read_text(encoding="utf-8")
        assert "## Transcribed Text" in text   # unchanged vision+OCR label
        assert "source_type:" not in text       # no source_type for vision path


# ══════════════════════════════════════════════════════════════════════════════
# From test_voice_unique.py
# ══════════════════════════════════════════════════════════════════════════════

def _out_voice(text):
    return CaptureOutput(
        category="Notes",
        suggested_filename="voice-note",
        markdown_content=text,
        confidence=0.95,
    )


def test_voice_capture_always_new_timestamped_file(tmp_path):
    (tmp_path / "Notes").mkdir(parents=True)
    meta = {"audio_path": "a.webm", "whisper_model": "base"}
    p1 = write_to_vault(_out_voice("first recording"), vault_root=tmp_path, source_metadata=meta)
    p2 = write_to_vault(_out_voice("second recording"), vault_root=tmp_path, source_metadata=meta)
    assert p1 != p2
    assert "first recording" in p1.read_text(encoding="utf-8")
    assert "second recording" in p2.read_text(encoding="utf-8")
