import sys, tempfile, pathlib
from unittest import mock
import rag_engine
from rag_engine import hybrid_retrieve, build_system_prompt, REFUSAL

def _fake_embed(text, base_url, model="x"):
    # deterministic tiny vector keyed on word presence
    v = [0.0] * 4
    for w in text.lower().split():
        v[hash(w) % 4] += 1.0
    n = (sum(x*x for x in v) ** 0.5) or 1.0
    return [x / n for x in v]

def test_refusal_when_no_index():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(rag_engine, "_embed", _fake_embed):
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
        with mock.patch.object(rag_engine, "_embed", _fake_embed), \
             mock.patch.object(vector_store, "_embed", _fake_embed):
            with vector_store._connect(vault) as conn:
                for i, chunk in enumerate(["async python", "fastapi asyncio"]):
                    vec = _fake_embed(chunk, "http://localhost:11434")
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
