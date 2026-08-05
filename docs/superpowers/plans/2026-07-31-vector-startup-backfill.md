# Vector-Store Startup Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `vault_sync.sync_vault_indexes()` diff-sync into a new `@app.on_event("startup")` hook in `server.py` so pre-existing vault notes (created outside the capture pipeline, or before `vector_store.py` existed) get embedded into `vectors.db` automatically on boot, instead of only via the manual `POST /vault/sync-index` endpoint.

**Architecture:** `index_note()` only ever runs on write-time capture paths (`main.py`, `server.py` capture/add-to-vault routes, `jobs.py` YouTube job, `mobile_sync_agent.py` phone intake) — it never walks the vault. `vault_sync.sync_vault_indexes(vault_root, base_url, embed_model)` already does that walk (heal both derived DBs, purge orphans, add/update/re-embed) and is already used by the manual sync-index endpoint and covered by `test_store_rebuild.py`'s `_rebuild()` helper. This plan originally added a **second, independent** `@app.on_event("startup")` hook — `_startup_vector_backfill` — reasoning that `_startup_db_tasks` had its own dedicated test coverage asserting it does NOT re-embed, so folding the call in there would falsify that contract.

**Superseded by the final-review fix pass (commit `cfaa064`):** a separate hook shares the same 2-worker `jobs._bg_executor` as `_startup_db_tasks` and both independently heal/purge/rebuild the same derived stores — a real race, not a hypothetical one. The shipped design instead extracts a module-level `_backfill_vector_index(root)` and calls it as a 5th sequential step at the tail of `_startup_db_tasks._run`, removing the standalone hook entirely so there is exactly one task submitted to the executor. `test_store_rebuild.py`'s boot-path tests and their "boot leaves captures.db empty" contract were updated to match (the boot task now legitimately refills it). Task 1's steps below are kept verbatim as the historical record of what was first built and reviewed; they do not describe the final shipped shape.

**Tech Stack:** Python (FastAPI `@app.on_event("startup")`, `jobs._bg_executor` ThreadPoolExecutor), pytest, `unittest.mock`.

## Global Constraints

- `cfg.ollama.base_url` must stay bare, never `/v1`-suffixed (workspace hard rule) — pass `cfg.ollama.base_url` straight through unchanged, exactly as the existing `POST /vault/sync-index` handler does at `server.py:1570`.
- Files are the source of truth; `vectors.db` is a derived, rebuildable cache — this backfill must be fail-soft (never raise into startup, never crash the server) and must never write to any vault `.md` file (embedding does not touch note bytes).
- Every startup hook in `server.py` follows the same shape: `def _run(): ...` wrapped in `jobs._bg_executor.submit(_run)`, with each internal step in its own `try/except` that prints and continues. Match this shape exactly — do not introduce a new pattern.
- Non-trivial logic ships with one runnable check (workspace hard rule) — this task's own pytest test is that check.
- No code comment references "this session," "the fix," or any task/ticket number — comments explain the WHY (why a second hook instead of folding into `_startup_db_tasks`) the same way the existing startup hooks' docstrings do, not the history of how it got written.

---

### Task 1: Add the `_startup_vector_backfill` startup hook

**Files:**
- Modify: `Second Thought/omni_capture/server.py` (insert a new `@app.on_event("startup")` function immediately after `_startup_db_tasks`, i.e. after line 233's `jobs._bg_executor.submit(_run)` and before the blank lines preceding `_fire_due` at line 236)
- Test: `Second Thought/omni_capture/test_store_rebuild.py`

**Interfaces:**
- Consumes: `vault_sync.sync_vault_indexes(vault_root: Path, base_url: str, embed_model: str) -> SyncResult` (existing, `vault_sync.py:95`, already imported elsewhere via `from vault_sync import sync_vault_indexes`); `config.get_config()` (existing, already used by `_startup_reminders_thread` at `server.py:271`) for `cfg.ollama.base_url` and `cfg.vector.embed_model`; `server._get_vault_root()` (existing helper already used by `_startup_db_tasks` at `server.py:194`); `jobs._bg_executor` (existing shared pool).
- Produces: nothing new consumed by later tasks — this is the only task in the plan.

- [ ] **Step 1: Write the failing test**

Add to `Second Thought/omni_capture/test_store_rebuild.py`, directly after `test_healthy_captures_db_survives_the_boot_path` (after line 537):

```python
def _startup_vector_backfill(vault: Path) -> None:
    """The new boot path under test: server._startup_vector_backfill, run synchronously
    (same inline-submit trick as _startup() above) with the real embed call faked out."""
    import server

    _restart(vault)
    with mock.patch.object(server, "_get_vault_root", lambda: vault), \
         mock.patch.object(server.jobs._bg_executor, "submit", lambda fn: fn()), \
         mock.patch.object(vector_store, "_embed", side_effect=_fake_embed):
        server._startup_vector_backfill()


def test_startup_backfills_pre_existing_notes_never_indexed(vault: Path):
    """FIXED: notes that exist on disk but were never embedded (e.g. written outside the
    capture pipeline, or predating vectors.db) used to stay permanently unindexed — the only
    caller of the diff-sync's embedding pass was the manual POST /vault/sync-index endpoint,
    never anything on the boot path. A fresh vault (this fixture) has zero embedded notes at
    boot; after the new startup hook runs, every note on disk must be embedded."""
    assert vector_store.embedded_parents(vault) == set(), \
        "fixture precondition: nothing embedded yet"

    _startup_vector_backfill(vault)

    embedded = vector_store.embedded_parents(vault)
    expected = set(_oracle(vault)["notes"].keys())
    assert embedded == expected, "boot path did not embed every pre-existing note"


def test_startup_vector_backfill_is_idempotent(vault: Path):
    """A second boot must not re-embed notes whose captures.hash is unchanged (OF-1's
    embedded_parents check), matching sync_vault_indexes' own idempotence guarantee."""
    _startup_vector_backfill(vault)
    first = vector_store.embedded_parents(vault)

    _startup_vector_backfill(vault)
    second = vector_store.embedded_parents(vault)

    assert first == second == set(_oracle(vault)["notes"].keys())


def test_startup_vector_backfill_never_touches_vault_bytes(vault: Path):
    """BODY-SACRED: embedding is a derived-cache write, not a vault write."""
    before = _snapshot_vault(vault)

    _startup_vector_backfill(vault)

    _assert_bodies_sacred(before, vault, "startup vector backfill")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_store_rebuild.py -k backfill -v` (from `Second Thought/omni_capture/`)
Expected: FAIL — `AttributeError: module 'server' has no attribute '_startup_vector_backfill'` (or `AttributeError: <module 'server'> does not have the attribute '_startup_vector_backfill'` from `mock.patch.object`) on all three new tests.

- [ ] **Step 3: Implement the startup hook**

In `Second Thought/omni_capture/server.py`, insert immediately after the existing `_startup_db_tasks` function (after its closing `jobs._bg_executor.submit(_run)` line, currently line 233, before the blank lines leading into `_fire_due` at line 236):

```python
@app.on_event("startup")
def _startup_vector_backfill() -> None:
    """Best-effort startup embedding backfill. index_note() only ever runs on write-time
    capture paths (main.py, this file's capture/add-to-vault routes, jobs.py's YouTube job,
    mobile_sync_agent's phone intake) -- nothing walks the vault to embed notes that were
    already there (hand-written outside the pipeline, or predating vector_store.py). This
    reuses vault_sync.sync_vault_indexes, the same diff-sync POST /vault/sync-index already
    calls, so a note is embedded exactly once it's ever on disk without the user needing to
    trigger a manual sync-index. A SEPARATE hook from _startup_db_tasks (not folded in): that
    function has its own narrower contract, asserted in test_store_rebuild.py, of healing +
    purging + backfilling captures.db without ever re-embedding."""
    def _run():
        root = _get_vault_root()
        try:
            from config import get_config
            from vault_sync import sync_vault_indexes
            cfg = get_config()
            result = sync_vault_indexes(root, cfg.ollama.base_url, cfg.vector.embed_model)
            if result["error"]:
                print(f"[VaultSync] startup vector backfill aborted: {result['error']}", flush=True)
            elif result["added"] or result["reembedded"] or result["embed_failed"]:
                print(
                    f"[VaultSync] startup vector backfill: {result['added']} added, "
                    f"{result['reembedded']} reembedded, {result['embed_failed']} embed_failed",
                    flush=True,
                )
        except Exception as exc:
            print(f"[VaultSync] startup vector backfill skipped: {exc}", flush=True)
    jobs._bg_executor.submit(_run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_store_rebuild.py -k backfill -v` (from `Second Thought/omni_capture/`)
Expected: PASS — all 3 new tests green.

- [ ] **Step 5: Run the full desktop gate**

Run: `pytest -q` (from `Second Thought/omni_capture/`)
Expected: all previously-passing tests still pass, plus the 3 new ones (net +3 vs the last recorded gate count in `BUILD-STATE/PROGRESS/CURRENT.md` §2). No regression in `test_server.py` or the existing `test_store_rebuild.py` boot-path tests (`test_corrupt_captures_db_is_healed_by_the_boot_path`, `test_healthy_captures_db_survives_the_boot_path`) — those exercise `_startup_db_tasks` only and are untouched by this change.

- [ ] **Step 6: Commit**

```bash
git add omni_capture/server.py omni_capture/test_store_rebuild.py
git commit -m "fix: backfill vector index for pre-existing notes at startup"
```

---

## Self-Review

**Spec coverage:** the diagnosis's single recommendation — "wire `sync_vault_indexes()` into startup as a background job, not blocking boot" — is fully covered by Task 1 (new `@app.on_event("startup")` hook, `jobs._bg_executor.submit`, non-blocking). No threshold change is in scope (diagnosis found the coverage gap, not the threshold, is the bug) and none is made.

**Placeholder scan:** no TBD/TODO; every step has complete, runnable code; no "similar to Task N" references (single task).

**Type consistency:** `_startup_vector_backfill` takes no arguments and returns `None`, matching every sibling `@app.on_event("startup")` hook in the file (`_startup_load_jobs`, `_startup_sync_scheduler`, etc.). `sync_vault_indexes(vault_root: Path, base_url: str, embed_model: str) -> SyncResult` is called with the exact same three positional args, same order, as the existing `server.py:1570` call site. Test helper `_startup_vector_backfill(vault: Path) -> None` mirrors the existing `_startup(vault: Path) -> None` helper's shape exactly (same three `mock.patch.object` targets, same inline-submit trick), and reuses `_oracle`, `_fake_embed`, `_snapshot_vault`, `_assert_bodies_sacred`, `_restart` already defined earlier in the same file — no new fixtures introduced.

**Not done, deliberately out of scope:** re-running the s115 p09 query against the now-populated vault to see if the 0.480/0.452/0.449 near-miss resolves — the diagnosis flagged this as a follow-up verification step, not part of the fix itself, and needs a live Ollama embed model running (not a unit-test concern). Recommend as the very next manual/agent step after this plan lands, not folded into it.
