"""run_pipeline's image file-path entry (D3 CP2 photo intake)."""
from unittest.mock import patch
from pathlib import Path

import main


def test_run_pipeline_image_builds_image_bytes_payload(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff_fake_jpeg")

    captured = {}

    def _fake_route(payload):
        captured["input_type"] = payload.input_type
        captured["image_bytes"] = payload.image_bytes
        raise SystemExit("stop after Stage 1/2")   # we only assert the payload shaping

    with patch("enrichment_router.route_and_enrich", side_effect=_fake_route):
        try:
            main.run_pipeline(image=str(img), dry_run=True)
        except SystemExit:
            pass

    assert captured["input_type"] == "image_bytes"
    assert captured["image_bytes"] == b"\xff\xd8\xff_fake_jpeg"
