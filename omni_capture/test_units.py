"""
test_units.py
-------------
Consolidated unit tests merged from:
  test_temporal.py, test_tag_vocab.py, test_timing.py,
  test_scrutiny.py, test_new_config.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import io
import json
import time
import tempfile
from datetime import datetime

from models import DetectedEvent, filter_future_events
from tag_vocab import _norm, normalize_tags
from timing import StageTimer
from llm_engine import _build_system_prompt
from config import reload_config


# --- from test_temporal.py -------------------------------------------------

NOW = datetime(2026, 7, 3, 12, 0)


def test_keeps_valid_future_drops_past_and_garbage():
    events = [
        DetectedEvent(when_iso="2026-07-05T15:00", label="dentist"),
        DetectedEvent(when_iso="2020-01-01T00:00", label="past"),
        DetectedEvent(when_iso="not-a-date", label="garbage"),
    ]
    assert [e.label for e in filter_future_events(events, NOW)] == ["dentist"]


def test_empty_is_fine():
    assert filter_future_events([], NOW) == []


def test_dynamic_model_inherits_detected_events():
    from models import build_capture_model
    model = build_capture_model(["Tech_Notes"])
    assert "detected_events" in model.model_fields


def test_aware_when_iso_never_raises_and_compares_in_local_time():
    """'Z'/offset-suffixed when_iso (aware) vs the callers' naive now must not
    raise TypeError; future aware events survive, past aware events drop."""
    events = [
        DetectedEvent(when_iso="2099-01-01T00:00:00+00:00", label="aware future"),
        DetectedEvent(when_iso="2020-01-01T00:00:00Z", label="aware past"),
        DetectedEvent(when_iso="2026-07-05T15:00", label="naive future"),
    ]
    labels = [e.label for e in filter_future_events(events, NOW)]
    assert labels == ["aware future", "naive future"]


def test_filter_strips_spurious_utc_suffix_without_shifting():
    from datetime import datetime
    from models import DetectedEvent, filter_future_events
    now = datetime(2026, 7, 4, 12, 0)
    ev = DetectedEvent(when_iso="2026-07-05T19:30:00Z", label="call")
    kept = filter_future_events([ev], now)
    assert len(kept) == 1
    assert kept[0].when_iso == "2026-07-05T19:30"  # 7:30 PM stays 7:30 PM


# --- from test_tag_vocab.py ------------------------------------------------

def test_norm_collapses_case_space_plural():
    assert _norm("LLM Agents") == "llm-agent"
    assert _norm("llm_agents") == "llm-agent"


def test_normalize_maps_to_existing_canonical():
    vocab = {"llm-agent": "llm-agents"}   # vault already uses "llm-agents"
    assert normalize_tags(["LLM Agent", "llm-agents"], vocab) == ["llm-agents"]


def test_unknown_passes_through_deduped_and_capped():
    assert normalize_tags([f"t{i}" for i in range(15)], {}) == [f"t{i}" for i in range(10)]
    assert normalize_tags(["a", "A"], {}) == ["a"]


# --- from test_timing.py ---------------------------------------------------

def test_stage_records_elapsed_and_total():
    t = StageTimer(run_id="abc123")
    with t.stage("enrich"):
        time.sleep(0.02)
    with t.stage("llm"):
        time.sleep(0.01)
    data = json.loads(t.summary_json())
    assert data["run_id"] == "abc123"
    assert set(data["stages"]) == {"enrich", "llm"}
    assert data["stages"]["enrich"] >= 15      # ~20ms, allow slack
    assert data["total_ms"] >= data["stages"]["enrich"] + data["stages"]["llm"] - 1


def test_same_stage_name_accumulates():
    t = StageTimer()
    with t.stage("llm"):
        time.sleep(0.01)
    with t.stage("llm"):
        time.sleep(0.01)
    data = json.loads(t.summary_json())
    assert data["stages"]["llm"] >= 18  # two ~10ms passes accumulated


def test_log_summary_emits_single_parseable_line():
    t = StageTimer(run_id="r1")
    with t.stage("write"):
        pass
    buf = io.StringIO()
    t.log_summary(stream=buf)
    line = buf.getvalue().strip()
    assert line.startswith("[timing] ")
    payload = json.loads(line[len("[timing] "):])
    assert payload["run_id"] == "r1"
    assert "write" in payload["stages"]


def test_exception_in_stage_still_records():
    t = StageTimer()
    try:
        with t.stage("boom"):
            raise ValueError("x")
    except ValueError:
        pass
    data = json.loads(t.summary_json())
    assert "boom" in data["stages"]


# --- from test_scrutiny.py -------------------------------------------------

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


# --- from test_new_config.py -----------------------------------------------

def test_capture_defaults_match_legacy_behavior():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        cfg = reload_config(cfg_path)
        assert cfg.capture.confidence_threshold == 0.6
        assert cfg.capture.llm_scrutiny == "balanced"
        assert cfg.capture.ocr_fast_path_enabled is True
        assert cfg.capture.ocr_text_min_chars == 10


def test_capture_overrides_from_toml():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text(
            "[capture]\n"
            "confidence_threshold = 0.8\n"
            'llm_scrutiny = "strict"\n'
            "ocr_fast_path_enabled = false\n"
            "ocr_text_min_chars = 120\n",
            encoding="utf-8",
        )
        cfg = reload_config(cfg_path)
        assert cfg.capture.confidence_threshold == 0.8
        assert cfg.capture.llm_scrutiny == "strict"
        assert cfg.capture.ocr_fast_path_enabled is False
        assert cfg.capture.ocr_text_min_chars == 120


def test_invalid_scrutiny_falls_back_to_balanced():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text('[capture]\nllm_scrutiny = "aggressive"\n', encoding="utf-8")
        cfg = reload_config(cfg_path)
        assert cfg.capture.llm_scrutiny == "balanced"
