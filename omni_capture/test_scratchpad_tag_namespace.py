"""
test_scratchpad_tag_namespace.py — ISS-019 regression: the machine-written
failure placeholders from route_failed_vision/route_failed_llm must land in
the note's `tags` frontmatter under the `sys/` namespace, not as bare
`vision-failed`/`llm-failed` content tags (which the Tags browser filters
out wholesale -- see gui/src/components/FullWindow/TagsView.tsx).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scratchpad import route_failed_vision, route_failed_llm


def _tags_block(text: str) -> str:
    start = text.index("tags:")
    end = text.index("---", start)
    return text[start:end]


def test_route_failed_vision_writes_namespaced_tag(tmp_path: Path):
    path = route_failed_vision(
        {"vision_failure_reason": "vision model unavailable"},
        vault_root=tmp_path,
        scratchpad_folder="_scratchpad",
    )
    tags = _tags_block(path.read_text(encoding="utf-8"))
    assert "sys/vision-failed" in tags
    assert "- vision-failed\n" not in tags  # never the bare, unnamespaced form


def test_route_failed_llm_writes_namespaced_tag(tmp_path: Path):
    path = route_failed_llm(
        "raw captured text",
        "Ollama connection refused",
        vault_root=tmp_path,
        scratchpad_folder="_scratchpad",
    )
    tags = _tags_block(path.read_text(encoding="utf-8"))
    assert "sys/llm-failed" in tags
    assert "- llm-failed\n" not in tags


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
