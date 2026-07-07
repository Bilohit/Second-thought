"""
test_capture_idempotency.py
----------------------------
Covers the retry-safe idempotency short-circuit in `_stream_capture`
(server.py): a GUI retry after a lost SSE connection re-POSTs /capture with
the SAME X-Capture-Run-Id (useCapture.ts generates it once, before the retry
loop -- see gui/src/hooks/useCapture.ts:379/399). If the first attempt's
pipeline already completed (vault write succeeded), the retry must NOT
re-run the pipeline -- it should replay the recorded terminal event instead.

Uses TestClient + a fake `_run_pipeline_blocking` (mirrors the mocking style
already used for job/pipeline internals in test_server.py) so no real Ollama
call or vault write happens; we only assert the pipeline entry point's call
count and the replayed SSE payload.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OMNI_GUI_SECRET", "")

from fastapi.testclient import TestClient

import server


def _fake_pipeline_factory(call_counter: dict, path: str = "C:/vault/Notes/fake.md", category: str = "Notes"):
    """Stand-in for _run_pipeline_blocking: emits one 'done' event and the
    sentinel, exactly like the real function's queue protocol, but does no
    real enrichment/LLM/vault-write work."""
    def _fake(content_type, content, q, loop, run_id=None):
        call_counter["n"] += 1
        loop.call_soon_threadsafe(q.put_nowait, {"event": "done", "path": path, "category": category})
        loop.call_soon_threadsafe(q.put_nowait, None)
    return _fake


def test_retry_with_same_run_id_short_circuits_pipeline():
    server._capture_results.clear()
    call_counter = {"n": 0}
    client = TestClient(server.app)

    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline_factory(call_counter)):
        r1 = client.post(
            "/capture",
            json={"content_type": "text", "content": "hello world"},
            headers={"X-Capture-Run-Id": "retry-test-id-1"},
        )
        assert r1.status_code == 200
        assert "event: done" in r1.text
        assert "fake.md" in r1.text
        assert call_counter["n"] == 1, "first request must run the pipeline once"

        # Clear the unrelated content-hash repeat-hotkey gate (_DEDUP_WINDOW_S)
        # so this test isolates the run_id-based idempotency path rather than
        # accidentally passing via that separate short window.
        time.sleep(server._DEDUP_WINDOW_S + 0.2)

        r2 = client.post(
            "/capture",
            json={"content_type": "text", "content": "hello world"},
            headers={"X-Capture-Run-Id": "retry-test-id-1"},
        )
        assert r2.status_code == 200
        assert "event: done" in r2.text
        assert "fake.md" in r2.text
        assert "duplicate" not in r2.text
        # The pipeline must NOT have been invoked a second time -- exactly one
        # vault write for this logical capture, regardless of the retry.
        assert call_counter["n"] == 1, "retry with same run_id must not re-run the pipeline"


def test_different_run_id_is_not_deduped():
    server._capture_results.clear()
    call_counter = {"n": 0}
    client = TestClient(server.app)

    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline_factory(call_counter)):
        client.post(
            "/capture",
            json={"content_type": "text", "content": "capture A"},
            headers={"X-Capture-Run-Id": "id-a"},
        )
        client.post(
            "/capture",
            json={"content_type": "text", "content": "capture B"},
            headers={"X-Capture-Run-Id": "id-b"},
        )
    assert call_counter["n"] == 2, "distinct run_ids must each run the pipeline"


def test_no_run_id_behaves_as_before():
    """Requests without X-Capture-Run-Id (e.g. an older client) must still
    run the pipeline every time -- idempotency is opt-in via the header."""
    server._capture_results.clear()
    call_counter = {"n": 0}
    client = TestClient(server.app)

    with mock.patch.object(server, "_run_pipeline_blocking", side_effect=_fake_pipeline_factory(call_counter)):
        client.post("/capture", json={"content_type": "text", "content": "no id 1"})
        time.sleep(server._DEDUP_WINDOW_S + 0.2)
        client.post("/capture", json={"content_type": "text", "content": "no id 1"})
    assert call_counter["n"] == 2


if __name__ == "__main__":
    test_retry_with_same_run_id_short_circuits_pipeline()
    test_different_run_id_is_not_deduped()
    test_no_run_id_behaves_as_before()
    print("OK")
