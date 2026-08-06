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
import unittest.mock as mock
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Silence startup warnings for tests (must be set before importing server)
# SRV-01: server._require_secret now fails CLOSED, so an empty OMNI_GUI_SECRET
# 403s every route instead of disabling auth. Every server test module uses this
# SAME literal on purpose: the env var is process-global and pytest imports all
# modules before running any test, so differing values would make the suite
# order-dependent.
GUI_SECRET = "omni-test-secret-0123456789abcdef"
os.environ["OMNI_GUI_SECRET"] = GUI_SECRET
_AUTH = {"X-Omni-Secret": GUI_SECRET}


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
    project: str = "Tech_Notes",
    filepath: str = "/vault/Tech_Notes/test-note.md",
    filename: str = "test-note",
    source_url: str | None = None,
    confidence: float = 0.95,
    timestamp: str = "2025-06-17T10:00:00",
    input_type: str = "text",
    model: str = "llama3.2",
) -> dict:
    return {
        "project":    project,
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
    project: str    = "Tech_Notes",
    filepath: str   = "/v/T/note.md",
    filename: str   = "note",
    source_url: str = "",
    timestamp: str  = "2025-06-17T10:00:00",
) -> dict:
    return {
        "project":    project,
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

    def test_reinit_after_db_file_deleted_midprocess(self):
        """OF-12: if the db file vanishes while the process runs, the _INITIALIZED memo would
        skip DDL on the next open and leave the recreated file empty. init_db must re-apply the
        schema when the core table is missing."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            init_db(vault).close()  # populates _INITIALIZED for this path
            get_db_path(vault).unlink()  # file gone, but the memo still says "initialized"
            conn = init_db(vault)
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.close()
            self.assertIn("captures", tables, "schema must be re-applied after the file is deleted")
            self.assertIn("captures_fts", tables)


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
            self.assertEqual(row["project"],   "Tech_Notes")
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
            log_capture_db({"project": "Test"}, vault)  # no exception


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
                _entry_index(project="CRM",       filepath=f"/vault/CRM/note-{i}.md", filename=f"note-{i}")
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
            # A captures.jsonl on disk predates the `category`->`project` rename by definition,
            # so these rows keep the legacy key -- migrate_jsonl's fallback is what reads it.
            with open(jpath, "w") as f:
                f.write('{"category":"CRM","filepath":"/vault/x.md","filename":"x","timestamp":"2025-01-01T00:00:00"}\n')
                f.write("NOT JSON\n")
                f.write('{"category":"Finance","filepath":"/vault/y.md","filename":"y","timestamp":"2025-01-01T00:00:00"}\n')
            n = migrate_jsonl(jpath, vault)
            self.assertEqual(n, 2)


class TestSearch(unittest.TestCase):
    def _populate(self, vault: Path) -> None:
        entries = [
            _entry_index(project="Tech_Notes",  filepath="/v/T/asyncio.md",  filename="asyncio",   source_url=None),
            _entry_index(project="CRM",         filepath="/v/C/acme.md",      filename="acme",      source_url="https://acme.com"),
            _entry_index(project="Finance",     filepath="/v/F/invoice.md",   filename="invoice",   timestamp="2025-01-15T08:00:00"),
            _entry_index(project="Tech_Notes",  filepath="/v/T/docker.md",    filename="docker",    source_url="https://docs.docker.com"),
        ]
        for e in entries:
            log_capture_db(e, vault)

    def test_empty_query_returns_all(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault)
            self.assertEqual(len(results), 4)

    def test_fts_matches_project(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("Tech_Notes", vault)
            self.assertTrue(len(results) >= 2)
            for r in results:
                self.assertEqual(r["project"], "Tech_Notes")

    def test_fts_matches_filename(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("docker", vault)
            self.assertEqual(len(results), 1)
            self.assertIn("docker", results[0]["path"])

    def test_project_filter(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault, project="CRM")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["project"], "CRM")

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

    def test_offset_default_matches_pre_fr27_behavior(self):
        """FR-27 backward-compat: omitting offset must behave byte-identically
        to before it existed."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            no_offset_kw = search("", vault, limit=2)
            explicit_zero = search("", vault, limit=2, offset=0)
            self.assertEqual(no_offset_kw, explicit_zero)

    def test_offset_pages_through_without_repeating(self):
        """FR-27: fetching limit=k, offset=k must return the NEXT k rows, not
        page 1 again -- the defect this task fixes (no way to reach rows 201+
        under the old hard limit clamp, now generalized: no way to reach rows
        k+1..2k under any limit)."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            for i in range(6):
                log_capture_db(
                    _entry_index(
                        filepath=f"/v/T/note{i}.md", filename=f"note{i}",
                        timestamp=f"2025-01-{i + 1:02d}T00:00:00",
                    ),
                    vault,
                )
            page1 = search("", vault, limit=3, offset=0)
            page2 = search("", vault, limit=3, offset=3)
            self.assertEqual(len(page1), 3)
            self.assertEqual(len(page2), 3)
            paths1 = {r["path"] for r in page1}
            paths2 = {r["path"] for r in page2}
            self.assertEqual(paths1 & paths2, set(), "page 2 must not repeat page 1")
            # Newest-first browse order: page1 = note5,4,3 ; page2 = note2,1,0.
            self.assertEqual([r["filename"] for r in page1], ["note5", "note4", "note3"])
            self.assertEqual([r["filename"] for r in page2], ["note2", "note1", "note0"])

    def test_offset_past_end_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            results = search("", vault, limit=10, offset=100)
            self.assertEqual(results, [])

    def test_negative_offset_clamped_to_zero(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            self.assertEqual(search("", vault, limit=2, offset=-5), search("", vault, limit=2, offset=0))


class TestTieredSearch(unittest.TestCase):
    """P-DSEARCH: substring + exact + bm25-relevance tiers (ISS-011, ISS-012)."""

    def _write_note(self, vault: Path, project: str, name: str, body: str, **kw) -> None:
        project_dir = vault / project
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / f"{name}.md"
        path.write_text(f"---\ntitle: {name}\n---\n{body}\n", encoding="utf-8")
        log_capture_db(_entry_index(filepath=str(path), filename=name, project=project, **kw), vault)

    def test_substring_tier_finds_non_token_boundary_fragment(self):
        """'bug' inside 'debugger' is not a token/prefix match for FTS5 (the
        token starts with 'deb', not 'bug') -- only the raw LIKE net (item 3,
        tier 'substring') can find it."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._write_note(vault, "Tech_Notes", "debug-note", "An embedded debugger reference.")

            results = search("bug", vault)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["tier"], "substring")
            self.assertAlmostEqual(results[0]["score"], 0.35)

    def test_hyphenated_query_matches_hyphenated_index_term(self):
        """ISS-011: 'QA-CLIPTEST' must match even though FTS5's unicode61
        tokenizer splits the hyphen into separate index terms at write time."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._write_note(vault, "Unprocessed_Captures", "clip", "QA-CLIPTEST marker text.")

            results = search("QA-CLIPTEST", vault)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["filename"], "clip")

    def test_exact_phrase_tier_requires_adjacency(self):
        """Two adjacent words land in the 'exact' tier (FTS5 phrase match) --
        distinct from the looser per-token AND match ('substring')."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._write_note(vault, "Tech_Notes", "ml", "A machine learning pipeline overview.")

            results = search("machine learning", vault)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["tier"], "exact")

    def test_bm25_orders_by_relevance_not_recency(self):
        """The older-but-more-relevant note must rank ABOVE the newer-but-
        barely-relevant one -- the old `ORDER BY timestamp DESC` would have
        put them the other way around."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._write_note(
                vault, "Tech_Notes", "rocket-heavy",
                "rocket rocket rocket rocket engines",
                timestamp="2025-01-01T00:00:00",
            )
            self._write_note(
                vault, "Tech_Notes", "rocket-mention",
                "A short note mentioning a rocket in passing, among many other "
                "unrelated words that pad out this document considerably.",
                timestamp="2025-06-01T00:00:00",
            )

            results = search("rocket", vault)
            self.assertGreaterEqual(len(results), 2)
            self.assertEqual(results[0]["filename"], "rocket-heavy",
                              "bm25 relevance must win over recency")

    def test_offset_pages_through_scored_tier_without_repeating(self):
        """FR-27: pagination must hold for the bm25-scored/re-sorted path too,
        not just the blank-query browse path -- the whole point of slicing
        combined[offset:offset+limit] AFTER the global sort, rather than
        offsetting each tier's own SQL independently."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            for i in range(6):
                self._write_note(
                    vault, "Tech_Notes", f"rocket-{i}",
                    f"rocket rocket rocket engines variant {i}",
                )
            page1 = search("rocket", vault, limit=3, offset=0)
            page2 = search("rocket", vault, limit=3, offset=3)
            self.assertEqual(len(page1), 3)
            self.assertEqual(len(page2), 3)
            names1 = {r["filename"] for r in page1}
            names2 = {r["filename"] for r in page2}
            self.assertEqual(names1 & names2, set(), "page 2 must not repeat page 1")
            self.assertEqual(names1 | names2, {f"rocket-{i}" for i in range(6)})

    def test_blank_query_still_orders_by_recency_with_null_tier(self):
        """A blank query keeps the old 'browse everything, newest first'
        behavior -- there's nothing to rank by relevance."""
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._write_note(vault, "Tech_Notes", "a", "alpha", timestamp="2025-01-01T00:00:00")
            self._write_note(vault, "Tech_Notes", "b", "beta", timestamp="2025-06-01T00:00:00")

            results = search("", vault)
            self.assertEqual(results[0]["filename"], "b")
            self.assertIsNone(results[0]["tier"])
            self.assertIsNone(results[0]["score"])


class TestSemanticFusion(unittest.TestCase):
    """P-DSEARCH item 6: GET /search fuses the semantic tier server-side."""

    def _make_client(self, vault: Path) -> "TestClient":
        import server
        server._get_vault_root = lambda: vault   # type: ignore[attr-defined]
        return TestClient(server.app, headers=_AUTH)

    def test_semantic_tier_surfaced_with_score(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            fake_row = {
                "path": "Tech_Notes/related.md",
                "similarity": 0.87,
                "excerpt": "…",
                "category": "Tech_Notes",
            }
            with mock.patch.object(vector_store, "semantic_search", return_value=[fake_row]):
                data = client.get("/search?q=something").json()

            tiers = {r["tier"] for r in data["results"]}
            self.assertIn("semantic", tiers)
            sem = next(r for r in data["results"] if r["tier"] == "semantic")
            self.assertEqual(sem["score"], 0.87)
            self.assertEqual(sem["path"], "Tech_Notes/related.md")

    def test_semantic_tier_publishes_modified_from_vault_relative_path(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_dir = vault / "Tech_Notes"
            note_dir.mkdir(parents=True)
            note_path = note_dir / "related.md"
            note_path.write_text("---\ntitle: related\n---\nbody\n", encoding="utf-8")
            client = self._make_client(vault)
            import vector_store
            fake_row = {
                "path": "Tech_Notes/related.md",
                "similarity": 0.87,
                "excerpt": "…",
                "category": "Tech_Notes",
            }
            with mock.patch.object(vector_store, "semantic_search", return_value=[fake_row]):
                data = client.get("/search?q=something").json()

            sem = next(r for r in data["results"] if r["tier"] == "semantic")
            self.assertIsInstance(sem["modified"], float)
            self.assertAlmostEqual(sem["modified"], note_path.stat().st_mtime, places=3)

    def test_rescue_fires_when_no_keyword_hit_and_top_semantic_below_floor(self):
        """FR-13/FR-28: the true match at rank #1 below min_similarity, with
        nothing from the keyword tier, must still be surfaced (honestly
        labelled) when it genuinely paraphrases the query -- i.e. shares a
        meaningful token with it -- rather than silently dropped. This is the
        measured dominant failure FR-13 fixes; FR-28 narrows *which*
        below-floor candidates qualify, it doesn't kill the feature."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            near_miss = {
                "path": "Tech_Notes/near-miss.md",
                "similarity": 0.32,
                "excerpt": "A quick paraphrase of the sync workflow.",
                "category": "Tech_Notes",
                "below_threshold": True,
            }
            # Empty vault -> real idx_search legitimately returns [] (no keyword hit).
            with mock.patch.object(vector_store, "semantic_search", return_value=[near_miss]):
                data = client.get("/search?q=paraphrase+query").json()

            sem = next(r for r in data["results"] if r["tier"] == "semantic")
            self.assertEqual(sem["path"], "Tech_Notes/near-miss.md")
            self.assertEqual(sem["score"], 0.32)
            self.assertTrue(sem["rescued"])

    def test_rescue_stays_silent_on_gibberish_query(self):
        """FR-28 (the regression this task fixes): a query that shares no
        meaningful token with anything must NOT be rescued, even though its
        top semantic candidate scores higher cosine than a genuine near-miss
        would. Measured on the shipped release: the literal gibberish string
        below returned a "Related - 39%" row against a real note; "no
        results" must be reachable again."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            gibberish_hit = {
                "path": "Tech_Notes/unrelated.md",
                "similarity": 0.39,
                "excerpt": "Notes about syncing files to Google Drive on schedule.",
                "category": "Tech_Notes",
                "below_threshold": True,
            }
            with mock.patch.object(vector_store, "semantic_search", return_value=[gibberish_hit]):
                data = client.get(
                    "/search?q=zxqvbfhwpq93+qwoiuty+aksjdhf+zzxq47"
                ).json()

            self.assertEqual(data["results"], [])
            self.assertEqual(data["count"], 0)

    def test_rescue_does_not_fire_when_keyword_tier_already_answered(self):
        """FR-13 hard constraint: a below-floor semantic candidate must never
        be rescued once the keyword tier already returned results."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import index_writer
            import vector_store
            keyword_row = {
                "id": 1, "timestamp": "2025-06-17T10:00:00", "project": "Tech_Notes",
                "path": "/vault/Tech_Notes/hit.md", "filename": "hit",
                "source_url": None, "confidence": 0.9, "tags": "",
                "tier": "exact", "score": 0.9,
            }
            near_miss = {
                "path": "Tech_Notes/near-miss.md",
                "similarity": 0.32,
                "excerpt": "…",
                "category": "Tech_Notes",
                "below_threshold": True,
            }
            with mock.patch.object(index_writer, "search", return_value=[keyword_row]), \
                 mock.patch.object(vector_store, "semantic_search", return_value=[near_miss]):
                data = client.get("/search?q=paraphrase+query").json()

            self.assertFalse(any(r.get("tier") == "semantic" for r in data["results"]),
                              "below-floor candidate must not surface once the keyword tier answered")
            self.assertFalse(any(r.get("rescued") for r in data["results"]))

    def test_rescue_never_surfaces_more_than_the_top_candidate(self):
        """FR-13: rescue is a single top-rank surface, never a second ranking
        pass -- a second below-floor candidate must not also appear."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            near_miss_1 = {
                "path": "Tech_Notes/near-miss-1.md", "similarity": 0.33,
                "excerpt": "A paraphrase of the query, roughly.",
                "category": "Tech_Notes", "below_threshold": True,
            }
            near_miss_2 = {
                "path": "Tech_Notes/near-miss-2.md", "similarity": 0.31,
                "excerpt": "…", "category": "Tech_Notes", "below_threshold": True,
            }
            with mock.patch.object(vector_store, "semantic_search",
                                    return_value=[near_miss_1, near_miss_2]):
                data = client.get("/search?q=paraphrase+query").json()

            sem_paths = {r["path"] for r in data["results"] if r["tier"] == "semantic"}
            self.assertEqual(sem_paths, {"Tech_Notes/near-miss-1.md"})

    def test_rerank_promotes_lexical_match_over_higher_cosine_noise(self):
        """FR-28 re-rank half (the 1-of-8 measured failure: true match
        present among semantic candidates but outranked by noise): with the
        keyword tier empty, a lower-cosine candidate sharing a meaningful
        token with the query must sort ABOVE a higher-cosine candidate that
        shares none -- while each row's published `score` stays its own
        honest cosine value, unchanged by the reorder."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            # Deliberately parked under "Misc" (not "Tech_Notes") so neither
            # row's own path tokenizes into a spurious match against the
            # query -- only the excerpt content should decide this.
            noisy_but_high_cosine = {
                "path": "Misc/noise.md", "similarity": 0.55,
                "excerpt": "Completely unrelated filler content.",
                "category": "Misc",
            }
            true_match_lower_cosine = {
                "path": "Misc/true-match.md", "similarity": 0.45,
                "excerpt": "How to sync notes to Google Drive automatically.",
                "category": "Misc",
            }
            with mock.patch.object(
                vector_store, "semantic_search",
                return_value=[noisy_but_high_cosine, true_match_lower_cosine],
            ):
                data = client.get("/search?q=sync+drive+notes").json()

            sem = [r for r in data["results"] if r["tier"] == "semantic"]
            self.assertEqual([r["path"] for r in sem],
                              ["Misc/true-match.md", "Misc/noise.md"],
                              "lexically-matching candidate must outrank higher-cosine noise")
            # Published scores stay the honest cosine values -- reorder never
            # touches the number.
            by_path = {r["path"]: r["score"] for r in sem}
            self.assertEqual(by_path["Misc/true-match.md"], 0.45)
            self.assertEqual(by_path["Misc/noise.md"], 0.55)


class TestStats(unittest.TestCase):
    def _populate(self, vault: Path) -> None:
        for i, (cat, fp) in enumerate([
            ("Tech_Notes", "/v/T/note1.md"),
            ("Tech_Notes", "/v/T/note2.md"),
            ("CRM",        "/v/C/contact.md"),
        ]):
            log_capture_db(_entry_index(project=cat, filepath=fp, filename=f"note{i}"), vault)

    def test_total(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s = stats(vault)
            self.assertEqual(s["total"], 3)

    def test_by_project_structure(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s    = stats(vault)
            cats = {r["project"]: r["count"] for r in s["by_project"]}
            self.assertEqual(cats["Tech_Notes"], 2)
            self.assertEqual(cats["CRM"],        1)

    def test_pct_sums_to_100(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            self._populate(vault)
            s    = stats(vault)
            total_pct = sum(r["pct"] for r in s["by_project"])
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
            self.assertEqual(s["by_project"], [])


class TestProjectColumnAgreesWithFrontmatterCache(unittest.TestCase):
    """Task 11: the renamed `project` column is written from the note's directory name, and the
    `project:` frontmatter line is written from resolve_project(body, reg) -- both derived from the
    SAME `#project@<name>` body tag (contract §1.3), so they must never disagree for one note."""

    def test_db_column_and_frontmatter_cache_agree_for_the_same_note(self):
        from note_model import parse_note, serialize_note
        from project_registry import empty_registry

        with tempfile.TemporaryDirectory() as td:
            vault = _vault(Path(td))
            reg = empty_registry()
            reg["projects"]["research"] = {
                "description": "", "created": "", "modified": "", "device": "",
            }

            note = parse_note("---\nid: x\n---\n#project@research\n\nsome body\n")
            serialized = serialize_note(note, reg)

            note_dir = vault / "research"
            note_dir.mkdir(parents=True)
            note_path = note_dir / "note.md"
            note_path.write_text(serialized, encoding="utf-8")

            # Persist the registry so the DB side (which loads it from disk when no
            # registry is passed) resolves the same `#project@research` tag the
            # frontmatter side just resolved from the in-memory `reg`.
            from project_registry import save as save_registry
            save_registry(vault, reg)

            upsert_capture_from_file(vault, note_path)
            conn = init_db(vault)
            row = conn.execute("SELECT project FROM captures WHERE path = ?", (str(note_path),)).fetchone()
            conn.close()

            from frontmatter import read_all_fields
            fm_project = read_all_fields(serialized)["project"].strip("[]")

            self.assertEqual(row["project"], "research")
            self.assertEqual(fm_project, "research")
            self.assertEqual(row["project"], fm_project)


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
                "INSERT INTO captures (timestamp, project, path, filename) VALUES (?,?,?,?)",
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
        return TestClient(server.app, headers=_AUTH)

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
                _entry_search(project="Tech_Notes",  filepath="/v/T/docker.md",   filename="docker"),
                _entry_search(project="CRM",         filepath="/v/C/acme.md",     filename="acme"),
            ])
            client  = self._make_client(vault)
            data    = client.get("/search?q=docker").json()
            paths   = [r["path"] for r in data["results"]]
            self.assertTrue(any("docker" in p for p in paths))
            self.assertFalse(any("acme" in p for p in paths))

    def test_search_project_filter(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [
                _entry_search(project="Tech_Notes", filepath="/v/T/a.md"),
                _entry_search(project="CRM",        filepath="/v/C/b.md"),
            ])
            client = self._make_client(vault)
            data   = client.get("/search?project=CRM").json()
            for r in data["results"]:
                self.assertEqual(r["project"], "CRM")

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

    # GET /search?offset= — FR-27
    def test_search_offset_pages_without_repeating(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            for i in range(6):
                self._seed(vault, [_entry_search(filepath=f"/v/T/{i}.md", filename=str(i),
                                                  timestamp=f"2025-01-{i + 1:02d}T00:00:00")])
            client = self._make_client(vault)
            page1 = client.get("/search?limit=3&offset=0").json()["results"]
            page2 = client.get("/search?limit=3&offset=3").json()["results"]
            self.assertEqual(len(page1), 3)
            self.assertEqual(len(page2), 3)
            paths1 = {r["path"] for r in page1}
            paths2 = {r["path"] for r in page2}
            self.assertEqual(paths1 & paths2, set(), "page 2 must not repeat page 1")

    def test_search_omitting_offset_matches_explicit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [_entry_search(filepath="/v/T/a.md", filename="a"),
                                _entry_search(filepath="/v/T/b.md", filename="b")])
            client = self._make_client(vault)
            no_offset = client.get("/search").json()
            explicit_zero = client.get("/search?offset=0").json()
            self.assertEqual(no_offset["results"], explicit_zero["results"])

    def test_search_semantic_tier_skipped_when_offset_positive(self):
        """FR-27: the semantic rescue/related band is a fixed top-k, not a
        paginated corpus -- it must only be computed on page 1 (offset=0),
        never re-run (and re-surfaced) on page 2+."""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            import vector_store
            fake_row = {
                "path": "Tech_Notes/related.md", "similarity": 0.87,
                "excerpt": "…", "category": "Tech_Notes",
            }
            with mock.patch.object(vector_store, "semantic_search", return_value=[fake_row]) as m:
                data = client.get("/search?q=something&offset=25").json()
            m.assert_not_called()
            self.assertFalse(any(r["tier"] == "semantic" for r in data["results"]))

    # GET /search — projects screen "recently edited" sort needs a modified field
    def test_search_result_publishes_note_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_dir = vault / "Tech_Notes"
            note_dir.mkdir(parents=True)
            note_path = note_dir / "docker.md"
            note_path.write_text("---\ntitle: docker\n---\nbody\n", encoding="utf-8")
            self._seed(vault, [_entry_search(filepath=str(note_path), filename="docker")])
            client = self._make_client(vault)
            data = client.get("/search?q=docker").json()
            row = next(r for r in data["results"] if r["filename"] == "docker")
            self.assertIsInstance(row["modified"], float)
            self.assertAlmostEqual(row["modified"], note_path.stat().st_mtime, places=3)

    def test_search_result_modified_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault, [_entry_search(filepath="/v/T/gone.md", filename="gone")])
            client = self._make_client(vault)
            data = client.get("/search?q=gone").json()
            row = next(r for r in data["results"] if r["filename"] == "gone")
            self.assertIsNone(row["modified"])


class TestSearchIncludeVectors(unittest.TestCase):
    """`include_vectors` (opt-in, STARS "smart connections"): every result
    row gains `vec` -- that note's chunk vectors mean-pooled+normalized to
    one vector -- only when explicitly requested, and `null` for a note
    with no embedding rather than an error."""

    def _make_client(self, vault: Path) -> "TestClient":
        import server
        server._get_vault_root = lambda: vault  # type: ignore[attr-defined]
        return TestClient(server.app, headers=_AUTH)

    def _write_note(self, vault: Path, project: str, name: str) -> Path:
        note_dir = vault / project
        note_dir.mkdir(parents=True, exist_ok=True)
        note_path = note_dir / f"{name}.md"
        note_path.write_text(f"---\ntitle: {name}\n---\nbody\n", encoding="utf-8")
        return note_path

    def _insert_embedding(self, vault: Path, doc_id: str, vec: list[float]) -> None:
        import numpy as np
        import vector_store
        blob = np.array(vec, dtype=np.float32).tobytes()
        with vector_store._connect(vault) as conn:
            conn.execute(
                "INSERT INTO embeddings (id, embedding, document, category) VALUES (?,?,?,?)",
                (doc_id, blob, "doc", "Tech_Notes"),
            )

    def test_vec_field_absent_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_path = self._write_note(vault, "Tech_Notes", "docker")
            log_capture_db(_entry_search(filepath=str(note_path), filename="docker"), vault)
            self._insert_embedding(vault, "Tech_Notes/docker.md", [1.0, 0.0, 0.0, 0.0])
            client = self._make_client(vault)

            data = client.get("/search?q=docker").json()

            row = next(r for r in data["results"] if r["filename"] == "docker")
            self.assertNotIn("vec", row)

    def test_vec_present_and_mean_pooled_across_chunks(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_path = self._write_note(vault, "Tech_Notes", "docker")
            log_capture_db(_entry_search(filepath=str(note_path), filename="docker"), vault)
            # Two chunk vectors for the same note -- mean-pool then L2-normalize
            # must match vector_store.note_vectors' own behaviour exactly.
            self._insert_embedding(vault, "Tech_Notes/docker.md::c0", [1.0, 0.0, 0.0, 0.0])
            self._insert_embedding(vault, "Tech_Notes/docker.md::c1", [0.0, 1.0, 0.0, 0.0])
            client = self._make_client(vault)

            data = client.get("/search?q=docker&include_vectors=true").json()

            row = next(r for r in data["results"] if r["filename"] == "docker")
            self.assertIn("vec", row)
            expected = [0.7071067811865475, 0.7071067811865475, 0.0, 0.0]
            self.assertEqual(len(row["vec"]), 4)
            for got, want in zip(row["vec"], expected):
                self.assertAlmostEqual(got, want, places=5)

    def test_vec_null_when_note_has_no_embedding(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_path = self._write_note(vault, "Tech_Notes", "unembedded")
            log_capture_db(_entry_search(filepath=str(note_path), filename="unembedded"), vault)
            # No vectors.db row for this note at all -- must degrade to null,
            # not raise, and must not affect any other result.
            client = self._make_client(vault)

            data = client.get("/search?q=unembedded&include_vectors=true").json()

            row = next(r for r in data["results"] if r["filename"] == "unembedded")
            self.assertIn("vec", row)
            self.assertIsNone(row["vec"])

    def test_vec_null_when_vectors_db_missing_entirely(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            note_path = self._write_note(vault, "Tech_Notes", "docker")
            log_capture_db(_entry_search(filepath=str(note_path), filename="docker"), vault)
            client = self._make_client(vault)
            # vectors.db was never created for this vault at all.

            data = client.get("/search?q=docker&include_vectors=true").json()

            row = next(r for r in data["results"] if r["filename"] == "docker")
            self.assertIsNone(row["vec"])


class TestStatsEndpoint(unittest.TestCase):
    def _make_client(self, vault: Path) -> "TestClient":
        import server
        server._get_vault_root = lambda: vault   # type: ignore[attr-defined]
        return TestClient(server.app, headers=_AUTH)

    def _seed(self, vault: Path) -> None:
        entries = [
            _entry_search(project="Tech_Notes",  filepath="/v/T/note1.md", filename="note1"),
            _entry_search(project="Tech_Notes",  filepath="/v/T/note2.md", filename="note2"),
            _entry_search(project="CRM",         filepath="/v/C/contact.md", filename="contact"),
            _entry_search(project="Finance",     filepath="/v/F/invoice.md",  filename="invoice", timestamp="2025-01-10T08:00:00"),
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
            self.assertIn("total",      data)
            self.assertIn("by_project", data)
            self.assertIn("by_day",     data)
            self.assertIn("recent",     data)

    def test_stats_total(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault)
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            self.assertEqual(data["total"], 4)

    def test_stats_by_project(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            self._seed(vault)
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            cats   = {r["project"]: r["count"] for r in data["by_project"]}
            self.assertEqual(cats["Tech_Notes"], 2)
            self.assertEqual(cats["CRM"],        1)

    def test_stats_empty_vault(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            client = self._make_client(vault)
            data   = client.get("/stats").json()
            self.assertEqual(data["total"],      0)
            self.assertEqual(data["by_project"], [])
            self.assertEqual(data["recent"],     [])


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
