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
