# Omni Capture

Local-first clipboard/URL/audio capture pipeline that enriches input via Ollama and files it into an Obsidian-style markdown vault. Frontended by a Tauri pill-and-radial-menu GUI.

**Architecture:** Python backend (FastAPI + Ollama enrichment) + TypeScript/React frontend (Tauri window + TailwindCSS) + Manifest V3 browser extension.

## Quick start

**Requirements:** Python 3.10+, Node 18+, Rust (for GUI build), Ollama running locally.

```bash
# Backend
cd omni_capture
pip install -r requirements.txt
python main.py --self-check                    # verify Ollama/vault/whisper/index

# GUI (Tauri + Vite)
cd gui
npm install
npm run dev                                    # Tauri dev: Vite + Rust + Python together

# Or via whole-app launcher (Windows)
.\launch.ps1                                   # builds if stale, runs release binary
```

## Commands

From `omni_capture/`:
```bash
python main.py                                 # capture from clipboard
python main.py --text "..."                    # inject text, skip clipboard
python main.py --url "https://..."             # inject a URL directly
python main.py --audio path.mp3                # transcribe via Whisper
python main.py --dry-run                       # print LLM output, no vault write
python main.py --verbose                       # print every pipeline stage
python main.py --log [--stats]                 # tail/summarize capture audit log
pytest                                         # run test suite
```

GUI dev (`gui/`):
```bash
npm run dev                                    # Tauri dev
npm run dev:vite                               # Vite only (no shell)
npm run build                                  # typecheck + build
npm test                                       # vitest
```

## Browser extension

Manifest V3 Chrome extension that sends tab URL + selection directly to `/share` endpoint (no clipboard).

**Install:** Open `chrome://extensions` → **Developer mode** → **Load unpacked** → `browser_extension/` folder

**Setup:** Extension icon → **Settings** → Set **Server URL** to `http://localhost:7070`

## Architecture

- **`omni_capture/`** — Python pipeline: clipboard/URL/audio input → enrichment router → LLM (Ollama) → vault storage
- **`gui/`** — React/Tauri: pill window (always-on-top trigger) + radial/capsule menu overlay
- **`browser_extension/`** — Manifest V3 vanilla JS, mirrors GUI API protocol via SSE
- **Vault** — Obsidian-style markdown files (source of truth, not a database)

## Key constraints

- `ollama.base_url` must be bare (`http://localhost:11434`), never `/v1`-suffixed
- Vault categories derive live from folder names, never hardcoded
- Vision failure is fail-fast; other enrichment paths fail gracefully
- Files are source of truth, DBs are derived indexes only
- Tauri geometry uses only `LogicalPosition`/`LogicalSize` (DPI-safe)

See `CLAUDE.md` for full developer guidance.
