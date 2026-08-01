from pathlib import Path

import project_tidy as pt
from project_registry import SCHEMA


def _reg(*names):
    return {"schema": SCHEMA,
            "projects": {n: {"description": "", "created": "", "modified": "", "device": ""}
                         for n in names}}


VAULT = Path("/vault")


def test_a_tagged_note_in_the_wrong_folder_moves_to_its_project():
    entries = [pt.NoteLoc(VAULT / "_loose" / "a.md", "body #project@research")]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert moves == [pt.Move(VAULT / "_loose" / "a.md", VAULT / "research" / "a.md")]


def test_a_note_already_in_place_does_not_move():
    entries = [pt.NoteLoc(VAULT / "research" / "a.md", "body #project@research")]
    assert pt.plan_tidy(entries, VAULT, _reg("research")) == []


def test_an_untagged_note_moves_to_loose_not_to_the_vault_root():
    # Depth 1 is the invariant that keeps `../_attachments/<id>/<file>` body refs valid across
    # every move without rewriting a sacred body (contract §1.3).
    entries = [pt.NoteLoc(VAULT / "research" / "a.md", "no tag")]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert moves == [pt.Move(VAULT / "research" / "a.md", VAULT / "_loose" / "a.md")]


def test_a_dangling_tag_is_treated_as_loose():
    entries = [pt.NoteLoc(VAULT / "gone" / "a.md", "#project@gone")]
    moves = pt.plan_tidy(entries, VAULT, _reg())
    assert moves == [pt.Move(VAULT / "gone" / "a.md", VAULT / "_loose" / "a.md")]


def test_every_planned_destination_is_at_depth_one():
    entries = [
        pt.NoteLoc(VAULT / "_loose" / "a.md", "#project@research"),
        pt.NoteLoc(VAULT / "research" / "b.md", "no tag"),
    ]
    for move in pt.plan_tidy(entries, VAULT, _reg("research")):
        assert move.dst.relative_to(VAULT).parts[:-1] == (move.dst.parent.name,)


def test_a_name_collision_at_the_destination_is_planned_with_a_suffixed_filename():
    entries = [
        pt.NoteLoc(VAULT / "_loose" / "a.md", "#project@research"),
        pt.NoteLoc(VAULT / "research" / "a.md", "#project@research"),
    ]
    moves = pt.plan_tidy(entries, VAULT, _reg("research"))
    assert len(moves) == 1
    assert moves[0].dst != VAULT / "research" / "a.md"
    assert moves[0].dst.parent == VAULT / "research"
