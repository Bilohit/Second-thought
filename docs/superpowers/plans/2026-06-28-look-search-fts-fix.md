# Look Vault Search & Chat FTS Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore exact-keyword search and Chat retrieval in the Look panel by fixing the broken FTS5 maintenance triggers that silently block all index updates, then force a one-time heal of already-stale data and lock the behavior with regression tests.

**Architecture:** `captures.db` holds a SQLite FTS5 index (`captures_fts`) over each vault note. The table was migrated from external-content (`content=captures`) to **standard internal** storage, but the `AFTER UPDATE`/`AFTER DELETE` triggers still use the *external-content* delete command (`INSERT INTO captures_fts(captures_fts, rowid, body) VALUES('delete', …)`). On an internal FTS5 table that command raises `SQL logic error`, so every `UPDATE`/`DELETE` on `captures` fails. Because all callers swallow exceptions (`log_capture_db`, `reindex_bodies`, `upsert_capture_from_file`, `sync_vault_indexes`), the index can never be maintained or rebuilt — yet the GUI reports "index up to date". Fix the triggers to use the internal-table delete (`DELETE FROM captures_fts WHERE rowid = …`), force one rebuild of existing stale rows, and verify the already-applied upstream fixes now take effect.

**Tech Stack:** Python 3, stdlib `sqlite3` (FTS5), `unittest` (existing test style in `test_index_writer.py`), FastAPI server endpoints, pytest runner.

## Global Constraints

Copied verbatim from `CLAUDE.md` — every task implicitly includes these:

- **Files are the source of truth; `captures.db`/`vectors.db`/`dedup_index.json` are derived indexes.** Never make a SQLite table authoritative over vault `.md` files. *(constrains: `storage_engine.py`, `index_writer.py`, `vector_store.py`)*
- **`_TRIGGERS_DDL` trigger bodies must stay in sync with `_row_fts_body()`** — the concatenation in the triggers and the Python helper must produce identical FTS body text (`category || ' ' || filename || ' ' || source_url || ' ' || tags || ' ' || body_excerpt`).
- **Non-trivial logic ships with one runnable check** — any new branch/parser/migration needs an `assert`-based `__main__` smoke block or a small `test_*.py`, and that check must be run (`pytest <file>`) before the change is considered done.
- **No new dependencies, no linter/formatter config, no abstraction for a single implementation.** Match surrounding file style exactly.
- **Preserve the `ponytail:` comment convention** — mark deliberate shortcuts with a named ceiling and upgrade path.
- Run all Python commands from `omni_capture/` (or with `omni_capture` on `PYTHONPATH`).

## Plugins & Skills — when to use which

| Where | Plugin / Skill | Why |
| --- | --- | --- |
| Driving this plan end-to-end | `superpowers:subagent-driven-development` (or `superpowers:executing-plans`) | One fresh worker per task, review between tasks. |
| Every task | `superpowers:test-driven-development` | Each task is written failing-test-first; this plan already encodes that order — follow it, do not skip the "verify it fails" step. |
| Before claiming any task done | `superpowers:verification-before-completion` | Run the exact `pytest` command shown and confirm the output before checking the box. No "should pass" claims. |
| If a task's stated root cause turns out wrong mid-fix | `superpowers:systematic-debugging` | The H1–H7 investigation already ran; only re-open it if a test contradicts this plan's diagnosis. |
| Task 1 & Task 2 (resist scope creep) | `ponytail:ponytail` + `ponytail:ponytail-review` | The trigger fix is ~6 lines and the rebuild is one gated loop. Do NOT refactor the FTS layer, add a migration framework, or generalize. Mark the full-rebuild ceiling with a `ponytail:` comment (Task 2 specifies the exact text). |
| Task 4 cleanup | `ponytail:ponytail` | Deleting the debug `#region agent log` blocks is pure deletion — the laziest correct change. |
| Locating any caller before editing | `caveman:cavecrew-investigator` (optional) | If you need to re-confirm callers of `init_db`/`search`/`hybrid_retrieve`, dispatch this read-only agent; output is compressed. Not required — callers are already listed in this plan. |
| Writing the commits | `caveman:caveman-commit` | Conventional Commits, terse. Per user memory: **no `Co-Authored-By` footers**, and **do not auto-commit** — stage and let the user run the commit, or commit only when the user asks. |

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `omni_capture/index_writer.py` | FTS5 schema, triggers, search, rebuild | Modify `_TRIGGERS_DDL`; add `_rebuild_fts_once()`; call it from `_migrate_schema()`; delete debug log block in `search()`. |
| `omni_capture/rag_engine.py` | Chat hybrid retrieval | Delete debug log block in `hybrid_retrieve()`. (Retrieval logic itself is already correct — see Task 3 verification.) |
| `omni_capture/test_index_writer.py` | Index/trigger tests (`unittest`) | Add trigger-update + rebuild regression tests. |
| `omni_capture/test_rag_engine.py` | Chat retrieval tests | Add FTS-only-hit-survives-floor regression test. |
| `<vault_root>/debug-a05393.log` | Investigation artifact | Delete (Task 4). |

---

## Task 1: Fix the FTS5 maintenance triggers (root blocker, H7)

**Files:**
- Modify: `omni_capture/index_writer.py` — `_TRIGGERS_DDL` at lines 96–143 (the `captures_ad` and `captures_au` trigger bodies).
- Test: `omni_capture/test_index_writer.py`

**Interfaces:**
- Consumes: existing `init_db(vault_root) -> sqlite3.Connection`, `log_capture_db(entry, vault_root)`, `search(query, vault_root, ...)`, `_row_fts_body(...)`.
- Produces: triggers that maintain `captures_fts` correctly on `UPDATE`/`DELETE` of `captures` (no behavior-signature change; the contract is "UPDATE/DELETE on captures no longer raises and FTS reflects the change").

**Root cause recap:** `captures_ad`/`captures_au` use `INSERT INTO captures_fts(captures_fts, rowid, body) VALUES('delete', old.id, …)`. That `'delete'` special command is only valid for **external-content** FTS5 tables. `captures_fts` is now `CREATE VIRTUAL TABLE captures_fts USING fts5(body)` (standard internal storage, see `index_writer.py:81` and `_migrate_fts_internal`). On an internal table that command raises `SQL logic error`, so any `UPDATE captures` / `DELETE FROM captures` aborts. The correct delete for an internal FTS5 table is a plain `DELETE FROM captures_fts WHERE rowid = old.id;`.

- [ ] **Step 1: Write the failing test**

Add to `omni_capture/test_index_writer.py` (match the existing `unittest.TestCase` + `tempfile` style already used in that file). Place it inside the existing test class, or in a new `class TestTriggerMaintenance(unittest.TestCase)`:

```python
def test_update_captures_maintains_fts_without_error(self):
    """H7 regression: updating a captures row must not raise SQL logic error
    and must make the new body_excerpt searchable (and the old text gone)."""
    import tempfile
    from pathlib import Path
    from index_writer import init_db, log_capture_db, search

    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        note = vault / "note.md"
        note.write_text("triceratops roamed the plains", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-01T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "note.md"},
            vault,
        )
        # First insert is searchable
        self.assertEqual(len(search("triceratops", vault)), 1)

        # Rewrite the note and re-upsert -> fires AFTER UPDATE trigger.
        note.write_text("a stegosaurus appeared", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-02T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "note.md"},
            vault,
        )

        # New term is found, old term is gone — proves the UPDATE trigger ran.
        self.assertEqual(len(search("stegosaurus", vault)), 1)
        self.assertEqual(len(search("triceratops", vault)), 0)

def test_delete_captures_removes_fts_row(self):
    """H7 regression: deleting a captures row must remove its FTS shadow."""
    import tempfile
    from pathlib import Path
    from index_writer import init_db, log_capture_db, search, remove_capture_by_path

    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        note = vault / "note.md"
        note.write_text("velociraptor pack hunting", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-01T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "note.md"},
            vault,
        )
        self.assertEqual(len(search("velociraptor", vault)), 1)
        remove_capture_by_path(vault, note)
        self.assertEqual(len(search("velociraptor", vault)), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_index_writer.py -k "trigger or delete_captures or update_captures" -v`

Expected: FAIL. `test_update_captures_maintains_fts_without_error` fails because `log_capture_db`'s `ON CONFLICT DO UPDATE` fires `captures_au`, which raises `sqlite3.OperationalError: SQL logic error` (swallowed inside `log_capture_db`, so the row's `body_excerpt` is never updated) → `search("stegosaurus")` returns 0 and/or `search("triceratops")` still returns 1. `test_delete_captures_removes_fts_row` fails for the same reason on `captures_ad`.

- [ ] **Step 3: Write minimal implementation**

In `omni_capture/index_writer.py`, replace the `captures_ad` and `captures_au` trigger definitions inside `_TRIGGERS_DDL` (lines 96–143). Keep `captures_ai` exactly as-is. The full corrected `_TRIGGERS_DDL` value:

```python
_TRIGGERS_DDL = """
DROP TRIGGER IF EXISTS captures_ai;
DROP TRIGGER IF EXISTS captures_ad;
DROP TRIGGER IF EXISTS captures_au;

CREATE TRIGGER captures_ai AFTER INSERT ON captures BEGIN
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'') || ' ' ||
        COALESCE(new.body_excerpt,'')
    );
END;

CREATE TRIGGER captures_ad AFTER DELETE ON captures BEGIN
    DELETE FROM captures_fts WHERE rowid = old.id;
END;

CREATE TRIGGER captures_au AFTER UPDATE ON captures BEGIN
    DELETE FROM captures_fts WHERE rowid = old.id;
    INSERT INTO captures_fts(rowid, body)
    VALUES (
        new.id,
        COALESCE(new.category,'') || ' ' ||
        COALESCE(new.filename,'') || ' ' ||
        COALESCE(new.source_url,'') || ' ' ||
        COALESCE(new.tags,'') || ' ' ||
        COALESCE(new.body_excerpt,'')
    );
END;
"""
```

Also update the stale comment block above `_TRIGGERS_DDL` (lines 91–95) so it no longer implies the external-content `'delete'` command is in use. Replace it with:

```python
# Trigger bodies must stay in sync with the captures_fts concatenation used
# by _row_fts_body() below. captures_fts is a standard (internal-storage)
# FTS5 table, so row removal uses a plain DELETE — NOT the external-content
# 'delete' command, which raises "SQL logic error" on an internal table.
# Re-CREATE'd unconditionally (not IF NOT EXISTS) because existing databases
# already have older trigger versions installed under these names.
```

Note: `_migrate_schema()` already runs `conn.executescript(_TRIGGERS_DDL)` on every `init_db()` (index_writer.py:222), and `_TRIGGERS_DDL` starts with `DROP TRIGGER IF EXISTS`, so existing vaults pick up the corrected triggers automatically on the next connection — no extra migration step needed for the triggers themselves. (Existing **stale FTS data** is healed separately in Task 2.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_index_writer.py -k "trigger or delete_captures or update_captures" -v`

Expected: PASS (both new tests).

- [ ] **Step 5: Run the full index test file to confirm no regression**

Run: `pytest test_index_writer.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/index_writer.py omni_capture/test_index_writer.py
git commit -m "fix(index): use internal FTS5 delete in triggers (H7 blocker)"
```

(Per user preference: do not auto-commit — run this only if the user asks, or leave staged for the user.)

---

## Task 2: Force a one-time rebuild of existing stale FTS data

**Files:**
- Modify: `omni_capture/index_writer.py` — add `_rebuild_fts_once()`; call it from `_migrate_schema()` (around line 220–223, after `_migrate_fts_internal` and after the triggers are re-installed).
- Test: `omni_capture/test_index_writer.py`

**Interfaces:**
- Consumes: `_row_fts_body(...)`, an open `sqlite3.Connection` with `row_factory = sqlite3.Row`.
- Produces: `_rebuild_fts_once(conn: sqlite3.Connection) -> None` — idempotent (gated by a `_meta` flag), rebuilds `captures_fts` from every `captures` row exactly once per vault.

**Why this is needed even after Task 1:** Task 1 fixes *future* maintenance, but rows that were written or edited while the triggers were broken have stale (or missing) FTS bodies. `reindex_bodies()` is gated by the `body_indexed_v65536` meta flag and may already be set to `'1'` from a prior partial run, so it will not re-run. A separate, freshly-keyed one-shot rebuild guarantees existing vaults are healed once after the trigger fix ships. Because `_migrate_schema()` now re-CREATEs correct triggers first, the rebuild's `INSERT`s are maintained correctly going forward.

- [ ] **Step 1: Write the failing test**

Add to `omni_capture/test_index_writer.py`:

```python
def test_rebuild_fts_once_heals_stale_index(self):
    """Simulate a DB whose FTS row is stale (text differs from captures.body_excerpt);
    a fresh init must rebuild it once so search matches the real body."""
    import tempfile, sqlite3
    from pathlib import Path
    from index_writer import init_db, log_capture_db, search, get_db_path

    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        note = vault / "note.md"
        note.write_text("ankylosaurus armored dinosaur", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-01T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "note.md"},
            vault,
        )
        self.assertEqual(len(search("ankylosaurus", vault)), 1)

        # Corrupt the FTS shadow directly to simulate stale data, and clear the
        # rebuild flag so the next init re-runs the heal.
        db = sqlite3.connect(str(get_db_path(vault)))
        db.execute("UPDATE captures_fts SET body = 'totally unrelated text'")
        db.execute("DELETE FROM _meta WHERE key = 'fts_rebuilt_trigger_fix_v1'")
        db.commit()
        db.close()

        # Sanity: stale FTS now misses the term.
        self.assertEqual(len(search("ankylosaurus", vault)), 0)

        # init_db() runs _migrate_schema() -> _rebuild_fts_once(): heal happens.
        init_db(vault).close()
        self.assertEqual(len(search("ankylosaurus", vault)), 1)

def test_rebuild_fts_once_is_idempotent(self):
    """Second init must NOT wipe the FTS (flag already set -> no-op)."""
    import tempfile
    from pathlib import Path
    from index_writer import init_db, log_capture_db, search

    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        note = vault / "note.md"
        note.write_text("brachiosaurus long neck", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-01T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "note.md"},
            vault,
        )
        init_db(vault).close()
        init_db(vault).close()
        self.assertEqual(len(search("brachiosaurus", vault)), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test_index_writer.py -k "rebuild_fts_once" -v`

Expected: FAIL — `_rebuild_fts_once` does not exist / is not called, so the stale-index test still returns 0 after re-init.

- [ ] **Step 3: Write minimal implementation**

Add this function to `omni_capture/index_writer.py` (place it directly above `_migrate_schema`):

```python
def _rebuild_fts_once(conn: sqlite3.Connection) -> None:
    """Heal existing FTS rows that went stale while the AFTER UPDATE/DELETE
    triggers were broken (see Task 1 / H7). Runs exactly once per vault,
    gated by a _meta flag. Safe to call on every init.

    ponytail: full DELETE + re-INSERT of every row. Fine for the small vaults
    this app targets; if a vault ever holds 100k+ notes, switch to a
    diff-based rebuild keyed on captures.hash.
    """
    flag = conn.execute(
        "SELECT value FROM _meta WHERE key = 'fts_rebuilt_trigger_fix_v1'"
    ).fetchone()
    if flag and flag[0] == "1":
        return

    rows = conn.execute(
        "SELECT id, category, filename, source_url, tags, body_excerpt FROM captures"
    ).fetchall()
    conn.execute("DELETE FROM captures_fts")
    for r in rows:
        body = _row_fts_body(
            r["category"], r["filename"], r["source_url"], r["tags"], r["body_excerpt"],
        )
        conn.execute(
            "INSERT INTO captures_fts(rowid, body) VALUES (?, ?)",
            (r["id"], body),
        )
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('fts_rebuilt_trigger_fix_v1', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = '1'"
    )
    print(f"[IndexWriter] rebuilt captures_fts ({len(rows)} rows) after trigger fix", flush=True)
```

Then call it from `_migrate_schema()`. The current body (lines 217–223) ends with two `commit()`s; add the rebuild after the triggers are installed:

```python
def _migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema upgrade for databases created before body_excerpt
    existed: adds the column if missing and unconditionally re-installs the
    FTS triggers so they pick up the new concatenation (CREATE TRIGGER IF NOT
    EXISTS in _DDL would silently keep the stale ones).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(captures)").fetchall()}
    if "body_excerpt" not in cols:
        conn.execute("ALTER TABLE captures ADD COLUMN body_excerpt TEXT")
    _migrate_fts_internal(conn)
    conn.commit()
    conn.executescript(_TRIGGERS_DDL)
    conn.commit()
    _rebuild_fts_once(conn)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test_index_writer.py -k "rebuild_fts_once" -v`

Expected: PASS (both tests).

- [ ] **Step 5: Run the full index test file**

Run: `pytest test_index_writer.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/index_writer.py omni_capture/test_index_writer.py
git commit -m "fix(index): one-time FTS rebuild to heal stale rows after trigger fix"
```

---

## Task 3: Lock the already-applied upstream fixes with regression tests (H1, H3, H4, H6)

**Files:**
- Test: `omni_capture/test_index_writer.py` (H1, H3)
- Test: `omni_capture/test_rag_engine.py` (H4, H6)

**Context — these fixes are already present in the working tree; this task only adds guards so they cannot silently regress:**
- **H1** — `_BODY_EXCERPT_MAX_CHARS = 65536` (index_writer.py:50); deep keywords are indexed.
- **H3** — `_sanitize_fts_query` (index_writer.py:547) emits prefix tokens (`dinosaur` → `dinosaur*`), so singular queries match plurals. The old behavior wrapped the term in strict quotes and dropped plural matches.
- **H4** — `_read_snippet(p, query)` (rag_engine.py:95) centers a 1500-char window on the first matching token instead of always `text[:1500]`, so deep keywords reach the LLM.
- **H6** — `hybrid_retrieve` (rag_engine.py:147) adds FTS paths to the RRF map **unconditionally** (rag_engine.py:182–183); only *semantic* paths are gated by `min_similarity_floor` (line 179). FTS-only hits survive.

- [ ] **Step 1: Write the failing tests (H1 + H3 in `test_index_writer.py`)**

```python
def test_deep_keyword_is_indexed_and_prefix_matched(self):
    """H1+H3: a keyword far past the old 4k cap is indexed, and a singular
    query prefix-matches it."""
    import tempfile
    from pathlib import Path
    from index_writer import log_capture_db, search

    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        note = vault / "deep.md"
        # 'dinosaurs' sits ~4800 chars in — past the retired 4000-char cap.
        filler = "lorem ipsum " * 450  # > 4800 chars
        note.write_text(filler + " dinosaurs roamed here", encoding="utf-8")
        log_capture_db(
            {"timestamp": "2026-01-01T00:00:00", "category": "Notes",
             "filepath": str(note), "filename": "deep.md"},
            vault,
        )
        # singular query must prefix-match the plural in the deep body
        self.assertEqual(len(search("dinosaur", vault)), 1)

def test_sanitize_fts_query_uses_prefix_tokens(self):
    """H3: plain word tokens become prefix queries; metachar tokens are quoted."""
    from index_writer import _sanitize_fts_query
    self.assertEqual(_sanitize_fts_query("dinosaur"), "dinosaur*")
    self.assertEqual(_sanitize_fts_query("red panda"), "red* panda*")
    # token with FTS metacharacters is quoted, not prefixed
    self.assertEqual(_sanitize_fts_query('a"b'), '"a""b"')
```

- [ ] **Step 2: Run them to verify current state**

Run: `pytest test_index_writer.py -k "deep_keyword or sanitize_fts_query_uses_prefix" -v`

Expected: PASS *if* Task 1+2 are merged (the H1/H3 source fixes are already in place). If either FAILS, the upstream fix regressed — stop and apply `superpowers:systematic-debugging` before continuing. (These tests are guards; they assert the fix that should already exist.)

- [ ] **Step 3: Write the chat regression test (H4 + H6 in `test_rag_engine.py`)**

Match the existing style in `test_rag_engine.py`. This test isolates the RRF fusion logic by stubbing the semantic side empty and the FTS side with one hit, then asserts the FTS-only hit survives the similarity floor:

```python
def test_fts_only_hit_survives_similarity_floor(monkeypatch, tmp_path):
    """H6: an FTS-only hit (zero semantic similarity) must still be returned —
    the floor only gates semantic paths, not FTS paths."""
    import rag_engine

    note = tmp_path / "Notes" / "rex.md"
    note.parent.mkdir(parents=True)
    note.write_text("tyrannosaurus rex was a predator", encoding="utf-8")

    # No semantic matches at all (simulates embeddings missing / below floor).
    monkeypatch.setattr(
        rag_engine, "_semantic_ranked",
        lambda *a, **k: ([], 0.0, {}),
    )
    # FTS returns the note.
    monkeypatch.setattr(
        rag_engine, "fts_search",
        lambda q, root, **k: [{"path": str(note), "category": "Notes", "filename": "rex.md"}],
    )

    sources, _conf, tier = rag_engine.hybrid_retrieve(
        tmp_path, "tyrannosaurus", base_url="http://x", embed_model="m",
    )
    assert len(sources) == 1
    assert sources[0]["filename"] == "rex.md"
    assert tier != "none"

def test_read_snippet_centers_on_deep_keyword(tmp_path):
    """H4: snippet window centers on the matched token even when it sits far
    past the first 1500 chars."""
    from rag_engine import _read_snippet

    note = tmp_path / "deep.md"
    filler = "lorem ipsum " * 450  # > 4800 chars
    note.write_text(filler + " stegosaurus plates", encoding="utf-8")
    snippet = _read_snippet(note, "stegosaurus")
    assert "stegosaurus" in snippet.lower()
```

- [ ] **Step 4: Run the chat regression tests**

Run: `pytest test_rag_engine.py -k "fts_only_hit or read_snippet_centers" -v`

Expected: PASS. (`test_rag_engine.py` already imports/uses pytest-style fixtures — confirm `monkeypatch`/`tmp_path` are available; they are pytest built-ins.)

- [ ] **Step 5: Run both full test files**

Run: `pytest test_index_writer.py test_rag_engine.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/test_index_writer.py omni_capture/test_rag_engine.py
git commit -m "test(look): lock FTS depth/prefix and chat FTS-only-hit regressions"
```

---

## Task 4: Remove investigation debug artifacts

**Files:**
- Modify: `omni_capture/index_writer.py` — delete the `# #region agent log` … `# #endregion` block inside `search()` (lines 533–542) and the now-unused `sanitized` local on line 528 if it is only used by that block.
- Modify: `omni_capture/rag_engine.py` — delete the `# #region agent log` … `# #endregion` block inside `hybrid_retrieve()` (lines 219–232).
- Delete: `<vault_root>/debug-a05393.log` and the repo-root `debug-a05393.log` if present.

**Interfaces:** none — pure removal of side-channel logging written during the H1–H7 investigation. No behavior change.

- [ ] **Step 1: Remove the debug block in `index_writer.py:search()`**

Delete lines 533–542 (the `# #region agent log` … `# #endregion` block). Then check line 528 — `sanitized = _sanitize_fts_query(query) if query.strip() else ""` — and delete it too if (after removing the block) `sanitized` has no remaining references in the function. The real query sanitization happens at line 508 (`params: list = [_sanitize_fts_query(query)]`), so the `sanitized` local was only for the debug block.

Resulting tail of `search()`:

```python
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        rows = cursor.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Remove the debug block in `rag_engine.py:hybrid_retrieve()`**

Delete lines 219–232 (the `# #region agent log` … `# #endregion` block). The `look_debug(...)` call immediately above it (lines 214–218) stays. Resulting tail:

```python
    look_debug(
        f"hybrid_retrieve q={question!r} expand={retrieval_query!r} "
        f"sem={len(sem_paths)} fts={len(fts_rows)} sources={len(sources)} "
        f"best_sim={best_sim:.3f} floor={min_similarity_floor} tier={tier}"
    )
    return sources, confidence, tier
```

- [ ] **Step 3: Delete the debug log files**

Run (from project root):

```bash
rm -f debug-a05393.log
```

And remove the per-vault copy if it exists (path printed by the old blocks was `<repo-root>/debug-a05393.log`, i.e. `parents[1]` of `omni_capture/`). Confirm none remain:

Run: `git status --porcelain | grep -i debug-a05393 || echo "clean"`
Expected: `clean`

- [ ] **Step 4: Verify both modules still import and self-check**

Run: `python -c "import index_writer, rag_engine; print('import OK')"`
Expected: `import OK`

Run: `python rag_engine.py`
Expected: `rag_engine smoke: OK`

- [ ] **Step 5: Run the affected test files**

Run: `pytest test_index_writer.py test_rag_engine.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/index_writer.py omni_capture/rag_engine.py
git commit -m "chore(look): remove H1-H7 debug log instrumentation"
```

---

## Task 5: End-to-end verification (search + chat through the running server)

**Files:** none — verification only. Apply `superpowers:verification-before-completion` here.

This proves the user-visible symptoms are resolved: Search tab no longer returns "no indexed notes match", `/strict` chat finds the document textually, and the manual "sync" actually heals the index.

- [ ] **Step 1: Confirm the vault has a known note containing a deep keyword**

Pick (or create) a real vault note containing a keyword far into the body — e.g. the existing `dinosaur` note from the investigation. Note its exact path.

- [ ] **Step 2: Start the server fresh (this triggers the one-time rebuild)**

Run (from project root): `python -m uvicorn omni_capture.server:app --port 7070`

Expected in logs: a line `[IndexWriter] rebuilt captures_fts (N rows) after trigger fix` on first start (and NOT on subsequent restarts — the flag gates it).

- [ ] **Step 3: Hit the search endpoint for the previously-failing term**

In a second shell:

Run: `curl "http://localhost:7070/search?q=dinosaur&limit=5"`

Expected: JSON `results` array with ≥1 entry whose `path` is the known note. Previously this returned an empty result (Search tab: "no indexed notes match [keyword]").

- [ ] **Step 4: Confirm the CLI search agrees**

Run (from `omni_capture/`): `python index_writer.py search dinosaur`

Expected: at least one row printed (timestamp / category / path).

- [ ] **Step 5: Exercise the Chat path with `/strict`**

Run:

```bash
curl -N -X POST http://localhost:7070/look/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "/strict what does the note say about dinosaurs", "history": []}'
```

Expected (SSE stream): a non-`none` tier, the known note among the cited sources, and an answer drawn from the note body — NOT the `Information not found in vault` refusal. (Before the fix, the note appeared only in reference links but the model could not answer textually because the snippet/FTS path was starved.)

- [ ] **Step 6: Confirm "sync" is now a real heal, not a no-op**

Run: `curl -X POST http://localhost:7070/vault/sync-index -H "X-Omni-Secret: <secret-if-required>"`

Expected: JSON `{"added": …, "removed": …, "updated": …, "skipped": …}` returns without error. Edit the known note's body (add a new unique word), POST sync-index again, then `GET /search?q=<newword>` returns the note — proving `upsert_capture_from_file` → `captures_au` trigger now maintains FTS instead of silently failing.

- [ ] **Step 7: Final full-suite run**

Run (from `omni_capture/`): `pytest -q`

Expected: full suite green. If anything unrelated fails, note it but it is out of scope for this plan.

---

## Self-Review (completed against the H1–H7 spec)

**1. Spec coverage:**
- H1 (4k cap) — guarded by Task 3 `test_deep_keyword_is_indexed_and_prefix_matched` (source fix already in tree: `_BODY_EXCERPT_MAX_CHARS = 65536`).
- H2 (FTS empty/out of sync) — rejected in investigation; Task 2 rebuild + Task 5 verification confirm rows present.
- H3 (strict quotes block plurals) — guarded by Task 3 `test_sanitize_fts_query_uses_prefix_tokens`.
- H4 (static 1500-char snippet) — guarded by Task 3 `test_read_snippet_centers_on_deep_keyword`.
- H5 (`content=captures` broken schema) — already migrated by existing `_migrate_fts_internal`; the corrected triggers in Task 1 assume internal storage; Task 1/2 tests pass only on the internal schema, implicitly covering it.
- H6 (semantic floor gates FTS hits) — guarded by Task 3 `test_fts_only_hit_survives_similarity_floor`.
- H7 (broken FTS5 delete triggers — the blocker) — fixed in Task 1, healed in Task 2, verified in Task 5.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — all code blocks are complete and repeated where needed.

**3. Type consistency:** `_rebuild_fts_once(conn)`, `_row_fts_body(...)`, `search(query, vault_root)`, `hybrid_retrieve(vault_root, question, base_url, embed_model)`, `_read_snippet(p, query)` match their definitions in the source files read for this plan. Meta flag key `fts_rebuilt_trigger_fix_v1` is used identically in the function, the call site, and the test.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-look-search-fts-fix.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task via `superpowers:subagent-driven-development`, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
