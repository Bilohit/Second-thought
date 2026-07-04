"""
test_temporal.py
-----------------
Tests for detected_events: LLM-surfaced concrete future dates/times
(meetings, deadlines, appointments) and the filter that drops past/garbage
entries from untrusted LLM output.

Run:  pytest omni_capture/test_temporal.py -v
"""
from datetime import datetime
from models import DetectedEvent, filter_future_events

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
