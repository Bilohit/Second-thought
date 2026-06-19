"""
test_routing_and_merge.py
-------------------------
Tests for the file-routing bug fix and the smart context-aware merging feature.

Covers:
  * The file-routing bug fix (a shared source URL no longer collapses two
    distinct captures into one file).
  * The category-aware dedup guard (a content-hash hit in a different category
    than the freshly-decided one must not short-circuit to the stale note).
  * The stale dedup-index entry guard (a hash pointing at a missing note must
    not silently drop a fresh capture).
  * Smart context-aware merging (confident same-topic merge vs distinct-topic
    split, single-shared-tag and no-tag cases).
  * The Ollama embedding endpoint fallback (/api/embed 404 -> /api/embeddings).

Run:  pytest omni_capture/test_routing_and_merge.py -q
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
from storage_engine import (
    write_to_vault,
    check_duplicate,
    register_in_dedup_index,
    find_merge_target,
    _content_hash,
)
import vector_store


def _make(category="Tech_Notes", filename="note", content="content",
          signals=None, confidence=0.9):
    return CaptureOutput(
        category=category,
        suggested_filename=filename,
        markdown_content=content,
        key_signals=signals or [],
        confidence=confidence,
        requires_new_category=False,
    )


@pytest.fixture()
def vault(tmp_path):
    return tmp_path


# -- Bug fix: a URL must not collapse distinct content -----------------------

class TestRoutingBugFix:
    def test_same_url_different_content_not_deduped(self, vault):
        """The reported bug: two unrelated captures sharing a source URL were
        treated as duplicates.  They must now land in separate files."""
        url = "https://example.com/wiki/article"
        t1 = _make(filename="mri-scans", content="MRI scans use magnetic fields.",
                   signals=["mri", "imaging"])
        t2 = _make(filename="mouse-dongle", content="ATK mouse dongle sharing limitation.",
                   signals=["mouse", "usb"])
        p1 = write_to_vault(t1, source_url=url, vault_root=vault)
        p2 = write_to_vault(t2, source_url=url, vault_root=vault)
        assert p1 != p2, "Distinct content on same URL must not be deduped"
        assert p1.exists() and p2.exists()

    def test_same_url_same_content_is_deduped(self, vault):
        url = "https://example.com/page"
        t = _make(content="identical body", signals=["x"])
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
        old = _make(category="Tech_Notes", filename="tech-notes",
                    content=body, signals=["history"])
        p_old = write_to_vault(old, vault_root=vault)
        assert "Tech_Notes" in str(p_old)

        new = _make(category="CRM", filename="historical-matter",
                    content=body, signals=["history"], confidence=0.95)
        p_new = write_to_vault(new, vault_root=vault)

        assert "CRM" in str(p_new), f"Expected CRM landing, got {p_new}"
        assert "Tech_Notes" not in str(p_new)
        assert p_new.exists()

    def test_dedup_skips_exact_duplicate_in_same_category(self, vault):
        """Genuine re-capture into the same decided category still dedups."""
        t = _make(category="Tech_Notes", filename="asyncio", content="same body",
                  signals=["python"], confidence=0.95)
        p1 = write_to_vault(t, vault_root=vault)
        p2 = write_to_vault(t, vault_root=vault)
        assert p1 == p2

    def test_stale_index_entry_does_not_drop_capture(self, vault):
        """If the dedup index points to a note that no longer exists, a new
        capture with that hash must still be written, not silently skipped."""
        t = _make(content="orphaned hash content", signals=["y"])
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
        day1 = _make(filename="logitech-g502-review",
                     content="The G502 has great sensors.",
                     signals=["gaming-mice", "logitech", "hardware"])
        day2 = _make(filename="razer-deathadder-notes",
                     content="The DeathAdder is comfortable.",
                     signals=["gaming-mice", "razer", "hardware"])
        p1 = write_to_vault(day1, vault_root=vault)
        p2 = write_to_vault(day2, vault_root=vault)
        assert p1 == p2, "Same-topic captures should merge into one file"
        body = p1.read_text()
        assert "G502" in body and "DeathAdder" in body

    def test_distinct_topics_stay_separate(self, vault):
        """No shared tags -> never merge, even in the same category."""
        a = _make(filename="python-asyncio", content="asyncio event loop.",
                  signals=["python", "asyncio", "concurrency"])
        b = _make(filename="docker-networking", content="docker bridge networks.",
                  signals=["docker", "networking", "containers"])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2

    def test_single_shared_tag_does_not_merge_without_semantics(self, vault):
        """A single shared tag is not enough confidence on its own."""
        a = _make(filename="note-a", content="content a", signals=["hardware", "keyboards"])
        b = _make(filename="note-b", content="content b", signals=["hardware", "monitors"])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2, "One shared tag should not trigger a merge"

    def test_no_tags_never_merges(self, vault):
        a = _make(filename="note-a", content="alpha", signals=[])
        b = _make(filename="note-b", content="beta", signals=[])
        p1 = write_to_vault(a, vault_root=vault)
        p2 = write_to_vault(b, vault_root=vault)
        assert p1 != p2

    def test_find_merge_target_returns_none_when_no_candidates(self, vault):
        out = _make(signals=["gaming-mice", "hardware"])
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
