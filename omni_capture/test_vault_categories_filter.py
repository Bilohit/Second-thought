"""
test_vault_categories_filter.py — ISS-014 regression: GET /vault/categories
must never surface dot-prefixed internal bookkeeping folders (`.omni_capture`,
`.sync`) as renamable/deletable user categories, but must keep surfacing
`_scratchpad` -- VaultManager.tsx (owned by another package) relabels that
row "Needs review" from this same response.
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

SECRET = "categories-filter-test-secret"
HEADERS = {"X-Omni-Secret": SECRET}


@pytest.fixture
def gui(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setenv("OMNI_GUI_SECRET", SECRET)
    monkeypatch.setattr(server, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(server, "reload_config", lambda *a, **k: None)
    return TestClient(server.app), vault


def test_dot_prefixed_system_folders_are_excluded(gui):
    client, vault = gui
    (vault / ".omni_capture").mkdir()
    (vault / ".sync").mkdir()
    (vault / "Tech_Notes").mkdir()

    r = client.get("/vault/categories", headers=HEADERS)
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["categories"]}

    assert names == {"Tech_Notes"}


def test_scratchpad_folder_still_surfaces_for_needs_review_display(gui):
    client, vault = gui
    (vault / "_scratchpad").mkdir()
    (vault / "Tech_Notes").mkdir()

    r = client.get("/vault/categories", headers=HEADERS)
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["categories"]}

    # NOT excluded here -- unlike storage_engine.discover_categories (which
    # excludes it so the LLM never routes to it), the CRUD listing must keep
    # it so VaultManager can relabel/restrict it, not lose it entirely.
    assert "_scratchpad" in names
    assert "Tech_Notes" in names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
