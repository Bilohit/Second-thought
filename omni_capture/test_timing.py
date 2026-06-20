import json
import io
import time
from timing import StageTimer


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
