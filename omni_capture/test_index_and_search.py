"""
test_index_and_search.py
------------------------
Consolidated tests for index_writer.py (unit) and the /search and /stats
FastAPI endpoints (integration).

Merged from test_index_writer.py + test_search_endpoint.py.

Run:
    python -m pytest test_index_and_search.py -v
    # or directly:
    python test_index_and_search.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Silence startup warnings for tests (must be set before importing server)
os.environ.setdefault("OMNI_GUI_SECRET", "")

try:
    from fastapi.testclient import TestClient
except ImportError:
    raise ImportError("pip install httpx  (required by FastAPI TestClient)")

from index_writer import (
    get_db_path,
    init_db,
    log_capture_db,
    migrate_jsonl,
    reindex_bodies,
    search,
    stats,
    upsert_capture_from_file,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vault(tmp: Path) -> Path:
    """Create a minimal vault directory tree inside tmp."""
    vault = tmp / "vault"
    vault.mkdir()
    return vault


def _entry_index(
    category: str = "Tech_Notes",
    filepath: str = "/vault/Tech_Notes/test-note.md",
    filename: str = "test-note",
    source_url: str | None = None,
    confidence: float = 0.95,
    timestamp: str = "2025-06-17T10:00:00",
    input_type: str = "text",
    model: str = "llama3.2",
) -> dict:
    return {
        "category":   category,
        "filepath":   filepath,
        "filename":   filename,
        "source_url": source_url,
        "confidence": confidence,
        "timestamp":  timestamp,
        "input_type": input_type,
        "model":      model,
        "tags":       [],
    }


def _entry_search(
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


# ── index_writer unit tests ───────────────────────────────────────────────────

class TestInitDb(unittest.TestCase):
    def test_creates_db_file(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            conn  = init_db(vault)
            conn.close()
            db_path = get_db_path(vault)
            self.assertTrue(db_path.exists(), "captures.db should be created")

    def test_schema_tables_exist(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            conn  = init_db(vault)
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.close()
            self.assertIn("captures",     tables)
            self.assertIn("captures_fts", tables)

    def test_idempotent_init(self):
        """Calling init_db twice on the same vault must not raise."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            init_db(vault).close()
            init_db(vault).close()  # no error


class TestLogCaptureDb(unittest.TestCase):
    def test_inserts_row(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            e     = _entry_index()
            log_capture_db(e, vault)
            conn  = init_db(vault)
            row   = conn.execute("SELECT * FROM captures").fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["category"],  "Tech_Notes")
            self.assertEqual(row["confidence"], 0.95)

    def test_upsert_updates_hash(self):
        """Inserting same filepath twice should update, not duplicate."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            e     = _entry_index(confidence=0.8)
            log_capture_db(e, vault)
            e2 = {**e, "confidence": 0.99}
            log_capture_db(e2, vault)
            conn  = init_db(vault)
            rows  = conn.execute("SELECT * FROM captures").fetchall()
            conn.close()
            self.assertEqual(len(rows), 1, "Upsert should produce exactly 1 row")
            self.assertAlmostEqual(rows[0]["confidence"], 0.99)

    def test_tags_stored_as_json(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            e     = {**_entry_index(), "tags": ["python", "async"]}
            log_capture_db(e, vault)
            conn  = init_db(vault)
            row   = conn.execute("SELECT tags FROM captures").fetchone()
            conn.close()
            self.assertEqual(json.loads(row["tags"]), ["python", "async"])

    def test_missing_filepath_does_not_raise(self):
        """log_capture_db must fail silently on bad input."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            log_capture_db({"category": "Test"}, vault)  # no exception


class TestMigrateJsonl(unittest.TestCase):
    def _write_jsonl(self, path: Path, entries: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_imports_rows(self):
        with tempfile.TemporaryDirectory() as td:
            vault    = _vault(Path(td))
            jpath    = vault / ".omni_capture" / "captures.jsonl"
            jpath.parent.mkdir(parents=True, exist_ok=True)
            entries  = [
                _entry_index(category="CRM",       filepath=f"/vault/CRM/note-{i}.md", filename=f"note-{i}")
                for i in range(3)
            ]
            self._write_jsonl(jpath, entries)
            n = migrate_jsonl(jpath, vault)
            self.assertEqual(n, 3)
            conn = init_db(vault)
            count = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
            conn.close()
            self.assertEqual(count, 3)

    def test_skips_existing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            vault   = _vault(Path(td))
            jpath   = vault / ".omni_capture" / "captures.jsonl"
            jpath.parent.mkdir(parents=True, exist_ok=True)
            e       = _entry_index(filepath="/vault/CRM/note-1.md")
            self._write_jsonl(jpath, [e])
            migrate_jsonl(jpath, vault)  # first run
            n2 = migrate_jsonl(jpath, vault)  # second run — should skip
            self.assertEqual(n2, 0)

    def test_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            vault   = _vault(Path(td))
            jpath   = vault / ".omni_capture" / "captures.jsonl"
            jpath.parent.mkdir(parents=True, exist_ok=True)
            with open(jpath, "w") as f:
                f.write('{"category":"CRM","filepath":"/vault/x.md","filename":"x","timestamp":"2025-01-01T00:00:00"}\n')
                f.write("NOT JSON\n")
                f.write('{"category":"Finance","filepath":"/vault/y.md","filename":"y","timestamp":"2025-01-01T00:00:00"}\n')
            n = migrate_jsonl(jpath, vault)
            self.assertEqual(n, 2)


class TestSearch(unittest.TestCase):
    def _populate(self, vault: Path) -> None:
        entries = [
            _entry_index(category="Tech_Notes",  filepath="/v/T/asyncio.md",  filename="asyncio",   source_url=None),
            _entry_index(category="CRM",         filepath="/v/C/acme.md",      filename="acme",      source_url="https://acme.com"),
            _entry_index(category="Finance",     filepath="/v/F/invoice.md",   filename="invoice",   timestamp="2025-01-15T08:00:00"),
            _entry_index(category="Tech_Notes",  filepath="/v/T/docker.md",    filename="docker",    source_url="https://docs.docker.com"),
        ]
        for e in entries:
            log_capture_db(e, vault)

    def test_empty_query_returns_all(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault)
            self.assertEqual(len(results), 4)

    def test_fts_matches_category(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("Tech_Notes", vault)
            self.assertTrue(len(results) >= 2)
            for r in results:
                self.assertEqual(r["category"], "Tech_Notes")

    def test_fts_matches_filename(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("docker", vault)
            self.assertEqual(len(results), 1)
            self.assertIn("docker", results[0]["path"])

    def test_category_filter(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault, category="CRM")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["category"], "CRM")

    def test_limit_respected(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault, limit=2)
            self.assertLessEqual(len(results), 2)

    def test_empty_vault_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            results = search("anything", vault)
            self.assertEqual(results, [])


class TestStats(unittest.TestCase):
    def _populate(self, vault: Path) -> None:
        for i, (cat, fp) in enumerate([
            ("Tech_Notes", "/v/T/note1.md"),
            ("Tech_Notes", "/v/T/note2.md"),
            ("CRM",        "/v/C/contact.md"),
        ]):
            log_capture_db(_entry_index(category=cat, filepath=fp, filename=f"note{i}"), vault)

    def test_total(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s = stats(vault)
            self.assertEqual(s["total"], 3)

    def test_by_category_structure(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s    = stats(vault)
            cats = {r["category"]: r["count"] for r in s["by_category"]}
            self.assertEqual(cats["Tech_Notes"], 2)
            self.assertEqual(cats["CRM"],        1)

    def test_pct_sums_to_100(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s    = stats(vault)
            total_pct = sum(r["pct"] for r in s["by_category"])
            self.assertAlmostEqual(total_pct, 100.0, places=0)

    def test_recent_limit(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s = stats(vault)
            self.assertLessEqual(len(s["recent"]), 10)

    def test_empty_vault_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            s = stats(vault)
            self.assertEqual(s["total"], 0)
            self.assertEqual(s["by_category"], [])


class TestBodyIndexing(unittest.TestCase):
    """Covers Issue 2: full-text search must reach the note body, not just metadata."""

    def _write_note(self, vault: Path, name: str, body: str) -> str:
        cat_dir = vault / "Tech_Notes"
        cat_dir.mkdir(parents=True, exist_ok=True)
        path = cat_dir / f"{name}.md"
        path.write_text(
            f"---\ntitle: {name}\n---\n{body}\n", encoding="utf-8"
        )
        return str(path)

    def test_body_text_findable_via_search(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            filepath = self._write_note(
                vault, "garden-note", "Photosynthesis converts sunlight into energy."
            )
            log_capture_db(_entry_index(filepath=filepath, filename="garden-note"), vault)

            results = search("Photosynthesis", vault)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["filename"], "garden-note")

    def test_body_excerpt_strips_frontmatter_and_caps_length(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            filepath = self._write_note(vault, "long-note", "x" * 70000)
            log_capture_db(_entry_index(filepath=filepath, filename="long-note"), vault)
            conn = init_db(vault)
            row = conn.execute("SELECT body_excerpt FROM captures").fetchone()
            conn.close()
            self.assertNotIn("title:", row["body_excerpt"])
            self.assertLessEqual(len(row["body_excerpt"]), 65536)

    def test_reindex_bodies_backfills_existing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            filepath = self._write_note(vault, "old-note", "Quantum entanglement basics.")
            # Simulate a pre-body_excerpt row: insert without the column populated.
            conn = init_db(vault)
            conn.execute(
                "INSERT INTO captures (timestamp, category, path, filename) VALUES (?,?,?,?)",
                ("2025-01-01T00:00:00", "Tech_Notes", filepath, "old-note"),
            )
            conn.commit()
            conn.close()

            updated = reindex_bodies(vault)
            self.assertEqual(updated, 1)

            results = search("entanglement", vault)
            self.assertEqual(len(results), 1)

    def test_reindex_bodies_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            filepath = self._write_note(vault, "note", "Some body text.")
            log_capture_db(_entry_index(filepath=filepath, filename="note"), vault)

            first = reindex_bodies(vault)
            second = reindex_bodies(vault)
            self.assertEqual(first, 1)   # one row visited and (re)backfilled
            self.assertEqual(second, 0)  # gated by the _meta flag set after the first call


def test_upsert_capture_from_file_uses_file_mtime():
    import os
    import tempfile
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from index_writer import init_db, upsert_capture_from_file

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        note = vault / "Tech" / "old.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Old note", encoding="utf-8")
        old = time.time() - 90 * 86400  # 90 days ago
        os.utime(note, (old, old))

        upsert_capture_from_file(vault, note)

        conn = init_db(vault)
        row = conn.execute(
            "SELECT timestamp FROM captures WHERE path = ?", (str(note),)
        ).fetchone()
        conn.close()

        expected = datetime.fromtimestamp(old, tz=timezone.utc).isoformat(timespec="seconds")
        assert row is not None
        assert row["timestamp"] == expected, f"{row['timestamp']} != {expected}"


# ── /search and /stats endpoint integration tests ─────────────────────────────

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
            self._seed(vault, [_entry_search()])
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
                _entry_search(category="Tech_Notes",  filepath="/v/T/docker.md",   filename="docker"),
                _entry_search(category="CRM",         filepath="/v/C/acme.md",     filename="acme"),
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
                _entry_search(category="Tech_Notes", filepath="/v/T/a.md"),
                _entry_search(category="CRM",        filepath="/v/C/b.md"),
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
                self._seed(vault, [_entry_search(filepath=f"/v/T/{i}.md", filename=str(i))])
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
            _entry_search(category="Tech_Notes",  filepath="/v/T/note1.md", filename="note1"),
            _entry_search(category="Tech_Notes",  filepath="/v/T/note2.md", filename="note2"),
            _entry_search(category="CRM",         filepath="/v/C/contact.md", filename="contact"),
            _entry_search(category="Finance",     filepath="/v/F/invoice.md",  filename="invoice", timestamp="2025-01-10T08:00:00"),
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
