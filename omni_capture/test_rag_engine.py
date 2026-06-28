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
            sources, answerable = hybrid_retrieve(
                pathlib.Path(tmp), "anything", "http://localhost:11434", "all-minilm")
    assert sources == []
    assert answerable is False

def test_prompt_numbers_sources_and_embeds_refusal_rule():
    srcs = [{"n": 1, "path": "/v/Tech/a.md", "category": "Tech",
             "filename": "a.md", "snippet": "async io"}]
    p = build_system_prompt(srcs)
    assert "[1] (Tech/a.md)" in p
    assert REFUSAL in p
