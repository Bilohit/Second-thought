"""
test_index_writer.py
--------------------
Unit tests for index_writer.py — covers schema init, upsert, migration,
full-text search, and stats aggregation.

Run:
    python -m pytest test_index_writer.py -v
    # or directly:
    python test_index_writer.py
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

# Adjust sys.path so we can import index_writer without installing the package
import sys
sys.path.insert(0, str(Path(__file__).parent))

from index_writer import (
    get_db_path,
    init_db,
    log_capture_db,
    migrate_jsonl,
    search,
    stats,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vault(tmp: Path) -> Path:
    """Create a minimal vault directory tree inside tmp."""
    vault = tmp / "vault"
    vault.mkdir()
    return vault


def _entry(
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


# ── Tests ─────────────────────────────────────────────────────────────────────

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
            e     = _entry()
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
            e     = _entry(confidence=0.8)
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
            e     = {**_entry(), "tags": ["python", "async"]}
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
                _entry(category="CRM",       filepath=f"/vault/CRM/note-{i}.md", filename=f"note-{i}")
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
            e       = _entry(filepath="/vault/CRM/note-1.md")
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
            _entry(category="Tech_Notes",  filepath="/v/T/asyncio.md",  filename="asyncio",   source_url=None),
            _entry(category="CRM",         filepath="/v/C/acme.md",      filename="acme",      source_url="https://acme.com"),
            _entry(category="Finance",     filepath="/v/F/invoice.md",   filename="invoice",   timestamp="2025-01-15T08:00:00"),
            _entry(category="Tech_Notes",  filepath="/v/T/docker.md",    filename="docker",    source_url="https://docs.docker.com"),
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
            log_capture_db(_entry(category=cat, filepath=fp, filename=f"note{i}"), vault)

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


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
