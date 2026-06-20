from llm_engine import _build_system_prompt


def _descs():
    return {"Tech_Notes": "Engineering notes.", "Journal": "Daily journal."}


def test_balanced_adds_no_extra_instruction():
    base = _build_system_prompt(_descs(), "2026-06-20", scrutiny="balanced")
    assert "high scrutiny" not in base.lower()
    assert "best-effort" not in base.lower()


def test_strict_injects_high_scrutiny_paragraph():
    p = _build_system_prompt(_descs(), "2026-06-20", scrutiny="strict")
    assert "high scrutiny" in p.lower()
    assert "do not guess" in p.lower()


def test_relaxed_injects_best_effort_paragraph():
    p = _build_system_prompt(_descs(), "2026-06-20", scrutiny="relaxed")
    assert "best-effort" in p.lower()


def test_unknown_scrutiny_falls_back_to_balanced():
    p = _build_system_prompt(_descs(), "2026-06-20", scrutiny="bogus")
    assert "high scrutiny" not in p.lower()
    assert "best-effort" not in p.lower()


def test_default_arg_is_balanced():
    p = _build_system_prompt(_descs(), "2026-06-20")
    assert "high scrutiny" not in p.lower()
