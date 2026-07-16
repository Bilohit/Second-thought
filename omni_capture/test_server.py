"""
test_server.py
---------------
Consolidated server/pipeline test suite. Merged verbatim from:
  test_health.py, test_look_chat.py, test_config_patch.py, test_voice_job.py,
  test_large_text.py, test_reminders.py, test_inbox_auto_describe.py

Collision handling: test_config_patch's `_client` -> `_client_config`;
test_inbox_auto_describe's `_client` -> `_client_inbox`.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from unittest import mock as _mock  # look_chat used `from unittest import mock`
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OMNI_GUI_SECRET", "")

from fastapi.testclient import TestClient

import server
from config import Config
from models import EnrichedPayload, CaptureOutput
import llm_engine
from summarizer import digest_chunks, _ChunkDigest
from storage_engine import write_to_vault, list_scratchpad, write_category_description
from reminders import (
    create_reminder,
    list_reminders,
    due_reminders,
    mark_fired,
    delete_reminder,
)


# ============================================================================
# test_health.py
# ============================================================================
def test_health_shape_before_and_after_ready():
    client = TestClient(server.app)

    def _base(resp):
        body = resp.json()
        # index_health is a process-global observability snapshot (see
        # index_health.py) whose exact content depends on whichever tests
        # ran before this one -- assert its shape, not its value, and check
        # the rest of the payload by exact equality as before.
        assert "index_health" in body
        assert set(body["index_health"].keys()) >= {"captures", "vectors"}
        return {k: v for k, v in body.items() if k != "index_health"}

    server._MODEL_READY = False
    server._MODEL_OK = None
    resp = client.get("/health")
    assert resp.status_code == 200
    assert _base(resp) == {"ok": True, "ready": False, "model_ok": None}

    server._MODEL_READY = True
    server._MODEL_OK = True
    resp = client.get("/health")
    assert _base(resp) == {"ok": True, "ready": True, "model_ok": True}

    server._MODEL_READY = True
    server._MODEL_OK = False
    resp = client.get("/health")
    assert _base(resp) == {"ok": True, "ready": True, "model_ok": False}


# ============================================================================
# test_look_chat.py
# ============================================================================
def test_vault_refusal_when_no_match():
    with _mock.patch("rag_engine.hybrid_retrieve", return_value=([], 0.0, "none")):
        client = TestClient(server.app)
        r = client.post("/look/chat", json={"question": "anything"})
        body = r.text
    assert "Information not found in vault" in body
    assert "event: done" in body

def test_talk_mode_skips_retrieval():
    with _mock.patch("rag_engine.hybrid_retrieve") as retrieve:
        client = TestClient(server.app)
        r = client.post("/look/chat", json={"question": "/talk hello"})
        body = r.text
    retrieve.assert_not_called()
    assert '"tier": "talk"' in body or '"tier":"talk"' in body
    assert "event: done" in body


# ============================================================================
# test_config_patch.py  (_client -> _client_config)
# ============================================================================
def _client_config(tmp_config: Path):
    import server
    importlib.reload(server)
    server.CONFIG_PATH = tmp_config
    from fastapi.testclient import TestClient
    return TestClient(server.app), server


def test_patch_writes_capture_keys_under_capture_section():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={
                "confidence_threshold": 0.75,
                "llm_scrutiny": "strict",
                "ocr_fast_path_enabled": False,
                "ocr_text_min_chars": 64,
            })
        assert r.status_code == 200
        import tomlkit
        doc = tomlkit.loads(cfg.read_text(encoding="utf-8"))
        assert float(doc["capture"]["confidence_threshold"]) == 0.75
        assert str(doc["capture"]["llm_scrutiny"]) == "strict"
        assert bool(doc["capture"]["ocr_fast_path_enabled"]) is False
        assert int(doc["capture"]["ocr_text_min_chars"]) == 64


def test_patch_rejects_invalid_scrutiny():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"llm_scrutiny": "aggressive"})
        assert r.status_code == 400


def test_patch_rejects_confidence_threshold_below_zero():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"confidence_threshold": -1.0})
        assert r.status_code == 400


def test_patch_rejects_confidence_threshold_above_one():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"confidence_threshold": 1.5})
        assert r.status_code == 400


def test_patch_rejects_negative_ocr_text_min_chars():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"ocr_text_min_chars": -5})
        assert r.status_code == 400


def test_patch_survives_a_real_reload_from_disk():
    """
    Round-trip regression: PATCH /config, then load the config from a *fresh*
    load_config() call (not the process-wide get_config() cache) to prove the
    written file itself -- not just in-memory state -- carries the new
    llm_scrutiny/confidence_threshold values. This is what a genuine app
    restart does: a brand-new process calls load_config() with no prior
    in-memory state to fall back on.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={
                "confidence_threshold": 0.85,
                "llm_scrutiny": "relaxed",
            })
        assert r.status_code == 200

        import config
        importlib.reload(config)
        fresh = config.load_config(cfg)
        assert fresh.capture.confidence_threshold == 0.85
        assert fresh.capture.llm_scrutiny == "relaxed"


def test_patch_reminders_delivery_persists_and_survives_reload():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"reminders_delivery": "os"})
        assert r.status_code == 200

        import config
        importlib.reload(config)
        fresh = config.load_config(cfg)
        assert fresh.reminders.delivery == "os"


# ============================================================================
# test_voice_job.py
# ============================================================================
def _audio_payload(text: str) -> EnrichedPayload:
    return EnrichedPayload(raw_input="x.webm", input_type="audio", enriched_text=text)


def test_append_transcript_adds_section_once():
    from server import _append_transcript
    body = _append_transcript("# Note\n\nSummary.", _audio_payload("hello world"))
    assert body.count("## Transcript") == 1
    assert body.rstrip().endswith("hello world")


def test_append_transcript_noop_for_non_audio():
    from server import _append_transcript
    payload = EnrichedPayload(raw_input="t", input_type="text", enriched_text="hello")
    assert _append_transcript("# Note", payload) == "# Note"


def test_voice_job_threshold():
    from server import _voice_needs_summarize_job
    assert _voice_needs_summarize_job(token_count=500, threshold=6000) is False
    assert _voice_needs_summarize_job(token_count=9000, threshold=6000) is True


# ============================================================================
# test_large_text.py
# ============================================================================
def _stub_client(digest: _ChunkDigest | None = None, *, raises: bool = False):
    client = mock.MagicMock()
    if raises:
        client.chat.completions.create.side_effect = RuntimeError("model unavailable")
    else:
        client.chat.completions.create.return_value = digest
    return client


def test_digest_chunks_happy_path_returns_one_result_per_chunk():
    digest = _ChunkDigest(tags=["deep-topic"], summary="s")
    with mock.patch.object(llm_engine, "_make_client", lambda: _stub_client(digest)):
        results = digest_chunks(
            ["a", "b"], base_url="http://localhost:11434", model="llama3.2",
            temperature=0.1, max_retries=1,
        )
    assert results == [(["deep-topic"], "s"), (["deep-topic"], "s")]


def test_digest_chunks_fails_soft_per_chunk():
    with mock.patch.object(llm_engine, "_make_client", lambda: _stub_client(raises=True)):
        results = digest_chunks(
            ["a", "b"], base_url="http://localhost:11434", model="llama3.2",
            temperature=0.1, max_retries=1,
        )
    assert results == [([], ""), ([], "")]


def test_merge_large_text_tags_dedupes_and_caps():
    from server import _merge_large_text_tags

    merged = _merge_large_text_tags(
        key_signals=["K1"], chunk_tags=[["deep-topic"], []], vocab={},
    )
    assert "K1" in merged
    assert "deep-topic" in merged
    assert len(merged) == len(set(merged))
    assert len(merged) <= 10


def test_merge_large_text_tags_mirrored_in_main():
    from main import _merge_large_text_tags as main_merge

    merged = main_merge(key_signals=["K1"], chunk_tags=[["deep-topic"], []], vocab={})
    assert "K1" in merged
    assert "deep-topic" in merged


# ============================================================================
# test_reminders.py
# ============================================================================
def test_create_and_list_pending(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(
        db, note_path="a.md", label="follow up", fire_at_iso="2030-01-01T00:00"
    )
    assert isinstance(rid, int)

    rows = list_reminders(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == rid
    assert row["note_path"] == "a.md"
    assert row["label"] == "follow up"
    assert row["fire_at"] == "2030-01-01T00:00"
    assert row["status"] == "pending"
    assert row["delivery"] == "app"
    assert row["created_at"]


def test_due_reminders_past_vs_future(tmp_path):
    db = tmp_path / "captures.db"
    create_reminder(db, note_path="past.md", label="past", fire_at_iso="2020-01-01T00:00")
    create_reminder(db, note_path="future.md", label="future", fire_at_iso="2099-01-01T00:00")

    due_now = due_reminders(db, now_iso="2025-01-01T00:00")
    assert len(due_now) == 1
    assert due_now[0]["note_path"] == "past.md"

    due_early = due_reminders(db, now_iso="2019-01-01T00:00")
    assert due_early == []


def test_mark_fired_flips_status_and_removes_from_due(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(db, note_path="a.md", label="due", fire_at_iso="2020-01-01T00:00")

    assert len(due_reminders(db, now_iso="2025-01-01T00:00")) == 1

    mark_fired(db, rid)

    assert due_reminders(db, now_iso="2025-01-01T00:00") == []
    rows = list_reminders(db, include_done=True)
    assert rows[0]["status"] == "fired"


def test_delete_reminder_removes_from_list(tmp_path):
    db = tmp_path / "captures.db"
    rid = create_reminder(db, note_path="a.md", label="gone", fire_at_iso="2030-01-01T00:00")
    assert len(list_reminders(db)) == 1

    delete_reminder(db, rid)

    assert list_reminders(db) == []


def test_fire_due_notifies_and_marks(tmp_path):
    from reminders import create_reminder, list_reminders
    from server import _fire_due
    db = tmp_path / "captures.db"
    create_reminder(db, note_path="a.md", label="due now", fire_at_iso="2020-01-01T00:00", delivery="app")
    create_reminder(db, note_path="b.md", label="future", fire_at_iso="2099-01-01T00:00", delivery="app")
    fired = []
    _fire_due(db, notify_fn=lambda title, msg: fired.append(title))
    assert fired == ["⏰ due now"]
    statuses = {r["label"]: r["status"] for r in list_reminders(db, include_done=True)}
    assert statuses == {"due now": "fired", "future": "pending"}


def test_create_reminder_os_delivery_calls_schtasks_create_on_windows():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert args[0] == "schtasks"
            assert "/Create" in args
            assert "/SC" in args
            sc_idx = args.index("/SC")
            assert args[sc_idx + 1] == "ONCE"
            tn_idx = args.index("/TN")
            assert args[tn_idx + 1] == f"SecondThought\\reminder-{rid}"


def test_create_reminder_app_delivery_runs_no_subprocess():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="app",
            )
            assert not mock_run.called


def test_create_reminder_os_delivery_on_non_windows_falls_back_to_app():
    with patch("reminders._IS_WINDOWS", False), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            assert not mock_run.called
            row = list_reminders(db)[0]
            assert row["id"] == rid
            assert row["delivery"] == "app"


def test_delete_reminder_os_delivery_calls_schtasks_delete_on_windows():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="os",
            )
            mock_run.reset_mock()
            delete_reminder(db, rid)
            assert mock_run.called
            args = mock_run.call_args[0][0]
            assert args[0] == "schtasks"
            assert "/Delete" in args
            tn_idx = args.index("/TN")
            assert args[tn_idx + 1] == f"SecondThought\\reminder-{rid}"
            assert mock_run.call_args[1].get("check") is not True


def test_delete_reminder_app_delivery_runs_no_subprocess():
    with patch("reminders._IS_WINDOWS", True), \
         patch("reminders.subprocess.run") as mock_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captures.db"
            rid = create_reminder(
                db, note_path="a.md", label="follow up",
                fire_at_iso="2030-01-01T09:30", delivery="app",
            )
            mock_run.reset_mock()
            delete_reminder(db, rid)
            assert not mock_run.called


# ============================================================================
# test_inbox_auto_describe.py  (_client -> _client_inbox)
# ============================================================================
def _seed_inbox(vault: Path, content="Plants need water and sunlight to grow.") -> str:
    t = CaptureOutput(
        category="Tech_Notes",
        suggested_filename="garden-note",
        markdown_content=content,
        key_signals=[],
        confidence=0.1,
        requires_new_category=False,
    )
    write_to_vault(t, vault_root=vault)
    items = list_scratchpad(vault)
    assert items
    return items[0]["note_id"]


def _client_inbox(vault: Path, auto_describe: bool):
    import server
    server._get_vault_root = lambda: vault  # type: ignore[attr-defined]

    cfg = Config()
    cfg.capture.auto_describe_new_folders = auto_describe
    return TestClient(server.app), cfg


class TestApproveAutoDescribe(unittest.TestCase):
    def test_toggle_on_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Notes about plants and gardening."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())

    def test_toggle_off_does_not_write_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertFalse(cat_toml.exists())

    def test_approve_into_existing_category_skips_describe_even_if_on(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            (vault / "Botany").mkdir(parents=True)
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertFalse(cat_toml.exists())


class TestSuggestCategories(unittest.TestCase):
    def test_suggest_returns_suggestions(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "suggest_category_names", lambda *a, **k: ["Botany", "Gardening"]), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get(f"/inbox/{note_id}/suggest-categories")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], ["Botany", "Gardening"])

    def test_suggest_404_for_unknown_note(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client_inbox(vault, auto_describe=False)
            with mock.patch("config.get_config", lambda: cfg):
                r = client.get("/inbox/does-not-exist/suggest-categories")
            self.assertEqual(r.status_code, 404)

    def test_suggest_llm_failure_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)

            import llm_engine
            with mock.patch.object(llm_engine, "summarize",
                                    mock.Mock(side_effect=llm_engine.SummarizationError("boom"))), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get(f"/inbox/{note_id}/suggest-categories")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], [])


class TestAutoDescribeRealAsyncPath(unittest.TestCase):
    """
    Regression coverage for the "asyncio.run() cannot be called from a
    running event loop" bug: generate_category_description()'s sync wrapper
    (llm_engine.summarize) ends in asyncio.run(), but it used to be invoked
    directly from inside async routes (create_category, approve_inbox),
    which already have a running loop -- asyncio.run() raised RuntimeError,
    which generate_category_description's bare `except Exception` swallowed,
    so no description was ever written.

    Unlike the tests above (which mock storage_engine.generate_category_description
    directly and so never touch asyncio.run() at all), these mock only
    llm_engine.summarize_async -- the real generate_category_description()
    and the real summarize()/asyncio.run() wrapper still execute, through the
    real async route. They fail if that regression reappears.
    """

    def test_create_category_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client_inbox(vault, auto_describe=True)

            import llm_engine

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post("/vault/categories", json={"name": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())

    def test_approve_inbox_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import llm_engine

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())


class TestWriteCategoryDescription(unittest.TestCase):
    def test_write_then_clear_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as td:
            cat_dir = Path(td) / "Botany"
            cat_dir.mkdir()
            (cat_dir / ".category.toml").write_text('format = "custom"\n', encoding="utf-8")

            write_category_description(cat_dir, "Plants and gardening notes.")
            text = (cat_dir / ".category.toml").read_text()
            self.assertIn("custom", text)
            self.assertIn("Plants and gardening", text)

            write_category_description(cat_dir, None)
            text = (cat_dir / ".category.toml").read_text()
            self.assertIn("custom", text)
            self.assertNotIn("Plants and gardening", text)


class TestDigestToday(unittest.TestCase):
    """GET /digest/today (F-14). The route calls get_config(), which server.py only ever imports
    function-locally -- without that local import every request 500s with a NameError, i.e. the
    endpoint was 100% dead."""

    def test_returns_the_four_counts(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            (vault / "n1.md").write_text(
                "---\nid: 01DIGEST\ntitle: T\norigin: note\n---\nBody\n",
                encoding="utf-8", newline="")

            cfg = Config()
            cfg.vault.root = vault
            client = TestClient(server.app)
            with mock.patch.object(server, "_GUI_SECRET", "s3cret"), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get("/digest/today", headers={"X-Omni-Secret": "s3cret"})

            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(set(body), {"captured", "touched", "reminders_due", "unrevisited"})
            for k, v in body.items():
                self.assertIsInstance(v, int, k)
            self.assertEqual(body["touched"], 1)      # the note was written today
            self.assertEqual(body["unrevisited"], 0)  # ...so nothing is 30d stale


# ============================================================================
# E6 -- Drive auth routes (/drive/auth/{status,connect,disconnect})
#
# The Sync tab's first question is "is Drive connected?", and the answer must
# never cost a browser window. Every test below therefore also asserts that
# InstalledAppFlow was not touched on any path that isn't an explicit connect.
# ============================================================================


def _drive_client():
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    return TestClient(server.app), server


def test_drive_auth_status_reports_both_causes_without_consent():
    """'not connected' has two causes the user fixes differently -- no OAuth
    client file (setup) vs never authorized (one click). Status must tell them
    apart, and must not open consent to find out."""
    client, _ = _drive_client()
    with patch("drive_auth.has_cached_credentials", return_value=False) as cached, \
         patch("drive_auth.client_secret_present", return_value=True), \
         patch("drive_auth.InstalledAppFlow") as flow:
        r = client.get("/drive/auth/status")
    assert r.status_code == 200
    assert r.json() == {"connected": False, "client_secret_present": True, "connecting": False}
    cached.assert_called_once()
    flow.from_client_secrets_file.assert_not_called()  # no browser from a status poll


def test_drive_auth_connect_400s_when_no_client_secret():
    """Offering Connect with no client file could only ever raise
    FileNotFoundError -- 400 so the GUI shows a setup fix, not a retry."""
    client, _ = _drive_client()
    with patch("drive_auth.client_secret_present", return_value=False), \
         patch("drive_auth.load_credentials") as load:
        r = client.post("/drive/auth/connect")
    assert r.status_code == 400
    load.assert_not_called()


def test_drive_auth_connect_409s_when_a_consent_is_already_in_flight():
    """Two clicks would race two local callback servers and two browsers."""
    client, srv = _drive_client()
    srv._drive_connect_flight.acquire()
    try:
        with patch("drive_auth.client_secret_present", return_value=True), \
             patch("drive_auth.load_credentials") as load:
            r = client.post("/drive/auth/connect")
    finally:
        srv._drive_connect_flight.release()
    assert r.status_code == 409
    load.assert_not_called()


def test_drive_auth_connect_502s_and_releases_the_flight_on_failure():
    """A declined/closed consent must not wedge Connect forever -- the lock is
    released even on the raising path, so the next click still works."""
    client, srv = _drive_client()
    with patch("drive_auth.client_secret_present", return_value=True), \
         patch("drive_auth.load_credentials", side_effect=RuntimeError("user closed the window")):
        r = client.post("/drive/auth/connect")
    assert r.status_code == 502
    assert not srv._drive_connect_flight.locked(), "flight lock leaked on the failure path"

    with patch("drive_auth.client_secret_present", return_value=True), \
         patch("drive_auth.load_credentials", return_value=object()):
        r2 = client.post("/drive/auth/connect")
    assert r2.status_code == 200 and r2.json() == {"connected": True}


def test_drive_auth_disconnect_forgets_the_token():
    client, _ = _drive_client()
    with patch("drive_auth.forget_credentials", return_value=True) as forget:
        r = client.post("/drive/auth/disconnect")
    assert r.status_code == 200
    assert r.json() == {"connected": False, "removed": True}
    forget.assert_called_once()


# ============================================================================
# E6 -- the two sync switches
#
# They are DIFFERENT things and must stay distinguishable at the API:
#   [sync] enabled = false      -> the whole syncing system is off: no automatic
#                                  passes AND no manual Sync now (403).
#   [sync] interval_minutes = 0 -> "never auto-sync": no automatic passes of any
#                                  kind, but Sync now still runs (200).
#
# `enabled` is never injected here: each test writes a real config.toml and runs
# it through the real load_config() -> config singleton the handler reads, so a
# regression anywhere on that path (e.g. the sentinel being clamped away at
# parse time) shows up as a red test rather than a passing fake.
# ============================================================================


def _sync_client(tmp_path, sync_toml: str, monkeypatch, pass_fn=None):
    """TestClient + a real config.toml + a scheduler singleton, as if start_scheduler() had run.
    Only Drive (pass_fn) and the vault root are fakes; the config path is the real one."""
    import config as _config
    import sync_scheduler as _ss

    vault = tmp_path / "vault"
    vault.mkdir()
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[vault]\nroot = "' + str(vault).replace("\\", "/") + '"\n\n[sync]\n' + sync_toml,
        encoding="utf-8",
    )
    # monkeypatch restores the previous singleton, so the rest of the suite is unaffected.
    monkeypatch.setattr(_config, "_cfg", _config.load_config(cfg_path))
    sch = _ss.SyncScheduler(
        pass_fn=pass_fn or (lambda: {"uploaded": 0}),
        cfg_fn=lambda: _config.get_config().sync,
    )
    monkeypatch.setattr(_ss, "_scheduler", sch)  # no thread: nothing here needs the loop
    return TestClient(server.app), sch


def test_sync_run_403_when_master_off(tmp_path, monkeypatch):
    """Master OFF means off. Hiding the button in the GUI is not a kill switch -- the refusal has
    to be server-side, and no Drive pass may run."""
    ran = []
    client, _ = _sync_client(tmp_path, "enabled = false\n", monkeypatch,
                             pass_fn=lambda: ran.append(1) or {})
    r = client.post("/sync/run")
    assert r.status_code == 403
    assert ran == [], "a refused Sync now still ran a Drive pass"


def test_sync_run_200_when_master_on(tmp_path, monkeypatch):
    """The positive control: the 403 must gate on `enabled`, not break Sync now outright."""
    ran = []
    client, _ = _sync_client(tmp_path, "enabled = true\n", monkeypatch,
                             pass_fn=lambda: ran.append(1) or {"uploaded": 0})
    r = client.post("/sync/run")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert ran == [1]


def test_sync_run_409_stays_distinct_from_403(tmp_path, monkeypatch):
    """Three refusals, three client states: busy is not disabled."""
    client, sch = _sync_client(tmp_path, "enabled = true\n", monkeypatch)
    assert sch._flight.acquire(blocking=False)  # simulate a pass already running
    try:
        r = client.post("/sync/run")
    finally:
        sch._flight.release()
    assert r.status_code == 409


def test_sync_run_503_stays_distinct_from_403(tmp_path, monkeypatch):
    """503 must also WIN over 403: with no scheduler there is no pass to refuse, and the user's
    fix is completely different (a broken server vs a setting they chose)."""
    import sync_scheduler as _ss
    client, _ = _sync_client(tmp_path, "enabled = false\n", monkeypatch)
    monkeypatch.setattr(_ss, "_scheduler", None)
    assert client.post("/sync/run").status_code == 503


def test_sync_run_still_runs_under_the_never_sentinel(tmp_path, monkeypatch):
    """The whole point of "Never" vs master-off: it gates AUTOMATIC passes only. If this 403s, the
    two switches have collapsed into one and "Never" has become a second kill switch."""
    ran = []
    client, _ = _sync_client(tmp_path, "enabled = true\ninterval_minutes = 0\n", monkeypatch,
                             pass_fn=lambda: ran.append(1) or {"uploaded": 0})
    r = client.post("/sync/run")
    assert r.status_code == 200 and ran == [1]


# -- trigger 3: sync_after_capture (the other two live in test_sync_scheduler.py) --------------
#
# Driven through a real /capture with test_capture_idempotency.py's fake pipeline, because the
# gate reads config inside `_stream_capture`'s terminal-event branch. This asserts ONLY whether a
# sync pass fired; capture behaviour itself is covered elsewhere.


def _capture_and_wait(client, content: str, fired, timeout: float):
    from test_capture_idempotency import _fake_pipeline_factory
    server._capture_results.clear()
    with mock.patch.object(server, "_run_pipeline_blocking",
                           side_effect=_fake_pipeline_factory({"n": 0})):
        r = client.post("/capture", json={"content_type": "text", "content": content})
    assert r.status_code == 200 and "event: done" in r.text
    return fired.wait(timeout)


def test_sentinel_blocks_sync_after_capture(tmp_path, monkeypatch):
    """Trigger 3. `interval_minutes = 0` must suppress this too -- a user who asked for no
    automatic syncing would otherwise sync on every single capture, the most frequent trigger
    of the three."""
    import threading
    fired = threading.Event()
    client, _ = _sync_client(
        tmp_path, "enabled = true\nsync_after_capture = true\ninterval_minutes = 0\n", monkeypatch,
        pass_fn=lambda: (fired.set(), {})[1],
    )
    assert _capture_and_wait(client, "e6 sentinel after-capture", fired, 0.5) is False, \
        "a capture triggered an automatic sync pass despite interval_minutes = 0"


def test_sync_after_capture_still_fires_for_a_real_interval(tmp_path, monkeypatch):
    """The positive control: proves the test above observes the real trigger rather than a
    trigger that never fires under this harness at all."""
    import threading
    fired = threading.Event()
    client, _ = _sync_client(
        tmp_path, "enabled = true\nsync_after_capture = true\ninterval_minutes = 60\n", monkeypatch,
        pass_fn=lambda: (fired.set(), {})[1],
    )
    assert _capture_and_wait(client, "e6 real-interval after-capture", fired, 5.0) is True, \
        "sync_after_capture did not fire for a normal interval"


# -- the sentinel has to be REACHABLE end-to-end, not just honoured once set ---------------------
#
# Two places clamped it out of existence before the option could ever be chosen: POST /config
# rejected anything < 5 (so the GUI could not set it) and load_config() ran max(5, ...) (so a
# hand-edited config.toml still arrived as 5). Either one alone makes "Never" silently mean
# "every 5 minutes" -- the loudest possible version of the bug.


def _config_patch_client(tmp):
    cfg = Path(tmp) / "config.toml"
    cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
    client, srv = _client_config(cfg)
    return client, srv, cfg


def test_patch_accepts_the_never_sentinel():
    with tempfile.TemporaryDirectory() as tmp:
        client, srv, cfg = _config_patch_client(tmp)
        with mock.patch.object(srv, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"sync_interval_minutes": 0})
        assert r.status_code == 200
        import tomlkit
        doc = tomlkit.loads(cfg.read_text(encoding="utf-8"))
        assert int(doc["sync"]["interval_minutes"]) == 0, "the GUI cannot select Never"


def test_patch_still_rejects_a_real_interval_below_5():
    """0 is a sentinel; 1-4 is just a bad interval and stays a 400."""
    with tempfile.TemporaryDirectory() as tmp:
        client, srv, _ = _config_patch_client(tmp)
        with mock.patch.object(srv, "reload_config", lambda *a, **k: None):
            for mins in (1, 4, -1):
                assert client.patch("/config", json={"sync_interval_minutes": mins}).status_code == 400


def test_load_config_preserves_the_sentinel_and_clamps_everything_else(tmp_path):
    """The parse-time half. `max(5, 0)` here would swallow the sentinel before any trigger sees it."""
    from config import load_config
    for written, expected in [(0, 0), (1, 5), (4, 5), (5, 5), (15, 15), (60, 60)]:
        cfg_path = tmp_path / f"config_{written}.toml"
        cfg_path.write_text(
            '[vault]\nroot = "' + str(tmp_path).replace("\\", "/") + '"\n\n'
            f"[sync]\ninterval_minutes = {written}\n",
            encoding="utf-8",
        )
        got = load_config(cfg_path).sync.interval_minutes
        assert got == expected, f"interval_minutes = {written} parsed to {got}, expected {expected}"
