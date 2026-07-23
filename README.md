# Second Thought

*Offload to offline, snap-to-store pipeline. Keep thinking; we handle the rest.*

## What is it?

Most tools force you to categorize the moment inspiration strikes. Second Thought removes that friction by automating filing, organization, and linking via a local reasoning pipeline. Capture raw input — text, URLs, voice, images, code snippets — and the system intelligently routes it into your markdown knowledge base. No flow interruption. No folder navigation. No naming conventions. Think of it as a personal librarian that never asks where to put things.

The entire system runs on your machine. The only network access is to your local Ollama instance and optional URL fetches for content you explicitly capture. No cloud backend. No account. No telemetry. No lock-in. Your vault is a portable folder of plain `.md` files — compatible with Obsidian, Logseq, or any text editor.

**TL;DR:** Capture anything, instantly. A local LLM structures, tags, and routes it directly to the markdown vault. No cloud. No context switching. Zero friction. Local-first · AI-organized · Yours

## Highlights

- **Local-first by design** — notes, indexes, config, and models stay on your machine.
- **Markdown vault as source of truth** — files are authoritative; SQLite/vector indexes are rebuildable caches.
- **Always-available desktop capture** — Tauri pill window, global hotkey, tray, and radial menu keep capture one gesture away.
- **Multiple input paths** — clipboard, direct text, URLs, GitHub links, YouTube transcripts, images, audio, CLI, and browser extension.
- **Local AI enrichment** — Ollama powers structured extraction, summarization, categorization, tagging, and note generation.
- **Offline transcription** — Whisper transcribes voice memos and audio locally.
- **Smart searchable knowledge base** — full-text search, vector similarity, backlinks, aliases, and wikilink resolution.
- **Inbox workflow** — review, categorize, approve, or discard captures before they land in the vault.
- **Dashboard & library views** — monitor capture health, browse categories, explore capture rhythm.
- **Vault sync** — index orphan cleanup and reconciliation on startup.
- **Fail-safe storage** — uncertain captures route to scratchpad, transcripts land before summaries, derived indexes stay derived.



## Architecture

Second Thought has three cooperating layers:

1. **Desktop shell** — Tauri + React + TypeScript. Owns the always-on pill window, radial menu overlay, full-window dashboard, library browser, Look panel (search/chat), settings, inbox, global hotkey, and tray.
2. **Capture pipeline** — Python backend that runs as CLI or FastAPI server. Intercepts input, enriches content (web pages, YouTube, audio, images), structures via local Ollama, handles dedup/merge, and writes to vault.
3. **Vault** — Obsidian-compatible `.md` directory. The authoritative source of truth. Indexes (`captures.db`, `vectors.db`, `dedup_index.json`) are derived and rebuildable.

```text
[clipboard / CLI / browser extension / GUI]
        |
        v
1. intercept -- interceptor.py -> InputPayload
        |
        v
2. enrich    -- enrichment_router.py -> EnrichedPayload
        |         (long/expensive jobs -- YouTube, long voice memos --
        |          hand off here to a background job; GUI polls
        |          GET /jobs/{id} instead of waiting on the SSE stream)
        v
3. decide    -- pre_resolver.py category hint + llm_engine.py -> CaptureOutput
        |
        v
4. write     -- storage_engine.py
        |
        +-- write new note
        +-- merge into existing note
        +-- route uncertain capture to scratchpad
        |
        v
index_writer.py + vector_store.py + link_resolver.py
```



## Repository Layout

```text
.
├── omni_capture/          # Python capture pipeline and FastAPI backend
├── gui/                   # Tauri + React desktop app
├── browser_extension/     # Manifest V3 Chrome extension
├── launch.ps1             # Windows launcher for the full app
├── config.toml            # Local configuration
└── README.md
```

Key backend modules:

- `main.py` — CLI entry point and synchronous pipeline runner.
- `server.py` — FastAPI server, SSE capture stream, settings, search, stats, inbox, vault sync, and vault management endpoints.
- `interceptor.py` — converts clipboard, text, URL, and audio input into normalized payloads.
- `pre_resolver.py` — heuristic category hint computed during the decide stage on enriched text.
- `enrichment_router.py` — dispatches URL fetches, GitHub metadata, YouTube transcripts, audio transcription, image OCR, and long-form summarization.
- `llm_engine.py` — calls Ollama via structured output parsing with two-pass retry on parse failures.
- `storage_engine.py` — deduplicates, merges, writes notes, or routes low-confidence captures to scratchpad.
- `vector_store.py` — SQLite-backed embedding search and semantic indexing.
- `rag_engine.py` — hybrid RRF retrieval (semantic + FTS5) and zero-hallucination context for Look panel chat.
- `index_writer.py` — SQLite FTS5 index over vault Markdown files.
- `link_resolver.py` — builds wikilink and alias relationships from vault frontmatter.
- `summarizer.py` — map-reduce chunked summarization for long documents and transcripts.
- `vault_sync.py` — index reconciliation: removes orphans, adds/updates changed files on startup.
- `frontmatter.py` — YAML frontmatter parsing helpers.

Key frontend modules (single-window design — there is no separate menu window; the menu
renders as an overlay inside the same Tauri window):

- `src-tauri/` — Rust shell: spawns Python backend, global hotkey, tray, window lifecycle.
- `App.tsx` — pill window controller: dragging, snapping, clamping, display-mode/panel state.
- `PillOverlay.tsx` — pill chrome, voice-record gesture, hosts the radial/capsule menu overlay.
- `PillMenu/RadialMenu.tsx` / `PillMenu/CapsuleMenu.tsx` — the two menu presentations (minimal vs capsule display mode).
- `FullWindow/FullWindow.tsx` — full-window app: rail navigation between Dashboard, Look, Library, and Settings.
- `FullWindow/DashboardView.tsx` — capture status, recent activity, health indicators, inbox tile.
- `FullWindow/LibraryView.tsx` — vault browser, category breakdown, daily capture rhythm sparkline.
- `LookPanel.tsx` — dual-mode search and RAG chat over vault with source attribution.
- `InboxPanel.tsx` — review, approve, discard, and auto-categorize captures before vault write.
- `CompactPanels/` — in-pill compact panels for capsule/minimal display modes: `CompactShell` (header + body chrome) hosting `CompactLook`, `CompactInbox`, `CompactVault`, `CompactHistory`, and `CompactSettings`.
- `ErrorBoundary.tsx` — crash containment for panel content; compact panels collapse to the pill on error, full-window views show an inline retry.
- `hooks/useCapture.ts` — capture lifecycle state machine and SSE polling.
- `lib/*.ts` — pure geometry, monitor, API, config, and layout helpers with sibling tests.



## Requirements

- Python 3.10+
- Node.js 18+
- Rust toolchain
- Ollama running locally
- A local Ollama model, for example:

```bash
ollama pull mistral
```

Optional capabilities:

- A vision-capable Ollama model for image capture.
- `openai-whisper` and `torch` for local audio transcription.
- `rapidocr-onnxruntime` for OCR-assisted image capture.



## Quick Start



### 1. Start Ollama

```bash
ollama serve
curl http://localhost:11434/api/tags
```

The configured Ollama base URL must be bare:

```toml
[ollama]
base_url = "http://localhost:11434"
```

Do not add `/v1` in `config.toml`. The app appends `/v1` internally only where the OpenAI-compatible API path is required.

### 2. Install backend dependencies

```bash
cd omni_capture
pip install -r requirements.txt
python main.py --self-check
```



### 3. Run the desktop app in development

```bash
cd gui
npm install
npm run dev
```



### 4. Run the full Windows app

```powershell
.\launch.ps1
```

The launcher builds the GUI only when needed, starts the release app, and runs the Python backend from source.

## CLI Usage

Run these commands from `omni_capture/`.

```bash
python main.py
python main.py --text "A thought to file into the vault"
python main.py --url "https://example.com/article"
python main.py --audio path/to/memo.mp3
python main.py --dry-run
python main.py --verbose
python main.py --log
python main.py --log --stats
```

Common workflows:

- Capture clipboard contents with `python main.py`.
- Inject text directly with `--text`.
- Capture and summarize a page with `--url`.
- Transcribe and structure audio with `--audio`.
- Preview model output without writing to the vault with `--dry-run`.
- Inspect pipeline stages with `--verbose`.
- Tail or summarize the audit log with `--log`.



## Desktop App

The Tauri app is a single window that switches between three display modes — `full` (dashboard with rail navigation), `capsule` (pill with an expanded menu strip), and `minimal` (bare pill, radial menu). The menu overlay renders inside the same window rather than a second window, which avoids cross-monitor `WM_DPICHANGED` jumps; geometry stays stable.

**Pill (capsule/minimal modes):**

- Global hotkey trigger (default `Ctrl+Shift+Space`).
- Drag-snap-clamp behavior; follows screen edges and respects multiple monitors.
- Radial menu (minimal) or capsule menu (capsule) for quick capture actions.
- Voice memo recording: right-click the pill to start recording, left-click to stop and send, Esc to cancel.
- In capsule/minimal mode, opening Look, Inbox, Vault, History, or Settings expands the pill into an in-place compact panel instead of switching to the full window.

**Full-window dashboard:**

- **Dashboard** — capture-in-progress card, recent activity, system health, and inbox tile. Drag-and-drop files to queue for capture.
- **Library** — vault browser, live category breakdown, daily capture rhythm sparkline.
- **Look panel** — dual-mode search and RAG chat. Search queries vault via FTS5 full-text. Chat mode retrieves relevant notes via hybrid semantic + lexical ranking (Reciprocal Rank Fusion), cites sources inline, never hallucinates outside vault context. Access via `Ctrl+K` or menu.
- **Inbox workflow** — review low-confidence captures, auto-suggest categories, approve to vault or discard. Prevents noisy/uncertain notes from cluttering knowledge base.
- **Settings** — vault path, model selection, capture behavior, theme, display modes, pill anchor, fan styles, and vault sync control.
- **System tray** — quick access to dashboard, capture, search, settings.

All window positioning uses logical coordinates; monitor geometry helpers ensure DPI-aware placement across multi-monitor setups.

## Browser Extension

The Manifest V3 Chrome extension sends the current tab URL and selected text directly to the FastAPI server without using the clipboard.

Install it locally:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `browser_extension/` folder.
5. Open extension settings and set the server URL to:

```text
http://localhost:7070
```

The extension follows the same SSE capture protocol as the desktop GUI.

## Capture Pipeline

Each capture follows the same four-stage sequence in both CLI and GUI paths — the GUI's SSE
stream emits a `step` event (`intercept|enrich|decide|write`, each `active`/`done`/`error`) for
each one.

### 1. Intercept

`interceptor.py` reads clipboard, injected text, file drag-drop, or API input and normalizes it into an `InputPayload`.

### 2. Enrich

`enrichment_router.py` dispatches content-specific enrichment:

- **Web pages** — fetched and converted to readable text via readability-lxml.
- **GitHub links** — parsed as technical metadata source.
- **YouTube URLs** — transcripts fetched via youtube-transcript-api.
- **Audio files** — transcribed locally via openai-whisper.
- **Images** — optional OCR via rapidocr-onnxruntime; vision-capable Ollama models extract content.
- **Long-form content** — map-reduce chunked summarization with token budgeting.

Most enrichment paths fail softly: if web fetch fails, raw URL is preserved. Vision capture is stricter: if image understanding is required but unavailable, the pipeline marks the capture and routes it away from confident LLM processing.

YouTube transcripts and voice memos long enough to need map-reduce summarization are handed off
to a background job instead of blocking this stage: the server emits a `job` SSE event
(`job_id`, `kind: "youtube"|"voice"`) and closes the stream, and the GUI polls
`GET /jobs/{job_id}` until the job completes.

### 3. Decide

`pre_resolver.py` detects content shape (plain text, URL, GitHub, YouTube, image, audio file) and emits a category hint from the *enriched* text, then `llm_engine.py` calls Ollama to produce structured `CaptureOutput` (category, title, tags, body). On parse failure, the engine retries with stricter instructions (two-pass retry).

### 4. Write

`storage_engine.py` decides: write new note, merge into existing via content similarity, or route uncertain captures to scratchpad. `index_writer.py` updates SQLite FTS5 and audit log. `vector_store.py` embeds and indexes for semantic search.

### Voice Capture

The GUI pill supports voice memo recording: right-click the pill to start recording, left-click to stop and send, or press Esc to cancel. Recordings are limited to 10 minutes. Captured audio is transcribed via local `openai-whisper` and automatically routed to the enrichment pipeline.

**Requirement:** `ffmpeg` must be on your PATH for webm/opus decoding. Install via:

```bash
winget install Gyan.FFmpeg
```



### Reminders

When a capture contains a concrete future date/time, the app offers to set a reminder. Reminders are stored locally in SQLite and delivered one of two ways (Settings → Reminders): **In-app** (default) — an in-server due-checker fires a desktop notification while the app is running; or **Windows Task Scheduler** — the reminder fires even when the app is closed.

## Vault Model

The vault is a folder of Markdown files with YAML frontmatter. It's portable, compatible with Obsidian, Logseq, or any text editor, and stays meaningful even if all databases disappear.

**Key rules:**

- Files are authoritative. Indexes (`captures.db`, `vectors.db`, `dedup_index.json`) are derived and rebuildable.
- Folder names define available categories at runtime (never hardcoded).
- Frontmatter aliases and tags power wikilink resolution and dedup matching.
- Full-text and vector indexes are continuously rebuilt as files change.
- `vault_sync.py` runs on startup: removes orphan index rows, reconciles file changes.



## Privacy

Second Thought is designed to run on a single user machine.

- No cloud backend is required.
- No telemetry is required.
- No external database is required.
- Ollama calls go to the local host.
- Whisper transcription runs locally.
- URL, GitHub, and YouTube fetches only happen for content the user explicitly captures.

Moving the vault folder and updating `config.toml` is the migration path.

## Failure Philosophy

The pipeline is designed to avoid losing data and avoid inventing certainty.

- Web, GitHub, YouTube, and audio enrichment preserve the raw capture when enrichment fails.
- Vision capture can fail fast when image understanding is required.
- Low-confidence captures are routed to scratchpad.
- YouTube transcripts are written before summarization so a failed summary does not lose the transcript.
- Merge and dedup decisions read actual Markdown files, not only derived indexes.

Known gap: a total LLM failure (Ollama unreachable, both structured-output passes fail) currently
drops the capture with no scratchpad fallback — tracked as a P0 item in `docs/ROADMAP.md`; this
line will be removed once that fallback ships.

## Inbox Workflow

Uncertain captures are held in inbox for human review before landing in the vault. This prevents low-confidence LLM outputs and noisy duplicates from cluttering your knowledge base.

The inbox interface shows:

- Raw capture content and extracted text.
- Auto-suggested category (editable).
- Approve to write to vault, or discard.
- Category auto-learn from your approvals over time.

Inbox items are transient and cleared after approval or discard. The vault remains the single source of truth.

## Vault Sync & Index Reconciliation

On startup, `vault_sync.py` runs an index reconciliation:

- Removes index rows for deleted vault files.
- Adds/updates index entries for changed files.
- Rebuilds FTS5 and vector embeddings incrementally.

Orphan cleanup is fast (no LLM calls) and safe for every startup. Use it to recover vault state if databases become stale or corrupted.

```bash
python -c "from vault_sync import purge_orphan_index_entries; purge_orphan_index_entries(vault_root)"
```



## Development Commands



### Python

```bash
cd omni_capture
pytest
python main.py --self-check
python main.py --verbose --dry-run --text "Test capture"
```



### GUI

```bash
cd gui
npm run dev
npm run dev:vite
npm run build
npm test
```



### Rust

```bash
cd gui/src-tauri
cargo check
cargo build
```



## Testing

The project uses focused tests per layer:

- `pytest` for Python pipeline modules.
- Vitest for pure TypeScript modules under `gui/src/lib`.
- `npm run build` for TypeScript and Vite production build validation.
- `cargo check` or `cargo build` for the Tauri shell.

Before committing GUI changes, `npm run build` should pass.

## Key Constraints

These are load-bearing decisions. Violating them causes real regressions:

- **Ollama base URL must be bare** (`http://localhost:11434`), never `/v1`-suffixed. App appends `/v1` only where OpenAI-compatible paths are required (text LLM calls); native endpoints (vision, embeddings, `/api/tags`) require the bare host.
- **Files are authoritative.** Never let a database row override file-based decisions for dedup, merge, or category routing.
- **Vision failures are fail-fast.** When `image_required = true` and vision unavailable, mark it and route away from confident LLM processing; don't silently become a text capture.
- **CLI and FastAPI paths duplicate intentionally.** Same four-stage sequence in `main.py:run_pipeline()` and `server.py:_run_pipeline_blocking()`. Any change (retry logic, context assembly, index updates) must be mirrored in both by hand — don't collapse into a callback to avoid inverting control flow over the hottest code path.
- **Tauri geometry uses** `LogicalPosition`**/**`LogicalSize`**.** All monitor reads go through `gui/src/lib/monitor.ts` (divides by `scaleFactor`). Never write physical coordinates into `Logical`* calls.
- **Vault categories are never hardcoded.** Live folder names define the enum at runtime via `models.py:build_capture_model()`.



## Workflows

**Capturing:**

- Hit `Ctrl+Shift+Space`, capture from clipboard or open the menu for text/URL/audio input.
- Pill follows you across monitors; snaps to edges; drag to move.
- Switch to the full window (Dashboard) if you want to monitor progress, review inbox, or search.

**Filing:**

- Most captures land directly in vault (auto-categorized, tagged, linked).
- Low-confidence captures hold in inbox for your review.
- Approve to vault or discard; categories auto-learn from your choices.

**Searching & exploring:**

- Dashboard shows recent activity, capture rhythm, category breakdown.
- Library browser navigates vault; Look panel searches (FTS5) or chats (RAG).
- Chat cites sources inline; never answers outside vault context.

**Maintaining:**

- Vault sync reconciles indexes on startup (safe to run whenever).
- All data stays in `.md` files; databases are rebuildable.

**Result:** A growing Markdown knowledge base searchable, linkable, synced, backed up, and edited with normal tools. Zero lock-in.

**Stop deciding where things go.**
Copy data. Click capture. Let the pipeline file it.
Your first thought is the idea — the second thought, is yours