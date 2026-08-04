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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
