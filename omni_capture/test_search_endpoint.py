"""
test_search_endpoint.py
-----------------------
Integration tests for the /search and /stats FastAPI endpoints.

Uses TestClient (httpx-based) — no real server needed.

Run:
    python -m pytest test_search_endpoint.py -v
    # or:
    python test_search_endpoint.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Silence startup warnings for tests
import os
os.environ.setdefault("OMNI_GUI_SECRET", "")

try:
    from fastapi.testclient import TestClient
except ImportError:
    raise ImportError("pip install httpx  (required by FastAPI TestClient)")

from index_writer import init_db, log_capture_db


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _entry(
    category: str   = "Tech_Notes",
    filepath: str   = "/v/T/note.md",
    filename: str   = "note",
    source_url: str = "",
    timestamp: str  = "2025-06-17T10:00:00",
) -> dict:
    return {
        "category":   category,
        "filepath":   filepath,
        "filename":   filename,
        "source_url": source_url or None,
        "confidence": 0.95,
        "timestamp":  timestamp,
        "input_type": "text",
        "model":      "llama3.2",
        "tags":       [],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSearchEndpoint(unittest.TestCase):
    """
    Each test creates an isolated temporary vault, seeds the DB,
    then monkeypatches server._get_vault_root to use that vault.
    """

    def _make_client(self, vault: Path) -> "TestClient":
        import server
        server._get_vault_root = lambda: vault   # type: ignore[attr-defined]
        return TestClient(server.app)

    def _seed(self, vault: Path, entries: list[dict]) -> None:
        for e in entries:
            log_capture_db(e, vault)

    # GET /search — basic happy-path
    def test_search_returns_200(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            r = client.get("/search")
            self.assertEqual(r.status_code, 200)

    def test_search_response_shape(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [_entry()])
            client = self._make_client(vault)
            data = client.get("/search").json()
            self.assertIn("results", data)
            self.assertIn("count",   data)
            self.assertIn("query",   data)

    def test_search_query_param(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [
                _entry(category="Tech_Notes",  filepath="/v/T/docker.md",   filename="docker"),
                _entry(category="CRM",         filepath="/v/C/acme.md",     filename="acme"),
            ])
            client  = self._make_client(vault)
            data    = client.get("/search?q=docker").json()
            paths   = [r["path"] for r in data["results"]]
            self.assertTrue(any("docker" in p for p in paths))
            self.assertFalse(any("acme" in p for p in paths))

    def test_search_category_filter(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [
                _entry(category="Tech_Notes", filepath="/v/T/a.md"),
                _entry(category="CRM",        filepath="/v/C/b.md"),
            ])
            client = self._make_client(vault)
            data   = client.get("/search?category=CRM").json()
            for r in data["results"]:
                self.assertEqual(r["category"], "CRM")

    def test_search_limit_capped_at_200(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            # Seed 10 entries
            for i in range(10):
                self._seed(vault, [_entry(filepath=f"/v/T/{i}.md", filename=str(i))])
            client = self._make_client(vault)
            # limit=5 → at most 5
            data = client.get("/search?limit=5").json()
            self.assertLessEqual(len(data["results"]), 5)
            # limit=9999 → capped at 200, but only 10 rows so count ≤ 10
            data = client.get("/search?limit=9999").json()
            self.assertLessEqual(len(data["results"]), 200)

    def test_search_empty_vault(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            data   = client.get("/search?q=anything").json()
            self.assertEqual(data["count"],   0)
            self.assertEqual(data["results"], [])


class TestStatsEndpoint(unittest.TestCase):
    def _make_client(self, vault: Path) -> "TestClient":
        import server
        server._get_vault_root = lambda: vault   # type: ignore[attr-defined]
        return TestClient(server.app)

    def _seed(self, vault: Path) -> None:
        entries = [
            _entry(category="Tech_Notes",  filepath="/v/T/note1.md", filename="note1"),
            _entry(category="Tech_Notes",  filepath="/v/T/note2.md", filename="note2"),
            _entry(category="CRM",         filepath="/v/C/contact.md", filename="contact"),
            _entry(category="Finance",     filepath="/v/F/invoice.md",  filename="invoice", timestamp="2025-01-10T08:00:00"),
        ]
        for e in entries:
            log_capture_db(e, vault)

    def test_stats_returns_200(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            r = client.get("/stats")
            self.assertEqual(r.status_code, 200)

    def test_stats_response_shape(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            self.assertIn("total",       data)
            self.assertIn("by_category", data)
            self.assertIn("by_day",      data)
            self.assertIn("recent",      data)

    def test_stats_total(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault)
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            self.assertEqual(data["total"], 4)

    def test_stats_by_category(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault)
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            cats   = {r["category"]: r["count"] for r in data["by_category"]}
            self.assertEqual(cats["Tech_Notes"], 2)
            self.assertEqual(cats["CRM"],        1)

    def test_stats_empty_vault(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            self.assertEqual(data["total"],       0)
            self.assertEqual(data["by_category"], [])
            self.assertEqual(data["recent"],      [])


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
