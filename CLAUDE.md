# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Second Thought is a local-first "second brain" capture pipeline: clipboard/share content (text, URLs, images, audio) is enriched, classified by a local LLM (Ollama), and written as Markdown into an Obsidian-style vault. It has three parts:

- `omni_capture/` — Python pipeline + FastAPI server (the actual brains).
- `gui/` — Tauri (Rust) + React/TypeScript desktop shell that spawns the Python server and provides a capture overlay, settings, inbox, search/stats UI.
- `browser_extension/` — Manifest V3 Chrome extension that POSTs directly to `/share` (no clipboard).

Vault root, Ollama settings, and pipeline tuning all live in `omni_capture/config.toml`.

## Common commands

Python (run from `omni_capture/`, or with `omni_capture` on `PYTHONPATH`):

```bash
pip install -r omni_capture/requirements.txt

python main.py                       # capture from clipboard (full pipeline)
python main.py --text "..."          # inject text directly (skip clipboard)
python main.py --url "https://..."   # inject a URL directly
python main.py --audio path.mp3      # transcribe via local Whisper
python main.py --dry-run             # print LLM output, don't write to vault
python main.py --verbose             # print every pipeline stage's output
python main.py --self-check          # verify Ollama/vault/whisper/index are all OK
python main.py --log                 # tail the capture audit log
python main.py --log --stats         # category breakdown stats
```

Tests (pytest, no special config file — run from `omni_capture/`):

```bash
pytest                                          # full suite
pytest test_routing_and_merge.py                # one file
pytest test_routing_and_merge.py -k test_name   # one test
pytest tests/test_e2e.py                        # end-to-end pipeline tests
```

Several modules (`enrichment_router.py`, others) also have an `if __name__ == "__main__":` smoke-test block runnable directly, e.g. `python enrichment_router.py`.

GUI server (FastAPI bridge, used standalone or spawned by the Tauri app):

```bash
python -m uvicorn omni_capture.server:app --port 7070   # run from project root
```

GUI frontend/app (run from `gui/`):

```bash
npm run dev         # tauri dev (spins up Vite + Rust + Python together)
npm run dev:vite     # Vite only, no Tauri shell
npm run build        # tsc typecheck + vite build
```

Whole-app launcher (Windows, from project root):

```powershell
.\launch.ps1            # builds (if stale) and runs the release Tauri binary
OMNI_DEV=1 .\launch.ps1  # force dev mode (npx tauri dev)
```

## Architecture: the pipeline

Every capture — whether from the CLI, the GUI hotkey, or the browser extension's `/share` — flows through the same four stages, defined across separate modules and orchestrated in `main.py:run_pipeline()` (CLI) and `server.py:_run_pipeline_blocking()` (GUI/HTTP, kept in sync with the CLI path):

1. **Interceptor** (`interceptor.py`) — reads the clipboard (or accepts injected text/url/image bytes) into an `InputPayload`.
2. **Enrichment Router** (`enrichment_router.py`) — classifies input by regex/shape and dispatches: web URL → `readability-lxml` article extraction, GitHub URL → GitHub API metadata, YouTube URL → caption transcript + "anti-tutorial-hell" code-line filter, image → local LLaVA vision model (+ optional RapidOCR pass) via Ollama, audio → local Whisper, plain text → pass-through. Produces an `EnrichedPayload`.
3. **Pre-Resolver + Semantic Retrieval** (`pre_resolver.py`, `vector_store.py`) — cheap heuristic category hint plus embedding-based "related notes" search (Ollama embedding model, configurable similarity floor) — both fed into the LLM as context.
4. **LLM Decision Engine** (`llm_engine.py`) — calls Ollama (via the `instructor`-wrapped OpenAI-compatible client) with a dynamically-built Pydantic schema (`models.py:build_capture_model()`) whose `category` field is a JSON-schema enum constrained to the vault's *actual* current folder names — categories are discovered live from the filesystem on every run, not hardcoded. Returns a `CaptureOutput` (category, filename, markdown, rationale, confidence, etc.).
5. **Storage Engine** (`storage_engine.py`) — writes/merges the note into the vault, handles dedup (content-hash index), wikilink injection, and routes low-confidence/no-fit captures to a `_scratchpad` inbox for manual review instead of guessing wrong.

Side channels: `notifier.py` (desktop notifications), `capture_log.py` (JSONL audit log read by `--log`), `config.py` (TOML config singleton with `reload_config()`/`get_config()`).

### Two-pass classification fallback

When the pre-resolver's confidence is `"low"` and the LLM's first-pass category lands in `CRM` or `Finance`, the pipeline re-runs the LLM call with the existing on-disk note for that entity loaded as context (`read_existing_context`), so it can merge into the right file instead of creating a duplicate. This happens identically in both `main.py` and `server.py`.

### YouTube is special: async background jobs

Because YouTube transcript fetch + (possibly chunked) summarization can take a long time, `/capture` does **not** block on it: `server.py` detects a YouTube URL, hands off to `_run_youtube_job` on a separate executor, and immediately emits a `job` SSE event so the GUI polls `/jobs/{job_id}` instead. The raw transcript is written to the vault note *before* any LLM summarization call (`create_youtube_note` → `finalize_youtube_note`), so a transcript can never be lost even if summarization fails mid-job. Long transcripts go through Map-Reduce chunked summarization (`summarizer.py`) with token-budget math driven by `[capture]` keys in `config.toml`.

### The `/v1` base-URL invariant

`cfg.ollama.base_url` must always stay **bare** (e.g. `http://localhost:11434`), never `/v1`-suffixed. `/v1` is appended only at the point an OpenAI-compatible client is constructed (`llm_engine._normalize_base_url`), because native Ollama endpoints used directly (vision `/api/generate`, embeddings, `/api/tags`, tokenize) require the bare host. Writing `/v1` into the env var or back into config has caused real regressions (404s on every image capture) — see the regression tests at the bottom of `enrichment_router.py` (T10/T10b) and `tests/test_e2e.py` before touching anything that sets `OLLAMA_BASE_URL`.

### Graceful degradation, not hard failures

Most enrichment paths (web fetch, GitHub API, YouTube, vision, audio) catch their own exceptions and return a placeholder `EnrichedPayload` rather than raising, so a single failed network call doesn't crash a capture — except vision, which raises instead when `[ollama] image_required = true`. When vision fails, `source_metadata["vision_available"] = False` is checked explicitly by both `main.py` and `server.py` *before* the LLM stage, and the capture is routed straight to a scratchpad retry queue rather than letting the LLM classify a useless placeholder with false confidence.

## Architecture: GUI shell

`gui/src-tauri/src/lib.rs` is the Rust entry point. On startup it:
1. Spawns `python -m uvicorn omni_capture.server:app --port 7070` as a child process, generating a fresh random `X-Omni-Secret` per launch and passing it via env (never logged).
2. Pipes the Python child's stdout/stderr into the same unified, size-rotated, age-pruned log file used for Rust-origin and frontend-origin log lines (`logs/second-thought-<launch-id>.log`), so one timeline covers all three sources.
3. Registers a global hotkey (read from `config.toml [gui] hotkey`, default `ctrl+shift+space`) that shows the window and emits a debounced `trigger-capture` event to the frontend.
4. Builds a system tray (Vault Settings / Open Settings / Inbox / Stats / Quit) that kills the Python child on quit.

`server.py` is the only thing the frontend (`gui/src/`) talks to over HTTP — see the endpoint list and SSE event shapes documented at the top of that file. All routes except `/health` require the `X-Omni-Secret` header (skipped with a startup warning if `OMNI_GUI_SECRET` is unset, e.g. running the server standalone for local dev).

`launch.ps1` only rebuilds the Rust/Tauri binary when GUI source paths change (`$watchPaths`) — it deliberately excludes `omni_capture/`, since the Python backend runs from source via `uvicorn` and needs no compile step.
