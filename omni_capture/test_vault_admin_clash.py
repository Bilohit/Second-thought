"""
test_vault_admin_clash.py — Phase 2 Task 2.6: `/vault/categories/{name}/files`
must expose the server-authoritative name-clash signal so the GUI can badge a
clashing row without recomputing naming rules in TS.

The clash rule itself already lives in mobile_sync_agent._resolve_hub_names /
_hub_filename (used for hub uploads); this only asserts the vault_admin route
surfaces that SAME resolution per note as `hub_name` + `name_clash`, so the
two never drift.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
# SRV-01: server._require_secret now fails CLOSED, so an empty OMNI_GUI_SECRET
# 403s every route instead of disabling auth. Every server test module uses this
# SAME literal on purpose: the env var is process-global and pytest imports all
# modules before running any test, so differing values would make the suite
# order-dependent.
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET
_AUTH = {"X-Omni-Secret": GUI_SECRET}


from fastapi.testclient import TestClient

import server

SECRET = "clash-test-secret-1234567890"
HEADERS = {"X-Omni-Secret": SECRET}


@pytest.fixture
def gui(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Work").mkdir(parents=True)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[vault]\nroot = "' + str(vault).replace("\\", "/") + '"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(server, "reload_config", lambda *a, **k: None)
    return TestClient(server.app), vault


def _write_note(vault: Path, folder: str, filename: str, *, id_: str, title: str, created: str) -> None:
    (vault / folder / filename).write_text(
        f"---\nid: {id_}\ntitle: {title}\ncategory: {folder}\ncreated: {created}\norigin: note\n---\n"
        f"# {title}\n\nBody.\n",
        encoding="utf-8",
    )


def test_later_note_with_same_title_is_flagged_as_name_clash(gui):
    client, vault = gui
    # Two notes titled "Meeting" in the same folder: the earlier-created one
    # (01AAAAAA) is the winner (clean "Meeting.md"), the later one (01BBBBBB)
    # is the suffixed loser -- matches mobile_sync_agent._resolve_hub_names'
    # tie rule (created, then id) exactly.
    _write_note(vault, "Work", "winner.md", id_="01AAAAAA", title="Meeting", created="2026-07-19T10:00:00Z")
    _write_note(vault, "Work", "loser.md", id_="01BBBBBB", title="Meeting", created="2026-07-19T11:00:00Z")

    r = client.get("/vault/categories/Work/files", headers=HEADERS)
    assert r.status_code == 200
    files = {f["filename"]: f for f in r.json()["files"]}

    assert files["winner.md"]["name_clash"] is False
    assert files["winner.md"]["hub_name"] == "Meeting.md"

    assert files["loser.md"]["name_clash"] is True
    assert files["loser.md"]["hub_name"] == "Meeting (2026-07-19 1100).md"


def test_unique_title_is_never_flagged(gui):
    client, vault = gui
    _write_note(vault, "Work", "solo.md", id_="01CCCCCC", title="Solo", created="2026-07-19T10:00:00Z")

    r = client.get("/vault/categories/Work/files", headers=HEADERS)
    assert r.status_code == 200
    f = r.json()["files"][0]
    assert f["name_clash"] is False
    assert f["hub_name"] == "Solo.md"
