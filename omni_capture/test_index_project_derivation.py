"""
test_index_project_derivation.py
--------------------------------
The captures.db `project` column is a DERIVED cache of the body tag resolved
against `.projects.toml` -- never of the directory the file happens to sit in.

Three defects are pinned here, all found by running the app against a real vault
that predates the projects rework (s127):

  1. `upsert_capture_from_file` derived `project` from `p.parent.name`. The
     comment claimed the directory "IS the resolved project by construction",
     which holds only once the tidy pass has re-pathed every file. On a vault
     whose notes still sit in legacy `personal/`, `work/`, `recipes/` folders
     with no `#project@` tag at all, every row asserted a project the registry
     has never held -- and design §1 is explicit that the directory is derived
     housekeeping and "no surface may present a path as the source of truth".

  2. The upsert's `ON CONFLICT(path) DO UPDATE` set every column EXCEPT
     `project`, so a row's project could never be corrected once written.

  3. `sync_vault_indexes` gated the project column on the file hash. A note's
     project changes when the REGISTRY changes -- project created, renamed or
     deleted -- with the file byte-identical, so the hash is not a valid gate.
     This is structurally the same bug OF-1 fixed for embeddings, which is why
     the fix lives on the same skip path.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import index_writer
import project_registry
import vault_sync
import vector_store as vs
from index_writer import derive_project, init_db, upsert_capture_from_file
from projects import LOOSE_DIR


def _reg(*names: str) -> dict:
    reg = project_registry.empty_registry()
    for n in names:
        reg["projects"][n] = {"description": "", "created": "", "modified": "", "device": ""}
    return reg


def _row_project(vault: Path, path: Path) -> str | None:
    conn = init_db(vault)
    row = conn.execute("SELECT project FROM captures WHERE path = ?", (str(path),)).fetchone()
    conn.close()
    return row["project"] if row else None


# ── derive_project: the tag, never the directory ──────────────────────────────

def test_tag_wins_over_a_disagreeing_directory():
    """The load-bearing case: file in `personal/`, body tagged `#project@research`."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "personal" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("body text #project@research more", encoding="utf-8")

        assert derive_project(note, _reg("research"), vault) == "research"


def test_legacy_folder_with_no_tag_is_loose():
    """The user's ACTUAL vault: legacy category folders, zero `#project@` tags.
    Every one of those notes is loose -- the folder name is not a project."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        for folder in ("personal", "work", "recipes"):
            note = vault / folder / "n.md"
            note.parent.mkdir(parents=True)
            note.write_text("no tag here at all", encoding="utf-8")
            assert derive_project(note, _reg(), vault) == LOOSE_DIR, folder


def test_unregistered_tag_reads_as_loose():
    """"Dangling reads as loose" (contract §1.3) -- the tag names a project the
    registry does not hold, so the note is loose, NOT a project called `ghost`."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "ghost" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("text #project@ghost text", encoding="utf-8")

        assert derive_project(note, _reg("research"), vault) == LOOSE_DIR


def test_tag_past_the_body_excerpt_cap_is_still_found():
    """derive_project must read the WHOLE file. `_read_body_excerpt` truncates at
    _BODY_EXCERPT_MAX_CHARS, so reusing it would miss a tag written past the cap."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "_loose" / "long.md"
        note.parent.mkdir(parents=True)
        filler = "x" * (index_writer._BODY_EXCERPT_MAX_CHARS + 500)
        note.write_text(f"{filler} #project@research", encoding="utf-8")

        assert derive_project(note, _reg("research"), vault) == "research"


# ── the upsert must be able to CORRECT a row ──────────────────────────────────

def test_upsert_updates_project_on_conflict():
    """Defect 2: re-upserting the same path must move the project column, not
    keep whatever was written the first time."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "_loose" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("plain body, no tag", encoding="utf-8")

        upsert_capture_from_file(vault, note, _reg())
        assert _row_project(vault, note) == LOOSE_DIR

        # the user tags it, and the project exists in the registry
        note.write_text("plain body #project@research", encoding="utf-8")
        upsert_capture_from_file(vault, note, _reg("research"))
        assert _row_project(vault, note) == "research", (
            "ON CONFLICT DO UPDATE omitted `project`, so the row was frozen at its first value"
        )


# ── the sync pass must not gate the project on the file hash ──────────────────

def test_registry_change_reprojects_an_unchanged_file():
    """Defect 3. The file is byte-identical across both passes -- only the
    registry moves. A hash-gated skip left the row asserting a stale project."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "_loose" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("body #project@research here", encoding="utf-8")
        before = note.read_bytes()

        # Pass 1: `research` is not registered yet, so the note is loose.
        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")
        assert _row_project(vault, note) == LOOSE_DIR

        # The user creates the project. The FILE does not change.
        project_registry.save(vault, _reg("research"))

        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            result = vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert note.read_bytes() == before, "the sync pass must not touch the file"
        assert result["reprojected"] == 1
        assert _row_project(vault, note) == "research"


def test_reproject_is_silent_when_nothing_moved():
    """The correction must fire only on a real difference -- a steady-state pass
    reports zero, so `reprojected` stays a signal and not noise."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "_loose" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("body with no tag", encoding="utf-8")

        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")
        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            result = vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result["reprojected"] == 0
        assert result["skipped"] == 1


def test_deleting_a_project_returns_its_notes_to_loose():
    """§5: deleting a project never destroys notes -- they become loose. The
    index must follow, again with no file change."""
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "_loose" / "n.md"
        note.parent.mkdir(parents=True)
        note.write_text("body #project@research here", encoding="utf-8")
        project_registry.save(vault, _reg("research"))

        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")
        assert _row_project(vault, note) == "research"

        project_registry.save(vault, _reg())  # project deleted

        with mock.patch.object(vs, "_embed", return_value=[0.1] * 8):
            result = vault_sync.sync_vault_indexes(vault, "http://localhost:11434", "all-minilm")

        assert result["reprojected"] == 1
        assert _row_project(vault, note) == LOOSE_DIR
