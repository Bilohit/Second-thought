from tag_vocab import _norm, normalize_tags


def test_norm_collapses_case_space_plural():
    assert _norm("LLM Agents") == "llm-agent"
    assert _norm("llm_agents") == "llm-agent"


def test_normalize_maps_to_existing_canonical():
    vocab = {"llm-agent": "llm-agents"}   # vault already uses "llm-agents"
    assert normalize_tags(["LLM Agent", "llm-agents"], vocab) == ["llm-agents"]


def test_unknown_passes_through_deduped_and_capped():
    assert normalize_tags([f"t{i}" for i in range(15)], {}) == [f"t{i}" for i in range(10)]
    assert normalize_tags(["a", "A"], {}) == ["a"]
