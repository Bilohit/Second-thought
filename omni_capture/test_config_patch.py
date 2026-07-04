import importlib
import tempfile
from pathlib import Path
import unittest.mock as mock


def _client(tmp_config: Path):
    import server
    importlib.reload(server)
    server.CONFIG_PATH = tmp_config
    from fastapi.testclient import TestClient
    return TestClient(server.app), server


def test_patch_writes_capture_keys_under_capture_section():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client(cfg)
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
        client, server = _client(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"llm_scrutiny": "aggressive"})
        assert r.status_code == 400


def test_patch_rejects_confidence_threshold_below_zero():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"confidence_threshold": -1.0})
        assert r.status_code == 400


def test_patch_rejects_confidence_threshold_above_one():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"confidence_threshold": 1.5})
        assert r.status_code == 400


def test_patch_rejects_negative_ocr_text_min_chars():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        client, server = _client(cfg)
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
        client, server = _client(cfg)
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
        client, server = _client(cfg)
        with mock.patch.object(server, "reload_config", lambda *a, **k: None):
            r = client.patch("/config", json={"reminders_delivery": "os"})
        assert r.status_code == 200

        import config
        importlib.reload(config)
        fresh = config.load_config(cfg)
        assert fresh.reminders.delivery == "os"
