# Implementation Plan — Performance, Large-Text Capture, and Tagging

**Audience:** Claude Sonnet, executing in this repo (`C:\Users\biloh\Claude\Projects\Second Thought`).
**Author:** Opus (audit + plan). **Date:** 2026-06-19.
**Scope:** three asked areas — (1) code-level performance, (2) faster large-text copy/paste processing, (3) a better file-tagging system — plus four approved creative extras.

This document is the spec. Work the tasks **in order**; later tasks depend on earlier ones. Each task states the problem, the exact file/anchor, what to change, how to verify, and the no-regression contract. Do not improvise scope beyond what is written; if a task is genuinely blocked, stop and report rather than guess.

---

## 0. Ground rules (read once, apply to every task)

### 0.1 Design-language contract (this codebase has a strong, consistent style — match it)

- **Module docstring** at the top of every file explaining purpose + any non-obvious invariants (see `storage_engine.py:1`, `vector_store.py:1`).
- **Embedded smoke tests** in an `if __name__ == "__main__":` block at the bottom of each module, numbered `T1, T2, …` with `print("[Tn] … PASS")` lines and `assert`s. Every module you touch must keep its existing `__main__` tests passing and **gain new ones** for new behavior. This is the project's primary test idiom (see the large blocks in `storage_engine.py:1228`, `enrichment_router.py:778`, `summarizer.py:382`).
- `**pytest` suite** also exists (`omni_capture/test_*.py`, `omni_capture/tests/`). Keep it green.
- **Graceful degradation**: side-channel/optional work (vision, OCR, embeddings, link injection, DB index) **must never raise into the capture path**. Follow the existing `try/except → print("[Module] non-fatal …", flush=True) → return safe default` idiom (e.g. `index_writer.log_capture_db:193`, `vector_store.index_note:263`, `storage_engine._try_inject_wikilinks:804`).
- **Config-driven tunables**: any new threshold/limit goes in `config.py` `CaptureConfig`/`VectorConfig` (or a new dataclass) with a default that preserves today's behavior, read from `config.toml` with the same `cap_raw.get(...)` pattern (`config.py:169`). Never hardcode a magic number that a user might want to change.
- **Fence/frontmatter-safe text rewriting**: any code that edits note bodies or frontmatter must preserve fenced code blocks and YAML, like `storage_engine._trim_content:375`, `_strip_padding:326`, and `link_resolver._protect:55`. Reuse those helpers; do not write naïve regex that corrupts code blocks.
- `**OLLAMA_BASE_URL` stays bare**; `/v1` is appended only at OpenAI-client construction (`llm_engine._normalize_base_url:59`). Never write `/v1` back into config/env — there are regression tests guarding this (`enrichment_router.py` T10/T10b, `test_e2e.py`).
- **Timestamps**: user-facing/log timestamps that already use IST do so via `vector_store._ist_now:46`; match the surrounding file's convention, don't introduce a new one.

### 0.2 No-regression contract

- The vault frontmatter schema is the **source of truth** and must stay Obsidian-compatible (flat schema, `storage_engine._build_frontmatter:458`). All new SQLite tables are **derived indexes**, rebuildable from frontmatter. Never make a note unreadable to Obsidian.
- Existing public function signatures keep working. If you must change one, keep a backward-compatible shim and update all call sites (search with Grep first).
- Behavior for **small text / URL / image / YouTube captures must be byte-identical** unless a task explicitly changes it. The large-text path (Phase 2) is gated behind a threshold whose default leaves current behavior unchanged for normal-sized captures.

### 0.3 Verification discipline (required — tests + benchmarks)

For **every** task:

1. Run the touched module's `__main__` smoke tests: `python omni_capture/<module>.py` (run from the `omni_capture/` dir so the flat imports resolve — that is how the existing tests run).
2. Run `pytest omni_capture/` and confirm green.
3. For any task tagged **[BENCH]**, add/extend a micro-benchmark in the new `omni_capture/bench_capture.py` harness (Task P0.3) and record before/after numbers in the task's commit message. A perf claim without a measured before/after is not done.
4. Never claim a task complete without showing the actual passing output. Evidence before assertions.

### 0.4 The hot path you are optimizing

One capture of pasted text currently runs (server path `server.py:283 _run_pipeline_blocking`, CLI path `main.py:121 run_pipeline`):

```
route_and_enrich            (text: passthrough — cheap)
pre_resolve                 (regex over text — cheap)
retrieve_related            (vector: loads ALL embeddings, Python cosine loop)   ← O(vault)
run_llm_engine              (whole enriched_text → one structured LLM call)       ← O(text size)
write_to_vault
  ├ check_duplicate         (reads+parses full dedup JSON)                         ← O(vault)
  ├ _try_inject_wikilinks → build_link_index (rglob whole vault + read each .md)   ← O(vault)  ← worst
  ├ inject_wikilinks        (one compiled regex PER note, .sub over whole body)    ← O(vault×text)
  ├ find_merge_target       (reads+regex-parses tags of every .md in category)     ← O(category)
  └ register_in_dedup_index (rewrites full dedup JSON)                             ← O(vault)
index_note                  (embeds note, upserts vectors.db — separate connection)
log_capture / log_capture_db (init_db reopens conn + replays full DDL)             ← per-write
```

The five `O(vault)`/`O(vault×text)` steps are the targets. The keystone is a small shared **index layer** (Phase P0) that the perf, large-text, and tagging work all build on.

---

## Phase P0 — Indexing foundation (keystone; do this first)

Everything else leans on this. The goal: one place that owns the SQLite connection(s) and the derived indexes (captures, tags, dedup, link-index), with a cached connection and a backfill command.

### Task P0.1 — Cached SQLite connection + run DDL once

**Problem:** `index_writer.init_db` (`index_writer.py:120`) is called by `log_capture_db`, `search`, and `stats` on **every** invocation, and each call opens a fresh `sqlite3.connect` **and** runs `conn.executescript(_DDL)` (full schema + triggers) every time. Per-capture and per-search overhead that grows with trigger count.

**Change (`index_writer.py`):**

- Introduce a module-level connection cache keyed by resolved DB path: `_CONN_CACHE: dict[str, sqlite3.Connection]`. `init_db` returns the cached connection if present, else creates it, sets the PRAGMAs (`journal_mode=WAL`, `foreign_keys=ON`), runs `executescript(_DDL)` **once**, and caches it. Keep `check_same_thread=False` (already set) — the server uses a thread-pool executor.
- Stop calling `conn.close()` in `log_capture_db`/`search`/`stats`; the cached connection lives for the process. Keep `conn.commit()` after writes.
- Add `close_all()` for test teardown (the `__main__`/pytest tempdir tests must be able to release the file on Windows — see the analogous lock issue documented in `vector_store._connect:82`). Call it at the end of the `__main__` block and from any pytest fixture that tears down a tempdir vault.
- Guard the DDL-once with an idempotent check (e.g. `PRAGMA user_version`): set `user_version=1` after first DDL; skip `executescript` when already set. `CREATE … IF NOT EXISTS` makes this safe either way, but skipping the script is the actual speedup.

**Keep:** WAL, the FTS5 triggers, the existing schema columns. Do not change the row schema in this task.

**Tests:** extend `index_writer.py __main__` (it currently has none — add a numbered block): T1 two `init_db` calls on the same vault return the **same** connection object; T2 DDL is not re-run (assert via a sentinel/`user_version`); T3 `log_capture_db` upsert still works; T4 `search`/`stats` still return correct rows; T5 `close_all()` releases the file (open then `close_all()` then delete tempdir succeeds on Windows). **[BENCH]** time 1000 `log_capture_db` calls before/after.

**No-regression:** `test_index_writer.py`, `test_search_endpoint.py` must stay green. If any test assumed a fresh connection per call, update it to use `close_all()` in teardown.

### Task P0.2 — Schema additions: tags index + dedup table + link-index cache

**Problem:** dedup lives in a full-rewrite JSON file (`storage_engine._save_dedup_index:188`); tags live only as a JSON **string** column (`index_writer` `tags TEXT`), not queryable; the link index is rebuilt from the filesystem every capture. All three want a real index.

**Change (`index_writer.py` `_DDL`):** add (all `IF NOT EXISTS`, derived/rebuildable):

```sql
-- Normalized tags (Phase 3 uses canonical_id; nullable until then)
CREATE TABLE IF NOT EXISTS tags (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,     -- already-normalized tag string
    canonical_id INTEGER,                  -- FK→tags.id; NULL means this IS canonical
    count        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS note_tags (
    note_path TEXT NOT NULL,               -- vault-relative POSIX path
    tag_id    INTEGER NOT NULL,
    PRIMARY KEY (note_path, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id);

-- Content dedup (replaces dedup_index.json)
CREATE TABLE IF NOT EXISTS dedup (
    content_hash TEXT PRIMARY KEY,
    note_path    TEXT NOT NULL             -- vault-relative POSIX path
);

-- Link-index cache (display name → vault-relative stem), invalidated by mtime
CREATE TABLE IF NOT EXISTS link_index (
    display  TEXT PRIMARY KEY,
    rel_stem TEXT NOT NULL,
    is_alias INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS index_meta (   -- generic key/value for cache validity stamps
    key TEXT PRIMARY KEY,
    val TEXT
);
```

Add small typed helpers in `index_writer.py` for each (insert/lookup/delete), each wrapped in the non-fatal try/except idiom. These are the API the rest of the phases call.

**Tests:** new numbered smoke tests for each helper (insert/lookup/delete round-trips). **No-regression:** additive only — existing columns/triggers untouched.

### Task P0.3 — Benchmark harness + backfill/migration command  *(creative extra: backfill)*

**Problem:** the new indexes must be buildable from an existing vault without reprocessing, and perf claims need a repeatable measurement.

**Change:**

- New `omni_capture/bench_capture.py`: builds a synthetic tempdir vault of N notes (parametrized: 100 / 1k / 5k) with realistic frontmatter + tags, then times: `build_link_index`, `find_merge_target`, dedup check+register, `retrieve_related`, and a full `write_to_vault`. Prints a table. Pure stdlib + the project modules; no network (mock `_embed`). This is the [BENCH] target for all perf tasks.
- New CLI subcommand `python omni_capture/index_writer.py backfill` (extend the existing argparse at `index_writer.py:388`): walk the vault once, and for every `.md` populate `note_tags`/`tags` (from frontmatter tags via the canonicalizer once Phase 3 lands — until then, raw tags), `dedup` (content hash of each note, reusing `storage_engine._content_hash`), and `link_index` (reusing `link_resolver.build_link_index`). Idempotent (`INSERT OR REPLACE`/`OR IGNORE`). Print counts. This is also the one-time rollout migration from `dedup_index.json`.
- Backfill must read existing `dedup_index.json` if present and import it, so no dedup history is lost on upgrade.

**Tests:** `bench_capture.py` runs end to end on N=100 without network. Backfill on a tempdir vault populates all four tables; running it twice changes nothing (idempotent). **No-regression:** backfill is read-only w.r.t. note files.

---

## Phase 1 — Code-level performance

> Dependencies: P0 complete. Each task is independent after that; do in listed order for clean benchmarking.

### Task P1.1 — Cache the wikilink link-index instead of re-walking the vault  **[BENCH] (biggest win)**

**Problem:** `storage_engine._try_inject_wikilinks:788` calls `link_resolver.build_link_index(vault_root)` on **every** capture, which `rglob("*.md")`s the entire vault and `read_text`s each note's frontmatter for aliases (`link_resolver.py:142`, `_parse_aliases:88`). O(vault) file reads per capture — the single worst scaling cost.

**Change:**

- Add `link_resolver.build_link_index_cached(vault_root)` that reads the `link_index` table (P0.2). Validity stamp: store the count of `.md` files + the max mtime under the vault in `index_meta` (`link_index_stamp`). If the current `(count, max_mtime)` matches, return the cached dict; otherwise rebuild via the existing `build_link_index`, replace the table, update the stamp, and return. A fast cheap stamp (count + max mtime via `os.scandir` walk, no file reads) avoids the per-capture full read while staying correct when notes change.
- Point `_try_inject_wikilinks` at the cached version. Keep the existing `build_link_index` intact (backfill + rebuild use it; its `__main__` tests stay).
- Incremental update: after a successful `write_to_vault`, upsert just the new/changed note's display name into `link_index` and bump the stamp, so the next capture doesn't trigger a full rebuild merely because the vault grew by one. (Cheap: one row.)

**Tests:** new smoke tests — cached index equals fresh index; adding a note invalidates/refreshes; deleting a note refreshes. **[BENCH]** capture latency vs vault size (100/1k/5k) before/after — expect the per-capture cost to go from O(N) reads to ~O(1) on cache hit.

**No-regression:** `link_resolver.py __main__` tests and any wikilink assertions in `storage_engine.py` (T6, T20…) unchanged.

### Task P1.2 — Single combined regex for wikilink injection  **[BENCH]**

**Problem:** `link_resolver.inject_wikilinks:218` compiles a fresh regex per index entry and runs `.sub()` over the whole content **for every entry** — O(entries × content length). Large vault × large paste = near-quadratic.

**Change:** build **one** alternation regex from all display names, sorted longest-first (preserves the existing "John Smith Jr before John Smith" precedence at `link_resolver.py:215`), compiled once, with a `dict` lookup in the replace callback to find the `rel_stem` for the matched display (case-insensitive key map). Keep the `_protect`/`_restore` placeholder pass exactly as is. Keep `exclude_stems` semantics. Escape each display with `re.escape`; join with `|`; wrap with the existing `(?<!\x00)\b(...)\b(?!\x00)` guards.

**Tests:** the existing `inject_wikilinks` smoke tests (T2–T6) must pass **unchanged** (this is a pure perf refactor — identical output). Add T7: 500-entry index injects in one pass and matches the old per-entry result on a fixture. **[BENCH]** inject over a 50 KB body with a 1k-entry index, before/after.

**No-regression:** output must be identical to current for all existing fixtures — this is the correctness bar.

### Task P1.3 — Move dedup from JSON to SQLite  **[BENCH]**

**Problem:** `storage_engine._load_dedup_index:178` / `_save_dedup_index:188` read and **rewrite the entire JSON file** on every capture (`register_in_dedup_index:235`). O(vault) per capture, and duplicates hashes already implied by `captures.db`.

**Change:**

- Reimplement `check_duplicate` and `register_in_dedup_index` (`storage_engine.py:224`, `:235`) against the `dedup` table (P0.2) via `index_writer` helpers: `check_duplicate` = one indexed `SELECT note_path WHERE content_hash=?`; `register_in_dedup_index` = one `INSERT OR REPLACE`. Keep `_content_hash` (and its blank-content guard at `:215`) exactly.
- Keep the JSON path readable for one migration: on first use, if `dedup_index.json` exists and the `dedup` table is empty, import it (delegate to the backfill from P0.3), then ignore the JSON thereafter. Do not delete the JSON (leave it as a backup; document this).

**Tests:** `storage_engine.py` T7 (dedup) and the dedup tests in `test_dedup_and_inbox.py` must stay green against the new backend. Add a test: re-filing a capture whose category changed still works (the existing logic at `storage_engine.py:1131` that distrusts a stale-category dedup hit must be preserved). **[BENCH]** 1000 register+check cycles before/after.

**No-regression:** the category-mismatch dedup behavior (`storage_engine.py:1122`–`1148`) is subtle — keep it identical; only the storage backend changes.

### Task P1.4 — Vectorized cosine similarity + cached matrix  **[BENCH] (creative extra: vectorized)**

**Problem:** `vector_store._cosine_top_k:202` loops in Python computing `np.linalg.norm` per row; `retrieve_related:268` and `best_match:312` each load **all** embedding rows and re-normalize every call. `retrieve_related` runs every capture; `best_match` runs per candidate when semantic merge is on.

**Change:**

- Vectorize `_cosine_top_k`: stack all embeddings into one `np.ndarray` (float32), L2-normalize the matrix once, normalize the query once, do a single `matrix @ q` dot product, `argpartition` for top-k. Identical results, far fewer Python ops.
- Add a process-level cache of the **normalized matrix + id/doc lists**, keyed on `(db_path, row_count)` and invalidated when `index_note` upserts (bump a counter in `index_meta`/module state). Rebuild lazily on next query. Keeps `retrieve_related`/`best_match` from re-reading + re-normalizing the whole store every capture.
- Preserve `min_similarity` filtering and the empty-store `[]`/`None` returns and the non-fatal try/except.

**Tests:** `vector_store.py __main__` T1–T5 unchanged (same ranking). Add a test asserting vectorized top-k equals a brute-force reference on a random fixture. **[BENCH]** `retrieve_related` over 5k embeddings before/after.

**No-regression:** ranking order and similarity values must match the current implementation within float tolerance.

### Task P1.5 — Cheaper token-count cache key + content-hash ordering  **[BENCH]**

**Problem:** (a) `summarizer.count_tokens:67` builds its cache key by SHA-256-hashing the **full text** every call; the chunker calls `count()` many times on large growing windows, so hashing dominates on big inputs. (b) `storage_engine._content_hash:210` runs `re.sub(r"\s+"," ", text)` over the **entire** text and only then truncates to 2000 chars — wasteful on a megabyte paste.

**Change:**

- `count_tokens`: key the cache on `(base_url, model, len(text), blake2b(text, digest_size=16))` or, simpler and as safe here, hash only a bounded head+tail (`text[:512] + text[-512:]` + `len`). Document the (astronomically low) collision tolerance. Keep the network tokenize path and char-estimate fallback untouched.
- `_content_hash`: slice first (`text[:6000]`), then normalize, then `[:2000]`. Identical output for inputs ≤ the window (the function already truncates normalized text to 2000); add a test proving the hash is unchanged for representative inputs.

**Tests:** `summarizer.py` T5 (counter-call proportionality) stays green; add a test that two large texts differing only past the sampled window are extremely unlikely to collide AND that identical texts hit cache. `storage_engine` dedup tests stay green. **[BENCH]** `chunk_transcript` over a 200 KB transcript before/after.

**No-regression:** dedup keys for existing notes must not change (or you'd orphan dedup history) — verify `_content_hash` output is byte-identical for normal-size content; the reorder only affects very large inputs that were being truncated anyway.

### Task P1.6 — Cache category discovery per capture

**Problem:** `storage_engine.build_category_descriptions:125` → `discover_categories:69` runs `iterdir()` + reads each folder's `.category.toml` on every capture (called in `main.py:176` and `server.py:404`). Top-level only, so cheaper than P1.1, but still per-capture TOML reads.

**Change:** memoize on `(vault_root, max mtime of vault root + each category's` .category.toml`)`. Invalidate when a category folder or its toml changes. Keep `discover_categories`/`read_category_config` intact for callers/tests; add a `build_category_descriptions_cached` and point the two pipeline call sites at it.

**Tests:** new smoke test — adding a folder at runtime is still discovered (mirror `storage_engine.py` T12). **No-regression:** runtime folder discovery is an advertised feature (`storage_engine.py:1334`) — the mtime stamp must catch new folders.

---

## Phase 2 — Faster large-text copy/paste processing

> Chosen behavior: **threshold → both**. Below the threshold: unchanged. Above it: cap the classifier input to a representative head, and Map-Reduce summarize the full body into the note (reusing the existing summarizer), while still storing the full text.

### Task P2.1 — Config: large-text thresholds

**Change (`config.py` `CaptureConfig` ~`:59`, and the loader ~`:169`):** add, with defaults that **preserve current behavior** for normal captures:

- `text_classify_max_chars: int = 8000` — cap on the slice of pasted text sent to the classifier LLM (mirrors `web_max_chars`).
- `text_summarize_threshold_chars: int = 12000` — above this, the long-text path engages; below, today's passthrough.
- `text_store_full: bool = True` — keep the full pasted text in the note body even when summarized.
Reuse the existing `summary_*` token-budget knobs (`config.py:68`–`76`) for the Map-Reduce of large text — no new summarizer knobs.

**Tests:** config load test asserts defaults + override parsing (follow `config.py` patterns; add to whichever `test_*` covers config, or a new smoke test in `config.py __main__` if none).

### Task P2.2 — Long-text capture path

**Problem:** `route_and_enrich` (`enrichment_router.py:750`) passes pasted text through verbatim; `run_llm_engine` (`llm_engine.py:233`) then puts the **entire** `enriched_text` into the user message (`:282`). A large paste → one giant structured call → slow / context overflow / retries. Only YouTube uses the Map-Reduce summarizer (`summarizer.py`, wired in `server.py:_run_youtube_job`).

**Change (do this without disturbing the small-text path):**

1. **Classifier input cap (always safe):** in `run_llm_engine`, slice the content placed under `--- CONTENT TO CAPTURE ---` to `cfg.capture.text_classify_max_chars` **for classification only** (do not mutate `enriched.enriched_text`). The full text still flows to storage. Mark truncation in the prompt with a short `…[truncated for routing]` note so the model knows it's a head sample. This alone removes the latency cliff for large pastes. (Pass the cap in, or read config inside — match how `web_max_chars` is read at `enrichment_router.py:114`.)
2. **Optional summarized body (threshold → both):** add a helper (new `omni_capture/long_text.py`, or a function in `summarizer.py`) `summarize_long_text(text, *, cfg, base_url, model) -> str` that, when `len(text) >= text_summarize_threshold_chars`, runs the existing Map-Reduce: wrap the text as fake segments (`[{"text": para} for para in text.split("\n\n")]`), `chunk_transcript(...)` with the summary_* budgets, `_map_phase` + `reduce_summaries` (reuse `summarizer.py:250`/`:312` and `llm_engine` `DETAILED_SUMMARY_PROMPT`/`COMBINE_PROMPT`). Bound concurrency by `summary_max_concurrency`. Never raise — on failure, fall back to the raw text (mirrors `reduce_summaries`'s own fallback at `summarizer.py:374`).
3. **Wire it in both pipelines** (`main.py:269` region and `server.py:405` region): when the input is `text` and over threshold, run the classifier on the capped head (step 1), and set the note body to the summarized markdown (step 2). If `text_store_full`, append the full original text under a `## Full Text` heading **verbatim** using the deterministic-append seam that already exists (`storage_engine._build_deterministic_append:768` carries verbatim artifacts via `source_metadata`) — pass the full text as a new `source_metadata["full_text"]` and render it there, so the LLM can't paraphrase/drop it. This matches how OCR transcripts and image embeds are already preserved (`storage_engine.py:782`).
4. **Progress events:** the server path should emit the existing `step` events; for the summarize sub-steps you may reuse the `thinking`/`detail` channel the YouTube job uses so the GUI HUD shows movement (`useCapture.ts:135` already renders `summarizing` detail). Do **not** add fake stages — only real ones.

**Tests:** new smoke tests in the chosen module: small text (< threshold) is byte-identical to today (passthrough, no summarize call — assert the summarizer is not invoked); large text triggers chunk→map→reduce (mock the LLM client like `llm_engine.py:308`); full text is preserved verbatim when `text_store_full`. Add an `test_e2e`-style case for a >12 KB paste. **[BENCH]** capture latency for a 50 KB paste before/after (expect lower + bounded, no context-overflow retries).

**No-regression:** URL/YouTube/image/audio paths untouched. The `_run_youtube_job` Map-Reduce is the reference implementation — reuse its functions, don't fork them.

### Task P2.3 — Large-body wikilink/merge are already covered

P1.1 (cached link index) and P1.2 (single regex) remove the large-body wikilink cost; P3.2 (SQL merge, below) removes the large-body merge scan. No extra work here beyond confirming the [BENCH] for P2.2 reflects those wins (run P2.2 bench *after* Phase 1 + P3.2 land).

---

## Phase 3 — Better file tagging system (full system)

> The keystone payoff. Tags become a normalized, queryable, self-reconciling index; the LLM reuses existing vocabulary; merge logic stops scanning files; and there's real tag-management tooling. Frontmatter stays source-of-truth; the DB is the derived index from P0.2.

### Task P3.1 — Deterministic tag canonicalizer

**Problem:** tags are produced ad hoc from LLM `key_signals` via `storage_engine._signals_to_tags:447` with no canonicalization, so `async`, `asyncio`, `async-await` never reconcile (root cause of vocabulary drift). Reads are fragile (`_read_note_tags:813` only scans `text[:1000]` for block form and can mis-capture body list items as tags).

**Change:** new `omni_capture/tag_engine.py` — the single chokepoint for tag normalization:

- `normalize_tag(raw: str) -> str`: the existing slug rules from `_signals_to_tags` (lowercase, strip punctuation except `/-`, spaces→`-`) — extract them here so there is one definition. Update `_signals_to_tags` to delegate to it (keep the function + its callers/tests working).
- `canonicalize(tag: str, synonyms: dict) -> str`: map known synonyms/aliases to a canonical form. Load synonyms from an optional vault-level `_tags.toml` (`{ "asyncio" = ["async", "async-await"] }`) read like `read_category_config` (`storage_engine.py:94`); absent file ⇒ identity. Deterministic, no LLM.
- `read_note_tags(text: str) -> set[str]`: a robust frontmatter-only tag parser (parse the `---…---` block via `link_resolver._FRONTMATTER_RE`, read `tags:` inline list or block list). Replace the fragile `storage_engine._read_note_tags:813` with a call to this (fixes the `text[:1000]` body-list bug). Keep the old function name as a thin wrapper if other code/tests reference it.

**Tests:** `tag_engine.py __main__` — normalize idempotency; synonym→canonical; the frontmatter parser handling inline `tags: [a, b]`, block form, and **not** picking up body bullet lists (the exact bug); empty/missing frontmatter → `set()`. **No-regression:** `storage_engine` tag-dependent tests (T6, T13, T20b, merge tests) must stay green — `_signals_to_tags` output is unchanged for current inputs.

### Task P3.2 — Maintain the tag index on write; SQL-backed merge  **[BENCH]**

**Problem:** `find_merge_target:858` reads + regex-parses tags of **every** `.md` in the category per capture. The tag data should come from `note_tags` (P0.2), not the filesystem.

**Change:**

- On every successful `write_to_vault` (and `finalize_youtube_note` where tags are set, `storage_engine.py:1046`), upsert the note's canonical tags into `tags`/`note_tags` via `index_writer` helpers (bump `tags.count`). Do this in the same place `register_in_dedup_index` is called (`storage_engine.py:1166`, `:1221`) so all derived indexes update together (Phase 4 consolidates this).
- Rewrite `find_merge_target` to get candidates from SQL: `note_tags` joined for the capture's category, ranked by shared-tag count / Jaccard using the **canonical** tag sets — same thresholds (`MERGE_MIN_SHARED_TAGS`, `MERGE_MIN_TAG_JACCARD`, `MERGE_SEMANTIC_THRESHOLD` at `storage_engine.py:46`). Keep the optional semantic confirmation via `vector_store.best_match` exactly. Only fall back to a file scan if the index is empty (fresh vault pre-backfill).
- Update `_is_same_topic:838` similarly (use canonical tag sets from the index when available).

**Tests:** `storage_engine.py` merge tests (T20b image 2-tag threshold, smart-merge) must pass against the SQL backend; add a test that canonical synonyms now merge (`async` capture merges into an `asyncio`-tagged note when configured). **[BENCH]** `find_merge_target` in a category of 1k notes before/after.

**No-regression:** merge thresholds and the image-capture `min_shared=2` rule (`storage_engine.py:1206`) unchanged.

### Task P3.3 — Feed existing vault tags to the LLM (stop drift at the source)

**Problem:** the classifier never sees existing tags, so it invents fresh variants every time — the actual cause of vocabulary fragmentation.

**Change (`llm_engine.py`):** extend `_build_system_prompt:212` / `run_llm_engine:233` to accept an optional `existing_tags: list[str]` (top-N most frequent canonical tags from the `tags` table, fetched by the caller via a new `index_writer.top_tags(vault_root, n)`). Add a prompt section: `EXISTING TAGS (reuse an existing tag when it fits; only invent a new one for genuinely new topics): tag1, tag2, …`. Wire the two call sites (`main.py:269`, `server.py:405`) to pass the top tags. Keep `key_signals` semantics; the model still returns signals, but now biased toward reuse.

**Tests:** prompt-builder test asserting the tag block renders and is omitted when empty (no behavior change for fresh vaults). **No-regression:** the structured-output contract and `build_capture_model` (`llm_engine.py:268`) unchanged; this is additive prompt context.

### Task P3.4 — Tag-management CLI + API (rename / merge / list / rebuild)

**Change:**

- **CLI** (extend `index_writer.py` argparse, `:388`): `tags list` (name + count), `tags rename OLD NEW`, `tags merge SRC... DEST`, `tags rebuild` (re-derive `tags`/`note_tags` from frontmatter — same as backfill's tag portion). Rename/merge must **rewrite frontmatter** in every affected note using a fence/frontmatter-safe rewrite (reuse the discipline in `storage_engine._rewrite_frontmatter_for_approval:718` and the YAML-block handling in `finalize_youtube_note:1042`), then update `tags`/`note_tags`. Operate atomically per note (read→rewrite→write-temp→replace) and report a summary; never corrupt a note on partial failure (catch+continue+report).
- **API** (`server.py`): add read-only `GET /tags` (list with counts) and, mirroring the existing category-management endpoints (`create_category`/`rename_category`/`delete_category` around `server.py:769`–`:864`, all secret-guarded via `_require_secret:196`), `POST /tags/rename` and `POST /tags/merge`. Reuse the same `ShareRequest`-style pydantic models + `_require_secret` guard. These call the same core functions as the CLI (factor the logic into `tag_engine.py`, call it from both).

**Tests:** CLI/`tag_engine` smoke tests: rename rewrites frontmatter across N notes and updates the index; merge folds counts and points `canonical_id`; rebuild reconstructs from frontmatter; a note with the tag string inside a code block is **not** corrupted. Add an endpoint test mirroring `test_search_endpoint.py`/`test_routing_and_merge.py` style (secret required, happy path, 400 on bad input). **No-regression:** category endpoints and their tests untouched; tag endpoints follow the identical guard/validation pattern.

### Task P3.5 — Backfill wiring

Ensure P0.3 backfill now uses the P3.1 canonicalizer for tags and populates `tags`/`note_tags` correctly, and that `tags rebuild` and backfill share one implementation. Run backfill once against the real vault during rollout (document the command in the commit).

---

## Phase 4 — Approved creative extras

### Task P4.1 — Unified index write path (creative extra)

**Problem:** each capture writes three stores through three code paths/connections: `dedup` (now SQLite), `note_tags`/`tags` (P3.2), `captures.db` row (`index_writer.log_capture_db`), plus `vectors.db` (`vector_store.index_note`). Drift-prone and redundant I/O.

**Change:** add `index_writer.record_capture(entry, *, tags, content_hash, vault_root)` that, in **one** cached connection / one transaction, upserts the `captures` row, the `dedup` row, and `note_tags`/`tags`. Call it once from `write_to_vault` instead of the scattered calls. Keep `vector_store.index_note` separate for now (different DB, embedding latency) but route it through the off-critical-path queue in P4.2. Keep each sub-write individually non-fatal (a tag-index failure must not abort the capture row).

**Tests:** one capture populates captures + dedup + tags atomically; a forced failure in one sub-write doesn't lose the others (within the non-fatal contract). **No-regression:** end-to-end capture still writes the same note file and the same `captures` row schema.

### Task P4.2 — Off-critical-path post-processing (creative extra)  **[BENCH]**

**Problem:** wikilink injection (after caching, cheap) but especially **vector `index_note`** (an embedding network call, `main.py:325`, `server.py` post-write) run **before** the user sees "done", inflating perceived latency.

**Change:** after the note file is written and the `done`/result is emitted, enqueue vector indexing (and any non-essential index maintenance) onto the existing background executor (`server.py` uses `_bg_executor`; the CLI path can run it in a daemon thread or simply keep it synchronous since CLI has no HUD). The note body + wikilinks are already on disk before handoff; only the **derived** vector index is deferred. Preserve all current behavior under `cfg.vector.enabled=false`. Ensure a capture immediately followed by another doesn't race the index (the cache-invalidation counter in P1.4 handles staleness; deferred index just lands a moment later).

**Tests:** capture emits `done` before the embedding call resolves (assert ordering with a mock that blocks); deferred index eventually populates `vectors.db`. **[BENCH]** perceived capture latency (time-to-`done`) for a text capture with `vector.enabled=true`, before/after.

**No-regression:** `retrieve_related` for the *next* capture still finds prior notes (they were indexed by then in normal use); document that a back-to-back capture may not yet see the immediately-prior note semantically — acceptable and already possible under failures.

---

## Sequencing & dependency graph

```
P0.1 (cached conn) ─ P0.2 (schema) ─ P0.3 (bench + backfill)
                                       │
   ┌───────────────────────────────────┼───────────────────────────────┐
   ▼                                   ▼                                 ▼
P1.1 link cache   P1.3 dedup→SQL    P3.1 canonicalizer ─ P3.2 SQL merge ─ P3.3 LLM tags ─ P3.4 tag CLI/API ─ P3.5
P1.2 regex (indep)                                                          │
P1.4 vectorized (indep)                                          P4.1 unified write ─ P4.2 off-path
P1.5 hash keys (indep)
P1.6 category cache (indep)
P2.1 config ─ P2.2 long-text path ─ (bench after P1 + P3.2)
```

Recommended commit order: **P0.1 → P0.2 → P0.3 → P1.2 → P1.4 → P1.5 → P1.6 → P1.1 → P1.3 → P3.1 → P3.2 → P3.3 → P3.4 → P3.5 → P2.1 → P2.2 → P4.1 → P4.2.** (Tagging before large-text so P2.2's bench reflects the SQL merge.) One commit per task, each green before the next.

## Definition of done (every task)

- Touched module's `__main__` smoke tests pass (show output).
- `pytest omni_capture/` green (show summary).
- New behavior has new numbered smoke tests.
- [BENCH] tasks: before/after numbers from `bench_capture.py` in the commit message.
- Design-language contract (§0.1) honored: docstring, embedded tests, config tunables, graceful degradation, fence-safe rewrites.
- No change to note-file frontmatter schema or to small-text/URL/image/YouTube behavior except where a task explicitly says so.

## Rollout note

After P3.5, run once against the live vault:

```
python omni_capture/index_writer.py backfill
```

This imports `dedup_index.json`, builds `tags`/`note_tags`/`link_index` from existing frontmatter, and makes the first post-upgrade capture fast. Keep `dedup_index.json` as a backup; do not delete it in this work.