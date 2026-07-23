"""
test_vault_setup.py — ISS-002/P-WIZARD: first-run vault-setup wizard endpoints.

Covers `GET /vault/setup/check` (existing-vault detection at a candidate path,
read-only) and `POST /vault/setup` (persist vault root + eager init_vault +
per-folder `.category.toml` creation). Mirrors test_server.py's
`_client_config` pattern (CONFIG_PATH monkeypatched to a tmp file,
reload_config mocked out so a test process never touches the real
config.toml) since these endpoints write config exactly the same way
PATCH /config does.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET
HEADERS = {"X-Omni-Secret": GUI_SECRET}

from fastapi.testclient import TestClient

import server


def _client(tmp_config: Path):
    server.CONFIG_PATH = tmp_config
    return TestClient(server.app, headers=HEADERS), server


def test_setup_writes_vault_root_and_eager_inits(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    vault = tmp_path / "MyVault"
    client, srv = _client(cfg)

    with mock.patch.object(srv, "reload_config", lambda *a, **k: None):
        r = client.post("/vault/setup", json={"root": str(vault), "folders": []})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert Path(body["root"]) == vault

    # init_vault() ran eagerly: scratchpad + .omni_capture exist even with no
    # chosen folders, so the vault is never "empty" the moment setup finishes.
    assert (vault / "_scratchpad").is_dir()
    assert (vault / ".omni_capture").is_dir()

    import tomlkit
    doc = tomlkit.loads(cfg.read_text(encoding="utf-8"))
    assert Path(str(doc["vault"]["root"])) == vault


def test_setup_creates_every_chosen_folder_with_its_category_toml(tmp_path):
    """The user's explicit requirement (P-WIZARD): a fresh vault must never
    ship a description-less folder -- every seeded folder gets .category.toml
    written AT CREATION, using the catalog's pre-written routing description."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    vault = tmp_path / "Vault2"
    client, srv = _client(cfg)

    folders = [
        {"name": "Work", "description": "Job, meetings, work projects, and professional documents."},
        {"name": "Personal", "description": "Personal life, household, and everyday notes."},
    ]
    with mock.patch.object(srv, "reload_config", lambda *a, **k: None):
        r = client.post("/vault/setup", json={"root": str(vault), "folders": folders})

    assert r.status_code == 200
    returned = {f["name"]: f["description"] for f in r.json()["folders"]}
    assert returned == {f["name"]: f["description"] for f in folders}

    from storage_engine import read_category_config
    for f in folders:
        folder_dir = vault / f["name"]
        assert folder_dir.is_dir()
        toml_path = folder_dir / ".category.toml"
        assert toml_path.exists(), f"{f['name']}/.category.toml must exist at creation"
        assert read_category_config(folder_dir)["description"] == f["description"]

    # models.py's category enum is built live from folders — setup never
    # hardcodes an enum, it only seeds directories + descriptions on disk.
    from storage_engine import discover_categories
    assert set(discover_categories(vault)) == {"Work", "Personal"}


def test_setup_rejects_relative_root():
    cfg_dir = tempfile.mkdtemp()
    cfg = Path(cfg_dir) / "config.toml"
    cfg.write_text("", encoding="utf-8")
    client, srv = _client(cfg)
    r = client.post("/vault/setup", json={"root": "relative/path", "folders": []})
    assert r.status_code == 400


def test_check_reports_fresh_when_path_does_not_exist(tmp_path):
    client, srv = _client(tmp_path / "config.toml")
    candidate = tmp_path / "DoesNotExistYet"
    r = client.get("/vault/setup/check", params={"root": str(candidate)})
    assert r.status_code == 200
    body = r.json()
    assert body == {"exists": False, "has_categories": False, "categories": []}


def test_check_detects_existing_vault_with_user_categories(tmp_path):
    client, srv = _client(tmp_path / "config.toml")
    candidate = tmp_path / "ExistingVault"
    (candidate / "Tech_Notes").mkdir(parents=True)
    (candidate / ".omni_capture").mkdir()

    r = client.get("/vault/setup/check", params={"root": str(candidate)})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["has_categories"] is True
    assert body["categories"] == ["Tech_Notes"]


def test_check_existing_empty_dir_has_no_categories(tmp_path):
    client, srv = _client(tmp_path / "config.toml")
    candidate = tmp_path / "EmptyDir"
    candidate.mkdir()

    r = client.get("/vault/setup/check", params={"root": str(candidate)})
    assert r.status_code == 200
    body = r.json()
    assert body == {"exists": True, "has_categories": False, "categories": []}


def test_check_rejects_relative_root():
    client, srv = _client(Path(tempfile.mkdtemp()) / "config.toml")
    r = client.get("/vault/setup/check", params={"root": "relative/path"})
    assert r.status_code == 400


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
