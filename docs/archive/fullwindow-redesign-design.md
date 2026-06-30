# Full-Window Redesign — Design Spec

**Date:** 2026-06-30
**Status:** Design approved, pending implementation plan
**Mock:** `scratchpad/b-rail-mock.html` (interactive, all 9 themes + corner toggle + status states)

---

## 1. Goal

Replace the current "full" display mode with a new full-window layout that (a) is **visually consistent** with the two existing pill modes (capsule + minimal), (b) **unifies code** by reusing their already-extracted shared logic, and (c) introduces a **genuinely new layout** — a command-center grid realized as a locked icon rail.

This is **not** a crash fix and **not** a reskin of the existing panel stack. It is a new top-level window whose shell owns its own chrome.

### Non-goals
- No change to the capsule or minimal pill modes themselves.
- No new Tauri windows. All context switching happens via internal views in one frame.
- No migration of any authority into a DB (files stay source of truth per CLAUDE.md).

---

## 2. Hard-rule reconciliation

| Rule | How this design complies |
|------|--------------------------|
| Sharp 0px radius lock (pill is sole rounding exception) | Rounding is a **top-level shell property only** (`--r`/`--r-sm` on `.win`), toggled sharp↔rounded. No inner panel re-introduces a competing radius system; inner cards inherit `--r-sm` which is `0px` in sharp mode. The window shell is declared a brand-new surface that owns corners, with no inner panel breaking the lock. |
| `LogicalPosition`/`LogicalSize` only, monitor reads via `monitor.ts` | Window sizing/positioning unchanged from existing full-mode plumbing; this redesign is layout-internal and adds no new geometry math. |
| Non-trivial logic ships one runnable check | New pure modules (rail selection model, status mapping reuse) get sibling `*.test.ts`. |

---

## 3. Layout — command-center grid (Option B "rail")

```
┌────┬───────────────────────────────────────────┐
│ ●  │  topbar: title · subtitle      [toggle]    │  ← status light (ONE), drag region
│    ├───────────────────────────────────────────┤
│ ⊞  │                                            │
│ ⌕  │   active view (Dashboard / Look / Library) │
│ ▥  │                                            │
│    │                                            │
│ ⚙  │                                            │
│ ⊝  │                                            │
└────┴───────────────────────────────────────────┘
```

### 3.1 Rail (locked, icon-only, permanent)
- Width fixed at 56px. **No hover/click expansion** — icons only, always.
- Header: a single drag region holding **one** status light (`.statuslight`). The previous two-light redundancy is removed; the second indicator became a text-only Health row in the Dashboard.
- Middle (`.navmain`): **3 equal symmetrical primary buttons** (`flex:1` each), filling all space between header and footer:
  - `⊞` **Dashboard** (Console)
  - `⌕` **Look** (Search + Chat)
  - `▥` **Library** (Vault + Stats, combined)
- Footer (`.navfoot`): `⚙` **Settings**, `⊝` **Hide to tray** — fixed positions, not part of the sliding selection.
- **Sliding selection** (`.navslider`): an absolutely-positioned block that animates `translateY` + `height` between the 3 primary buttons on `.34s var(--menu-ease)`, with a 2px accent bar (`::before`) on its inner edge. Selection has pronounced "slide" per request. Footer buttons get their own `.on` background treatment, not the slider.

### 3.2 Status light (single source)
Reuses the existing extracted status logic — `statusModel.ts:statusVisual()`, `llmStatusLabel.ts`, `StatusIndicator.tsx`. States:
- **amber** — LLM disconnected: `--yellow`, `warn` fade pulse.
- **work** — warming/working: `--accent`, ring pulse.
- **ok** — ready: `--green`, static.

---

## 4. Views (internal, no new windows)

### 4.1 Dashboard Console — capture + recent + health + inbox merged
Two-column grid. Standalone Inbox rail tab is **removed**; its triage lives here.

- **Left column:**
  - **Capture** card — drop target, 4-step pipeline bar (intercept → enrich → reason → file) with the active step animated, plus the last result (title, routed category, confidence, resolved wikilinks, tags).
  - **Recent activity** card (fills remaining height) — clickable rows (`.rrow`: filename + category chip + relative time). **Click → open that file directly**, same mechanics as the pill-mode History window.
- **Right column:**
  - **Health** strip — text-only rows (LLM / Vault / Index / Queue) with a tiny status dot each. This replaces the old redundant second status light.
  - **Inbox** triage card — low-confidence/uncategorized captures with File / Recat / Dismiss actions.

### 4.2 Look — search + chat over the vault
- **No global shortcuts.** Invoked only from the rail.
- A **symmetrical Search↔Chat toggle** (`.toggle`, built by a reusable `makeToggle()` factory) injected into the topbar's right slot. This same toggle pattern is intended to be reusable across pill window states.
- **Search** sub-view: query bar + result rows (file, snippet, category).
- **Chat** sub-view: bubble thread with `[[wikilink]]` source citations + an ask input pinned to the bottom.

### 4.3 Library — Vault + Stats combined (name approved)
Vertical layout: a two-column grid over a full-width footer.

- **Vault pane** (left, mirrors `VaultManager.tsx` `CategoryCard`): scrollable folder rows (`.vrow`) — accent folder SVG icon, name, "N notes" count, accent-tinted description, **hover-revealed** Edit (✎) / Rename (⇄) / Delete (🗑) actions. Header actions: **New folder**, Open vault in OS (↗), Refresh (↻). The `_scratchpad` system folder renders dimmed (`.vrow.sys`). Visual stays close to current pill-mode Vault.
- **By category** pane (right, mirrors `StatsPanel.tsx`): horizontal bars per category (name · proportional bar · count), bars animate in (`barIn` scaleX).
- **Daily rhythm** footer (full width): a small 30-day sparkline. **Interactive** — hovering a day's bar reveals a tooltip with that day's capture count + "Nd ago / today" and dims the footer total; leaving resets to the weekly/total summary. Clean fade + slight bar scale on hover.

> **Placement rule (per user):** Vault pane, By-category graph, and daily-activity sparkline are **Library-only**. Recent activity is **Dashboard-only**. They do not appear together on other tabs.

### 4.4 Settings
Standard preference rows: Appearance (Theme, Corners, Display mode) + Pipeline (Vault root, Ollama, Monitor).

---

## 5. Visual language (reused verbatim)
- **9 themes** via `[data-theme]` CSS custom properties (Void/Paper/Sage/Sky/Bubba Pink/Mist/Lilac/Sand/Wine) — token sets copied from `index.css`.
- **Geist Mono** throughout.
- **Corner toggle:** `[data-corner="rounded"]` sets `--r:12px; --r-sm:8px;`; sharp default keeps `0px`. Shell + cards transition radius on `.25s var(--menu-ease)`.
- **Motion:** `--menu-ease: cubic-bezier(.22,1,.36,1)` shared with the pill menus. Rail slider slide, pipeline fill, category bar grow-in, sparkline hover.

---

## 6. Code unification points
- **Status:** consume `statusModel.ts` / `llmStatusLabel.ts` / `StatusIndicator.tsx` for the single rail light — no new status logic.
- **Vault rows:** reuse `VaultManager.tsx` `CategoryCard` (folder icon, name, count, description, action buttons, inline delete confirm).
- **Stats:** reuse `StatsPanel.tsx` By-category bars + `DaySparkline`.
- **Recent / file-open:** reuse the pill History window's open-file-on-click mechanics.
- **Toggle:** one reusable symmetrical toggle factory shared with pill states.

---

## 7. Open items deferred to implementation plan
1. **Folder drill-in** (click a vault folder → file list within Library) — not in mock; decide v1 inclusion during planning.
2. Concrete wiring of `DisplayMode = "full"` to render this layout vs. the current full panel stack, and how the rail's Hide returns to tray.
3. Test coverage: sibling `*.test.ts` for the rail-selection model and any new pure layout/geometry helper.

---

## 8. Acceptance (mock-level, met)
- [x] Single status light, three states.
- [x] Locked icon rail, 3 equal primary buttons + Settings/Hide, sliding selection with slide.
- [x] Corner toggle works on the shell, sharp default, no inner radius-lock conflict.
- [x] Dashboard merges capture + recent + health + inbox; Inbox tab removed.
- [x] Look = no shortcuts, symmetrical Search/Chat toggle.
- [x] Library = Vault pane + By-category bars + interactive daily sparkline; Recent activity moved to Dashboard.
- [x] All 9 themes + Geist Mono.
