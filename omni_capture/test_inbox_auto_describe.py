"""
test_inbox_auto_describe.py
----------------------------
Covers the Issue 1 (Inbox overhaul) backend additions:

  1. Approving an inbox item into a brand-new category creates the folder
     (pre-existing behavior) and, with auto_describe_new_folders=True,
     writes a .category.toml description generated from the item's content.
  2. With the toggle off, no .category.toml is written.
  3. GET /inbox/{note_id}/suggest-categories returns suggestions, 404s for
     an unknown note_id, and degrades to [] when the LLM call fails.
  4. storage_engine.write_category_description merges/clears without
     clobbering other keys.

LLM calls are mocked (storage_engine.generate_category_description /
suggest_category_names) -- nothing here hits Ollama.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OMNI_GUI_SECRET", "")

from fastapi.testclient import TestClient

from config import Config
from models import CaptureOutput
from storage_engine import write_to_vault, list_scratchpad, write_category_description


def _seed_inbox(vault: Path, content="Plants need water and sunlight to grow.") -> str:
    t = CaptureOutput(
        category="Tech_Notes",
        suggested_filename="garden-note",
        markdown_content=content,
        key_signals=[],
        confidence=0.1,
        requires_new_category=False,
    )
    write_to_vault(t, vault_root=vault)
    items = list_scratchpad(vault)
    assert items
    return items[0]["note_id"]


def _client(vault: Path, auto_describe: bool):
    import server
    server._get_vault_root = lambda: vault  # type: ignore[attr-defined]

    cfg = Config()
    cfg.capture.auto_describe_new_folders = auto_describe
    return TestClient(server.app), cfg


class TestApproveAutoDescribe(unittest.TestCase):
    def test_toggle_on_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Notes about plants and gardening."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())

    def test_toggle_off_does_not_write_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertFalse(cat_toml.exists())

    def test_approve_into_existing_category_skips_describe_even_if_on(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            (vault / "Botany").mkdir(parents=True)
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=True)

            import storage_engine
            with mock.patch.object(storage_engine, "generate_category_description",
                                    lambda *a, **k: "Should not be written."), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertFalse(cat_toml.exists())


class TestSuggestCategories(unittest.TestCase):
    def test_suggest_returns_suggestions(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=False)

            import storage_engine
            with mock.patch.object(storage_engine, "suggest_category_names", lambda *a, **k: ["Botany", "Gardening"]), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get(f"/inbox/{note_id}/suggest-categories")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], ["Botany", "Gardening"])

    def test_suggest_404_for_unknown_note(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client(vault, auto_describe=False)
            with mock.patch("config.get_config", lambda: cfg):
                r = client.get("/inbox/does-not-exist/suggest-categories")
            self.assertEqual(r.status_code, 404)

    def test_suggest_llm_failure_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=False)

            import llm_engine
            with mock.patch.object(llm_engine, "summarize",
                                    mock.Mock(side_effect=llm_engine.SummarizationError("boom"))), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.get(f"/inbox/{note_id}/suggest-categories")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["suggestions"], [])


class TestAutoDescribeRealAsyncPath(unittest.TestCase):
    """
    Regression coverage for the "asyncio.run() cannot be called from a
    running event loop" bug: generate_category_description()'s sync wrapper
    (llm_engine.summarize) ends in asyncio.run(), but it used to be invoked
    directly from inside async routes (create_category, approve_inbox),
    which already have a running loop -- asyncio.run() raised RuntimeError,
    which generate_category_description's bare `except Exception` swallowed,
    so no description was ever written.

    Unlike the tests above (which mock storage_engine.generate_category_description
    directly and so never touch asyncio.run() at all), these mock only
    llm_engine.summarize_async -- the real generate_category_description()
    and the real summarize()/asyncio.run() wrapper still execute, through the
    real async route. They fail if that regression reappears.
    """

    def test_create_category_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client, cfg = _client(vault, auto_describe=True)

            import llm_engine

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post("/vault/categories", json={"name": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())

    def test_approve_inbox_real_async_path_writes_description(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            note_id = _seed_inbox(vault)
            client, cfg = _client(vault, auto_describe=True)

            import llm_engine

            async def fake_summarize_async(*_a, **_k):
                return "Notes about plants and gardening."

            with mock.patch.object(llm_engine, "summarize_async", fake_summarize_async), \
                 mock.patch("config.get_config", lambda: cfg):
                r = client.post(f"/inbox/{note_id}/approve", json={"target_category": "Botany"})
            self.assertEqual(r.status_code, 200)

            cat_toml = vault / "Botany" / ".category.toml"
            self.assertTrue(cat_toml.exists())
            self.assertIn("Notes about plants", cat_toml.read_text())


class TestWriteCategoryDescription(unittest.TestCase):
    def test_write_then_clear_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as td:
            cat_dir = Path(td) / "Botany"
            cat_dir.mkdir()
            (cat_dir / ".category.toml").write_text('format = "custom"\n', encoding="utf-8")

            write_category_description(cat_dir, "Plants and gardening notes.")
            text = (cat_dir / ".category.toml").read_text()
            self.assertIn("custom", text)
            self.assertIn("Plants and gardening", text)

            write_category_description(cat_dir, None)
            text = (cat_dir / ".category.toml").read_text()
            self.assertIn("custom", text)
            self.assertNotIn("Plants and gardening", text)


if __name__ == "__main__":
    unittest.main()
