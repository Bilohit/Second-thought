# Second Thought

*Offloaded to offline, snap-to-store pipeline. So keep thinking, we'll handle the rest.*


## What is it ?

Most tools force you to categorize the moment inspiration strikes. Second Thought removes the cognitive load of filing by automating the decision, organizing, and linking processes via a local reasoning pipeline. Instead of breaking your flow with folder navigation, tags, or naming conventions, it lets you capture raw input — text, voice, or images — and intelligently files it into your knowledge base. Think of it as a personal librarian that never interrupts you.

The system runs entirely on your machine. The only network calls are to your local Ollama instance and optional outbound fetches for URLs you explicitly capture. There is no cloud, no account, no telemetry, and no lock-in. Your vault is a portable folder of plain `.md` files — fully compatible with Obsidian, Logseq, or any text editor.

TL;DR -  Capture anything, instantly. A local LLM structures, tags, and routes it directly to your Markdown vault. No cloud, no context switching, zero friction. Local-first · AI-organized · Yours

## Highlights

- **Local-first by design** - your notes, indexes, config, and models stay on your machine.
- **Markdown vault as source of truth** - files are authoritative; SQLite/vector indexes are rebuildable caches.
- **Always-available desktop capture** - a Tauri pill window, global hotkey, tray entry, and radial menu keep capture one gesture away.
- **Multiple input paths** - clipboard, direct text, URLs, GitHub links, YouTube content, images, audio, CLI input, and browser extension captures.
- **Local AI enrichment** - Ollama powers structured extraction, summarization, categorization, tagging, and note generation.
- **Offline transcription** - Whisper handles voice memo and audio capture locally.
- **Searchable knowledge base** - full-text search, vector similarity, backlinks, aliases, and wikilink resolution help notes find each other.
- **Fail-safe storage** - uncertain captures go to scratchpad, long content is written before summarization, and derived indexes never replace source files.

## Architecture

Second Thought has three cooperating layers:

1. **Trigger surface** - a Tauri desktop shell built with Rust, React, TypeScript, and TailwindCSS. It owns the pill window, radial menu overlay, global hotkey, tray, settings, vault views, search, inbox, and capture status UI.
2. **Capture pipeline** - a Python backend that runs as either a CLI process or a FastAPI server. It normalizes input, enriches content, calls local models, and writes structured Markdown into the vault.
3. **Vault** - an Obsidian-compatible directory of `.md` files. This is the durable source of truth. Databases such as `captures.db`, `vectors.db`, and `dedup_index.json` are derived indexes and can be rebuilt.

```text
[clipboard / CLI / browser extension / GUI]
        |
        v
interceptor.py -> InputPayload
        |
        v
pre_resolver.py -> category hint
        |
        v
enrichment_router.py -> EnrichedPayload
        |
        v
llm_engine.py -> CaptureOutput
        |
        v
storage_engine.py
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

- `main.py` - CLI entry point and synchronous pipeline runner.
- `server.py` - FastAPI server, SSE capture stream, settings, search, stats, inbox, and vault endpoints.
- `interceptor.py` - converts clipboard, text, URL, and audio input into a normalized payload.
- `pre_resolver.py` - detects content shape before LLM routing.
- `enrichment_router.py` - dispatches URL, GitHub, YouTube, image, audio, and text enrichment.
- `llm_engine.py` - calls Ollama through structured output parsing with retry.
- `storage_engine.py` - deduplicates, merges, writes notes, or routes to scratchpad.
- `vector_store.py` - SQLite-backed embedding search.
- `index_writer.py` - SQLite FTS5 index over vault Markdown files.
- `link_resolver.py` - builds wikilink and alias relationships from vault frontmatter.
- `summarizer.py` - map-reduce summarization for long documents and transcripts.

Key frontend modules:

- `src-tauri/` - Rust shell, process spawning, global hotkey, tray, and window configuration.
- `App.tsx` - pill behavior, dragging, snapping, clamping, and menu control.
- `MenuWindow.tsx` - radial/capsule menu overlay.
- `hooks/useCapture.ts` - capture lifecycle state machine and SSE polling guards.
- `lib/*.ts` - pure geometry, monitor, API, config, and layout helpers with sibling tests.

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

The Tauri app provides an always-on-top pill and separate menu overlay. The split-window design avoids cross-monitor DPI jumps and keeps geometry stable.

Desktop features include:

- Global hotkey capture, default `Ctrl+Shift+Space`.
- Drag, snap-to-edge, and clamp-to-screen behavior.
- Radial/capsule menu for capture actions.
- Inbox for reviewing recent captures.
- Vault browser for navigating generated notes.
- Search panel backed by FTS5 and vector search.
- Stats panel for capture history.
- Settings for vault path, models, and capture behavior.
- System tray controls.

All Tauri window positioning uses logical coordinates through the monitor geometry helpers.

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

Each capture follows the same four-stage sequence in both CLI and GUI paths.

### 1. Intercept

`interceptor.py` reads clipboard content or injected input and converts it into an `InputPayload`.

### 2. Pre-resolve

`pre_resolver.py` detects the content shape, such as plain text, URL, GitHub link, YouTube link, image, or audio. This produces a category hint before the LLM runs.

### 3. Enrich

`enrichment_router.py` dispatches content-specific enrichment:

- Web pages are fetched and converted into readable content.
- GitHub links are treated as technical sources.
- YouTube captures fetch transcripts when available.
- Audio is transcribed locally through Whisper.
- Images can use OCR and vision models.
- Long-form content is summarized with map-reduce chunking.

Most enrichment paths fail softly and preserve the original capture. Vision capture is stricter: when image understanding is required and the vision model is unavailable, the pipeline marks the capture accordingly and routes it away from confident LLM processing.

### 4. Structure and Store

`llm_engine.py` asks Ollama to produce a structured `CaptureOutput`. If structured parsing fails, the engine performs a two-pass retry. `storage_engine.py` then decides whether to write a new note, merge into an existing note, or place the capture in scratchpad.

## Vault Model

The vault is a normal folder of Markdown files with frontmatter. It is compatible with Obsidian-style workflows and remains portable across machines.

Important rules:

- The vault is the source of truth.
- Folder names define available categories at runtime.
- Categories are never hardcoded.
- Frontmatter aliases power wikilink resolution.
- Full-text and vector indexes are derived from files.
- Deleting derived indexes should not delete user data.

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

## Configuration Notes

Keep these constraints in mind:

- `ollama.base_url` must be a bare host such as `http://localhost:11434`.
- Do not configure Ollama with a `/v1` suffix.
- Vault categories are derived from live folder names.
- Files are authoritative; databases are derived.
- Vision failures should not silently become confident text captures.
- Tauri geometry should use `LogicalPosition` and `LogicalSize`.
- The CLI and FastAPI pipeline paths intentionally duplicate the same four-stage flow.

## Daily Workflows

Use Second Thought for:

- Quick clipboard capture.
- Research articles and documentation.
- GitHub links, error messages, and code snippets.
- YouTube transcripts and summaries.
- Voice memos and meeting takeaways.
- Image and screenshot capture.
- Searchable technical notes.

The result is a growing Markdown knowledge base that can be browsed, searched, linked, synced, backed up, or edited with normal tools.


**Stop deciding where things go.**

Copy data. Click capture. Let the pipeline file it. 

