# Second Thought Browser Extension

A Manifest V3 Chrome extension that sends the current tab's URL and any selected text directly to your local Second Thought `/share` endpoint — no clipboard involved.

## Install (developer mode)

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `browser_extension/` folder
4. The Second Thought icon appears in the toolbar

## First-time setup

1. Click the extension icon → **Settings**
2. Set **Server URL** to `http://localhost:7070` (or your custom port)
3. Set **X-Omni-Secret** if you configured `OMNI_GUI_SECRET` on the server
4. Click **Save** — the dot turns green when the server is reachable

## Usage

### Popup
- Click the toolbar icon to open the popup
- The current page URL is pre-filled; any highlighted text is pre-loaded into the selection box
- Click **Capture** — pipeline steps animate as the note is written

### Right-click menu
- Select text on any page → right-click → **Send selection to Second Thought**
- On any page or link → right-click → **Send page to Second Thought**
- A ✓ or ✗ badge briefly appears on the extension icon

## How it works

```
Browser Extension
  → POST /share  {url, title, selection}
      → server.py
          → Enrichment Router (URL path if no selection, text path if selection present)
              → LLM Engine → Storage Engine → vault write
```

No clipboard is read or written at any point.
