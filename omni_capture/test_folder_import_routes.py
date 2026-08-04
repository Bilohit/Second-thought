"""
test_folder_import_routes.py -- FR-23 Option C: GET /vault/folder-import/preview and
POST /vault/folder-import/apply.

The apply route is the only route in the product that edits a note body outside the
editor, so the tests here assert the three properties that make that safe: the tag and
the registry entry are written together, an unusable name is refused rather than guessed
at (and its notes stay byte-identical), and a second identical call is a no-op.

Fixture idiom copied from test_vault_folders_filter.py -- there is no conftest.py in this
repo, so each route-test file builds its own TestClient over the real server.app with
`server._get_vault_root` monkeypatched at a temp vault.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET

from fastapi.testclient import TestClient

import project_registry
import project_tidy
import server

SECRET = "folder-import-test-secret"
HEADERS = {"X-Omni-Secret": SECRET}


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def client(vault, monkeypatch):
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(server, "reload_config", lambda *a, **k: None)
    return TestClient(server.app, headers=HEADERS)


def test_preview_lists_candidate_folders_with_counts(client, vault):
    (vault / "Work").mkdir()
    (vault / "Work" / "a.md").write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    (vault / "My Notes").mkdir()
    (vault / "My Notes" / "b.md").write_text("---\nid: 2\n---\n# B\n", encoding="utf-8")

    body = client.get("/vault/folder-import/preview").json()

    assert body["count"] == 2
    by_folder = {f["folder"]: f for f in body["folders"]}
    assert by_folder["Work"]["valid"] is True and by_folder["Work"]["count"] == 1
    assert by_folder["My Notes"]["valid"] is False
    assert by_folder["My Notes"]["suggested"] == "My-Notes"


def test_preview_discloses_how_many_notes_were_written_on_the_phone(client, vault):
    """s140: phone-authored notes are imported like any other; the row only discloses the
    count so the user sees it at the moment of consent."""
    (vault / "Work").mkdir()
    (vault / "Work" / "a.md").write_text(
        "---\nid: 1\norigin_device: phone\n---\n# A\n", encoding="utf-8")
    (vault / "Work" / "b.md").write_text("---\nid: 2\n---\n# B\n", encoding="utf-8")

    body = client.get("/vault/folder-import/preview").json()

    row = body["folders"][0]
    assert row["phone_count"] == 1
    assert row["count"] == 2, "the phone note is still a candidate, not filtered out"


def test_apply_writes_the_tag_the_registry_and_the_derived_cache(client, vault):
    (vault / "Work").mkdir()
    note = vault / "Work" / "a.md"
    note.write_text("---\nid: 1\nproject: [-]\n---\n# A\n\nprose\n", encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "Work", "name": "Work"}]}).json()

    text = note.read_text(encoding="utf-8")
    assert res["tagged"] == 1 and res["registered"] == ["Work"]
    assert "# A\n#project@Work\n" in text
    assert "project: [Work]" in text          # derived cache recomputed, not left stale
    assert "prose\n" in text                   # every other body byte survives

    import project_registry
    assert "Work" in project_registry.load(vault)["projects"], (
        "the tag alone would still read loose -- resolve_project needs the registry entry"
    )
    assert note.exists(), "the import never moves a file"


def test_apply_rejects_an_invalid_name_without_touching_the_folder(client, vault):
    (vault / "My Notes").mkdir()
    note = vault / "My Notes" / "b.md"
    before = "---\nid: 2\n---\n# B\n"
    note.write_text(before, encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "My Notes", "name": "My Notes"}]}).json()

    assert res["tagged"] == 0
    assert res["skipped"] == [{"folder": "My Notes", "reason": "invalid-name"}]
    assert note.read_text(encoding="utf-8") == before


def test_apply_is_idempotent_and_never_double_tags(client, vault):
    (vault / "Work").mkdir()
    note = vault / "Work" / "a.md"
    note.write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    payload = {"folders": [{"folder": "Work", "name": "Work"}]}

    client.post("/vault/folder-import/apply", json=payload)
    first = note.read_text(encoding="utf-8")
    second_res = client.post("/vault/folder-import/apply", json=payload).json()

    assert second_res["tagged"] == 0
    assert note.read_text(encoding="utf-8") == first


# -- FR-33: the import records the folder's real name as the project's `dir` (§13.1 v3.2) ------

def _register(vault, name, **fields):
    entry = {"description": "", "created": "2026-08-01T10:00:00Z",
             "modified": "2026-08-01T10:00:00Z", "device": "desktop"}
    entry.update(fields)
    project_registry.update(vault, lambda r: r["projects"].update({name: entry}))


def test_apply_records_a_differently_spelled_folder_as_the_projects_dir(client, vault):
    # `My Notes` cannot be a project NAME: a `#hashtag` ends at the first whitespace, so
    # `#project@My Notes` would parse as `My`. Before FR-33 the folder was left mismatched and
    # the tidy pass then drained it into `My-Notes/` one note at a time, unasked.
    (vault / "My Notes").mkdir()
    note = vault / "My Notes" / "b.md"
    note.write_text("---\nid: 2\n---\n# B\nprose\n", encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "My Notes", "name": "My-Notes"}]}).json()

    assert res["tagged"] == 1 and res["registered"] == ["My-Notes"] and res["skipped"] == []
    assert project_registry.load(vault)["projects"]["My-Notes"]["dir"] == "My Notes"
    assert note.exists(), "the import never moves a file"

    # The whole point: the tidy pass now plans nothing for this note.
    entries = [project_tidy.NoteLoc(note, note.read_text(encoding="utf-8"))]
    assert project_tidy.plan_tidy(entries, vault, project_registry.load(vault)) == []


def test_apply_sets_no_dir_when_the_folder_is_spelled_like_the_project(client, vault):
    (vault / "Work").mkdir()
    (vault / "Work" / "a.md").write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")

    client.post("/vault/folder-import/apply",
                json={"folders": [{"folder": "Work", "name": "Work"}]})

    assert "dir" not in project_registry.load(vault)["projects"]["Work"]


def test_joining_an_existing_project_never_overwrites_its_home(client, vault):
    # A folder whose name matches an existing project JOINS it (resolved decision 2). `dir` is
    # that project's HOME -- rewriting it here would relocate notes the user never discussed,
    # which is the exact defect FR-33 exists to fix, inverted.
    _register(vault, "Docs", description="kept", dir="Old Home")
    (vault / "New Folder").mkdir()
    (vault / "New Folder" / "c.md").write_text("---\nid: 3\n---\n# C\n", encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "New Folder", "name": "Docs"}]}).json()

    entry = project_registry.load(vault)["projects"]["Docs"]
    assert entry["dir"] == "Old Home", "the existing home must survive a join untouched"
    assert entry["description"] == "kept"       # created/description untouched too, as before
    assert res["tagged"] == 1                   # the notes are still tagged into the project


def test_joining_a_project_that_has_no_home_does_not_invent_one(client, vault):
    _register(vault, "Docs")
    (vault / "New Folder").mkdir()
    (vault / "New Folder" / "c.md").write_text("---\nid: 3\n---\n# C\n", encoding="utf-8")

    client.post("/vault/folder-import/apply",
                json={"folders": [{"folder": "New Folder", "name": "Docs"}]})

    assert "dir" not in project_registry.load(vault)["projects"]["Docs"]


def test_a_folder_whose_home_is_already_claimed_is_refused_and_its_notes_untouched(client, vault):
    _register(vault, "Alpha", dir="Shared Home")
    (vault / "Shared Home").mkdir()
    note = vault / "Shared Home" / "d.md"
    before = "---\nid: 4\n---\n# D\nprose\n"
    note.write_text(before, encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "Shared Home", "name": "Beta"}]}).json()

    assert res["tagged"] == 0 and res["registered"] == []
    assert res["skipped"] == [{"folder": "Shared Home", "reason": "unavailable-dir"}]
    assert note.read_text(encoding="utf-8") == before, "a refused folder is byte-identical"
    assert "Beta" not in project_registry.load(vault)["projects"]


def test_a_name_already_used_as_another_projects_home_is_refused(client, vault):
    # Registering `Shared` would leave two projects claiming the directory `Shared/`, which
    # project_registry.dumps refuses to write at all -- catch it here rather than 500ing.
    _register(vault, "Alpha", dir="Shared")
    (vault / "Shared").mkdir()
    note = vault / "Shared" / "e.md"
    before = "---\nid: 5\n---\n# E\n"
    note.write_text(before, encoding="utf-8")

    res = client.post("/vault/folder-import/apply",
                      json={"folders": [{"folder": "Shared", "name": "Shared"}]}).json()

    assert res["skipped"] == [{"folder": "Shared", "reason": "unavailable-dir"}]
    assert note.read_text(encoding="utf-8") == before
    assert "Shared" not in project_registry.load(vault)["projects"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
