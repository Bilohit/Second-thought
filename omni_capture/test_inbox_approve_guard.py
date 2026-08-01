"""
test_inbox_approve_guard.py — s114 / flow-review d07.

Two things pinned here, both P0-adjacent:

1. **The dead loop.** Approving a scratchpad item INTO the scratchpad used to
   "succeed": it stripped `status: needs_review` and `note_id`, renamed the
   file, and left it in the review folder -- so `list_scratchpad` (which lists
   the FOLDER, not the status) surfaced it again forever while the GUI showed a
   success transition.

   Projects S1 (Task 13) makes that STRUCTURALLY unreachable rather than guarded:
   the destination is now `note_dir_for(resolve_project(...))`, which can only ever
   be a registry-eligible project name or `_loose`. Every reserved `_`-prefixed hub
   folder -- `_scratchpad` included -- fails the name rule, so it can never be a
   destination at all. The tests below pin the replacement invariant: a scratchpad
   folder name offered as a target lands the note in `_loose/`, never back where it
   came from, and the approve still succeeds (there is no "no valid destination"
   failure any more).

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
        suggested_filename="mystery-thing",
        markdown_content=body,
        key_signals=["unknown"],
        confidence=0.4,
        requires_new_category=False,
    )
    route_to_scratchpad(out, source_url, vault, scratchpad_folder=SP, body_content=body)
    return list_scratchpad(vault, SP)[0]["note_id"]


# -- 1. the dead-loop guard --------------------------------------------------


def test_approving_into_the_scratchpad_lands_loose_instead(tmp_path: Path):
    """The scratchpad folder is not a registry-eligible name, so it cannot be a
    destination. The note goes loose -- out of the review folder either way."""
    note_id = _route(tmp_path)
    dest = approve_scratchpad_item(note_id, tmp_path, SP, target_project=SP)
    assert dest.parent.name == "_loose"
    assert list_scratchpad(tmp_path, SP) == []


def test_an_approved_item_is_never_left_reviewable(tmp_path: Path):
    """The whole point: an approve must not half-apply and strand the file back in
    the review folder. The item leaves the scratchpad and loses both review markers."""
    note_id = _route(tmp_path)
    dest = approve_scratchpad_item(note_id, tmp_path, SP, target_project=SP)

    assert list_scratchpad(tmp_path, SP) == []
    text = dest.read_text(encoding="utf-8")
    assert "status: needs_review" not in text
    assert f"note_id: {note_id}" not in text


def test_a_registered_project_still_approves(tmp_path: Path):
    import project_registry
    project_registry.save(tmp_path, {"schema": 1, "projects": {"Tech": {"description": ""}}})
    note_id = _route(tmp_path)
    dest = approve_scratchpad_item(note_id, tmp_path, SP, target_project="Tech")
    assert dest.parent.name == "Tech"
    assert "needs_review" not in dest.read_text(encoding="utf-8")
    assert list_scratchpad(tmp_path, SP) == []


def test_an_unregistered_project_goes_loose_and_is_still_a_success(tmp_path: Path):
    """A dangling name reads as loose (contract §1.3) -- never an error, never a
    note left stranded in the inbox."""
    note_id = _route(tmp_path)
    dest = approve_scratchpad_item(note_id, tmp_path, SP, target_project="NotRegistered")
    assert dest.parent.name == "_loose"
    assert list_scratchpad(tmp_path, SP) == []


def test_a_renamed_scratchpad_folder_is_equally_unreachable(tmp_path: Path):
    """The folder name is config-driven, but the rule is on the NAME, not on a
    comparison against the literal "_scratchpad"."""
    out = CaptureOutput(
        suggested_filename="x", markdown_content="body",
        key_signals=["unknown"], confidence=0.4, requires_new_category=False,
    )
    route_to_scratchpad(out, None, tmp_path, scratchpad_folder="_review", body_content="body")
    note_id = list_scratchpad(tmp_path, "_review")[0]["note_id"]
    dest = approve_scratchpad_item(note_id, tmp_path, "_review", target_project="_review")
    assert dest.parent.name == "_loose"


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
    assert item["project"] == SP
    assert item["filename"].endswith(".md")
