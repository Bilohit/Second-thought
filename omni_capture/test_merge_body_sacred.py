"""
test_merge_body_sacred.py — §3.4: the B-1 guard that stops a capture being
appended into a synced note's body.

Cold-spot finding: across the whole desktop suite, `merge._is_synced_note`
never once returned True (merge.py:94 and merge.py:96 — both `return True`
arms — were unexecuted), and `_is_same_topic` was entirely unexecuted. The
guard is load-bearing at two sites:

  - merge.py:150        — excludes synced notes from find_merge_target's
                          candidate list.
  - storage_engine.py:1038 — `_is_same_topic(base_path, ...)` before an append.

Both implement the workspace lock "a note's body is sacred": appending capture
text below a note's frontmatter is a body-sacred violation, and the next sync
pass would read those appended bytes as a local body edit (spuriously winning
a body-vs-body conflict against the phone). Tests below pin the guard's
positive cases, and each merge-exclusion test is paired with a control proving
the merge WOULD have happened without the guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from merge import _is_same_topic, _is_synced_note, _read_note_tags, find_merge_target
from models import CaptureOutput

_CAPTURE_TAGS = "---\ntags: [docker, networking]\n---\n# Cap\n\nbody\n"


def _out(signals, category="Tech_Notes", filename="new-note", content="new content"):
    return CaptureOutput(
        category=category,
        suggested_filename=filename,
        markdown_content=content,
        key_signals=signals,
        confidence=0.9,
        requires_new_category=False,
    )


# -- _is_synced_note: the two positive arms (merge.py:94 / merge.py:96) -----


def test_origin_note_is_a_synced_note(tmp_path):
    """`origin: note` is the phone/desktop note marker — body is sacred."""
    p = tmp_path / "note.md"
    p.write_text("---\norigin: note\ntags: [docker]\n---\n# N\n\nbody\n", encoding="utf-8")
    assert _is_synced_note(p) is True


def test_frontmatter_id_marks_a_synced_note(tmp_path):
    """A note carrying an `id:` came from the hub — also body-sacred, even
    without `origin: note` (older/phone-written notes)."""
    p = tmp_path / "note.md"
    p.write_text("---\nid: 01ABCDEF\ntags: [docker]\n---\n# N\n\nbody\n", encoding="utf-8")
    assert _is_synced_note(p) is True


def test_plain_capture_is_not_a_synced_note(tmp_path):
    """A pipeline capture has neither marker — it stays a legal merge target,
    or the guard would disable smart-merge entirely."""
    p = tmp_path / "cap.md"
    p.write_text(_CAPTURE_TAGS, encoding="utf-8")
    assert _is_synced_note(p) is False


def test_id_without_frontmatter_block_still_counts_as_synced(tmp_path):
    """No `---` block: the guard falls back to scanning the head of the file.
    It must stay conservative — protecting a body it is unsure about is the
    safe direction, appending into it is not."""
    p = tmp_path / "weird.md"
    p.write_text("id: 01ABCDEF\ntags: [docker]\n\nbody\n", encoding="utf-8")
    assert _is_synced_note(p) is True


def test_unreadable_file_is_not_synced_but_also_never_crashes(tmp_path):
    """An unreadable candidate must not blow up the whole capture write. It
    returns False (find_merge_target then judges it on tags, and a directory
    has none), never an exception."""
    d = tmp_path / "adir.md"
    d.mkdir()
    assert _is_synced_note(d) is False


# -- B-1 at merge.py:150 — find_merge_target must exclude synced notes ------


def test_find_merge_target_excludes_a_synced_note_despite_strong_tag_match(tmp_path):
    """The core B-1 case: a phone note filed under a category folder shares
    tags with a same-topic capture. Merging would append capture text into the
    note's sacred body. Must return None (write a new file instead)."""
    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    note = cat / "docker-notes.md"
    note.write_text(
        "---\norigin: note\nid: 01NOTE\ntags: [docker, networking]\n---\n"
        "# Docker notes\n\nMy own words.\n",
        encoding="utf-8",
    )
    before = note.read_bytes()

    target = find_merge_target(_out(["docker", "networking"]), tmp_path)

    assert target is None, "capture selected a synced note as a merge target (B-1 violation)"
    assert note.read_bytes() == before, "note body must be untouched by target selection"


def test_find_merge_target_control_same_tags_on_a_capture_does_merge(tmp_path):
    """Control for the test above: identical tag overlap on a plain capture
    DOES resolve to a merge target. Without this, the B-1 test could pass for
    the wrong reason (e.g. thresholds never met)."""
    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    cap = cat / "docker-capture.md"
    cap.write_text(_CAPTURE_TAGS, encoding="utf-8")

    target = find_merge_target(_out(["docker", "networking"]), tmp_path)

    assert target == cap


def test_find_merge_target_picks_the_capture_and_skips_the_note(tmp_path):
    """Mixed folder: both files match on tags. The capture must win and the
    synced note must never even be a candidate."""
    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    note = cat / "docker-notes.md"
    note.write_text(
        "---\norigin: note\ntags: [docker, networking]\n---\n# N\n\nsacred\n", encoding="utf-8"
    )
    cap = cat / "docker-capture.md"
    cap.write_text(_CAPTURE_TAGS, encoding="utf-8")

    assert find_merge_target(_out(["docker", "networking"]), tmp_path) == cap


# -- B-1 at storage_engine.py:1038 — _is_same_topic ------------------------


def test_is_same_topic_refuses_a_synced_note(tmp_path):
    """`_is_same_topic` gates the append in storage_engine. A synced note is
    never "same topic" for merge purposes, however well the tags line up."""
    p = tmp_path / "note.md"
    p.write_text(
        "---\norigin: note\ntags: [docker, networking]\n---\n# N\n\nbody\n", encoding="utf-8"
    )
    assert _is_same_topic(p, ["docker", "networking"]) is False


def test_is_same_topic_allows_a_capture_with_shared_tags(tmp_path):
    """Control: same tags on a capture is same-topic."""
    p = tmp_path / "cap.md"
    p.write_text(_CAPTURE_TAGS, encoding="utf-8")
    assert _is_same_topic(p, ["docker", "networking"]) is True


def test_is_same_topic_is_permissive_when_it_has_no_signal(tmp_path):
    """No new signals, or an untagged existing file, means there is nothing to
    disagree on — the caller's own filename/dedup decision stands."""
    p = tmp_path / "cap.md"
    p.write_text(_CAPTURE_TAGS, encoding="utf-8")
    assert _is_same_topic(p, []) is True

    untagged = tmp_path / "untagged.md"
    untagged.write_text("---\ntitle: X\n---\n# X\n\nbody\n", encoding="utf-8")
    assert _is_same_topic(untagged, ["docker"]) is True

    assert _is_same_topic(tmp_path / "ghost.md", ["docker"]) is True


def test_is_same_topic_honours_a_raised_min_shared_tags(tmp_path):
    """Image captures raise the bar to 2: a vision description sharing exactly
    one tag with an unrelated note is too weak to silently append a photo."""
    p = tmp_path / "cap.md"
    p.write_text(_CAPTURE_TAGS, encoding="utf-8")
    assert _is_same_topic(p, ["docker", "kubernetes"], min_shared_tags=1) is True
    assert _is_same_topic(p, ["docker", "kubernetes"], min_shared_tags=2) is False


# -- semantic merge is fail-soft (merge.py:157-167) -------------------------
#
# CLAUDE.md: "Vision failure is fail-fast, every other enrichment path is
# fail-soft." The embedding call here is an enrichment — if Ollama is down it
# must degrade to tag-only matching, never fail the capture write.


def test_semantic_merge_failure_degrades_to_tag_matching(tmp_path, monkeypatch):
    """Embedding endpoint down: find_merge_target must swallow it and fall
    back to tags, not propagate the exception into the capture write."""
    import vector_store

    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    cap = cat / "docker-capture.md"
    cap.write_text(_CAPTURE_TAGS, encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(vector_store, "best_match", boom)

    # Strong tag overlap still resolves, despite the embedding call blowing up.
    target = find_merge_target(
        _out(["docker", "networking"]), tmp_path,
        enable_semantic_merge=True, embed_base_url="http://localhost:11434",
    )
    assert target == cap


def test_semantic_confirmation_can_merge_on_a_single_shared_tag(tmp_path, monkeypatch):
    """One shared tag is below the tag-only bar (needs 2 + jaccard 0.5), but a
    high embedding similarity is independent evidence of the same topic and
    may confirm the merge on its own."""
    import vector_store

    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    cap = cat / "docker-capture.md"
    cap.write_text(_CAPTURE_TAGS, encoding="utf-8")

    # Tag-only: shared={docker}, jaccard=1/3 -> would NOT merge.
    assert find_merge_target(_out(["docker", "kubernetes"]), tmp_path) is None

    monkeypatch.setattr(
        vector_store, "best_match", lambda *a, **kw: ("Tech_Notes/docker-capture.md", 0.92)
    )
    target = find_merge_target(
        _out(["docker", "kubernetes"]), tmp_path,
        enable_semantic_merge=True, embed_base_url="http://localhost:11434",
    )
    assert target == cap


def test_semantic_confirmation_never_overrides_the_body_sacred_guard(tmp_path, monkeypatch):
    """B-1 outranks semantic evidence: a synced note is excluded from the
    candidate list before scoring, so even a perfect embedding match must not
    select it."""
    import vector_store

    cat = tmp_path / "Tech_Notes"
    cat.mkdir()
    note = cat / "docker-notes.md"
    note.write_text(
        "---\norigin: note\ntags: [docker, networking]\n---\n# N\n\nsacred\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        vector_store, "best_match", lambda *a, **kw: ("Tech_Notes/docker-notes.md", 1.0)
    )
    target = find_merge_target(
        _out(["docker", "networking"]), tmp_path,
        enable_semantic_merge=True, embed_base_url="http://localhost:11434",
    )
    assert target is None, "semantic match selected a synced note (B-1 violation)"


# -- _read_note_tags block form --------------------------------------------


def test_read_note_tags_parses_block_form(tmp_path):
    """YAML block-list tags must be read too — a note written in block form
    would otherwise look untagged and slip past the tag-overlap checks."""
    p = tmp_path / "block.md"
    p.write_text("---\ntags:\n  - Docker\n  - Networking\n---\n# B\n\nbody\n", encoding="utf-8")
    assert {"docker", "networking"} <= _read_note_tags(p)


def test_read_note_tags_on_unreadable_path_is_empty(tmp_path):
    """Never raises into the capture write path."""
    assert _read_note_tags(tmp_path / "missing.md") == set()
