"""Index-health degradation flag (ROADMAP: "Health-degradation flag for
silently failing index writes").

The flag is pure observability layered on the existing fail-soft index writes:
recording a failure must never raise, degraded() must reflect the last outcome,
and /health must surface the snapshot. A failing index write must still not
block the vault write (verified here via the never-raise contract on the
recorder that lives inside those swallow blocks).
"""
import index_health


def _reset():
    index_health.record_ok("captures")
    index_health.record_ok("vectors")


def test_fresh_state_not_degraded():
    _reset()
    assert index_health.degraded() is False
    snap = index_health.snapshot()
    assert snap["captures"]["ok"] is True
    assert snap["vectors"]["ok"] is True


def test_failure_reports_degraded_then_clears():
    _reset()
    index_health.record_failure("vectors", RuntimeError("disk full"))
    assert index_health.degraded() is True
    snap = index_health.snapshot()
    assert snap["vectors"]["ok"] is False
    assert snap["vectors"]["error"] == "disk full"
    assert snap["vectors"]["timestamp"] is not None
    # captures unaffected -- per-index independence
    assert snap["captures"]["ok"] is True

    index_health.record_ok("vectors")
    assert index_health.degraded() is False
    assert index_health.snapshot()["vectors"]["error"] is None


def test_recorder_never_raises():
    # Lives inside existing except blocks -- a bug here must not turn a soft
    # index failure into a hard capture failure.
    _reset()
    index_health.record_failure(None, object())   # type: ignore[arg-type]
    index_health.record_ok(123)                    # type: ignore[arg-type]
    # snapshot()/degraded() must also be crash-proof
    assert isinstance(index_health.snapshot(), dict)
    assert isinstance(index_health.degraded(), bool)


def test_failing_index_write_records_failure_but_does_not_raise(monkeypatch):
    """A forced index-write failure must be recorded as degraded while the
    caller (a capture) is unaffected -- the write swallows and annotates."""
    _reset()
    import index_writer

    # Force the underlying DB write to blow up; the swallow block in
    # index_writer should catch it, record_failure, and return without raising.
    def _boom(*a, **k):
        raise RuntimeError("simulated FTS5 lock")

    monkeypatch.setattr(index_writer, "init_db", _boom)
    # log_capture_db is the public write entry; it must not propagate.
    try:
        index_writer.log_capture_db({"path": "x.md", "category": "Tech"}, __import__("pathlib").Path("."))
    except Exception as exc:  # pragma: no cover - would be a fail-soft regression
        raise AssertionError(f"index write must be fail-soft, raised: {exc}")

    assert index_health.degraded() is True
    assert index_health.snapshot()["captures"]["ok"] is False


def test_health_endpoint_surfaces_snapshot():
    from fastapi.testclient import TestClient
    import server

    _reset()
    with TestClient(server.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert "index_health" in body
        assert "captures" in body["index_health"]
        assert "vectors" in body["index_health"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
