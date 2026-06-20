import json
import types
import tempfile
import unittest.mock as mock

import enrichment_router as er


def _cfg(tmp, *, fast_path=True, min_chars=10, ocr_enabled=False):
    cfg = types.SimpleNamespace()
    cfg.ollama = types.SimpleNamespace(
        base_url="http://localhost:11434", vision_model="llava",
        vision_prompt="Describe.", keep_alive="30m", image_required=False,
    )
    cfg.vault = types.SimpleNamespace(root=tmp)
    cfg.ocr = types.SimpleNamespace(enabled=ocr_enabled)
    cfg.capture = types.SimpleNamespace(
        ocr_fast_path_enabled=fast_path, ocr_text_min_chars=min_chars,
    )
    return cfg


def _tags_and_gen(response_text="a screenshot"):
    tags_ok = mock.MagicMock()
    tags_ok.read.return_value = json.dumps(
        {"models": [{"name": "llava:latest", "capabilities": ["vision"]}]}).encode()
    tags_ok.__enter__ = lambda s: s
    tags_ok.__exit__ = mock.MagicMock(return_value=False)
    gen_ok = mock.MagicMock()
    gen_ok.read.return_value = json.dumps({"response": response_text}).encode()
    gen_ok.__enter__ = lambda s: s
    gen_ok.__exit__ = mock.MagicMock(return_value=False)

    def _urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        return tags_ok if "/api/tags" in url else gen_ok
    return _urlopen


def test_ocr_fastpath_skips_vision_when_text_present():
    with tempfile.TemporaryDirectory() as tmp:
        long_text = "def handler(req):\n    return 200  # plenty of characters here"
        with mock.patch("config.get_config", return_value=_cfg(tmp)), \
             mock.patch.object(er, "_downscale_image", side_effect=lambda b, **k: b), \
             mock.patch.object(er, "_run_ocr", return_value=long_text), \
             mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("vision must NOT be called")):
            ep = er._enrich_image(b"fake-bytes")
        assert ep.input_type == "image_ocr"
        assert ep.enriched_text == long_text
        assert ep.source_metadata["source_type"] == "image_ocr"
        assert ep.source_metadata["transcribed_text"] == long_text
        assert "vision_available" not in ep.source_metadata  # never reached vision
        assert "image_embed" in ep.source_metadata           # image still persisted


def test_ocr_below_threshold_falls_back_to_vision():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch("config.get_config", return_value=_cfg(tmp, min_chars=80)), \
             mock.patch.object(er, "_downscale_image", side_effect=lambda b, **k: b), \
             mock.patch.object(er, "_run_ocr", return_value="hi"), \
             mock.patch("urllib.request.urlopen", side_effect=_tags_and_gen()):
            ep = er._enrich_image(b"fake-bytes")
        assert ep.input_type == "image"             # vision path
        assert ep.source_metadata["vision_available"] is True
        assert "a screenshot" in ep.enriched_text


def test_fastpath_disabled_uses_vision():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch("config.get_config", return_value=_cfg(tmp, fast_path=False)), \
             mock.patch.object(er, "_downscale_image", side_effect=lambda b, **k: b), \
             mock.patch.object(er, "_run_ocr", return_value="lots of text " * 10), \
             mock.patch("urllib.request.urlopen", side_effect=_tags_and_gen("img")):
            ep = er._enrich_image(b"fake-bytes")
        assert ep.input_type == "image"  # fast path off -> vision used despite OCR text
