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


# ============================================================================
# B-2 regression: terminal event must be recorded at EMIT time, not only
# when the SSE consumer loop (_stream_capture's `while True: item = await
# q.get()`) is still attached to drain the queue. A client disconnect before
# the 'done' event reaches that loop used to mean the idempotency map was
# never written -- a GUI retry with the same X-Capture-Run-Id would then
# re-run the whole pipeline (and, since dedup keys on the LLM's
# markdown_content which differs per run, write a second, duplicate note).
#
# Reproduced here by calling _run_pipeline_blocking directly and NEVER
# draining `q` afterwards -- i.e. simulating the exact "consumer walked
# away" scenario the docstring above describes -- then asserting the
# idempotency record exists anyway.
# ============================================================================
def test_terminal_event_recorded_even_when_consumer_never_drains_queue(tmp_path):
    import asyncio
    import os

    import config as cfg_mod
    cfg_mod._cfg = None
    os.environ["OMNI_VAULT_ROOT"] = str(tmp_path)
    os.environ.setdefault("OLLAMA_MODEL", "llama3.2")
    os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")

    from models import CaptureOutput

    server._capture_results.clear()

    fake_out = CaptureOutput(
        category="Tech_Notes",
        suggested_filename="never-drained-note",
        markdown_content="## Never drained\n\nContent.",
        key_signals=[],
        confidence=0.9,
        requires_new_category=False,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    q: asyncio.Queue = asyncio.Queue()

    with mock.patch("llm_engine.run_llm_engine", return_value=fake_out), \
         mock.patch("vector_store.retrieve_related", return_value=[]), \
         mock.patch("vector_store.index_note"):
        server._run_pipeline_blocking(
            "text", "hello world, never drained", q, loop, run_id="disconnect-test-id",
        )

    # Nothing ever called q.get() -- simulating the SSE client disconnecting
    # before the consumer loop in _stream_capture reached the 'done' event.
    recorded = server._get_capture_terminal("disconnect-test-id")
    assert recorded is not None, (
        "terminal event must be recorded the moment _run_pipeline_blocking "
        "emits it, regardless of whether a consumer ever drains the queue "
        "-- otherwise a post-disconnect retry re-runs the whole pipeline "
        "and writes a duplicate note"
    )
    assert recorded["event"] == "done"
    assert recorded["payload"]["category"] == "Tech_Notes"


if __name__ == "__main__":
    test_retry_with_same_run_id_short_circuits_pipeline()
    test_different_run_id_is_not_deduped()
    test_no_run_id_behaves_as_before()
    test_terminal_event_recorded_even_when_consumer_never_drains_queue()
    print("OK")
