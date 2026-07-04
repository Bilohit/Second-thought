"""
test_large_text.py
-------------------
Covers Task B2 (chunked Map-Reduce tagging + decide-context for large text):

  1. summarizer.digest_chunks: one structured call per chunk via
     llm_engine._make_client's instructor client; fail-soft per chunk.
  2. server._merge_large_text_tags (mirrored in main.py): pure merge of
     key_signals + all chunk tags, deduped/normalized/capped via
     tag_vocab.normalize_tags.

LLM calls are mocked at the llm_engine._make_client seam -- nothing here
hits Ollama.
"""
from __future__ import annotations

import os
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OMNI_GUI_SECRET", "")

import llm_engine
from summarizer import digest_chunks, _ChunkDigest


def _stub_client(digest: _ChunkDigest | None = None, *, raises: bool = False):
    client = mock.MagicMock()
    if raises:
        client.chat.completions.create.side_effect = RuntimeError("model unavailable")
    else:
        client.chat.completions.create.return_value = digest
    return client


def test_digest_chunks_happy_path_returns_one_result_per_chunk():
    digest = _ChunkDigest(tags=["deep-topic"], summary="s")
    with mock.patch.object(llm_engine, "_make_client", lambda: _stub_client(digest)):
        results = digest_chunks(
            ["a", "b"], base_url="http://localhost:11434", model="llama3.2",
            temperature=0.1, max_retries=1,
        )
    assert results == [(["deep-topic"], "s"), (["deep-topic"], "s")]


def test_digest_chunks_fails_soft_per_chunk():
    with mock.patch.object(llm_engine, "_make_client", lambda: _stub_client(raises=True)):
        results = digest_chunks(
            ["a", "b"], base_url="http://localhost:11434", model="llama3.2",
            temperature=0.1, max_retries=1,
        )
    assert results == [([], ""), ([], "")]


def test_merge_large_text_tags_dedupes_and_caps():
    from server import _merge_large_text_tags

    merged = _merge_large_text_tags(
        key_signals=["K1"], chunk_tags=[["deep-topic"], []], vocab={},
    )
    assert "K1" in merged
    assert "deep-topic" in merged
    assert len(merged) == len(set(merged))
    assert len(merged) <= 10


def test_merge_large_text_tags_mirrored_in_main():
    from main import _merge_large_text_tags as main_merge

    merged = main_merge(key_signals=["K1"], chunk_tags=[["deep-topic"], []], vocab={})
    assert "K1" in merged
    assert "deep-topic" in merged


if __name__ == "__main__":
    test_digest_chunks_happy_path_returns_one_result_per_chunk()
    print("[T1] digest_chunks happy path  PASS")
    test_digest_chunks_fails_soft_per_chunk()
    print("[T2] digest_chunks fails soft per chunk  PASS")
    test_merge_large_text_tags_dedupes_and_caps()
    print("[T3] _merge_large_text_tags (server) dedupes/caps  PASS")
    test_merge_large_text_tags_mirrored_in_main()
    print("[T4] _merge_large_text_tags (main, mirrored) matches  PASS")
    print("\nAll test_large_text.py smoke tests passed.")
