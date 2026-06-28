# AGENTS.md

Omni Capture is a local-first clipboard/URL/audio capture pipeline that enriches input via Ollama and files it into an Obsidian-style markdown vault, fronted by a Tauri pill-and-radial-menu GUI.

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

Tests — pytest, no config file, run from `omni_capture/`:
```bash
pytest                                          # full suite
pytest test_routing_and_merge.py -k test_name   # single test
pytest tests/test_e2e.py                        # end-to-end
```
Modules with an `if __name__ == "__main__":` smoke block run standalone, e.g. `python enrichment_router.py`, `python storage_engine.py`, `python llm_engine.py`, `python summarizer.py`.

GUI server (standalone, also auto-spawned by Tauri):
```bash
python -m uvicorn omni_capture.server:app --port 7070   # from project root
```

GUI frontend (`gui/`):
```bash
npm run dev          # tauri dev: Vite + Rust + Python together
npm run dev:vite      # Vite only, no Tauri shell
npm run build         # tsc typecheck + vite build — MUST pass before any GUI commit
npm test              # vitest run — pure lib/*.ts modules
```

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
- **Vault categories are never hardcoded.** `models.py:build_capture_model()` builds the `category` enum live from the vault's current folder names on every call. *(constrains: `models.py`)*
- **Vision failure is fail-fast, every other enrichment path is fail-soft.** When `[ollama] image_required = true` and vision fails, `source_metadata["vision_available"] = False` must be checked explicitly before the LLM stage and routed to the scratchpad — do not let a placeholder reach the LLM with false confidence. Web/GitHub/YouTube/audio handlers catch their own exceptions and return a placeholder instead. *(constrains: `enrichment_router.py`, `storage_engine.py`)*
- **Files are the source of truth, `captures.db`/`vectors.db`/`dedup_index.json` are derived indexes.** Never make a SQLite table authoritative over vault `.md` files for merge/dedup/link decisions — every perf fix in this codebase caches in front of the file read instead of migrating authority into the DB. *(constrains: `storage_engine.py`, `index_writer.py`, `vector_store.py`)*
- **Tauri window geometry: only `LogicalPosition`/`LogicalSize`.** Every monitor read goes through `gui/src/lib/monitor.ts` (already divides by `scaleFactor`). Never write a physical coordinate into a `Logical*` call — this is the recurring cross-monitor/DPI bug class in this code. *(constrains: `gui/src/App.tsx`, `gui/src/lib/monitor.ts`)*
- **`ponytail:` comments mark a deliberate shortcut with a named ceiling and upgrade path** (e.g. `# ponytail: unbounded tag cache; cap if a vault ever holds 10k+ notes`). Preserve this convention on any new intentional simplification; don't silently "fix" a `ponytail:`-marked shortcut without re-evaluating whether its stated ceiling has actually been hit.
- **Non-trivial logic ships with one runnable check.** For an agent: any new branch, loop, parser, or money/security path needs either an `assert`-based `__main__` smoke block in the same module, or a small sibling `test_*.py`/`*.test.ts` — not a full framework/fixture suite — and that check must be run (`pytest <file>` or `npm test`) before the change is considered done. Trivial one-liners need no test.

## Tech stack

- Python (`omni_capture/`): FastAPI+Uvicorn, Pydantic v2, instructor (structured Ollama output), openai SDK (as Ollama's OpenAI-compatible client only), readability-lxml, youtube-transcript-api, openai-whisper+torch, Pillow, rapidocr-onnxruntime (optional), pyperclip, tomlkit, plyer, stdlib sqlite3, pytest.
- TypeScript (`gui/`): React 18 (hooks only), Vite 8 multi-page (`index.html`+`menu.html`), Tauri v2 (`global-shortcut`/`clipboard-manager`/`shell`/`dialog`), TailwindCSS 3, Vitest. No state/router/UI-component library, no ESLint.
- Rust (`gui/src-tauri/`): tauri 2.3 (`tray-icon`), serde/serde_json, chrono (`clock`), rand. Hand-rolled mini-TOML scanner + keymap parser (deliberate, not a missing dependency).
- Browser extension: Manifest V3 vanilla JS, no build step, SSE parsing mirrors `gui/src/lib/api.ts`.

Other architectural patterns not covered by hard rules above: async job hand-off for slow paths (YouTube transcript+summarization runs on a background executor, write-before-summarize so a transcript is never lost on summarization failure); Map-Reduce chunked summarization with token-budget math in `summarizer.py`; two-window-per-concern in the Tauri shell (pill window stays static, `MenuWindow.tsx` is a separate overlay window, avoiding cross-monitor `WM_DPICHANGED` jumps).

## Coding conventions

- Python: snake_case; module-private helpers prefixed `_` (e.g. `_normalize_base_url`, `_read_note_tags`); type hints on function signatures; no class-based DI/abstraction layers — plain functions and module-level config singletons (`config.py:get_config()`/`reload_config()`).
- TypeScript: `strict` mode is on (`tsconfig.json`) with `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch` — code must satisfy these, not suppress them. Pure geometry/logic stays in `lib/*.ts` with no side effects and a sibling `*.test.ts`; stateful orchestration stays in components/hooks.
- Rust: hand-rolled parsing (mini-TOML scanner, keymap parser) is the deliberate choice over pulling in a crate for one narrow read — do not "fix" this by adding a dependency.
- No linter or formatter is configured in this repo (no ESLint, no Prettier, no `pytest.ini`, no `pyproject.toml`). Match surrounding file style exactly; do not introduce a linter/formatter config as a side effect of an unrelated change.
- No abstraction for a single implementation: single-entry dicts/maps tied to one real domain concept (e.g. `storage_engine._LEDGER_FILES`) are acceptable; do not generalize them speculatively.

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
  storage_engine.py             vault write, dedup, merge, scratchpad routing
  summarizer.py                Map-Reduce chunked summarization
  index_writer.py               captures.db (FTS5) read/write/migrate
  config.py                     TOML config singleton
  capture_log.py / notifier.py / timing.py   side channels
  daily_digest.py              orphaned — no call sites, not wired anywhere
  test_*.py                    pytest, one file per concern, no conftest
  config.toml                  vault root, Ollama, pipeline tuning

gui/
  src/
    App.tsx                  pill window controller: geometry, drag/snap/clamp, menu open/close
    MenuWindow.tsx             second Tauri window: renders radial/capsule menu overlay
    main.tsx / menu.tsx         Vite multi-page entry points (index.html / menu.html)
    components/                 panels: Settings, VaultManager, Inbox, Search, Stats, CaptureOverlay
    components/PillMenu/         RadialMenu, CapsuleMenu, DevTuner, icons
    lib/                         pure modules: monitor, menuGeometry, fanLayout, pillAnchor, api, config, logger, tauri, devTuning (each with sibling *.test.ts where logic is non-trivial)
    hooks/useCapture.ts          capture lifecycle, in-flight/dismiss/poll guards
  src-tauri/
    src/lib.rs                  Rust entry: spawns Python child, unified log, global hotkey, tray
    src/main.rs
    tauri.conf.json              window definitions (main pill + menu overlay)
    capabilities/                 Tauri v2 permission manifests

browser_extension/         Manifest V3, vanilla JS, no build step
  background.js              SSE stream parsing, mirrors gui/src/lib/api.ts protocol

launch.ps1                Windows whole-app launcher
```

## Imported Claude Cowork project instructions

# Role
You are an expert in local LLM integrations, Pydantic, and file-system automation. 

# Task
1. Write the core Python architecture for "Project Omni-Capture," a locally-hosted, autonomous Second Brain pipeline. 
2. Generate a simple, clear project document outlining the process, setup steps, and implementation plans.
