from pathlib import Path
import tempfile
from config import reload_config


def test_capture_defaults_match_legacy_behavior():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text('[vault]\nroot = "' + tmp.replace("\\", "/") + '"\n', encoding="utf-8")
        cfg = reload_config(cfg_path)
        assert cfg.capture.confidence_threshold == 0.6
        assert cfg.capture.llm_scrutiny == "balanced"
        assert cfg.capture.ocr_fast_path_enabled is True
        assert cfg.capture.ocr_text_min_chars == 10


def test_capture_overrides_from_toml():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text(
            "[capture]\n"
            "confidence_threshold = 0.8\n"
            'llm_scrutiny = "strict"\n'
            "ocr_fast_path_enabled = false\n"
            "ocr_text_min_chars = 120\n",
            encoding="utf-8",
        )
        cfg = reload_config(cfg_path)
        assert cfg.capture.confidence_threshold == 0.8
        assert cfg.capture.llm_scrutiny == "strict"
        assert cfg.capture.ocr_fast_path_enabled is False
        assert cfg.capture.ocr_text_min_chars == 120


def test_invalid_scrutiny_falls_back_to_balanced():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.toml"
        cfg_path.write_text('[capture]\nllm_scrutiny = "aggressive"\n', encoding="utf-8")
        cfg = reload_config(cfg_path)
        assert cfg.capture.llm_scrutiny == "balanced"
