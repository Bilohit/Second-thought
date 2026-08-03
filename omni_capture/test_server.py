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
# SRV-01: server._require_secret now fails CLOSED, so an empty OMNI_GUI_SECRET
# 403s every route instead of disabling auth. Every server test module uses this
# SAME literal on purpose: the env var is process-global and pytest imports all
# modules before running any test, so differing values would make the suite
# order-dependent.
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET
_AUTH = {"X-Omni-Secret": GUI_SECRET}


from fastapi.testclient import TestClient

import server
from config import Config
from models import EnrichedPayload, CaptureOutput
import llm_engine
from summarizer import digest_chunks, _ChunkDigest
from storage_engine import write_to_vault, list_scratchpad
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
    client = TestClient(server.app, headers=_AUTH)

    def _base(resp):
        body = resp.json()
        # index_health is a process-global observability snapshot (see
        # index_health.py) whose exact content depends on whichever tests
        # ran before this one -- assert its shape, not its value, and check
        # the rest of the payload by exact equality as before.
        assert "index_health" in body
        assert set(body["index_health"].keys()) >= {"captures", "vectors"}
        # s114/d06: `ffmpeg` is an environment probe (shutil.which), so like index_health its
        # VALUE depends on the machine -- assert its presence and type, exclude it from the
        # exact-equality comparison below. Its behaviour is pinned in test_api_surface.py.
        assert isinstance(body["ffmpeg"], bool)
        return {k: v for k, v in body.items() if k not in ("index_health", "ffmpeg")}

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


def test_ollama_reachable_probe():
    """ISS-018: unlike /health's model_ok (set once at startup and stale if
    Ollama stops afterward), /ollama/reachable must reflect Ollama's CURRENT
    state on every call."""
    client = TestClient(server.app, headers=_AUTH)

    with _mock.patch("server.urlopen") as m:
        m.return_value.__enter__.return_value.status = 200
        resp = client.get("/ollama/reachable")
    assert resp.status_code == 200
    assert resp.json() == {"reachable": True}

    with _mock.patch("server.urlopen", side_effect=OSError("connection refused")):
        resp = client.get("/ollama/reachable")
    assert resp.status_code == 200
    assert resp.json() == {"reachable": False}


# ============================================================================
# test_look_chat.py
# ============================================================================
def test_vault_refusal_when_no_match():
    with _mock.patch("rag_engine.hybrid_retrieve", return_value=([], 0.0, "none")):
        client = TestClient(server.app, headers=_AUTH)
        r = client.post("/look/chat", json={"question": "anything"})
        body = r.text
    assert "Information not found in vault" in body
    assert "event: done" in body

def test_ollama_offline_reply_distinct_from_no_match():
    """ISS-009: an Ollama connection failure (tier 'offline') must produce a
    distinct honest reply, never the same REFUSAL text as a genuine no-match
    (test_vault_refusal_when_no_match above)."""
    with _mock.patch("rag_engine.hybrid_retrieve", return_value=([], 0.0, "offline")):
        client = TestClient(server.app, headers=_AUTH)
        r = client.post("/look/chat", json={"question": "anything"})
        body = r.text
    assert "AI engine offline" in body
    assert "Information not found in vault" not in body
    assert "event: done" in body

def test_talk_mode_skips_retrieval():
    with _mock.patch("rag_engine.hybrid_retrieve") as retrieve:
        client = TestClient(server.app, headers=_AUTH)
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
    return TestClient(server.app, headers=_AUTH), server


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


def test_patch_accepts_tilde_vault_root():
    """FR-01: `~/...` is the shipped portable default (config.toml's own comment)
    and must not be rejected as a relative path -- Path.is_absolute() alone
    judges it relative because pathlib never expands `~`."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"vault_root": "~/second-thought-storage"})
        assert r.status_code == 200
        import tomlkit
        doc = tomlkit.loads(cfg.read_text(encoding="utf-8"))
        # stored value stays in tilde form -- portable, matches the shipped default;
        # expanding it here would silently bake in one user's home directory.
        assert str(doc["vault"]["root"]) == "~/second-thought-storage"


def test_patch_rejects_relative_vault_root():
    """FR-01 companion: a genuinely relative root (no `~`) must still 400 --
    the tilde fix must not weaken the SRV-15 guard it was added to preserve."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client_config(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"vault_root": "some/relative/path"})
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
    return TestClient(server.app, headers=_AUTH), cfg


def test_post_trash_moves_a_note_and_preserves_bytes():
    """ISS-005 A endpoint: POST /trash soft-moves a live note into _trash/, body byte-identical,
    and it then appears in GET /trash for restore."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        (vault / "Personal").mkdir(parents=True)
        note = vault / "Personal" / "delete-me.md"
        raw = b"---\ntitle: Delete me\ncategory: Personal\norigin: note\n---\n# X\r\n\r\nbody.   \n"
        note.write_bytes(raw)

        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        client = TestClient(server.app, headers=_AUTH)

        r = client.post("/trash", json={"path": "Personal/delete-me.md"})
        assert r.status_code == 200, r.text
        filename = r.json()["filename"]
        assert not note.exists()
        assert (vault / "_trash" / filename).read_bytes() == raw

        listed = client.get("/trash").json()["items"]
        assert any(it["filename"] == filename and it["category"] == "Personal" for it in listed)

        # Missing note → 404; escaping path → 400.
        assert client.post("/trash", json={"path": "Personal/ghost.md"}).status_code == 404
        assert client.post("/trash", json={"path": "../../etc/passwd.md"}).status_code == 400


def _seed_delete_prompt(vault: Path, note_id: str, kind: str = "trash") -> str:
    """Write a live note + a durable DELETE-PROMPT for it (what the reconcile pass records)."""
    from delete_detect import save_delete_prompts
    (vault / "Personal").mkdir(parents=True, exist_ok=True)
    raw = (f"---\nid: {note_id}\ntitle: Held\ncategory: Personal\norigin: note\n---\n"
           f"# Held\r\n\r\nSacred body.   \n").encode("utf-8")
    (vault / "Personal" / f"{note_id}.md").write_bytes(raw)
    (vault / ".omni_capture").mkdir(parents=True, exist_ok=True)
    state_path = str(vault / ".omni_capture" / "mobile_sync_state.json")
    save_delete_prompts(state_path, {"prompts": {note_id: {"kind": kind, "first_seen": "t"}},
                                     "pending_fs": {}, "keep_here": {}})
    return state_path


def test_resolve_delete_prompt_delete_both_trashes_locally_and_clears():
    """ISS-005 A follow-up gap 2: delete_both soft-moves the held note into _trash/ (body
    byte-identical) and clears the durable prompt."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        state_path = _seed_delete_prompt(vault, "N1")
        raw = (vault / "Personal" / "N1.md").read_bytes()

        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        client = TestClient(server.app, headers=_AUTH)

        r = client.post("/trash/delete-prompts/resolve", json={"id": "N1", "choice": "delete_both"})
        assert r.status_code == 200, r.text
        assert not (vault / "Personal" / "N1.md").exists()
        trashed = list((vault / "_trash").glob("*.md"))
        assert len(trashed) == 1 and trashed[0].read_bytes() == raw   # body-sacred soft move
        from delete_detect import load_delete_prompts
        assert load_delete_prompts(state_path)["prompts"] == {}


def test_resolve_delete_prompt_keep_here_keeps_note_and_records_decision():
    """keep_here leaves the local note untouched, clears the prompt, and durably records the decision
    so the reconcile pass never re-raises it."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        state_path = _seed_delete_prompt(vault, "N2")
        raw = (vault / "Personal" / "N2.md").read_bytes()

        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        client = TestClient(server.app, headers=_AUTH)

        r = client.post("/trash/delete-prompts/resolve", json={"id": "N2", "choice": "keep_here"})
        assert r.status_code == 200, r.text
        assert (vault / "Personal" / "N2.md").read_bytes() == raw     # local note kept verbatim
        assert not (vault / "_trash").exists()                        # nothing trashed
        from delete_detect import load_delete_prompts
        store = load_delete_prompts(state_path)
        assert store["prompts"] == {} and "N2" in store["keep_here"]


def test_resolve_delete_prompt_unknown_id_404_and_bad_choice_400():
    """Non-destructive guards: an unknown id → 404, a malformed choice → 400, never a blind delete."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        _seed_delete_prompt(vault, "N3")

        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        client = TestClient(server.app, headers=_AUTH)

        assert client.post("/trash/delete-prompts/resolve",
                           json={"id": "nope", "choice": "delete_both"}).status_code == 404
        assert client.post("/trash/delete-prompts/resolve",
                           json={"id": "N3", "choice": "nuke"}).status_code == 400
        # The held note and its prompt are untouched after both rejected calls.
        assert (vault / "Personal" / "N3.md").exists()


class TestApproveAutoDescribe(unittest.TestCase):
    """Projects S1: approving into a NEW project registers it in `.projects.toml` with a
    generated description. There is no `.category.toml` and no folder-creation step any
    more -- a project's directory appears because a note was filed into it."""

    def _projects(self, vault):
        import project_registry
        return project_registry.load(vault).get("projects", {})

    def test_toggle_on_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_project_description",
                                    lambda *a, **k: "Notes about plants and gardening."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_project": "Botany"})
            self.assertEqual(r.status_code, 200)

            entry = self._projects(vault)["Botany"]
            self.assertIn("Notes about plants", entry["description"])
            # The note landed in the project it was approved into, at depth 1.
            self.assertEqual(Path(r.json()["path"]).parent.name, "Botany")

    def test_toggle_off_does_not_write_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_project_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_project": "Botany"})
            self.assertEqual(r.status_code, 200)

            # Registered (the user chose it) but with NO description.
            self.assertEqual(self._projects(vault)["Botany"]["description"], "")

    def test_approve_into_existing_project_skips_describe_even_if_on(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            import project_registry
            project_registry.save(vault, {"schema": 1, "projects": {
                "Botany": {"description": "Already described."},
            }})
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_project_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_project": "Botany"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self._projects(vault)["Botany"]["description"], "Already described.")

    def test_approve_with_no_target_lands_loose_and_is_a_success(self):
        """The whole point of the rework: there is no "no valid destination" failure."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)
            with mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["project"], "_loose")

    def test_approve_rejects_an_ineligible_project_name(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)
            with mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_project": "../escape"})
            self.assertEqual(r.status_code, 400)


class TestSuggestProjects(unittest.TestCase):
    def test_suggest_returns_suggestions(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "suggest_project_names", lambda *a, **k: ["Botany", "Gardening"]), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get(f"/inbox/{note_id}/suggest-projects")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], ["Botany", "Gardening"])

    def test_suggest_404_for_unknown_note(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client_inbox(vault, auto_describe=False)
            with mock.patch("config.get_config", lambda: cfg):
                r = client.get("/inbox/does-not-exist/suggest-projects")
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
                r = client.get(f"/inbox/{note_id}/suggest-projects")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], [])


class TestAutoDescribeRealAsyncPath(unittest.TestCase):
    """
    Regression coverage for the "asyncio.run() cannot be called from a
    running event loop" bug: generate_project_description()'s sync wrapper
    (llm_engine.summarize) ends in asyncio.run(), but it used to be invoked
    directly from inside async routes (create_project, approve_inbox),
    which already have a running loop -- asyncio.run() raised RuntimeError,
    which generate_project_description's bare `except Exception` swallowed,
    so no description was ever written.

    Unlike the tests above (which mock storage_engine.generate_project_description
    directly and so never touch asyncio.run() at all), these mock only
    llm_engine.summarize_async -- the real generate_project_description()
    and the real summarize()/asyncio.run() wrapper still execute, through the
    real async route. They fail if that regression reappears.
    """

    def test_create_project_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client_inbox(vault, auto_describe=True)

            import llm_engine, project_registry

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post("/vault/projects", json={"name": "Botany"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("Notes about plants",
                          project_registry.load(vault)["projects"]["Botany"]["description"])
            # Registering a project creates NO directory (contract: the folder appears
            # when a note is first filed into it).
            self.assertFalse((vault / "Botany").exists())

    def test_approve_inbox_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client_inbox(vault, auto_describe=True)

            import llm_engine, project_registry

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_project": "Botany"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("Notes about plants",
                          project_registry.load(vault)["projects"]["Botany"]["description"])


class TestProjectRegistryCrud(unittest.TestCase):
    """The CRUD half of Task 13: delete never touches a note, rename never rewrites a
    user-authored body."""

    def _client(self, vault):
        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        return TestClient(server.app, headers=_AUTH)

    def _seed(self, vault, project="Botany"):
        import project_registry
        vault.mkdir(parents=True, exist_ok=True)
        project_registry.save(vault, {"schema": 1, "projects": {project: {"description": "d"}}})
        d = vault / project
        d.mkdir(exist_ok=True)
        return d

    def test_delete_removes_the_entry_only_and_leaves_the_move_pending(self):
        """FR-23 Option A: delete no longer auto-tidies the filesystem. The note is
        dangling (reads as loose) immediately, but the physical move is a separate,
        confirmable step -- GET /vault/tidy/preview then POST /vault/tidy/apply."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            d = self._seed(vault)
            note = d / "n.md"
            note.write_text("---\ncreated: x\n---\n\nbody\n\ntags: #project@Botany\n", encoding="utf-8")
            before = note.read_bytes()

            client = self._client(vault)
            r = client.delete("/vault/projects/Botany")
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("went_loose", r.json())

            # Nothing has moved yet -- the delete is registry-only.
            self.assertTrue(note.exists(), "delete must not move a file on its own")
            self.assertEqual(note.read_bytes(), before, "delete must not edit a single byte")

            preview = client.get("/vault/tidy/preview").json()
            self.assertEqual(preview["count"], 1)
            self.assertEqual(preview["moves"], [{"from": "Botany/n.md", "to": "_loose/n.md"}])

            applied = client.post("/vault/tidy/apply").json()
            self.assertEqual(applied["moved"], 1)

            moved = vault / "_loose" / "n.md"
            self.assertTrue(moved.exists(), "a dangling note must go loose, never be deleted")
            self.assertEqual(moved.read_bytes(), before, "tidy must not edit a single byte")
            self.assertFalse(d.exists(), "the emptied project directory is removed by the tidy pass")

            # Declining (never calling apply) is a legitimate end state: re-previewing
            # afterwards should show nothing pending.
            self.assertEqual(client.get("/vault/tidy/preview").json()["count"], 0)

    def test_rename_retags_machine_bodies_and_only_offers_user_notes(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            d = self._seed(vault)
            capture = d / "cap.md"
            capture.write_text("---\ncreated: x\n---\n\ncap\n\ntags: #project@Botany\n", encoding="utf-8")
            user_note = d / "mine.md"
            user_note.write_text("---\norigin: note\nid: 01N\n---\n\nMy own words #project@Botany\n",
                                 encoding="utf-8")
            user_before = user_note.read_bytes()

            client = self._client(vault)
            r = client.patch("/vault/projects/Botany", json={"new_name": "Plants"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["retagged"], 1)
            self.assertEqual(body["offered"], ["Botany/mine.md"])

            import project_registry
            entry = project_registry.load(vault)["projects"]["Plants"]
            self.assertEqual(entry["renamed_from"], "Botany")

            # FR-23 Option A: rename retags bodies immediately (that's a body edit the
            # provenance gate already governs, unrelated to project-tidy) but no longer
            # auto-moves files -- both notes are still sitting in the OLD directory
            # until the pending tidy is previewed and explicitly applied.
            self.assertTrue((vault / "Botany" / "cap.md").exists(), "no auto-move on rename")
            self.assertFalse((vault / "Plants" / "cap.md").exists())

            preview = client.get("/vault/tidy/preview").json()
            self.assertEqual(preview["count"], 2, "both notes resolve into Plants via renamed_from")
            client.post("/vault/tidy/apply")

            # The machine-authored capture followed the rename.
            self.assertTrue((vault / "Plants" / "cap.md").exists())
            # The user-authored note is byte-identical and still resolves, via renamed_from.
            still = vault / "Plants" / "mine.md"
            self.assertTrue(still.exists())
            self.assertEqual(still.read_bytes(), user_before,
                             "a user-authored body must never be rewritten unprompted")

    def test_create_rejects_an_ineligible_name_and_a_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            self._seed(vault)
            client = self._client(vault)
            self.assertEqual(client.post("/vault/projects", json={"name": "a/b"}).status_code, 400)
            self.assertEqual(
                client.post("/vault/projects", json={"name": "Botany", "description": "x"}).status_code, 409)

    def test_description_patch_round_trips_and_404s(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            self._seed(vault)
            client = self._client(vault)
            r = client.patch("/vault/projects/Botany/description", json={"description": "  Plants.  "})
            self.assertEqual(r.json()["description"], "Plants.")
            self.assertEqual(client.patch("/vault/projects/Nope/description",
                                          json={"description": "x"}).status_code, 404)


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
    return TestClient(server.app, headers=_AUTH), server


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


def test_drive_auth_connect_502_does_not_leak_the_raw_exception_text(capsys):
    """FR-19: the raw OAuth exception must not be interpolated into the client
    response -- it goes to the server-side log only."""
    client, _ = _drive_client()
    secret_looking_detail = "invalid_grant: refresh token abc123SECRET revoked"
    with patch("drive_auth.client_secret_present", return_value=True), \
         patch("drive_auth.load_credentials", side_effect=RuntimeError(secret_looking_detail)):
        r = client.post("/drive/auth/connect")
    assert r.status_code == 502
    assert secret_looking_detail not in r.json()["detail"]
    assert secret_looking_detail in capsys.readouterr().out, "detail should still be logged server-side"


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
    return TestClient(server.app, headers=_AUTH), sch


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


def test_sniff_audio_suffix_webm():
    """GUI recorder.ts records audio/webm;codecs=opus -- magic bytes 1a 45 df a3."""
    assert server._sniff_audio_suffix(b"\x1a\x45\xdf\xa3\x00\x00rest") == ".webm"


def test_sniff_audio_suffix_wav():
    assert server._sniff_audio_suffix(b"RIFF\x24\x00\x00\x00WAVEfmt ") == ".wav"


def test_sniff_audio_suffix_unknown_defaults_to_wav():
    assert server._sniff_audio_suffix(b"not a real audio header") == ".wav"


def test_attach_to_capture_origin_note_returns_clean_400_not_raw_exception():
    """FR-10: a capture-origin .md has no frontmatter `id`, so note_editor.add_attachment
    raises ValueError at note_editor.py:301-302. POST /note/attachment must turn that into
    a clean, client-presentable 4xx (existing except ValueError -> HTTPException(400, ...)
    at server.py:1934-1935) -- never let the raw exception reach the client."""
    import base64
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        cat = vault / "Tech_Notes"
        cat.mkdir()
        note = cat / "capture1.md"
        note.write_text("---\ncategory: Tech_Notes\n---\nSome capture body\n", encoding="utf-8")
        with mock.patch.object(server, "_get_vault_root", lambda: vault):
            client = TestClient(server.app, headers=_AUTH)
            r = client.post("/note/attachment", json={
                "path": "Tech_Notes/capture1.md",
                "filename": "x.png",
                "data_b64": base64.b64encode(b"hi").decode(),
                "expected_mtime": note.stat().st_mtime,
            })
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "Traceback" not in detail
        assert "id" in detail.lower()


# ============================================================================
# P2a-8: wire retry_pending into startup / post-capture / manual route
# ============================================================================
def test_retry_inbox_route_runs_a_bounded_pass(tmp_path: Path):
    cfg = Config()
    cfg.vault.root = tmp_path
    cfg.vault.scratchpad_folder = "_scratchpad"

    with mock.patch("server._get_vault_root", return_value=tmp_path), \
         mock.patch("retry_engine.retry_pending", return_value={"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}) as m:
        client = TestClient(server.app, headers=_AUTH)
        resp = client.post("/inbox/retry")

    assert resp.status_code == 200
    assert resp.json() == {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}
    m.assert_called_once()


def test_successful_capture_triggers_a_retry_pass():
    """After ANY successful capture, server.py must run a bounded retry pass over
    needs_llm_retry placeholders -- one of P2a's three triggers."""
    cfg = Config()
    cfg.vault.root = Path(tempfile.mkdtemp())
    cfg.vault.scratchpad_folder = "_scratchpad"
    cfg.vector.enabled = False
    cfg.notifications.enabled = False

    good_output = CaptureOutput(
        category="Notes", suggested_filename="ok", markdown_content="body",
        rationale="ok", key_signals=[], confidence=0.9, requires_new_category=False,
    )

    class _FakeQueue:
        def put_nowait(self, item): pass

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *args): fn(*args)

    import config as config_module
    import storage_engine as storage_engine_module

    def _fake_write(output, **kwargs):
        note_path = Path(cfg.vault.root, "Notes", "ok.md")
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("body", encoding="utf-8")
        return note_path

    with mock.patch.object(config_module, "reload_config", lambda *a, **k: cfg), \
         mock.patch.object(llm_engine, "run_llm_engine", return_value=good_output), \
         mock.patch.object(storage_engine_module, "write_to_vault", side_effect=_fake_write), \
         mock.patch("retry_engine.retry_pending") as m:
        server._run_pipeline_blocking("text", "some capture text", _FakeQueue(), _FakeLoop(), run_id="rp1")

    m.assert_called_once()


# ============================================================================
# Shell rework Task 1: POST /note -- generic desktop note origination.
# Must reuse create_daily_note's write path and emit the identical frontmatter key set
# (contract owned by Second Thought - Android App/data-model-and-contracts.md).
# ============================================================================
def _note_client(vault: Path):
    cfg = Config()
    cfg.vault.root = vault
    client = TestClient(server.app, headers=_AUTH)
    return client, cfg


def _read_frontmatter_keys(path: Path) -> set:
    """Raw frontmatter key set as written to disk. Unlike note_model.parse_note's `Note` (whose
    dataclass fields all exist regardless of what was actually serialized), this reflects exactly
    what landed between the `---` fences."""
    text = path.read_text(encoding="utf-8", newline="")
    fm = text.split("---", 2)[1]
    keys = set()
    for line in fm.splitlines():
        if line and not line[0].isspace() and ":" in line:
            keys.add(line.split(":", 1)[0])
    return keys


def test_post_note_creates_note_with_daily_note_frontmatter_shape(tmp_path: Path):
    """POST /note must emit the SAME frontmatter keys as POST /today/daily-note.
    A second origination path with a different shape is a contract fork."""
    client, cfg = _note_client(tmp_path)
    from note_model import parse_note

    with mock.patch("config.get_config", lambda: cfg):
        daily = client.post("/today/daily-note")
        assert daily.status_code == 200, daily.text
        daily_path = Path(daily.json()["path"])
        daily_keys = _read_frontmatter_keys(daily_path)

        made = client.post("/note", json={"title": "scratch thought"})
        assert made.status_code == 200, made.text
        note_path = Path(made.json()["path"])
        assert note_path.exists()

    assert _read_frontmatter_keys(note_path) == daily_keys
    assert parse_note(note_path.read_text(encoding="utf-8", newline="")).origin == "note"
    # generic notes do NOT go in Daily/
    assert note_path.parent != daily_path.parent


def test_post_note_lands_where_project_tidy_can_actually_see_it(tmp_path: Path):
    """FR-29: /note used to write straight into the vault ROOT, and `_filed_notes` checks
    `entry.is_dir()` before it ever looks at a file -- so a brand-new note was structurally
    invisible to project-tidy and could never be re-filed once the user tagged it. Pin BOTH
    halves: the note lands in `_loose/`, and the tidy scan genuinely yields it."""
    from projects import LOOSE_DIR
    from vault_admin import _filed_notes

    client, cfg = _note_client(tmp_path)
    with mock.patch("config.get_config", lambda: cfg):
        made = client.post("/note", json={"title": "findable"})
        assert made.status_code == 200, made.text
        note_path = Path(made.json()["path"])

    root = Path(cfg.vault.root)
    assert note_path.parent.name == LOOSE_DIR
    assert note_path.parent != root          # the regression itself: never bare in the root
    assert note_path in set(_filed_notes(root))


def test_post_note_twice_creates_two_distinct_notes(tmp_path: Path):
    """Unlike the daily note, /note is not find-or-create. Two calls, two files."""
    client, cfg = _note_client(tmp_path)
    with mock.patch("config.get_config", lambda: cfg):
        a = client.post("/note", json={"title": "one"}).json()["path"]
        b = client.post("/note", json={"title": "one"}).json()["path"]
    assert a != b
    assert Path(a).exists() and Path(b).exists()
