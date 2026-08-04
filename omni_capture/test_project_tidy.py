import os
from pathlib import Path

import index_writer
import vector_store
import project_registry
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


def test_apply_moves_files_and_creates_the_destination_directory(tmp_path):
    src_dir = tmp_path / "_loose"
    src_dir.mkdir()
    src = src_dir / "a.md"
    src.write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")

    result = pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "research" / "a.md")])

    assert result.moved == 1
    assert (tmp_path / "research" / "a.md").exists()
    assert not src.exists()


def test_apply_never_edits_file_content(tmp_path):
    # A tidy pass MOVES files and does nothing else. Body-sacred, and sync-is-pure-transport.
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "_loose" / "a.md"
    original = "---\nid: 1\n---\n\nbody #project@research\ntrailing spaces   \n"
    src.write_bytes(original.encode("utf-8"))

    pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "research" / "a.md")])

    assert (tmp_path / "research" / "a.md").read_bytes() == original.encode("utf-8")


def test_apply_refuses_to_clobber_an_existing_destination(tmp_path):
    (tmp_path / "_loose").mkdir()
    (tmp_path / "research").mkdir()
    src = tmp_path / "_loose" / "a.md"
    dst = tmp_path / "research" / "a.md"
    src.write_text("new", encoding="utf-8")
    dst.write_text("PRECIOUS", encoding="utf-8")

    result = pt.apply_tidy(tmp_path, [pt.Move(src, dst)])

    assert result.skipped == 1
    assert dst.read_text(encoding="utf-8") == "PRECIOUS"
    assert src.exists()


def test_apply_removes_an_emptied_project_directory_but_never_loose(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "old" / "a.md"
    src.write_text("x", encoding="utf-8")

    pt.apply_tidy(tmp_path, [pt.Move(src, tmp_path / "_loose" / "a.md")])

    assert not (tmp_path / "old").exists()
    assert (tmp_path / "_loose").exists()


def test_apply_on_an_empty_move_list_is_a_no_op(tmp_path):
    assert pt.apply_tidy(tmp_path, []) == pt.TidyResult(0, 0, 0)


def test_a_blocked_move_is_skipped_and_the_pass_continues(tmp_path, monkeypatch):
    (tmp_path / "_loose").mkdir()
    (tmp_path / "research").mkdir()
    blocked_src = tmp_path / "_loose" / "a.md"
    blocked_src.write_text("blocked", encoding="utf-8")
    healthy_src = tmp_path / "_loose" / "b.md"
    healthy_src.write_text("healthy", encoding="utf-8")

    blocked_dst = tmp_path / "research" / "a.md"
    healthy_dst = tmp_path / "research" / "b.md"

    real_replace = os.replace

    def flaky_replace(src, dst, *a, **kw):
        if Path(src) == blocked_src:
            raise OSError("held open by another writer")
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(pt.os, "replace", flaky_replace)

    result = pt.apply_tidy(tmp_path, [pt.Move(blocked_src, blocked_dst), pt.Move(healthy_src, healthy_dst)])

    assert result.skipped == 1
    assert result.moved == 1
    assert blocked_src.exists()
    assert not blocked_dst.exists()
    assert healthy_dst.exists()
    assert not healthy_src.exists()


# -- FR-26: captures.db/vectors.db must not keep pointing at a note's pre-tidy path -----------

def test_apply_updates_captures_db_and_vectors_db_off_the_stale_path(tmp_path):
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "_loose" / "a.md"
    dst = tmp_path / "research" / "a.md"
    src.write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")
    # derive_project resolves the tag against the ON-DISK registry -- an unregistered name
    # reads as loose (project_registry.resolve_project's contract), so "research" must
    # actually be registered for the moved note to land in captures.db as project=research.
    project_registry.save(tmp_path, _reg("research"))

    # Seed a captures.db row at the OLD path, as if the note was indexed before this tidy pass.
    index_writer.upsert_capture_from_file(tmp_path, src)
    # Seed a stale vectors.db embedding row keyed on the OLD vault-relative path.
    conn = vector_store._get_conn(tmp_path)
    conn.execute(
        "INSERT INTO embeddings (id, embedding, document, category) VALUES (?, ?, ?, ?)",
        ("_loose/a.md::c0", b"\x00" * 4, "body #project@research", ""),
    )
    conn.commit()
    conn.close()

    result = pt.apply_tidy(tmp_path, [pt.Move(src, dst)])
    assert result.moved == 1

    db = index_writer.init_db(tmp_path)
    rows = db.execute("SELECT path, project FROM captures").fetchall()
    db.close()
    paths = {r["path"] for r in rows}
    assert str(src) not in paths
    assert str(dst) in paths
    assert [r["project"] for r in rows if r["path"] == str(dst)][0] == "research"

    vconn = vector_store._get_conn(tmp_path)
    ids = {row[0] for row in vconn.execute("SELECT id FROM embeddings").fetchall()}
    vconn.close()
    assert "_loose/a.md::c0" not in ids


def test_an_index_write_failure_does_not_block_or_undo_the_move(tmp_path, monkeypatch):
    (tmp_path / "_loose").mkdir()
    src = tmp_path / "_loose" / "a.md"
    dst = tmp_path / "research" / "a.md"
    src.write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("index is on fire")

    monkeypatch.setattr(index_writer, "remove_capture_by_path", boom)
    monkeypatch.setattr(index_writer, "upsert_capture_from_file", boom)
    monkeypatch.setattr(vector_store, "remove_from_index", boom)

    result = pt.apply_tidy(tmp_path, [pt.Move(src, dst)])

    assert result.moved == 1
    assert dst.exists()
    assert not src.exists()


# -- FR-33: a project whose HOME is not spelled like its HANDLE (contract §13.1 v3.2) ----------

def _reg_with_dir(name, dirname):
    reg = _reg(name)
    reg["projects"][name]["dir"] = dirname
    return reg


def test_a_note_in_its_projects_dir_does_not_move():
    # THE POINT OF FR-33. The user imported their folder `My Notes`; the tag had to become
    # `#project@My-Notes` because a `#hashtag` ends at the first whitespace. Without `dir`,
    # plan_tidy reads that as mis-filing and drains the folder into `My-Notes/` one note at a
    # time, unasked -- mobile_sync_agent._maybe_refile_local does the same on every round-trip.
    entries = [pt.NoteLoc(VAULT / "My Notes" / "a.md", "body #project@My-Notes")]
    assert pt.plan_tidy(entries, VAULT, _reg_with_dir("My-Notes", "My Notes")) == []


def test_a_note_outside_its_projects_dir_moves_into_the_dir_not_the_name():
    entries = [pt.NoteLoc(VAULT / "_loose" / "a.md", "body #project@My-Notes")]
    moves = pt.plan_tidy(entries, VAULT, _reg_with_dir("My-Notes", "My Notes"))
    assert moves == [pt.Move(VAULT / "_loose" / "a.md", VAULT / "My Notes" / "a.md")]


def test_a_project_without_a_dir_still_files_by_name():
    entries = [pt.NoteLoc(VAULT / "My Notes" / "a.md", "body #project@My-Notes")]
    moves = pt.plan_tidy(entries, VAULT, _reg("My-Notes"))
    assert moves == [pt.Move(VAULT / "My Notes" / "a.md", VAULT / "My-Notes" / "a.md")]


def test_an_unusable_dir_falls_back_to_the_name_rather_than_leaving_a_note_homeless():
    entries = [pt.NoteLoc(VAULT / "_loose" / "a.md", "body #project@research")]
    moves = pt.plan_tidy(entries, VAULT, _reg_with_dir("research", "../evil"))
    assert moves == [pt.Move(VAULT / "_loose" / "a.md", VAULT / "research" / "a.md")]
