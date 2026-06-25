# Omni Capture — Architecture

## 1. System Overview

Omni Capture is a local-first capture pipeline with three cooperating tiers:

1. **Trigger surface** — a Tauri desktop shell (Rust + React/TypeScript) presenting an always-on-top "pill" window and a radial menu overlay.
2. **Pipeline** — a Python process (CLI entry or FastAPI server) that ingests a single piece of content, enriches it via a local LLM (Ollama), and writes the result into a markdown vault.
3. **Vault** — a plain directory of `.md` files (Obsidian-compatible) that is the sole source of truth. All databases (`captures.db`, `vectors.db`, `dedup_index.json`) are derived, rebuildable indexes over the vault, never authoritative.

The system runs entirely on the user's machine. The only network calls are to a local Ollama instance (`http://localhost:11434`) and, optionally, outbound HTTP fetches for URL/YouTube enrichment of content the user explicitly captured.

## 2. Component Breakdown

### 2.1 Trigger Surface (`gui/`)

- **`src-tauri/`** — Rust shell. Spawns the Python backend as a child process on launch, registers a global hotkey, owns the system tray, and defines two windows (`tauri.conf.json`): the static pill window and a separate `MenuWindow.tsx` overlay. Two windows are used deliberately to avoid `WM_DPICHANGED` cross-monitor jumps that a single repositioned window would suffer.
- **`App.tsx`** — pill controller: drag, snap-to-edge, clamp-to-screen-bounds, menu open/close. All geometry math goes through `lib/monitor.ts`, which is the single point that divides physical pixels by `scaleFactor` — every Tauri window call downstream uses only `LogicalPosition`/`LogicalSize`.
- **`MenuWindow.tsx`** — renders the radial/capsule menu (`components/PillMenu/`) as a separate overlay window.
- **`lib/*.ts`** — pure, side-effect-free geometry and protocol modules (`menuGeometry`, `fanLayout`, `pillAnchor`, `api`, `config`), each with a sibling `*.test.ts`.
- **`hooks/useCapture.ts`** — capture lifecycle state machine: in-flight guard, dismiss guard, SSE poll guard against the backend.

### 2.2 Pipeline (`omni_capture/`)

Two hand-duplicated entry points run the same 4-stage sequence by design (not accidentally — see CLAUDE.md hard rules):

- **`main.py:run_pipeline()`** — synchronous CLI path: print/return-dict progress.
- **`server.py:_run_pipeline_blocking()`** — FastAPI/SSE path used by the GUI: streams stage events to the frontend, and additionally hands YouTube jobs off to a background executor.

The 4 stages, common to both:

1. **Intercept** (`interceptor.py`) — turns clipboard contents or injected CLI input (`--text`/`--url`/`--audio`) into a normalized `InputPayload`.
2. **Pre-resolve** (`pre_resolver.py`) — heuristic content-shape detection (plain text vs. URL vs. GitHub vs. YouTube vs. image) to pick a category hint before the LLM is invoked.
3. **Enrich** (`enrichment_router.py`) — dispatches to a content-specific handler (web fetch + readability extraction, YouTube transcript fetch, Whisper transcription, vision model call for images) producing an `EnrichedPayload`. Web/GitHub/YouTube/audio handlers are fail-soft: exceptions are caught and a placeholder is returned. Vision is fail-fast: if `[ollama] image_required = true` and the vision call fails, `source_metadata["vision_available"]` is set to `False` and explicitly checked before the LLM stage, routing straight to the scratchpad rather than letting an LLM reason over a placeholder with false confidence.
4. **Structure + Store** — `llm_engine.py` calls Ollama (via `instructor`, using the OpenAI-compatible client only against the `/v1`-suffixed path internally) to produce a structured `CaptureOutput` (`models.py`), with a two-pass retry if the first structured-output parse fails. `storage_engine.py` then writes the result to the vault: dedup check, merge-into-existing-note decision, or new file, plus scratchpad fallback for low-confidence captures.

Supporting modules:

- **`models.py`** — `CaptureOutput` schema. The `category` enum is rebuilt from the vault's current folder names on every call; categories are never hardcoded.
- **`vector_store.py`** — SQLite-backed embedding store, cosine top-k similarity, used for semantic search and dedup candidate lookup.
- **`link_resolver.py`** — wikilink index built from frontmatter aliases across the vault, used to auto-link new notes to existing ones.
- **`summarizer.py`** — Map-Reduce chunked summarization with token-budget math, used for long-form content (articles, transcripts).
- **`index_writer.py`** — maintains `captures.db` (SQLite FTS5) as a derived full-text index over vault files.
- **`config.py`** — TOML-backed config singleton (`config.toml`): vault root, Ollama connection, pipeline tuning. `get_config()`/`reload_config()`.
- **`capture_log.py` / `notifier.py` / `timing.py`** — side channels: audit log, desktop notifications, stage timing instrumentation.

### 2.3 Server (`server.py`)

FastAPI + Uvicorn app, auto-spawned by the Tauri shell on launch (also runnable standalone for development). Exposes the capture pipeline over SSE for the GUI, plus endpoints for search, vault browsing, settings, and capture history backing the GUI's panels (`Settings`, `VaultManager`, `Inbox`, `Search`, `Stats`, `CaptureOverlay`). Owns the background executor for async YouTube jobs: a transcript is written to the vault immediately on fetch, then summarized in a follow-up step — write-before-summarize ensures a transcript is never lost if summarization later fails.

### 2.4 Browser Extension (`browser_extension/`)

Manifest V3, vanilla JS, no build step. Sends captures to the same FastAPI server and parses its SSE stream using the same protocol as `gui/src/lib/api.ts`, kept in sync by hand.

## 3. Data Flow & State Management

```
[clipboard / CLI input / browser extension]
        |
        v
  interceptor.py  ->  InputPayload
        |
        v
  pre_resolver.py ->  category hint
        |
        v
  enrichment_router.py -> EnrichedPayload   (fail-soft, except vision: fail-fast)
        |
        v
  llm_engine.py (Ollama, instructor, two-pass retry) -> CaptureOutput
        |
        v
  storage_engine.py
        |-- dedup/merge check (reads vault .md files directly)
        |-- write new note OR merge into existing note OR route to scratchpad
        |
        v
  index_writer.py (captures.db FTS5)  +  vector_store.py (embeddings)  +  notifier.py
```

State management is intentionally minimal and process-local:

- **Pipeline state** lives for the duration of a single capture call; there is no persistent in-process session state between captures.
- **Frontend state** (`useCapture.ts`) is a small lifecycle state machine guarding against duplicate in-flight captures, premature dismissal, and overlapping SSE polls — not a general state management library. No Redux/Zustand/router; React hooks only.
- **Durable state** is the vault itself (markdown files + frontmatter) plus the config TOML. `captures.db`, `vectors.db`, and `dedup_index.json` are caches/indexes that can be deleted and rebuilt from the vault without data loss — they never gate a merge/dedup/link decision ahead of reading the actual files.

## 4. Infrastructure, Deployment, Integration

- **Runtime topology**: single user machine. Tauri shell spawns the Python backend as a child process; `launch.ps1` is the Windows entry point and only triggers a GUI rebuild when GUI source paths changed (Python has no compile step and runs from source via `uvicorn`).
- **External integration points**:
  - **Ollama** (`http://localhost:11434`, bare host — never `/v1`-suffixed in config; `/v1` is appended only inside `llm_engine._normalize_base_url`/`_make_client` because native Ollama endpoints for vision, embeddings, `/api/tags`, and tokenize require the bare host).
  - **Outbound HTTP** for URL/GitHub/YouTube content fetched on explicit user capture only.
  - **Local Whisper** (`openai-whisper` + `torch`) for offline audio transcription.
  - **Optional OCR** via `rapidocr-onnxruntime` for image captures.
- **No cloud services, no telemetry, no external database.** The vault directory is portable; moving it (and updating `config.toml`) is the entire migration path.
- **Testing**: pytest for the Python pipeline (one file per concern, no `conftest.py`, plus standalone smoke blocks under `if __name__ == "__main__":` in modules like `enrichment_router.py`, `storage_engine.py`, `llm_engine.py`, `summarizer.py`); Vitest for pure TypeScript `lib/*.ts` modules; `cargo check`/`cargo build` for the Rust shell. `npm run build` (tsc + vite build) must pass before any GUI commit.
