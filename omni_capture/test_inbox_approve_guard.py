"""
test_inbox_approve_guard.py — s114 / flow-review d07.

Two things pinned here, both P0-adjacent:

1. **The dead loop.** Approving a scratchpad item INTO the scratchpad used to
   "succeed": it stripped `status: needs_review` and `note_id`, renamed the
   file, and left it in the review folder -- so `list_scratchpad` (which lists
   the FOLDER, not the status) surfaced it again forever while the GUI showed a
   success transition. The guard lives in `approve_scratchpad_item`, the one
   join every caller reaches, not in the HTTP route.

2. **What the Inbox row leads with.** `describe_capture` derives kind/source/
   failure from frontmatter and body that already exist, so the review row can
   say "link · en.wikipedia.org" or "image · vision model unavailable" instead
   of a generated filename that tells the user nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from models import CaptureOutput
from scratchpad import (
    approve_scratchpad_item,
    describe_capture,
    list_scratchpad,
    route_failed_llm,
    route_failed_vision,
    route_to_scratchpad,
)

SP = "_scratchpad"


def _route(vault: Path, *, body: str = "some captured text", source_url=None) -> str:
    out = CaptureOutput(
        category="Tech_Notes",
        suggested_filename="mystery-thing",
        markdown_content=body,
        key_signals=["unknown"],
        confidence=0.4,
        requires_new_category=False,
    )
    route_to_scratchpad(out, source_url, vault, scratchpad_folder=SP, body_content=body)
    return list_scratchpad(vault, SP)[0]["note_id"]


# -- 1. the dead-loop guard --------------------------------------------------


def test_approving_into_the_scratchpad_is_rejected(tmp_path: Path):
    note_id = _route(tmp_path)
    with pytest.raises(ValueError, match="review folder"):
        approve_scratchpad_item(note_id, tmp_path, SP, target_category=SP)


def test_rejected_approve_leaves_the_item_reviewable(tmp_path: Path):
    """The whole point: a rejected approve must not half-apply. The item keeps
    its needs_review status and its note_id, so it is still approvable for
    real -- the old code stripped both and stranded the file."""
    note_id = _route(tmp_path)
    with pytest.raises(ValueError):
        approve_scratchpad_item(note_id, tmp_path, SP, target_category=SP)

    items = list_scratchpad(tmp_path, SP)
    assert len(items) == 1
    assert items[0]["note_id"] == note_id
    text = Path(items[0]["path"]).read_text(encoding="utf-8")
    assert "status: needs_review" in text
    assert f"note_id: {note_id}" in text


def test_a_real_category_still_approves(tmp_path: Path):
    note_id = _route(tmp_path)
    dest = approve_scratchpad_item(note_id, tmp_path, SP, target_category="Tech_Notes")
    assert dest.parent.name == "Tech_Notes"
    assert "needs_review" not in dest.read_text(encoding="utf-8")
    assert list_scratchpad(tmp_path, SP) == []


def test_guard_honours_a_renamed_scratchpad_folder(tmp_path: Path):
    """The folder name is config-driven; the guard compares resolved paths, not
    the literal string "_scratchpad"."""
    out = CaptureOutput(
        category="Tech_Notes", suggested_filename="x", markdown_content="body",
        key_signals=["unknown"], confidence=0.4, requires_new_category=False,
    )
    route_to_scratchpad(out, None, tmp_path, scratchpad_folder="_review", body_content="body")
    note_id = list_scratchpad(tmp_path, "_review")[0]["note_id"]
    with pytest.raises(ValueError, match="review folder"):
        approve_scratchpad_item(note_id, tmp_path, "_review", target_category="_review")


# -- 2. what the row leads with ----------------------------------------------


def test_describe_plain_text_capture():
    d = describe_capture("---\ncreated: x\n---\njust some text\n")
    assert d == {"kind": "text", "source": None, "failure": None}


def test_describe_link_capture_reports_the_host():
    d = describe_capture(
        "---\ncreated: x\nsource: https://www.en.wikipedia.org/wiki/Cross-device_sync\n---\nbody\n"
    )
    assert d["kind"] == "link"
    assert d["source"] == "en.wikipedia.org"   # scheme, www. and path all dropped


def test_describe_image_capture_from_the_body_embed():
    d = describe_capture("---\ncreated: x\n---\n![[img-abcd1234.png]]\n")
    assert d["kind"] == "image"
    assert d["failure"] is None


def test_describe_voice_capture_from_a_transcript_heading():
    d = describe_capture("---\ncreated: x\n---\nsummary\n\n## Transcript\nhello\n")
    assert d["kind"] == "voice"


def test_vision_failure_is_reported_as_a_failure(tmp_path: Path):
    path = route_failed_vision(
        {"vision_failure_reason": "vision model unavailable"},
        vault_root=tmp_path, scratchpad_folder=SP,
    )
    d = describe_capture(path.read_text(encoding="utf-8"))
    assert d["kind"] == "image"
    assert d["failure"] == "vision model unavailable"


def test_llm_failure_is_reported_as_a_failure(tmp_path: Path):
    path = route_failed_llm(
        "raw text", "Ollama connection refused", vault_root=tmp_path, scratchpad_folder=SP,
    )
    d = describe_capture(path.read_text(encoding="utf-8"))
    assert d["failure"] == "enrichment unavailable"


def test_list_scratchpad_carries_the_description(tmp_path: Path):
    _route(tmp_path, source_url="https://example.com/a/b")
    item = list_scratchpad(tmp_path, SP)[0]
    assert item["kind"] == "link"
    assert item["source"] == "example.com"
    assert item["failure"] is None
    # the pre-existing contract is untouched
    assert item["category"] == SP
    assert item["filename"].endswith(".md")
