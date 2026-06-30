# Full-Window Polish — Plan

Date: 2026-06-30
Branch target: master (GUI only)
Verify gate: `npm run build` (tsc + vite, must pass) + `npm test` (vitest) from `gui/`.

Library layout decision (locked): **keep current proportions, unify chrome** —
Vault wide-left, By-category right, Daily-rhythm bottom; Vault just gets the same
card styling as its sibling panes. No layout restructure.

---

## Tasks

### 1. Settings tab — double title
- **File:** `gui/src/components/SettingsPanel.tsx` (~line 501)
- Header renders `Settings` title; FullWindow topbar already shows it → doubled.
- **Fix:** wrap the title `<span>Settings</span>` in `{!embedded && (...)}`.
- Keep the close button decision to task 6 (Settings close: leave as-is — task 6
  only names Vault + Look).

### 2. Sharp/Rounded corners do nothing in full mode
- **Cause:** `--radius*` tokens are hardcoded `0px` at `:root` (`index.css:49-52`).
  `pillCorner` is only wired to pill spokes/capsule (`data-corner` CSS), never to
  the full window. Full window cards reference `var(--radius-sm)` = always 0.
- **Fix:**
  - `gui/src/index.css` — add rule:
    `[data-corner="rounded"]{ --radius-sm:8px; --radius:8px; --radius-lg:12px; --radius-xl:12px; }`
    (place as standalone selector after the `:root` block, not inside it).
  - `gui/src/components/FullWindow/FullWindow.tsx` — accept a `pillCorner` prop and
    set `data-corner={pillCorner}` on the root shell div, so the token override
    cascades to every card/control inside.
  - `gui/src/App.tsx` (~line 1561) — pass `pillCorner={pillCorner}` into `<FullWindow>`.
- **Scope note:** scoping `data-corner` to FullWindow root (not `documentElement`)
  keeps pill-mode surfaces unaffected.
- **Check:** existing `menuGeometry`/render tests still green; manual toggle.

### 3. Window movable from topbar only
- **Cause:** both rail head (`FullWindow.tsx:86`, `data-tauri-drag-region`) and the
  embedded panel headers (`className="drag-region"` on Look/Vault/Settings) are
  draggable, in addition to the topbar.
- **Fix:**
  - Remove `data-tauri-drag-region` from the rail head div (`FullWindow.tsx:86`).
  - Embedded panel headers: make the drag class conditional — when `embedded`, drop
    `drag-region` (use `""` / `no-drag`). Files: `LookPanel.tsx:230`,
    `VaultManager.tsx:559`, `SettingsPanel.tsx:500`.
  - Topbar (`FullWindow.tsx:114`) keeps `data-tauri-drag-region` — sole drag handle.

### 4. Rail slide-selection animation (match mock)
- **Ref:** `b-rail-mock.html` `.navslider` + `.navslider::before` (left accent bar).
- **Current:** `FullWindow.tsx:90-97` already renders a sliding surface block via
  `railSliderRect` with transform/height transitions — but no accent bar, and verify
  it actually animates between the 3 main views.
- **Fix:** inside the slider div add a nested accent bar (mock `::before`: left edge,
  ~2px wide, `var(--accent)`, inset top/bottom). Confirm transition curve matches
  mock (`transform .34s var(--menu-ease)`). Geometry already covered by
  `railSelection.ts` (pure, has logic) — no math change.

### 5. Vault = its own pane (unify chrome, keep proportions)
- **File:** `gui/src/components/VaultManager.tsx` embedded branch (~line 548-553).
- **Current embedded style:** `background transparent, border none` → looks unlike the
  By-category / Daily-rhythm cards.
- **Fix:** in embedded mode use card chrome to match siblings:
  `background:var(--surface), border:1px solid var(--border), borderRadius:var(--radius-sm)`.
  Keep `position:relative, width/height:100%`.
- `LibraryView.tsx` grid stays `1fr 280px` + footer — proportions unchanged.

### 6. Vault + Look — no icon indicator, no close button (embedded)
- **Vault icon:** already hidden when embedded (done previous round).
- **Close buttons (embedded only):**
  - `VaultManager.tsx:632-642` — wrap close button in `{!embedded && (...)}`.
  - `LookPanel.tsx:299-304` — wrap close button in `{!embedded && (...)}`.
- Look title/icon already hidden when embedded (done previous round).

### 7. Full vault path visible at top of Vault pane, no `...`
- **File:** `VaultManager.tsx:580` (vaultRoot span).
- **Current:** path hidden when embedded; non-embedded uses `maxWidth:160 + ellipsis`.
- **Fix:** in embedded + top-level (`!drillCat`), render `vaultRoot` full width — drop
  `maxWidth`, drop `textOverflow:"ellipsis"`/`whiteSpace:"nowrap"` (allow wrap or full
  line). It becomes the pane's top label (title word "Vault" stays hidden per task 1-prev).

### 8. Settings tab can't scroll (Form + Function)
- **Cause:** SettingsPanel root is `overflow:hidden`; embedded body
  (`SettingsPanel.tsx:520-522`) has no scroll container, content clips.
- **Fix:** make the body div `flex:1, minHeight:0, overflowY:"auto"` so Form/Function
  content scrolls within the pane. (Header + Tabs stay fixed above.)

### 9. Library rail icon = folder/vault icon
- **File:** `FullWindow.tsx:100` — library glyph currently `▥`.
- **Fix:** render `<MenuIcon target="vault" size={18} />` for the library nav button
  (the folder icon used by Vault). MenuIcon already imported (task 2/prev). Keep
  dashboard + look glyphs as-is, OR swap all three to MenuIcon for consistency
  (decide during impl — minimal = just library).

### 10. Recent activity — show "click to open"
- **File:** `DashboardView.tsx:74` (renderRecentCard).
- **Status:** chip `click to open` already present in code. Verify it renders; if a
  prior edit dropped it, restore the chip in the card label row. Likely no-op —
  confirm visually.

### 11. Capture pane — no idle stage labels
- **File:** `DashboardView.tsx` renderCaptureCard (~line 48) + `StepIndicator`.
- **Current:** StepIndicator shows the 4 stage labels (intercept/enrich/reason/file,
  or youtube/image equivalents) even at idle.
- **Desired:**
  - **Idle:** show only the "Drop a file, paste, or auto-capture clipboard / URL /
    audio" box, enlarged to fill the capture pane sensibly. No stage labels.
  - **Processing (phase capturing/active):** show StepIndicator with the live stages.
  - **Done:** show result block (existing).
- **Fix:** gate `<StepIndicator>` render on `captureState.phase !== "idle"` (or on
  having active/non-empty steps); when idle, render the enlarged drop box instead of
  the small one. Confirm phase enum values in `hooks/useCapture` before wiring.
- **Check:** capture-flow logic is a branch → keep/extend a render assertion or the
  existing capture test green.

---

## Suggested execution order (token-optimal, parallel-safe)

Independent file groups → can fan out to subagents:
- **A:** `LookPanel.tsx` (tasks 3, 6) + `VaultManager.tsx` (tasks 3, 5, 6, 7)
- **B:** `SettingsPanel.tsx` (tasks 1, 3, 8)
- **C:** `FullWindow.tsx` (tasks 2, 3, 4, 9) + `index.css` (task 2) + `App.tsx` (task 2)
- **D:** `DashboardView.tsx` (tasks 10, 11) + `LibraryView.tsx` (task 5 grid check)

Shared contract: `embedded?: boolean` already exists on Look/Vault/Settings.
After all groups land: run `npm run build` + `npm test`, then `npm run dev` eyeball
against `b-rail-mock.html`.

---

## 12. NEW FEATURE — Drag-and-drop files onto the capture pane

Goal: capture pane becomes a drop target. Drop a file → it runs the normal
capture pipeline (steps animate, routes to vault).

### What already exists (reuse, do not rebuild)
- Backend `/capture` already accepts `content_type` = `text | url | image_b64 |
  audio_b64` (`server.py:268`, `:389-422`). Images → LLaVA, audio → Whisper. **No
  Python change needed for images/audio/text.**
- `useCapture.runCapture()` (`hooks/useCapture.ts:310`) owns the whole run:
  in-flight guard, retry/backoff, SSE stream, dismiss, job poll. It currently
  hard-codes `readClipboard()` as the source.
- Capture base64 size ceiling already enforced server-side (`_MAX_B64_LEN`).

### Approach (primary — frontend-only, no pipeline duplication)
1. **Refactor `useCapture`** so the source is pluggable. Extract the body of
   `runCapture` after the `readClipboard()` line into
   `runCaptureWith({ contentType, content, preview })`. `runCapture` becomes
   `readClipboard()` → `runCaptureWith(...)`. New `captureFile(path)` reads the
   file and calls the same `runCaptureWith`. One run path, one guard — no
   duplicated stream/dismiss logic. Return `captureFile` from the hook.
2. **File → payload mapping (pure module + test):** new
   `gui/src/lib/fileIngest.ts` — `fileKind(filename): "image" | "audio" | "text"
   | null` by extension (png/jpg/jpeg/gif/webp → image; mp3/wav/m4a/ogg/flac →
   audio; md/txt → text; else null = reject). Sibling `fileIngest.test.ts`.
3. **Read bytes:** add `@tauri-apps/plugin-fs` (`readFile` → Uint8Array → base64
   for image/audio; `readTextFile` for text). New dep — see Open item. Add fs
   read permission to `src-tauri/capabilities/default.json` (scope: any path the
   user explicitly drops; `$DOWNLOAD`/`$HOME` or unscoped read — narrow as far as
   the drop flow allows). Rust `tauri-plugin-fs` crate + `.plugin()` registration
   in `lib.rs`.
4. **Drop listener:** in `DashboardView` (or a small `useFileDrop` hook), subscribe
   to `getCurrentWebview().onDragDropEvent`. On `type:"over"` → set dropzone hover
   state; on `"drop"` → take `paths[0]`, `fileKind()`, reject-or-`captureFile()`;
   on `"leave"` → clear hover. `dragDropEnabled` is default-true (not disabled in
   `tauri.conf.json`) — confirm.
5. **Dropzone visual (capture card):** reuse the enlarged idle drop box from task
   11. States: idle ("Drop a file, paste, or auto-capture…"), drag-over (accent
   border/glow), rejected (brief red "Unsupported file type"). Only active in full
   mode + dashboard view.
6. **Gating to the pane (optional polish):** drag-drop fires window-global with a
   physical `position`. MVP = accept anywhere while dashboard visible. Hit-testing
   the event position against the capture card rect (convert physical→logical via
   `lib/monitor.ts` scaleFactor — never raw physical, per CLAUDE.md geometry rule)
   is a follow-up, not v1.

### Approach (alternative — backend `file_path`, flag before choosing)
Add `content_type:"file_path"` to `/capture`; Python reads the file directly
(reuses CLI `--audio`/file logic, dodges base64 size limit + the new JS dep).
**Cost:** must mirror the new branch into BOTH `main.py:run_pipeline()` and
`server.py:_run_pipeline_blocking()` by hand (CLAUDE.md hard rule — they are
deliberately duplicated). Heavier; pick only if the fs dep or size ceiling bites.

### Checks (CLAUDE.md "one runnable check" rule)
- `fileIngest.test.ts` — extension → kind mapping incl. reject + uppercase ext.
- Manual: drop image, audio, .md, and an unsupported file (.zip) → first three
  process, last shows rejection.

### Scope cuts (state in PR, add when asked)
- Multi-file drop (process `paths[0]` only for v1).
- PDF ingest (backend has no pdf content_type yet).
- Per-pane hit-testing (item 6).

---

## Skill Map — which skill, where

Process skills first (HOW), implementation skills second (execution).

| Phase / task | Skill | Why |
|---|---|---|
| Before building feature 12 (UX: file types, gating, visual states) | `superpowers:brainstorming` | Lock requirements before code — it's a new feature, not a tweak. |
| Feature 12 step 2 (`fileIngest.ts` mapping) + task 11 phase gate logic | `superpowers:test-driven-development` | Pure branchy logic → test first, then implement. |
| Task 4 dropzone + feature 12 step 5 (dropzone visual states) | `frontend-design:frontend-design` | Distinct, intentional drag-over / reject states, not templated defaults. |
| Executing the 11 polish tasks across independent file groups (A–D) | `superpowers:subagent-driven-development` + `superpowers:dispatching-parallel-agents` | Groups touch disjoint files → fan out; token-efficient. |
| Optional isolation while implementing | `superpowers:using-git-worktrees` then `superpowers:executing-plans` | Keep the polish branch off the live workspace; execute with review checkpoints. |
| Any cross-DPI / drop-event misbehavior | `superpowers:systematic-debugging` | Geometry + native-event bugs are this repo's recurring class — debug methodically, don't guess. |
| Verbose `npm run build` / `pytest` / `git` output during impl | `rtk` | Compact CLI output, save context. |
| Before claiming any task done | `superpowers:verification-before-completion` | Run build+test+manual, evidence before "done". |
| Before merge | `superpowers:requesting-code-review` (or `/code-review`) | Verify against requirements; `ponytail-review` to catch over-build. |

Caveman mode stays on for prose; code/commits written normal.

---

## Open / assumed (flag if wrong)
- Rounded scale values (8/12px) are a guess matching the mock's `--r:12 / --r-sm:8`.
- Task 9: swap only the library glyph (minimal) vs all three rail glyphs to MenuIcon —
  defaulting to library-only unless told otherwise.
- Settings close button kept (task 6 named only Vault + Look).
- Feature 12: defaulting to the **frontend-fs** approach (adds `@tauri-apps/plugin-fs`
  dep + capability). Switch to backend `file_path` only if you'd rather not add the
  dep / need files past the base64 size ceiling.
- Feature 12 file types v1: images + audio + md/txt. PDF + multi-file deferred.
