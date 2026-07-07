"""
test_route_failed_llm.py
-------------------------
P0 regression test: total LLM enrichment failure (Ollama down, model error,
or a parse failure surviving the two-pass retry) must not drop the capture.

Covers:
  * storage_engine.route_failed_llm() writes a flagged scratchpad placeholder
    directly (mirrors storage_engine's T21/T22 route_failed_vision checks).
  * main.py:run_pipeline() falls back to route_failed_llm() instead of
    losing the capture when llm_engine.run_llm_engine() raises.
  * server.py:_run_pipeline_blocking() does the same, emitting a "done"
    event (not a bare "error") pointing at the saved placeholder.

No fixtures/conftest -- plain functions, pytest's builtin tmp_path only.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import config
import llm_engine
import main
import server
import storage_engine
import vector_store
from config import Config
from storage_engine import route_failed_llm


# ── storage_engine.route_failed_llm() directly ────────────────────────────────

def test_route_failed_llm_writes_flagged_placeholder(tmp_path: Path):
    path = route_failed_llm(
        "the raw captured text that must not be lost",
        "Ollama connection refused",
        vault_root=tmp_path,
        scratchpad_folder="_scratchpad",
    )
    assert path.exists()
    assert "_scratchpad" in str(path)
    text = path.read_text(encoding="utf-8")
    assert 'needs_llm_retry: "true"' in text or "needs_llm_retry: true" in text
    assert "status: needs_review" in text
    assert "> [!warning] LLM enrichment failed" in text
    assert "Ollama connection refused" in text
    assert "the raw captured text that must not be lost" in text


# ── shared test config ─────────────────────────────────────────────────────────

def _make_cfg(vault_root: Path) -> Config:
    cfg = Config()
    cfg.vault.root = vault_root
    cfg.vault.scratchpad_folder = "_scratchpad"
    cfg.vector.enabled = False       # skip embedding calls (no Ollama in tests)
    cfg.notifications.enabled = False
    return cfg


# ── main.py: run_pipeline() ────────────────────────────────────────────────────

def test_run_pipeline_saves_capture_when_llm_fails(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    with mock.patch.object(config, "reload_config", lambda *a, **k: cfg), \
         mock.patch.object(llm_engine, "run_llm_engine", side_effect=RuntimeError("model unavailable")):
        result = main.run_pipeline(text="hello from main.py llm-failure test", notify=False)

    assert result.get("llm_failed") is True
    written = result.get("_written_to")
    assert written, "LLM failure must still write a capture, not drop it"
    written_path = Path(written)
    assert written_path.exists()
    assert "_scratchpad" in str(written_path)
    text = written_path.read_text(encoding="utf-8")
    assert 'needs_llm_retry: "true"' in text or "needs_llm_retry: true" in text
    assert "hello from main.py llm-failure test" in text
    assert "model unavailable" in text


# ── server.py: _run_pipeline_blocking() ────────────────────────────────────────

class _FakeLoop:
    """Runs call_soon_threadsafe callbacks inline -- _run_pipeline_blocking
    normally runs on a worker thread with a real asyncio loop; the test just
    needs the emitted events collected synchronously."""

    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


class _FakeQueue:
    def __init__(self):
        self.items: list = []

    def put_nowait(self, item):
        self.items.append(item)


def test_server_pipeline_saves_capture_when_llm_fails(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    q = _FakeQueue()
    loop = _FakeLoop()

    with mock.patch.object(config, "reload_config", lambda *a, **k: cfg), \
         mock.patch.object(llm_engine, "run_llm_engine", side_effect=RuntimeError("model unavailable")):
        server._run_pipeline_blocking("text", "hello from server.py llm-failure test", q, loop, run_id="t1")

    events = [item for item in q.items if item is not None]
    error_events = [e for e in events if e.get("event") == "error"]
    assert not error_events, f"LLM failure must not surface as a bare error event: {error_events}"

    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, f"expected a 'done' event pointing at the saved placeholder, got: {events}"
    written_path = Path(done_events[-1]["path"])
    assert written_path.exists()
    assert "_scratchpad" in str(written_path)
    text = written_path.read_text(encoding="utf-8")
    assert 'needs_llm_retry: "true"' in text or "needs_llm_retry: true" in text
    assert "hello from server.py llm-failure test" in text
    assert "model unavailable" in text


# ── server.py: index-write failure must NOT double-write (review #1) ────────────

def test_server_index_failure_does_not_double_write(tmp_path: Path):
    """A successful vault write followed by a derived-index (embeddings) failure
    must keep the single real note and emit 'done' with its true category --
    never route a second scratchpad placeholder (the old broad-except bug where
    the try wrapped write+index and an index 404 triggered route_failed_llm)."""
    from models import CaptureOutput

    cfg = _make_cfg(tmp_path)
    cfg.vector.enabled = True  # exercise the index stage

    real_note = tmp_path / "Notes" / "real-capture.md"

    def _fake_write(output, **kwargs):
        real_note.parent.mkdir(parents=True, exist_ok=True)
        real_note.write_text("# real note\n", encoding="utf-8")
        return real_note

    good_output = CaptureOutput(
        category="Notes",
        suggested_filename="real-capture",
        markdown_content="real note body",
        rationale="test",
        key_signals=["k"],
        confidence=0.9,
        requires_new_category=False,
    )

    q = _FakeQueue()
    loop = _FakeLoop()
    with mock.patch.object(config, "reload_config", lambda *a, **k: cfg), \
         mock.patch.object(llm_engine, "run_llm_engine", return_value=good_output), \
         mock.patch.object(vector_store, "retrieve_related", return_value=[]), \
         mock.patch.object(storage_engine, "write_to_vault", side_effect=_fake_write), \
         mock.patch.object(vector_store, "index_note", side_effect=RuntimeError("embeddings 404")):
        server._run_pipeline_blocking("text", "some capture text", q, loop, run_id="idx1")

    events = [item for item in q.items if item is not None]
    error_events = [e for e in events if e.get("event") == "error"]
    assert not error_events, f"index failure must not surface as error: {error_events}"
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, f"expected 'done' event, got: {events}"
    assert done_events[-1]["category"] == "Notes", "must report the real category, not scratchpad"
    scratch = tmp_path / "_scratchpad"
    scratch_files = list(scratch.glob("*.md")) if scratch.exists() else []
    assert not scratch_files, f"index failure must not double-write to scratchpad: {scratch_files}"
    assert real_note.exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
