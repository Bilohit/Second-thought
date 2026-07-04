import sys
from pathlib import Path
import unittest.mock as mock
import tempfile

sys.path.insert(0, str(Path(__file__).parent))
import vector_store as vs


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
