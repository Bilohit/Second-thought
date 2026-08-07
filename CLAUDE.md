# CLAUDE.md

Second Thought is a local-first clipboard/URL/audio capture pipeline that enriches input via Ollama and files it into an Obsidian-style markdown vault, fronted by a Tauri pill-and-radial-menu GUI.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Jargon used below:** "vault" = the user's markdown notes directory (source of truth, not a database); "scratchpad" = the vault's catch-all/unsorted folder that low-confidence captures route to; "pill" = the small always-on-top Tauri window that triggers capture; "two-pass retry" = the LLM engine re-prompting once with stricter instructions when the first structured-output parse fails.

## Commands

Python (run from `omni_capture/`, or with `omni_capture` on `PYTHONPATH`):
```bash
pip install -r omni_capture/requirements.txt
python main.py                       # capture from clipboard
python main.py --text "..."          # inject text, skip clipboard
python main.py --url "https://..."   # inject a URL directly
python main.py --audio path.mp3      # transcribe via local Whisper
python main.py --dry-run             # print LLM output, no vault write
python main.py --verbose             # print every pipeline stage's output
python main.py --self-check          # verify Ollama/vault/whisper/index
python main.py --log [--stats]       # tail / summarize capture audit log
```

**Tests — go through the ladder, not the raw commands (s153, 2026-08-07).** `python check.py N`
from the **workspace root** is the gate; it owns the env traps and runs the reachability, parity,
identity and mount-census checks that no raw command below covers. Tier table + rules: workspace
`CLAUDE.md` §"Work standards". **A blocking pre-commit hook runs tier 1 in this repo; `--no-verify`
is forbidden.**
```bash
python check.py 0      # reflex  ~3s   — after every edit (pytest --testmon + tsc)
python check.py 1      # surface ~10s  — before reporting done (also the pre-commit hook)
python check.py 2      # full    ~227s — main thread, before every commit. Agents never run it
python check.py 3      # truth         — phase boundaries: staleness guard, FUZZ=1, isolated, mutants
python check.py --explain N            # list a tier without running it
```
The raw commands below still work and are the right tool for **one** test while iterating — they
are not a gate. Run from `omni_capture/`; there is no pytest config file:
```bash
pytest                                          # full suite (= what `check.py 2` runs)
pytest test_routing_and_merge.py -k test_name   # single test — the reason this block still exists
pytest tests/test_e2e.py                        # end-to-end
pytest --testmon -q                             # only tests affected by your change (= tier 0)
FUZZ=1 pytest test_fuzz_races.py -q             # §3.1 race fuzz — opt-in, tier 3 only, ~250s at the full 2000
```
`pytest-testmon` (`requirements-dev.txt`) backs tier 0; its `.testmondata` is gitignored and the
first run rebuilds it in ~178s.
Modules with an `if __name__ == "__main__":` smoke block run standalone, e.g. `python enrichment_router.py`, `python storage_engine.py`, `python llm_engine.py`, `python summarizer.py`.

GUI server (standalone, also auto-spawned by Tauri):
```bash
python -m uvicorn omni_capture.server:app --port 7070   # from project root
```

GUI frontend (`gui/`):
```bash
npm run dev          # tauri dev: Vite + Rust + Python together
npm run dev:vite      # Vite only, no Tauri shell
npm run build         # tsc typecheck + vite build — part of `check.py 2`, not run by hand as a gate
npm test              # vitest run — lib/*.ts modules, component tests, and the mount census
npm test -- src/__census__/   # the mount census alone (also part of `check.py 1`)
```

**`vitest.config.ts` sets `happy-dom` as the default test environment** — a `.test.tsx` no longer
needs a `// @vitest-environment happy-dom` docblock, and the 17 files that still carry one are
redundant but harmless. **A component with passing tests but no import path from `src/main.tsx` is
dead code and fails `check.py 1`** — five such components exist today and are baselined in
`tools/reachability-baseline.txt`; that file emptying is the definition of done for the cleanup.

Rust shell (`gui/src-tauri/`):
```bash
cargo check
cargo build
```

Whole-app launcher (Windows, project root):
```powershell
.\launch.ps1            # builds (if GUI sources stale) and runs release binary
OMNI_DEV=1 .\launch.ps1  # force dev mode
```
`launch.ps1` rebuilds only on GUI source path changes — it never rebuilds for `omni_capture/` edits (Python runs from source via `uvicorn`, no compile step).

## Hard rules

- **`cfg.ollama.base_url` must stay bare** (`http://localhost:11434`), never `/v1`-suffixed. `/v1` is appended only inside `llm_engine._normalize_base_url`/`_make_client`, because native Ollama endpoints (vision `/api/generate`, embeddings, `/api/tags`, tokenize) require the bare host. Writing `/v1` into env or config has caused real 404 regressions on every image capture — see T10/T10b in `enrichment_router.py` and `tests/test_e2e.py`. *(constrains: `llm_engine.py`, `config.py`)*
- **`main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()` are hand-duplicated by design, and must stay that way** — same 4-stage sequence, two implementations (SSE `emit()` vs print/return-dict, YouTube hand-off only in `server.py`). Any change to one (vision bail-out, two-pass retry, context assembly, index/notify tail) must be mirrored in the other by hand. Do not collapse them into a shared generator/`on_step` callback — that inverts control flow over the most load-bearing code path in favor of leaf-helper extraction instead. *(constrains: `main.py`, `server.py`)*
- **Project names are never hardcoded.** A note's project is the body tag `#project@<name>`; the tag is the only truth, and `project:` frontmatter / the `project` index column are derived caches of it, both produced by `project_registry.resolve_project` against `.projects.toml` — never a literal name baked into code. *(constrains: `project_registry.py`, `projects.py`, `models.py`)*
- **Vision failure is fail-fast, every other enrichment path is fail-soft.** When `[ollama] image_required = true` and vision fails, `source_metadata["vision_available"] = False` must be checked explicitly before the LLM stage and routed to the scratchpad — do not let a placeholder reach the LLM with false confidence. Web/GitHub/YouTube/audio handlers catch their own exceptions and return a placeholder instead. *(constrains: `enrichment_router.py`, `storage_engine.py`)*
- **Files are the source of truth, `captures.db`/`vectors.db`/`dedup_index.json` are derived indexes.** Never make a SQLite table authoritative over vault `.md` files for merge/dedup/link decisions — every perf fix in this codebase caches in front of the file read instead of migrating authority into the DB. *(constrains: `storage_engine.py`, `index_writer.py`, `vector_store.py`)*
- **Tauri window geometry: only `LogicalPosition`/`LogicalSize`.** Every monitor read goes through `gui/src/lib/monitor.ts` (already divides by `scaleFactor`). Never write a physical coordinate into a `Logical*` call — this is the recurring cross-monitor/DPI bug class in this code. The ONE sanctioned physical-coordinate path is `setWindowBoundsAtomic` (`gui/src/lib/tauri.ts`), which must convert via `monitor.ts:logicalToPhysicalRect` (edge-stable rounding — never round pos and size independently, that drifts the pinned edge 1px at fractional DPI). *(constrains: `gui/src/App.tsx`, `gui/src/lib/monitor.ts`, `gui/src/lib/tauri.ts`)*
- **Pill lifecycle invariants (regression class: dead/blank window until restart).** (a) `renderPill` must never remain `true` while `displayMode === "full"` — reconcile edges are computed by the pure `computeReconcileEdges` in `gui/src/lib/reconcileEdges.ts` (edit + test there, never re-inline the truth-table into `App.tsx`); `leavingPill` is deliberately NOT gated on pill mode. (b) `panelReady`: a compact panel must always end visible or fully closed, never blank-but-grown — the watchdog effect only ever forces it `true`, and every `setPanelReady(false)` site must stay synchronous (edge-detection only, never behind an `await`). (c) Panel content is wrapped by `ErrorBoundary` at `CompactShell` body and FullWindow view level — never wrap the geometry-owning `App` shell. *(constrains: `gui/src/App.tsx`, `gui/src/lib/reconcileEdges.ts`, `gui/src/components/ErrorBoundary.tsx`)*
- **Compact-header suppression is gated on `compactHeader`, never on `embedded`.** `VaultManager`/`InboxPanel` take a distinct `compactHeader` prop because FullWindow also passes `embedded`; overloading an existing prop silently changes every current caller. Compact panels lift their header controls into `CompactShell`'s `headerActions` slot via `onHeaderActionsChange`. *(constrains: `gui/src/components/VaultManager.tsx`, `gui/src/components/InboxPanel.tsx`, `gui/src/components/CompactPanels/CompactShell.tsx`)*
- **`ponytail:` comments mark a deliberate shortcut with a named ceiling and upgrade path** (e.g. `# ponytail: unbounded tag cache; cap if a vault ever holds 10k+ notes`). Preserve this convention on any new intentional simplification; don't silently "fix" a `ponytail:`-marked shortcut without re-evaluating whether its stated ceiling has actually been hit.
- **Non-trivial logic ships with one runnable check.** For an agent: any new branch, loop, parser, or money/security path needs either an `assert`-based `__main__` smoke block in the same module, or a small sibling `test_*.py`/`*.test.ts` — not a full framework/fixture suite — and that check must be run (`pytest <file>` or `npm test`) before the change is considered done. Trivial one-liners need no test.
- **`test_fuzz_races.py` (§3.1 concurrency/race fuzz) is opt-in and NOT part of `pytest`'s default gate** — it only runs via `FUZZ=1 pytest test_fuzz_races.py -q` (see Commands above), so it must be run explicitly after touching the op-queue/sync/reconcile path; nothing else will catch a regression there.

## Tech stack

- Python (`omni_capture/`): FastAPI+Uvicorn, Pydantic v2, instructor (structured Ollama output), openai SDK (as Ollama's OpenAI-compatible client only), readability-lxml, youtube-transcript-api, openai-whisper+torch, Pillow, rapidocr-onnxruntime (optional), pyperclip, tomlkit, plyer, stdlib sqlite3, pytest.
- TypeScript (`gui/`): React 18 (hooks only), Vite 8 single-page (`index.html`), Tauri v2 (`global-shortcut`/`clipboard-manager`/`shell`/`dialog`), TailwindCSS 3, Vitest. No state/router/UI-component library, no ESLint.
- Rust (`gui/src-tauri/`): tauri 2.3 (`tray-icon`), serde/serde_json, chrono (`clock`), rand. Hand-rolled mini-TOML scanner + keymap parser (deliberate, not a missing dependency).
- Browser extension: Manifest V3 vanilla JS, no build step, SSE parsing mirrors `gui/src/lib/api.ts`.

Other architectural patterns not covered by hard rules above: async job hand-off for slow paths (YouTube transcript+summarization runs on a background executor, write-before-summarize so a transcript is never lost on summarization failure); Map-Reduce chunked summarization with token-budget math in `summarizer.py`; single-window design in the Tauri shell (menu and pill coexist in the main window with the menu rendered as an overlay inside `PillOverlay.tsx` + `PillMenu/`, avoiding cross-monitor `WM_DPICHANGED` jumps).

## Coding conventions

- Python: snake_case; module-private helpers prefixed `_` (e.g. `_normalize_base_url`, `_read_note_tags`); type hints on function signatures; no class-based DI/abstraction layers — plain functions and module-level config singletons (`config.py:get_config()`/`reload_config()`).
- TypeScript: `strict` mode is on (`tsconfig.json`) with `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch` — code must satisfy these, not suppress them. Pure geometry/logic stays in `lib/*.ts` with no side effects and a sibling `*.test.ts`; stateful orchestration stays in components/hooks.
- Rust: hand-rolled parsing (mini-TOML scanner, keymap parser) is the deliberate choice over pulling in a crate for one narrow read — do not "fix" this by adding a dependency.
- No linter or formatter is configured in this repo (no ESLint, no Prettier, no `pytest.ini`, no `pyproject.toml`). Match surrounding file style exactly; do not introduce a linter/formatter config as a side effect of an unrelated change.
- No abstraction for a single implementation: single-entry dicts/maps tied to one real domain concept (e.g. `storage_engine._LEDGER_FILES`) are acceptable; do not generalize them speculatively.
- Icons: every user-facing icon is an inline SVG (`stroke=currentColor`, `aria-hidden`, `size` prop) exported from `gui/src/components/PillMenu/icons.tsx` (`MenuIcon`, `RefreshIcon`, `ChatIcon`, `MicIcon`) — **never emoji**, and no new one-off inline SVG copies when an export exists.
- UI mocks & decision previews (AskUserQuestion previews, HTML mocks like `mock_compact_ui.html`): represent icons with the product's actual icon names or neutral tokens (`[search]`, `↻`) — never emoji stand-ins; every visual token in a mock is read as a design proposal.

## File structure

```
omni_capture/             Python pipeline + FastAPI server
  main.py                 CLI entry, run_pipeline()
  server.py                FastAPI app, SSE, _run_pipeline_blocking(), YouTube job executor
  interceptor.py            clipboard/injected-input -> InputPayload
  enrichment_router.py       content-shape dispatch -> EnrichedPayload
  pre_resolver.py             heuristic category hint
  vector_store.py             SQLite-backed embeddings, cosine top-k
  link_resolver.py            wikilink index (frontmatter aliases)
  llm_engine.py                Ollama call via instructor, two-pass retry
  models.py                     CaptureOutput / dynamic category schema
  projects.py                    project tag parser (#project@<name>), name validity, structural-tag rules
  project_registry.py             .projects.toml load/save/merge, resolve_project, rebuild_from_vault
  project_tidy.py                  pure move planner + locked atomic applier (desktop re-paths a file)
  storage_engine.py             vault write, dedup, merge, scratchpad routing
  summarizer.py                Map-Reduce chunked summarization
  index_writer.py               captures.db (FTS5) read/write/migrate
  tag_vocab.py                  normalize new tags against vault's existing tag vocabulary (reads captures.db)
  reminders.py                  SQLite reminders store (operational state; scheduling authority only) + Windows Task Scheduler delivery
  config.py                     TOML config singleton
  capture_log.py / notifier.py / timing.py   side channels
  test_*.py                    pytest, one file per concern, no conftest
  config.toml                  vault root, Ollama, pipeline tuning

gui/
  src/
    App.tsx                  pill window controller: geometry, drag/snap/clamp, menu open/close
    main.tsx                    Vite entry point (index.html)
    components/                 panels: Settings, VaultManager, Inbox, Search, Stats, CaptureOverlay
    components/PillMenu/         RadialMenu, CapsuleMenu, DevTuner, icons.tsx (MenuIcon/RefreshIcon/ChatIcon/MicIcon — the shared SVG icon set)
    components/PillMenu/FluidVisualizer.tsx   Siri-style fluid audio visualizer (line + ring variants)
    components/CompactPanels/    in-pill compact panels: CompactShell (text-only title header + headerActions slot, no tab strip) + Look/Settings/Inbox/Vault/History content (capsule extruded-sheet + minimal island-morph)
    components/ErrorBoundary.tsx  class boundary; compact panels auto-collapse to pill on crash (pill-error tint), FullWindow views show inline Retry
    lib/                         pure modules: monitor, menuGeometry, fanLayout, pillAnchor, api, config, logger, tauri, devTuning (each with sibling *.test.ts where logic is non-trivial)
    lib/compactPanel.ts          pure: vertical-zone resolve + capsule-panel & minimal island-morph window geometry (sibling compactPanel.test.ts)
    lib/reconcileEdges.ts        pure: reconcile-effect edge truth-table (leavingPill/openingPanel/panelModeSwitch...) — Bug-A regression tests live in sibling reconcileEdges.test.ts
    lib/waveform.ts              pure noise-gate math for voice recording (feeds lib/fluidviz.ts)
    lib/fluidviz.ts              pure fluid-visualizer curve/ring math
    lib/recorder.ts              MediaRecorder + AnalyserNode mic wrapper
    lib/voiceLimits.ts           recording cap + elapsed formatting
    lib/reminderFormat.ts        Today/Tomorrow/date formatting for reminders
    hooks/useCapture.ts          capture lifecycle, in-flight/dismiss/poll guards
    hooks/useVoiceRecording.ts   voice recording state machine
  src-tauri/
    src/lib.rs                  Rust entry: spawns Python child, unified log, global hotkey, tray
    src/main.rs
    tauri.conf.json              window definitions (single main window)
    capabilities/                 Tauri v2 permission manifests

browser_extension/         Manifest V3, vanilla JS, no build step
  background.js              SSE stream parsing, mirrors gui/src/lib/api.ts protocol

launch.ps1                Windows whole-app launcher
```

## Skills & session workflow

- `SKILLS.md` (repo root) lists the installed Claude Code skills. Load design skills before touching UI: `uiux-pro-max`/`impeccable-pbakaus` before layout edits, `animotion` before motion/easing changes — their guidance refines, never overrides, this file's hard rules.
- Plan execution is delegated to subagents with model tiering: Sonnet (low effort for mechanical edits, medium for multi-file) by default, Opus only for genuinely hard reasoning (state-machine/concurrency surgery). Tests + code review run once per batch after development, not per task. Claude may commit directly when gates are green (standing permission granted 2026-07-29, see
workspace CLAUDE.md); no Co-Authored-By lines.
- `skill-observations/log.md` (repo root, git-ignored) is the task-observer log — check OPEN observations at session start and log new ones as they occur.
- Manual QA for GUI lifecycle changes: run `.\launch.ps1`, cycle Minimal→Capsule→Full and back, toggle every compact sub-view fast, verify at 100% AND 125/150% display scale. Automated tests cannot drive the native window — geometry/animation changes are not "done" until this pass.
