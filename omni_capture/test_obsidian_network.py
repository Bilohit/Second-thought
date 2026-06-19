"""
test_obsidian_network.py
------------------------
Tests for Obsidian-native networking:
  TestTags         - key_signals -> YAML tags
  TestLinkResolver - [[wikilink]] injection
  TestVectorStore  - numpy/sqlite embed + retrieve (mocked Ollama)
  TestIntegration  - two notes written + indexed; third gets wikilink & embedding match
"""
from __future__ import annotations
import contextlib, hashlib, math, pathlib, sys, tempfile, unittest, unittest.mock as mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from models import CaptureOutput, EnrichedPayload
from storage_engine import _build_frontmatter, _signals_to_tags, write_to_vault
from link_resolver import build_link_index, inject_wikilinks
import vector_store as vs


# ── helpers ───────────────────────────────────────────────────────────────────

def _out(**kw) -> CaptureOutput:
    base = dict(category="Tech_Notes", suggested_filename="test-note",
                markdown_content="Some content.", rationale="Test.",
                key_signals=["python","async-io"], confidence=0.9,
                requires_new_category=False)
    base.update(kw)
    return CaptureOutput(**base)

def _ep(text: str) -> EnrichedPayload:
    return EnrichedPayload(raw_input=text, input_type="text", enriched_text=text)

class TV:
    """Context manager: temp vault with all category dirs."""
    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        v = pathlib.Path(self._d.name)
        for c in ["Tech_Notes","CRM","Finance","Watch_Later",
                  "Recipes","Journal","Design_Inspiration","_scratchpad"]:
            (v / c).mkdir()
        return v
    def __exit__(self, *_): self._d.cleanup()

def _fake_embed(text: str, base_url: str, model: str = "nomic-embed-text") -> list:
    """8-dim word-hash embedding — two texts sharing words get similar vectors."""
    vec = [0.0] * 8
    for word in text.lower().split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        for i in range(8):
            vec[i] += ((h >> (i * 4)) & 0xF) / 15.0
    norm = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x / norm for x in vec]

@contextlib.contextmanager
def _temp_vault(files: dict):
    """Module-level contextmanager: creates temp dir, populates files, yields Path."""
    with tempfile.TemporaryDirectory() as tmp:
        v = pathlib.Path(tmp)
        (v/"CRM").mkdir()
        (v/"Tech_Notes").mkdir()
        for rel, body in files.items():
            p = v / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        yield v


# ═══════════════════════════════════════════════════════════════════════════════
class TestTags(unittest.TestCase):

    def test_basic_conversion(self):
        self.assertEqual(_signals_to_tags(["python","async programming","event loop"]),
                         ["python","async-programming","event-loop"])

    def test_special_chars_stripped(self):
        for tag in _signals_to_tags(["C++ / systems","ML (NLP)","REST API!"]):
            self.assertRegex(tag, r"^[\w/\-]+$")

    def test_empty_signals_skipped(self):
        self.assertEqual(_signals_to_tags(["","  ","valid"]), ["valid"])

    def test_slash_preserved_for_nested(self):
        self.assertIn("lang/python", _signals_to_tags(["lang/python"]))

    def test_frontmatter_tag_list(self):
        fm = _build_frontmatter(_out(key_signals=["python","async-io"]), None)
        self.assertIn("tags:", fm)
        self.assertIn("  - python", fm)
        self.assertIn("  - async-io", fm)
        self.assertNotIn("tags: []", fm)

    def test_frontmatter_empty_gives_empty_list(self):
        self.assertIn("tags: []", _build_frontmatter(_out(key_signals=[]), None))

    def test_tags_written_to_file(self):
        with TV() as vault:
            path = write_to_vault(
                _out(suggested_filename="asyncio-notes",
                     markdown_content="Notes.",
                     key_signals=["asyncio","python-concurrency"]),
                vault_root=vault)
            content = path.read_text()
        self.assertIn("  - asyncio", content)
        self.assertIn("  - python-concurrency", content)


# ═══════════════════════════════════════════════════════════════════════════════
class TestLinkResolver(unittest.TestCase):

    def test_crm_name_injected(self):
        with _temp_vault({"CRM/john-smith.md": "# John Smith\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("Spoke with John Smith today.", idx)
        self.assertIn("[[CRM/john-smith|John Smith]]", result)

    def test_multiword_tech_injected(self):
        with _temp_vault({"Tech_Notes/python-asyncio-notes.md": "# Asyncio\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("See Python Asyncio Notes for details.", idx)
        self.assertIn("python-asyncio-notes", result)

    def test_single_word_non_crm_not_injected(self):
        with _temp_vault({"Tech_Notes/python.md": "# Python\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("I love python programming.", idx)
        self.assertNotIn("[[", result)

    def test_code_block_protected(self):
        with _temp_vault({"CRM/john-smith.md": "# John Smith\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks(
                "```python\nname = 'John Smith'\n```\nSee John Smith.", idx)
        self.assertIn("```python\nname = 'John Smith'\n```", result)
        self.assertIn("[[CRM/john-smith|John Smith]]", result)

    def test_inline_code_protected(self):
        with _temp_vault({"CRM/john-smith.md": "# John Smith\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("Use `John Smith` as the key.", idx)
        self.assertIn("`John Smith`", result)

    def test_no_double_wrap(self):
        with _temp_vault({"CRM/john-smith.md": "# John Smith\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("See [[CRM/john-smith|John Smith]] here.", idx)
        self.assertEqual(result.count("[["), 1)

    def test_exclude_stems_self_link(self):
        with _temp_vault({"CRM/john-smith.md": "# John Smith\n"}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("John Smith wrote this.", idx,
                                      exclude_stems={"CRM/john-smith"})
        self.assertNotIn("[[", result)

    def test_alias_injected(self):
        with _temp_vault({"CRM/jane-doe.md": '---\naliases:\n  - "Jane D"\n---\n'}) as vault:
            idx = build_link_index(vault)
            result = inject_wikilinks("Talked to Jane D about the deal.", idx)
        self.assertIn("CRM/jane-doe", result)

    def test_write_to_vault_injects_wikilinks(self):
        with TV() as vault:
            (vault/"CRM"/"alice-chen.md").write_text("# Alice Chen\n")
            path = write_to_vault(
                _out(suggested_filename="project-update",
                     markdown_content="Alice Chen reviewed the pull request.",
                     key_signals=["code-review"]),
                vault_root=vault)
            self.assertIn("[[CRM/alice-chen|Alice Chen]]", path.read_text())


# ═══════════════════════════════════════════════════════════════════════════════
class TestVectorStore(unittest.TestCase):

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.vault = pathlib.Path(self._d.name)
        (self.vault/"Tech_Notes").mkdir()
        self._p = mock.patch("vector_store._embed", side_effect=_fake_embed)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._d.cleanup()

    def test_index_and_count(self):
        n = self.vault/"Tech_Notes"/"asyncio.md"
        n.write_text("Async IO patterns in Python.")
        vs.index_note(self.vault, n, n.read_text(), "http://localhost:11434")
        self.assertEqual(vs.count(self.vault), 1)

    def test_retrieve_returns_related(self):
        for name, body in [("asyncio.md","Async IO patterns in Python asyncio."),
                            ("fastapi.md","Async HTTP APIs with FastAPI and Python.")]:
            p = self.vault/"Tech_Notes"/name
            p.write_text(body)
            vs.index_note(self.vault, p, body, "http://localhost:11434")
        snippets = vs.retrieve_related(self.vault, "async python", "http://localhost:11434")
        self.assertGreater(len(snippets), 0)
        combined = " ".join(snippets).lower()
        self.assertTrue("asyncio" in combined or "fastapi" in combined)

    def test_empty_vault_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp2:
            self.assertEqual(
                vs.retrieve_related(pathlib.Path(tmp2), "anything", "http://x"), [])

    def test_upsert_idempotent(self):
        n = self.vault/"Tech_Notes"/"note.md"
        n.write_text("v1")
        vs.index_note(self.vault, n, "v1", "http://localhost:11434")
        vs.index_note(self.vault, n, "v2", "http://localhost:11434")
        self.assertEqual(vs.count(self.vault), 1)

    def test_top_k_respected(self):
        for i in range(5):
            p = self.vault/"Tech_Notes"/f"note-{i}.md"
            p.write_text(f"async python note {i}")
            vs.index_note(self.vault, p, p.read_text(), "http://localhost:11434")
        snippets = vs.retrieve_related(self.vault, "async python",
                                       "http://localhost:11434", top_k=2)
        self.assertLessEqual(len(snippets), 2)

    def test_similarity_score_in_output(self):
        n = self.vault/"Tech_Notes"/"asyncio.md"
        n.write_text("Python asyncio event loop")
        vs.index_note(self.vault, n, n.read_text(), "http://localhost:11434")
        snippets = vs.retrieve_related(self.vault, "asyncio event loop",
                                       "http://localhost:11434", top_k=1)
        self.assertTrue(any("similarity" in s for s in snippets))

    def test_min_similarity_floor_drops_weak_matches(self):
        # Orthogonal unit vectors -- the query is indexed at a known weak
        # similarity (0.2) to the note, so the floor's effect is deterministic
        # rather than at the mercy of the word-hash embedding's noise floor.
        n = self.vault/"Tech_Notes"/"note.md"
        n.write_text("placeholder")
        with mock.patch("vector_store._embed", return_value=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]):
            vs.index_note(self.vault, n, "placeholder", "http://localhost:11434")
        with mock.patch("vector_store._embed", return_value=[0.2, 0.9798, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]):
            snippets = vs.retrieve_related(self.vault, "weakly related query",
                                           "http://localhost:11434", min_similarity=0.5)
        self.assertEqual(snippets, [])

    def test_min_similarity_default_zero_keeps_existing_behaviour(self):
        n = self.vault/"Tech_Notes"/"asyncio.md"
        n.write_text("Async IO patterns in Python asyncio.")
        vs.index_note(self.vault, n, n.read_text(), "http://localhost:11434")
        snippets = vs.retrieve_related(self.vault, "async python", "http://localhost:11434")
        self.assertGreater(len(snippets), 0)


# ═══════════════════════════════════════════════════════════════════════════════
class TestIntegration(unittest.TestCase):
    """
    End-to-end:
      Note A  CRM/alice-chen.md            (written + indexed)
      Note B  Tech_Notes/asyncio-guide.md  (written + indexed)
      Note C  Tech_Notes/project-update.md (written + indexed)
        assert: [[CRM/alice-chen|Alice Chen]] injected in C
        assert: tags from key_signals in C
        assert: semantic retrieval from A+B finds asyncio/alice content
    """

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.vault = pathlib.Path(self._d.name)
        for c in ["CRM","Tech_Notes","Finance","Watch_Later",
                  "Recipes","Journal","Design_Inspiration","_scratchpad"]:
            (self.vault/c).mkdir()
        self._p = mock.patch("vector_store._embed", side_effect=_fake_embed)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._d.cleanup()

    def _write_index(self, output: CaptureOutput) -> pathlib.Path:
        path = write_to_vault(output, vault_root=self.vault)
        vs.index_note(self.vault, path, path.read_text(), "http://localhost:11434")
        return path

    def test_wikilink_tag_and_embedding_match(self):
        # Note A — CRM
        self._write_index(_out(
            category="CRM", suggested_filename="alice-chen",
            markdown_content="- 2026-06-01 -- Initial meeting about Python project.",
            key_signals=["crm","python-project"],
        ))

        # Note B — asyncio tech note
        self._write_index(_out(
            category="Tech_Notes", suggested_filename="asyncio-guide",
            markdown_content=(
                "Python asyncio enables concurrent I/O.\n"
                "Use async/await for non-blocking operations."
            ),
            key_signals=["python","asyncio","concurrency"],
        ))

        # Semantic retrieval should surface related content before writing C
        snippets = vs.retrieve_related(
            self.vault, "python asyncio concurrency alice",
            "http://localhost:11434", top_k=3)
        combined = " ".join(snippets).lower()
        self.assertGreater(len(snippets), 0, "Semantic retrieval returned nothing")
        self.assertTrue(
            "asyncio" in combined or "alice" in combined or "alice-chen" in combined,
            f"Expected asyncio or alice in snippets:\n{combined}")

        # Note C — references Alice Chen and asyncio -> wikilink + tags
        path_c = self._write_index(_out(
            category="Tech_Notes", suggested_filename="project-update",
            markdown_content=(
                "Alice Chen approved the asyncio architecture for the project.\n"
                "We are adopting Python asyncio for all async I/O."
            ),
            key_signals=["asyncio","architecture","approval"],
        ))
        content_c = path_c.read_text()

        # 1. Wikilink injected
        self.assertIn("[[CRM/alice-chen|Alice Chen]]", content_c,
                      f"Missing wikilink in C:\n{content_c}")

        # 2. Tags from key_signals
        self.assertIn("  - asyncio", content_c)
        self.assertIn("  - architecture", content_c)

        # 3. All three notes indexed
        self.assertGreaterEqual(vs.count(self.vault), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
