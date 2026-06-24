# Ponytail Audit — Second Thought (repo-wide)

Scope: over-engineering / bloat only. Correctness, security, and performance are out of scope.

- [ ] **Delete orphaned `daily_digest.py` module** — `omni_capture/daily_digest.py` (210 lines: `build_digest`, `write_digest`, argparse CLI entry) has zero call sites in `server.py`, `main.py`, the GUI, or any scheduler/cron wiring, and isn't mentioned in CLAUDE.md's documented commands. It's a complete standalone feature nothing in the product invokes.
  - Suggestion: delete the file. If the digest feature is wanted later, it can be rebuilt then.

- [ ] **Drop dead `cfg.youtube.write_raw_transcript` config flag** — defined in `omni_capture/config.py:115,246` and set in `config.toml:77`, but `storage_engine.create_youtube_note` / `finalize_youtube_note` never read it — the transcript section is always written unconditionally regardless of the flag's value.
  - Suggestion: remove the dataclass field, the config.toml key, and the loader line; keep the always-write behavior as-is.

- [ ] **Drop unused `[vector].collection` / `COLLECTION_NAME` setting** — `omni_capture/config.py:104,235` defines and loads a collection-name config, but `omni_capture/vector_store.py:50` is SQLite-backed and never reads it. Leftover from an earlier (collection-based) vector store design.
  - Suggestion: remove the config field/key; nothing references it.

- [ ] **Deduplicate the two-pass CRM/Finance classification retry between `main.py` and `server.py`** — `omni_capture/main.py:287-302` and `omni_capture/server.py:445-458` each hand-implement the same ~15-line sequence: run `run_llm_engine` once, then on low pre-resolver confidence + CRM/Finance category, call `read_existing_context` and re-run `run_llm_engine` with that context loaded. Currently kept in sync only by a comment, which is how it'll silently drift.
  - Suggestion: extract the "first pass → conditional context-reload → second pass" sequence into one shared helper (e.g. in `llm_engine.py`) and have both `main.py` and `server.py` call it.

**net: -210 lines, -0 deps possible.**

## Second pass (remaining unread files: GUI components/lib/hooks, capture_log.py, notifier.py, interceptor.py, summarizer.py, index_writer.py, browser_extension/)

- [ ] **Delete dead async/diagnostic logger methods** — `withTiming()`, `flush()`, and `getDroppedCount()` in `gui/src/lib/logger.ts` have zero call sites anywhere in `gui/src` (grep-verified). Only the sync `time()` counterpart is actually used (in `useCapture.ts:319`, `api.ts:126,145`).
  - Suggestion: delete the three dead methods; `time()` alone covers every real call site. [gui/src/lib/logger.ts:283-294,297,300]

- [ ] **Dedupe monitor-resolution boilerplate** — `getActiveWorkArea()` and `getActiveMonitorBounds()` in `gui/src/lib/monitor.ts` duplicate ~12 lines verbatim (resolve `cx`/`cy` from `atPoint` or `outerPosition()`/`outerSize()`, then `monitorFromPoint(cx,cy) ?? currentMonitor()`, same try/catch), differing only in whether the final read is `mon.workArea.*` vs `mon.position`/`mon.size`.
  - Suggestion: extract one `_resolveMonitor(atPoint?)` helper returning the raw monitor + scale factor; have both functions just pick which rect to project. [gui/src/lib/monitor.ts:26-37,63-74]

- [ ] **Remove unused import** — `from typing import Optional` in `capture_log.py` is never referenced in the file body.
  - Suggestion: delete the import line. [omni_capture/capture_log.py:37]

**net (second pass): -18 lines, -0 deps possible.**

## Third pass (deep re-read of pipeline orchestration + small modules)

- [ ] **Collapse the whole duplicated pipeline body between `main.py` and `server.py`** — this is the architectural bottleneck the two-pass-retry item only nibbled at. `main.py:run_pipeline()` (≈200-365) and `server.py:_run_pipeline_blocking()` (≈336-499) are two hand-maintained copies of the *entire* stage sequence: intercept → enrich → `vision_available is False` scratchpad bail-out → pre_resolve + `retrieve_related` context assembly → `run_llm_engine` → CRM/Finance two-pass → `write_to_vault` → `index_note` → notify + `log_capture`. CLAUDE.md openly says they're "kept in sync" by hand, which guarantees drift (the vision-fail block, the context-assembly block, and the index/notify tail are already near-identical line-for-line). The only real differences are SSE `emit()` calls vs `print`/return-dict, and YouTube-job hand-off (server only).
  - Suggestion: extract one `run_core_pipeline(enriched, cfg, *, on_step=None)` (or a generator yielding stage events) into a new module both call; `main.py` ignores the events, `server.py` maps them to SSE. Folds the two-pass retry, vision bail-out, and context assembly into a single definition. [omni_capture/main.py:200-365, omni_capture/server.py:336-499] (~120 lines of true duplication)

- [ ] **Merge the byte-identical Windows/Darwin branches in `interceptor._try_read_image_from_clipboard`** — the `Windows` and `Darwin` arms are character-for-character the same (`from PIL import ImageGrab` → `grabclipboard()` → save PNG to `BytesIO`). Only Linux differs (xclip).
  - Suggestion: `if os_name in ("Windows", "Darwin"):` for the single PIL path, `elif os_name == "Linux":` for xclip. [omni_capture/interceptor.py:83-99] (~9 lines)

- [ ] **Extract the duplicated plyer fallback in `notifier.py`** — `_notify_windows` and `_notify_linux` each contain the identical `full_title` line plus the same `try: from plyer import notification; notification.notify(title=full_title, message=message, timeout=5) except Exception: pass` block.
  - Suggestion: one `_notify_plyer(full_title, message)` helper called from both. [omni_capture/notifier.py:55-60,73-78] (~6 lines)

- [ ] **Reuse `_normalize_base_url` in `server._warm_model`** — the startup warm-up hand-rolls the bare-host→`/v1` rule (`base.rstrip("/"); if not base.endswith("/v1"): base += "/v1"`) and constructs its own `OpenAI` client, making a *third* copy of the `/v1` invariant already owned by `llm_engine._normalize_base_url` / `_make_client` (the very invariant CLAUDE.md warns is regression-prone).
  - Suggestion: `from llm_engine import _normalize_base_url` and pass `_normalize_base_url(cfg.ollama.base_url)`. [omni_capture/server.py:112-122] (~4 lines)

- [ ] **Drop the redundant local `from config import reload_config` re-imports** — `server.py` imports `reload_config` at module top (line 63) yet re-imports it locally inside `_warm` (111) and `_run_pipeline_blocking` (317); neither needs the lazy form (reload_config has no env-ordering dependency, unlike the interceptor/enrichment imports below it).
  - Suggestion: delete both local import lines; use the top-level binding. [omni_capture/server.py:111,317] (~2 lines)

**net (third pass): -140 lines, -0 deps possible.**

## Not flagged (checked, found appropriately scoped)

- `vector_store.py`, `pre_resolver.py`, `link_resolver.py`, `timing.py`, `models.py`, `App.tsx`, `lib.rs`, `package.json`, `Cargo.toml`, `requirements.txt` — no unused deps duplicating stdlib/platform features, no single-implementation interfaces, no dead exports.
- `storage_engine.py`'s `_LEDGER_FILES` / `_CATEGORY_DEFAULT_STATUS` single-entry dicts — tied to real, distinct domain concepts (Finance ledger file, Watch_Later read-state), comment-justified, not speculative.
- Hand-rolled mini-TOML scanner in `lib.rs` and hand-rolled cubic-bezier easing in `App.tsx` — each the leaner choice over pulling in a crate/library for one narrow need.
- `if __name__ == "__main__"` smoke-test blocks in `storage_engine.py`, `enrichment_router.py`, `vector_store.py`, `pre_resolver.py`, `link_resolver.py` — mock-driven, no evidence of duplicating a parallel pytest suite.
- The two-pass classification fallback, YouTube async-job split, dynamic category enum, and OCR fast-path are deliberate, well-commented, single-purpose design — not bloat.
- `omni_capture/summarizer.py` — every piece of apparent complexity (propose-then-verify chunking, char-estimate fallback, env-configurable tokenize timeout) is comment-justified and covered by T1-T6 smoke tests.
- `omni_capture/index_writer.py` — `migrate_jsonl`/`reindex_bodies` both have real call sites (server startup, CLI, tests); trigger-DDL-as-template is explicitly required for existing-DB migration, not speculative.
- `browser_extension/` — small, single-purpose Manifest V3 extension; SSE-stream parsing in `background.js` mirrors the same protocol consumed by the GUI's `api.ts`, no redundant abstraction.
- `gui/src/lib/config.ts`'s re-export of `getConfig`/`patchConfig` from `api.ts` — consolidates a real shared import site (`SettingsPanel.tsx`, `CaptureOverlay.tsx`), not added indirection.
- `fanLayout.ts` / `menuGeometry.ts` / `pillAnchor.ts` — confirmed distinct concerns (angular fan math vs. window-position math vs. static anchor lookup), no duplication.
- `gui/src/components/{SettingsPanel,VaultManager,CaptureOverlay,SearchModal,InboxPanel,StatsPanel,StepIndicator,PillOverlay}.tsx`, `PillMenu/{RadialMenu,CapsuleMenu,DevTuner,icons}.tsx`, `ui/{Tabs,styles}.ts`, `lib/{api,devTuning}.ts`, `hooks/useCapture.ts`, `lib/{fanLayout,menuGeometry}.test.ts` — read in full, no further findings beyond the above.

### Third-pass verification (checked, NOT bloat)
- `config.py` fields `web_max_chars` / `youtube_max_chars` (read in `enrichment_router.py:114,321`) and `whisper.device` (read in `enrichment_router.py:744`) — all live; only `collection` and `write_raw_transcript` (already flagged) are dead.
- `storage_engine.suggest_category_names` + `/inbox/{id}/suggest-categories` endpoint — wired through to the GUI (`api.ts:364`, `InboxPanel.tsx:15,71`), not dead.
- `lib.rs` — clean; hand-rolled TOML scanner + `parse_shortcut` key tables are the leaner choice over adding a TOML/keymap crate for one narrow read each (matches first-pass verdict).
- `App.tsx`'s two window movers (`setWindowGeometryInstant` vs `animateWindowAndSizeTo`) and the dense pill-geometry effect — intrinsic to the multi-monitor/DPI window-positioning problem, genuinely distinct (instant atomic resize vs rAF tween), not collapsible without regressing the documented shake/clip bugs.
- `interceptor.py` / `notifier.py` per-OS dispatch — correct platform branching to keep; only the *within-dispatch* duplicates flagged above are bloat.

---

# Correctness & Performance Pass

Scope here is the opposite of the sections above: **correctness bugs and performance**, not over-engineering. Ranked biggest impact first.

## Performance

- [ ] **Whole-vault link index rebuilt on every single capture** — `storage_engine._try_inject_wikilinks` calls `link_resolver.build_link_index(vault_root)` (storage_engine.py:949), which `rglob("*.md")`s the entire vault *and* reads + regex-parses YAML frontmatter (`_parse_aliases`) of every note (link_resolver.py:142-176) — on every write. This is the dominant non-LLM cost as the vault grows (O(notes × file size) per capture).
  - Suggestion: the `tags`/`filename`/`path` needed are already in `captures.db`; build the link index from one indexed query, or cache it in-process keyed on vault mtime and only rebuild when a note is added/removed.

- [ ] **Full DDL + schema migration re-run on every DB open** — `index_writer.init_db` runs `executescript(_DDL)` plus `_migrate_schema` (which does `PRAGMA table_info`, an `ALTER` probe, and `executescript(_TRIGGERS_DDL)` that DROPs+CREATEs all three FTS triggers) on *every* call (index_writer.py:158-174). `log_capture_db`, `search`, and `stats` each open a fresh connection, so every capture and every search pays the full trigger rebuild.
  - Suggestion: gate `_migrate_schema` behind the same `_meta` version flag pattern `reindex_bodies` already uses, so an already-migrated DB skips the DDL/trigger churn and just connects.

- [ ] **Cosine similarity is a per-row Python loop, not a vectorized matmul** — `vector_store._cosine_top_k` iterates rows in Python, calling `np.frombuffer` + `np.linalg.norm` + `np.dot` once per note (vector_store.py:237-244). For N indexed notes every `retrieve_related`/`best_match` does N Python iterations.
  - Suggestion: stack all embeddings into one `(N, d)` matrix once and compute `M @ q` in a single BLAS call; normalize the matrix rows with `np.linalg.norm(M, axis=1)`. Same result, ~one C call instead of N.

- [ ] **`count_tokens` SHA-256s the full candidate text on every call** — inside `chunk_transcript`'s propose-then-verify loop, `count()` is invoked on a growing candidate string many times; each call hashes the entire candidate to build a cache key (summarizer.py:76-78). Cost is O(text) per call → O(text × calls) for a long transcript, and the cache almost never hits (each candidate differs).
  - Suggestion: drop the cache (the network `/api/tokenize` round-trip is what you actually wanted to memoize, and candidates are near-unique anyway), or key on `len(text)` + a short prefix/suffix instead of hashing all of it.

- [ ] **Dedup index fully read and fully rewritten on every capture** — `register_in_dedup_index` → `_save_dedup_index` re-serializes and rewrites the *entire* `dedup_index.json` on each write, and `check_duplicate` reloads the whole file (storage_engine.py:318-388). O(total notes) I/O per capture.
  - Suggestion: the `captures.db` already has a UNIQUE `hash` column path; fold dedup into one indexed SELECT/INSERT there and delete the JSON sidecar entirely.

- [ ] **`find_merge_target` / `_is_same_topic` re-read every note file in the category per write** — `find_merge_target` lists and `_read_note_tags`-parses every `.md` in the target category (storage_engine.py:1033-1058), then `write_to_vault` reads the base note again via `_is_same_topic` (storage_engine.py:1368). All those tags already live in `captures.db`.
  - Suggestion: query candidate tags from the index instead of re-reading and re-regexing each file off disk.

## Correctness

- [ ] **Note-body list bullets get parsed as frontmatter tags** — `_read_note_tags` block-form regex `^[ \t]*-[ \t]+(.+)$` runs against `text[:1000]` of the whole note, not the YAML frontmatter region (storage_engine.py:986). A note whose body opens with a Markdown bullet list within the first 1000 chars contributes those bullets as "tags", which then drives `find_merge_target`/`_is_same_topic` merge decisions — wrong-file merges.
  - Suggestion: slice out the `^---\n...\n---` frontmatter block first (the project already has `_FRONTMATTER_RE` in link_resolver.py) and parse tags only inside it. Same fix applies to `_extract_frontmatter_field` (storage_engine.py:857), which `re.search`es the entire document.

- [ ] **Search/stats keep returning notes from deleted or renamed categories** — `delete_category` (`shutil.rmtree`, server.py:898) and `rename_category` (`src.rename`, server.py:858) touch only the filesystem; the `captures.db` rows (and FTS index) and `vectors.db`/`dedup_index.json` entries still point at the old paths. `/search`, `/stats`, and semantic `retrieve_related` then surface dead paths / inject deleted notes as LLM context.
  - Suggestion: on delete, `DELETE FROM captures WHERE path LIKE '<cat>/%'` (+ vector rows + dedup keys); on rename, `UPDATE ... SET path = replace(path, old, new)`. One statement each, reusing the existing `init_db` connection.

- [ ] **SearchModal can show stale results (out-of-order responses)** — the debounced effect clears the *timeout* but never aborts an already-dispatched `searchCaptures` fetch (SearchModal.tsx:81-93). A slower earlier query can resolve after a faster later one and overwrite the newer results.
  - Suggestion: carry an `AbortController` (or a monotonically-increasing request id captured in the closure) and ignore a response whose id is no longer current — `streamCapture` already threads a `signal`, so the plumbing exists.

- [ ] **Background YouTube job dedup keys on the summary, not the URL-bearing content** — `_run_youtube_job` calls `register_in_dedup_index(summary, url, ...)` (server.py:632), but the normal path keys on `output.markdown_content`. Re-capturing the same video re-runs the whole transcript+summarize job before `check_duplicate` could ever short-circuit it (the dedup hash combines URL + normalized summary text, which differs run-to-run at temperature > 0).
  - Suggestion: register/check dedup on the URL (or video_id) up front in `_run_pipeline_blocking`'s YouTube branch, before handing off to the executor, so a duplicate video is dropped before paying for the job.

## Not flagged (checked, correct as-is)
- The `/v1` base-URL invariant, two-pass CRM/Finance retry, vision-fail scratchpad bail-out, and `_content_hash` blank-input guard — all handle their edge cases correctly.
- `summarizer` chunking math (propose-then-verify, overlap, coalesce-to-`max_chunks`, recursive reduce with depth cap) is correct and covered by T1-T6.
- `fanLayout.availableArc`/`unifiedFan`, `clampPillWindowToMonitor`, `computeMenuGeometry` — pure geometry, deterministic, test-backed; no correctness issues.
- `useCapture` in-flight/dismiss/poll lifecycle guards (`inFlightRef`, `stopJobPolling`, dismiss-timer clears) correctly prevent the documented double-fire / stale-timer races.
- `index_writer._sanitize_fts_query` correctly neutralizes FTS5 metacharacters; SettingsPanel's load-gating (`loadedRef`) correctly prevents auto-saving fallback values over real config.