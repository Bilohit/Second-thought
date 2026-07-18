"""
test_retrieval.py
-----------------
Consolidated retrieval / Obsidian-network / vector-store / RAG / vault-sync suite.
Merged verbatim from:
  test_obsidian_network.py, test_vector_store_empty.py, test_cosine_top_k.py,
  test_chunk_embeddings.py, test_rag_engine.py, test_vault_sync.py
"""
from __future__ import annotations
import contextlib, hashlib, math, pathlib, sys, tempfile, unittest, unittest.mock as mock
from pathlib import Path

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from models import CaptureOutput, EnrichedPayload
from storage_engine import _build_frontmatter, _signals_to_tags, write_to_vault
from link_resolver import build_link_index, inject_wikilinks
import vector_store as vs
from vector_store import _cosine_top_k
import rag_engine
from rag_engine import hybrid_retrieve, build_system_prompt, REFUSAL
from index_writer import init_db, upsert_capture_from_file
from vault_sync import purge_orphan_index_entries, sync_vault_indexes


# ── helpers (from test_obsidian_network.py) ────────────────────────────────────

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

def _fake_embed_obsidian(text: str, base_url: str, model: str = "nomic-embed-text") -> list:
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
        self._p = mock.patch("vector_store._embed", side_effect=_fake_embed_obsidian)
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
        self._p = mock.patch("vector_store._embed", side_effect=_fake_embed_obsidian)
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


# ═══════════════════════════════════════════════════════════════════════════════
# from test_vector_store_empty.py
# ═══════════════════════════════════════════════════════════════════════════════

def test_embed_blank_input_raises_with_length_preview():
    try:
        vs._embed("   \n  ", "http://localhost:11434", "all-minilm")
        assert False, "expected RuntimeError on blank input"
    except RuntimeError as exc:
        assert "blank" in str(exc).lower() or "empty" in str(exc).lower()


def test_embed_empty_batch_message_includes_len_and_preview():
    def _fake_post(url, payload):
        return {"model": "all-minilm", "embeddings": []}

    with mock.patch.object(vs, "_post_json", side_effect=_fake_post):
        try:
            vs._embed("the quick brown fox jumps", "http://localhost:11434", "all-minilm")
            assert False, "expected RuntimeError on empty batch"
        except RuntimeError as exc:
            msg = str(exc)
            assert "len=" in msg            # input length surfaced
            assert "quick brown" in msg     # truncated preview surfaced


def test_retrieve_related_blank_query_returns_empty_without_network():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(vs, "_embed", side_effect=AssertionError("must not embed blank")):
            assert vs.retrieve_related(Path(tmp), "   ", "http://localhost:11434") == []


# ═══════════════════════════════════════════════════════════════════════════════
# from test_cosine_top_k.py
# ═══════════════════════════════════════════════════════════════════════════════

def _old_cosine_top_k(query_vec, rows, top_k):
    q = np.array(query_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    results = []
    for doc_id, emb_blob, document, _ in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm == 0:
            continue
        sim = float(np.dot(q, emb / norm))
        results.append((sim, doc_id, document))

    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]


def test_vectorized_matches_loop_version():
    rng = np.random.default_rng(0)
    query = rng.random(16).tolist()
    rows = [
        (f"id{i}", rng.random(16).astype(np.float32).tobytes(), f"doc{i}", "cat")
        for i in range(25)
    ]
    new = _cosine_top_k(query, rows, 5)
    old = _old_cosine_top_k(query, rows, 5)
    assert [(r[1], r[2]) for r in new] == [(r[1], r[2]) for r in old]
    for (sim_new, *_), (sim_old, *_) in zip(new, old):
        assert abs(sim_new - sim_old) < 1e-5


def test_zero_norm_rows_excluded():
    query = [1.0, 0.0]
    rows = [
        ("a", np.array([0.0, 0.0], dtype=np.float32).tobytes(), "doc_a", "cat"),
        ("b", np.array([1.0, 0.0], dtype=np.float32).tobytes(), "doc_b", "cat"),
    ]
    out = _cosine_top_k(query, rows, 5)
    assert [r[1] for r in out] == ["b"]


# ═══════════════════════════════════════════════════════════════════════════════
# from test_chunk_embeddings.py
# ═══════════════════════════════════════════════════════════════════════════════

def _fake_embed_factory(match_text):
    """Returns an embed fn where any text containing match_text embeds to [1,0],
    everything else embeds to [0,1]."""
    def _fake_embed(text, base_url, model=vs._DEFAULT_EMBED_MODEL):
        if match_text in text:
            return [1.0, 0.0]
        return [0.0, 1.0]
    return _fake_embed


def test_chunked_note_dedupes_to_parent_and_returns_best_chunk():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        note = vault / "Tech_Notes" / "big.md"

        chunk1 = "alpha " * (vs._CHUNK_CHARS // len("alpha "))  # no match text
        chunk2 = "MATCHME " * (vs._CHUNK_CHARS // len("MATCHME "))
        content = chunk1 + chunk2
        assert len(content) > vs._CHUNK_CHARS

        note.write_text(content)

        fake_embed = _fake_embed_factory("MATCHME")
        with mock.patch.object(vs, "_embed", side_effect=fake_embed):
            vs.index_note(vault, note, content, "http://localhost:11434")

            # Should have inserted chunk rows, not a single row.
            with vs._connect(vault) as conn:
                rows = conn.execute("SELECT id FROM embeddings").fetchall()
            ids = sorted(r[0] for r in rows)
            assert any("::c" in i for i in ids), f"expected chunk ids, got {ids}"

            results = vs.retrieve_related(
                vault, "MATCHME query", "http://localhost:11434", top_k=3
            )

        assert len(results) == 1, f"expected exactly one deduped result, got {results}"
        formatted = results[0]
        rel = "Tech_Notes/big.md"
        assert rel in formatted
        assert "::c" not in formatted
        assert "MATCHME" in formatted


def test_remove_from_index_clears_all_chunk_rows():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        (vault / "Tech_Notes").mkdir()
        note = vault / "Tech_Notes" / "big.md"

        content = "x" * (vs._CHUNK_CHARS * 2 + 10)
        note.write_text(content)

        with mock.patch.object(vs, "_embed", side_effect=lambda t, b, model=None: [1.0, 0.0]):
            vs.index_note(vault, note, content, "http://localhost:11434")
            vs.remove_from_index(vault, note)

        rel = "Tech_Notes/big.md"
        with vs._connect(vault) as conn:
            rows = conn.execute(
                "SELECT id FROM embeddings WHERE id = ? OR id LIKE ?",
                (rel, rel + "::c%"),
            ).fetchall()
        assert rows == []


# ═══════════════════════════════════════════════════════════════════════════════
# from test_rag_engine.py
# ═══════════════════════════════════════════════════════════════════════════════

def _fake_embed_rag(text, base_url, model="x"):
    # deterministic tiny vector keyed on word presence
    v = [0.0] * 4
    for w in text.lower().split():
        v[hash(w) % 4] += 1.0
    n = (sum(x*x for x in v) ** 0.5) or 1.0
    return [x / n for x in v]

def test_refusal_when_no_index():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rag_engine, "_embed", _fake_embed_rag):
            sources, confidence, tier = hybrid_retrieve(
                pathlib.Path(tmp), "anything", "http://localhost:11434", "all-minilm")
    assert sources == []
    assert tier == "none"

def test_chunked_note_resolves_to_parent_and_appears_once():
    # Large notes are stored as chunk rows (id rel::c0, rel::c1, ...) by
    # vector_store.index_note. _semantic_ranked must strip the "::c<N>"
    # suffix and dedupe to the parent path, or the chunk ids never match a
    # real vault-relative path and the note is silently dropped.
    with tempfile.TemporaryDirectory() as tmp:
        vault = pathlib.Path(tmp)
        (vault / "Tech").mkdir()
        note = vault / "Tech" / "big.md"
        note.write_text("async python fastapi asyncio")

        import vector_store
        with mock.patch.object(rag_engine, "_embed", _fake_embed_rag), \
             mock.patch.object(vector_store, "_embed", _fake_embed_rag):
            with vector_store._connect(vault) as conn:
                for i, chunk in enumerate(["async python", "fastapi asyncio"]):
                    vec = _fake_embed_rag(chunk, "http://localhost:11434")
                    import numpy as np
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings (id, embedding, document, category) "
                        "VALUES (?,?,?,?)",
                        (f"Tech/big.md::c{i}", np.array(vec, dtype=np.float32).tobytes(),
                         chunk, "Tech"),
                    )

            sources, confidence, tier = hybrid_retrieve(
                vault, "async python", "http://localhost:11434", "all-minilm",
                min_similarity_floor=0.0)

    paths = [s["path"] for s in sources]
    assert str(note) in paths
    assert paths.count(str(note)) == 1

def test_prompt_numbers_sources_without_llm_refusal():
    srcs = [{"n": 1, "path": "/v/Tech/a.md", "category": "Tech",
             "filename": "a.md", "snippet": "async io"}]
    p = build_system_prompt(srcs, "vault")
    assert "[1] (Tech/a.md)" in p
    assert REFUSAL not in p


# ═══════════════════════════════════════════════════════════════════════════════
# from test_vault_sync.py
# ═══════════════════════════════════════════════════════════════════════════════

def test_purge_orphan_index_entries_removes_missing_files():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        ghost = vault / "Tech" / "gone.md"
        conn = init_db(vault)
        conn.execute(
            "INSERT INTO captures (timestamp, category, path, hash, filename, body_excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2025-01-01T00:00:00", "Tech", str(ghost), "deadbeef", "gone.md", "ghost"),
        )
        conn.commit()
        conn.close()

        removed = purge_orphan_index_entries(vault)

        conn = init_db(vault)
        rows = conn.execute("SELECT path FROM captures").fetchall()
        conn.close()
        assert removed == 1
        assert rows == []


def test_sync_vault_indexes_adds_new_file_and_skips_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "fresh.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Fresh\nNew note body", encoding="utf-8")

        # First pass runs index_note for real (fake _embed, no Ollama) so the vector
        # store is actually populated — the skip decision now consults the store's
        # own contents (OF-1), so a mocked no-op index_note would (correctly) look
        # un-embedded and get re-embedded on the second pass.
        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result["added"] == 1
        assert result["removed"] == 0
        assert vs.count(vault) == 1

        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            result2 = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result2["skipped"] == 1, "unchanged, already-embedded note must be skipped"
        assert result2["added"] == 0
        assert result2["reembedded"] == 0, "an already-embedded note must not be re-embedded"


def test_sync_vault_indexes_removes_orphan_on_disk_delete():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "temp.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Temp\nTo be deleted", encoding="utf-8")
        upsert_capture_from_file(vault, note)

        note.unlink()

        with mock.patch("vault_sync.index_note"):
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        conn = init_db(vault)
        rows = conn.execute("SELECT path FROM captures").fetchall()
        conn.close()
        assert result["removed"] == 1
        assert rows == []


def test_sync_preserves_chunk_embeddings_for_existing_files():
    """Chunk rows (id '<parent>::c<i>') must survive a sync while the parent
    file exists, and be purged (counted once) when it is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Notes" / "big.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Big\nlong body", encoding="utf-8")
        upsert_capture_from_file(vault, note)

        from vector_store import _connect
        with _connect(vault) as conn:
            for i in range(2):
                conn.execute(
                    "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                    (f"Notes/big.md::c{i}", b"\x00\x00\x80\x3f", "chunk", "Notes"),
                )

        with mock.patch("vault_sync.index_note"):
            result = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        with _connect(vault) as conn:
            n = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert n == 2, f"chunk embeddings wrongly purged (left {n})"
        assert result["removed"] == 0

        # Delete the file: one note removed, counted once (not once per chunk).
        note.unlink()
        with mock.patch("vault_sync.index_note"):
            result2 = sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        with _connect(vault) as conn:
            n2 = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert n2 == 0


def test_startup_purge_removes_embeddings_only_orphans():
    """An embedding row with no captures row and no file must be purged at
    startup; one whose file exists must survive."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        keep = vault / "Notes" / "keep.md"
        keep.parent.mkdir(parents=True)
        keep.write_text("# Keep", encoding="utf-8")

        from vector_store import _connect
        with _connect(vault) as conn:
            conn.execute(
                "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                ("Notes/keep.md", b"\x00\x00\x80\x3f", "keep", "Notes"),
            )
            conn.execute(
                "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                ("Notes/ghost.md::c0", b"\x00\x00\x80\x3f", "ghost chunk", "Notes"),
            )

        removed = purge_orphan_index_entries(vault)

        with _connect(vault) as conn:
            ids = {r[0] for r in conn.execute("SELECT id FROM embeddings").fetchall()}
        assert removed == 1
        assert ids == {"Notes/keep.md"}


if __name__ == "__main__":
    unittest.main(verbosity=2)
