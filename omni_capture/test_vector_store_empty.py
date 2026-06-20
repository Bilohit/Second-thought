import sys
from pathlib import Path
import unittest.mock as mock
import tempfile

# Allow importing from the current directory
sys.path.insert(0, str(Path(__file__).parent))
import vector_store as vs


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
