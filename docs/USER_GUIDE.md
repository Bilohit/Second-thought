# Second Thought — User Guide

The definitive reference manual for Second Thought: the local-first capture tool that turns anything you copy, type, or speak into a clean, organized note in your own markdown vault — with nothing ever leaving your machine.

## Why "Second Thought"?

The name is the whole philosophy. A thought, a document, a link, an idea — most tools make you stop and decide *where it goes, what to call it, how to file it* the moment it arrives. Second Thought removes that. You leave it, and it becomes a literal **second thought**: something you don't have to think about now, captured and filed for you, waiting whenever you come back for it. Drop it and move on. The "second thought" — the decision, the organizing, the recall — happens later, automatically, and without your attention.

---

## Table of Contents

1. [What is Second Thought?](#1-what-is-second-thought)
2. [Core Concepts & Vocabulary](#2-core-concepts--vocabulary)
3. [Installation & First Run](#3-installation--first-run)
4. [Understanding the Interface: Where Is Everything?](#4-understanding-the-interface-where-is-everything)
   - 4.1 [The Pill](#41-the-pill)
   - 4.2 [The Radial Menu](#42-the-radial-menu)
   - 4.3 [The Panels](#43-the-panels)
   - 4.4 [The System Tray](#44-the-system-tray)
   - 4.5 [Spatial Map](#45-spatial-map)
5. [Core Workflows (Step by Step)](#5-core-workflows-step-by-step)
   - 5.1 [Capture from clipboard](#51-capture-from-clipboard)
   - 5.2 [Capture a web link](#52-capture-a-web-link)
   - 5.3 [Capture a YouTube video](#53-capture-a-youtube-video)
   - 5.4 [Capture an image](#54-capture-an-image)
   - 5.5 [Capture audio / a voice memo](#55-capture-audio--a-voice-memo)
   - 5.6 [Search your vault](#56-search-your-vault)
   - 5.7 [Review & triage with the Inbox](#57-review--triage-with-the-inbox)
6. [How a Capture Is Processed (The Pipeline)](#6-how-a-capture-is-processed-the-pipeline)
7. [Categorization, Dedup & the Scratchpad](#7-categorization-dedup--the-scratchpad)
8. [Settings Reference](#8-settings-reference)
9. [Command-Line Mode](#9-command-line-mode)
10. [The Browser Extension](#10-the-browser-extension)
11. [Edge Cases & What Happens When Things Fail](#11-edge-cases--what-happens-when-things-fail)
12. [Troubleshooting](#12-troubleshooting)
13. [Keyboard Shortcuts & Gestures](#13-keyboard-shortcuts--gestures)
14. [Privacy & Data Ownership](#14-privacy--data-ownership)
15. [FAQ](#15-faq)

---

## 1. What is Second Thought?

Second Thought removes a single decision from your workflow: **"where does this go?"**

You copy a link, a quote, a screenshot, or record a voice memo. You trigger one capture. A local AI model (Ollama, running on *your* machine) reads the content, enriches it — fetching article text, summarizing a video, transcribing audio, reading an image — then tags it, picks the right folder, and writes a clean markdown note into your vault.

There is no cloud, no account, no manual filing, and no fixed taxonomy you have to learn. The categories come from the folders *you already have*.

| Property | Value |
|----------|-------|
| Runs | 100% locally on your machine |
| Storage | Plain `.md` files (Obsidian-compatible) |
| AI | Local Ollama instance (`http://localhost:11434`) |
| Network | Only local Ollama + optional outbound fetch for links *you* capture |
| Source of truth | Your vault folder — always. Databases are rebuildable caches. |

---

## 2. Core Concepts & Vocabulary

| Term | Meaning |
|------|---------|
| **Vault** | Your markdown notes directory. The single source of truth — not a database. |
| **Scratchpad** | The vault's catch-all/unsorted folder. Low-confidence captures land here instead of being mis-filed. |
| **Pill** | The small, always-on-top window that triggers a capture. |
| **Radial menu** | The fan of quick actions that opens from the pill. |
| **Capture** | One run of the pipeline over one piece of content. |
| **Enrichment** | The stage that fetches/transcribes/reads the raw content before the AI structures it. |
| **Two-pass retry** | If the AI's first structured response fails to parse, it re-prompts once, more strictly. |
| **Derived index** | `captures.db`, `vectors.db`, `dedup_index.json` — caches over the vault that can be deleted and rebuilt with zero data loss. |

---

## 3. Installation & First Run

> **Prerequisites:** [Ollama](https://ollama.com) installed and running, and Python 3 available.

**Step by step:**

1. **Install Python dependencies.**
   ```bash
   pip install -r omni_capture/requirements.txt
   ```
2. **Make sure Ollama is running** and has a model pulled (and, for image capture, a vision-capable model).
3. **Launch the app.**
   - Windows (recommended): `.\launch.ps1`
   - Development mode: `npm run dev` (from `gui/`)
4. **Set your vault location** on first run — point it at a new folder or an existing Obsidian vault. This folder becomes your source of truth.
5. **Make your first capture.** Copy some text or a link, then click the pill.
6. **Verify it worked.** Open your vault folder; a new note should appear in the right category folder (or the scratchpad if the AI wasn't sure).
7. **Run a self-check** any time something feels off:
   ```bash
   python main.py --self-check
   ```
   This verifies Ollama, the vault, transcription (Whisper), and the search index.

---

## 4. Understanding the Interface: Where Is Everything?

Second Thought is deliberately tiny on screen. There are only **two windows**: the static *pill* and a separate *menu overlay*. Everything else opens as a panel on demand.

### 4.1 The Pill

- A small, rounded, **always-on-top** window.
- **Location:** wherever you last left it. It snaps to screen edges and remembers its position across launches.
- **Drag** it anywhere; it clamps so it can never end up off-screen, even across monitors with different DPI.
- **Click** it to capture from the current clipboard.

### 4.2 The Radial Menu

- **Opens from the pill** (click-and-hold or the configured gesture) as a fan of icons around it.
- It's a **separate overlay window** — this is intentional, so opening it never causes a cross-monitor DPI jump.
- Actions fan out toward the screen interior (it re-orients itself near edges so options never spill off-screen).
- **Click outside** the menu to close it.

| Radial action | Opens |
|---------------|-------|
| Search | The Search panel |
| Inbox | Recent captures for review/triage |
| Vault | The Vault Manager |
| Stats | Capture statistics |
| Settings | Configuration panel |

### 4.3 The Panels

Each panel opens from the radial menu:

- **Settings** — vault path, Ollama connection, capture behavior.
- **Vault Manager** — browse your folders/notes.
- **Inbox** — review recent captures (especially scratchpad items needing a home).
- **Search** — keyword *and* semantic (meaning-based) search.
- **Stats** — counts, categories, activity over time.
- **Capture Overlay** — the live progress surface that appears during a capture, streaming each pipeline stage.

### 4.4 The System Tray

- The app lives in the **system tray** so you can quit, show/hide the pill, and access the global hotkey behavior even when the pill is tucked away.

### 4.5 Spatial Map

```
┌────────────────────────────── your screen ──────────────────────────────┐
│                                                                          │
│                                                       ╭─────────╮        │
│                                                       │  PILL   │ ← always│
│                                                       ╰────┬────╯   on top│
│                                              radial menu fans inward      │
│                                          ◜ Search  Inbox  Vault ◝         │
│                                            Stats        Settings          │
│                                                                          │
│   (panels open centered/overlay when an action is chosen)                │
│                                                                          │
│  ▣ system tray  ───────────────────────────────────────────────────────│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Core Workflows (Step by Step)

### 5.1 Capture from clipboard

1. Copy text, a link, or an image to your clipboard.
2. Click the pill (or press the global hotkey).
3. The capture overlay streams progress through each stage.
4. A confirmation flashes; the note is now in your vault.

### 5.2 Capture a web link

1. Copy a URL.
2. Trigger a capture.
3. Second Thought fetches the page, extracts the **readable article text** (stripping nav/ads), summarizes it, and files a useful reference note — not a bare link.

> **Note:** GitHub links are detected and handled with repo-aware enrichment.

### 5.3 Capture a YouTube video

1. Copy a YouTube URL and trigger a capture.
2. The transcript is fetched and **written to the vault immediately** (so it's never lost).
3. Summarization runs **in the background** (chunked Map-Reduce, so even long videos work). The pill is free to use again right away.
4. The note is updated with the summary when it completes.

### 5.4 Capture an image

1. Copy an image (or capture a screenshot to clipboard) and trigger a capture.
2. A local **vision model** describes the image; optional OCR extracts any text.
3. **Edge case:** if image analysis is *required* and fails, the capture is routed straight to the scratchpad rather than letting the AI guess from nothing. (See §11.)

### 5.5 Capture audio / a voice memo

1. From the command line:
   ```bash
   python main.py --audio path/to/memo.mp3
   ```
2. Local **Whisper** transcribes it — fully offline.
3. The transcript is filed as a note.

### 5.6 Search your vault

1. Open the **Search** panel from the radial menu.
2. Type a query.
   - **Keyword** search hits exact text (FTS5 index).
   - **Semantic** search finds notes by *meaning* (embeddings), even with different wording.
3. Click a result to open the note.

### 5.7 Review & triage with the Inbox

1. Open **Inbox** from the radial menu.
2. Scan recent captures, paying attention to anything in the **scratchpad**.
3. Move scratchpad notes into a real category folder when you're ready — Second Thought never forces that decision on you.

---

## 6. How a Capture Is Processed (The Pipeline)

Every capture runs the same **4-stage sequence**:

| # | Stage | What it does |
|---|-------|--------------|
| 1 | **Intercept** | Normalizes clipboard/CLI input into a single payload. |
| 2 | **Pre-resolve** | Heuristically detects content shape (text / URL / GitHub / YouTube / image) and a category hint. |
| 3 | **Enrich** | Runs the content-specific handler: web fetch, transcript fetch, Whisper, or vision. |
| 4 | **Structure + Store** | The AI produces a structured note (with a two-pass retry on parse failure); it's deduped, merged or written, and indexed. |

The GUI streams these stages live so you always see *what's happening*, not an opaque spinner.

---

## 7. Categorization, Dedup & the Scratchpad

- **Categories are never hardcoded.** The list of possible categories is rebuilt from your vault's current folder names on *every* capture. Rename or add a folder and categorization adapts immediately.
- **Dedup & merge.** If a new capture overlaps an existing note, Second Thought merges into that note instead of creating a duplicate — based on what's actually in your files, never a hidden database.
- **Scratchpad fallback.** When the AI isn't confident (or a required enrichment step fails), the capture goes to the scratchpad. Nothing is lost, and nothing is confidently mis-filed.

---

## 8. Settings Reference

Settings can be edited in the GUI **Settings** panel or directly in `omni_capture/config.toml`.

| Setting | What it controls |
|---------|------------------|
| **Vault root** | The directory that holds your `.md` notes. |
| **Ollama base URL** | Must stay **bare** (`http://localhost:11434`) — never add `/v1`. |
| **`image_required`** | If `true`, image captures must succeed at vision or they route to the scratchpad (fail-fast). |
| **Pipeline tuning** | Confidence thresholds, summarization budgets, etc. |

> ⚠️ **Do not write `/v1` into the Ollama URL.** The app appends it internally only where needed; a `/v1` in config breaks image captures with 404s.

---

## 9. Command-Line Mode

Everything the GUI does is scriptable:

```bash
python main.py                       # capture from clipboard
python main.py --text "..."          # inject text, skip clipboard
python main.py --url "https://..."   # inject a URL directly
python main.py --audio path.mp3      # transcribe via local Whisper
python main.py --dry-run             # print LLM output, no vault write
python main.py --verbose             # print every pipeline stage's output
python main.py --self-check          # verify Ollama/vault/whisper/index
python main.py --log [--stats]       # tail / summarize capture audit log
```

---

## 10. The Browser Extension

A Manifest V3 extension (vanilla JS, no build step) sends captures to the same local server as the GUI and parses the same live progress stream. Use it to capture the current page or selection straight from your browser.

---

## 11. Edge Cases & What Happens When Things Fail

Second Thought's failure philosophy: **vision is fail-fast; everything else is fail-soft.**

| Situation | Behavior |
|-----------|----------|
| Web fetch fails | Fail-soft: a placeholder is filed, you keep the note. |
| YouTube transcript missing | Fail-soft: placeholder; capture isn't lost. |
| YouTube summarization fails | The raw transcript is already saved (write-before-summarize). |
| Audio transcription fails | Fail-soft: placeholder. |
| **Vision fails** & `image_required = true` | **Fail-fast:** routed to scratchpad, never handed to the AI with false confidence. |
| AI structured output won't parse | **Two-pass retry** with stricter prompting; if it still fails, scratchpad. |
| AI low confidence on category | Routed to the scratchpad. |
| Duplicate content | Merged into the existing note. |
| Pill dragged off-screen / monitor unplugged | Clamped back into visible bounds on next move. |
| You delete a derived DB | Rebuilt from the vault — no data loss. |

---

## 12. Troubleshooting

| Symptom | Try this |
|---------|----------|
| Nothing happens on capture | Run `python main.py --self-check`; confirm Ollama is running. |
| Image captures 404 | Check that the Ollama URL is **bare** (no `/v1`). |
| Notes always land in scratchpad | Confidence may be low — check your category folders exist and are clearly named. |
| Search misses recent notes | The index may be stale; it's rebuildable from the vault. |
| Pill is missing | Show it from the system tray. |
| Want to see what the AI produced without writing | `python main.py --dry-run`. |
| Want full stage-by-stage output | `python main.py --verbose`. |
| Check recent activity | `python main.py --log --stats`. |

---

## 13. Keyboard Shortcuts & Gestures

| Action | How |
|--------|-----|
| Trigger capture | Click the pill, or the global hotkey |
| Open radial menu | Click-and-hold / configured gesture on the pill |
| Close radial menu | Click outside it |
| Move the pill | Drag it (snaps to edges) |
| Quit / show / hide | System tray |

---

## 14. Privacy & Data Ownership

- **No cloud, no accounts, no telemetry.**
- The only network traffic is to your local Ollama, plus outbound fetches for links *you explicitly capture*.
- Your vault is a **portable folder of plain markdown.** Move it anywhere; update `config.toml`; that's the entire migration path.
- Every database is a rebuildable cache. Your `.md` files are always authoritative.

---

## 15. FAQ

**Does anything leave my computer?**
Only outbound fetches for web/YouTube links you capture. The AI runs locally via Ollama.

**Can I use my existing Obsidian vault?**
Yes — point the vault root at it.

**What if I don't like where a note went?**
Move it. Categorization is a convenience, not a lock-in; the scratchpad exists exactly so nothing is forced.

**Do I have to define categories?**
No. They're inferred from your folders, live, on every capture.

**What happens to a long YouTube video?**
Transcript saved immediately, then summarized in the background in chunks. The pill stays usable.

**Is my data safe if a database gets corrupted?**
Yes. Delete it; it rebuilds from your markdown files.
</content>
</invoke>
