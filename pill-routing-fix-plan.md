# Plan — Restore independent Pill-menu routing (de-tangle from Full Window Mode)

**Status:** ready to implement
**Scope:** `gui/src/App.tsx` only (plus re-adding existing imports). No change to `FullWindow/`, no Python, no Rust.
**Goal:** Pill menus (Capsule + Minimal) route each pick to its own dedicated panel. Full Window Mode (`displayMode === "full"`) keeps the `FullWindow` dashboard exactly as-is.

---

## 1. Root cause

Two systems got merged by the `d05289d` refactor.

- `handleMenuSelect` (App.tsx:1486) still does the old thing:
  ```ts
  setMenuOpen(false);
  setExpanded(true);
  setView(target === "search" ? "look" : target);   // sets App's `view`
  ```
  `setExpanded(true)` flips `showPill` (App.tsx:385) to `false`, so the final
  `return` branch renders the expanded view.

- But that final branch (App.tsx:1566) now **always** renders `<FullWindow>`,
  and `FullWindow` keeps its **own** internal `view` state
  (`useState<MainView | "settings">("dashboard")`, FullWindow.tsx:74). It
  **ignores App's `view` prop** and boots at `"dashboard"` every time.

Net: every pill pick (vault / settings / look / inbox / stats) → `expanded` →
`FullWindow` → dashboard. The requested feature is discarded.

Pre-refactor (`git 9cc9338`, App.tsx ~1463–1560) the same branch rendered a
stack of dedicated panels keyed off App's `view`
(`<SettingsPanel visible={view==="settings"}/>`, `<VaultManager…>`, …). The
refactor replaced that whole stack with `FullWindow` but **left
`handleMenuSelect` and the `view` state untouched** — orphaning the routing.

All six dedicated panels still exist on disk and still compile
(`CaptureOverlay`, `SettingsPanel`, `VaultManager`, `InboxPanel`, `StatsPanel`,
`LookPanel`); they are simply no longer imported by `App.tsx`.

---

## 2. Design — two isolated systems

| Display mode | Entry point | Expanded render |
|---|---|---|
| `full` | no pill; tray/hotkey opens window | `<FullWindow>` dashboard (**untouched**) |
| `capsule` / `minimal` | pill + radial/capsule menu | dedicated panel for `view` (restored) |

The single switch that isolates them is `displayMode`:

- `displayMode === "full"` → render `FullWindow`.
- otherwise → render the dedicated-panel stack keyed off `view`.

Confirmed with user: the pill only exists in capsule/minimal; Full Window Mode
has no pill, so `handleMenuSelect` can never fire in full mode. The two code
paths therefore never overlap — full isolation by construction.

---

## 3. Changes (all in `gui/src/App.tsx`)

### 3.1 Re-add imports (top of file, alongside the `FullWindow` import)
```ts
import CaptureOverlay from "./components/CaptureOverlay";
import SettingsPanel from "./components/SettingsPanel";
import VaultManager from "./components/VaultManager";
import InboxPanel from "./components/InboxPanel";
import StatsPanel from "./components/StatsPanel";
import LookPanel from "./components/LookPanel";
```
Keep the `FullWindow` import.

### 3.2 Restore the `setMeasureEl` helper
The refactor deleted it, leaving the capture-height effect (App.tsx:579–591)
dead (`measureEls.current.capture` is read but never written). `CaptureOverlay`
needs it back so the capture card's dynamic height still drives `contentH`.

Add near the `measureEls` ref (App.tsx:569):
```ts
const setMeasureEl = (v: View) => (el: HTMLElement | null) => {
  measureEls.current[v] = el;
};
```
(Only `capture` is actually measured; the other views fall back to
`SECONDARY_H`, exactly as the current `displayH` logic at App.tsx:593 already
assumes.)

### 3.3 Branch the final `return` on `displayMode`

Replace the current unconditional `FullWindow` return (App.tsx:1566–1635) with:

- **`displayMode === "full"`** → the **exact current** `FullWindow` JSX
  (move it verbatim into this branch — do not touch it). Keep `DevTuner` +
  `ToastHost`.

- **else (pill modes)** → the restored dedicated-panel stack from `9cc9338`,
  wired to the props that exist in the current file:

```tsx
<div style={{ width:"100vw", height:"100vh", display:"flex",
              alignItems:"center", justifyContent:"center",
              background:"transparent", overflow:"hidden" }}>
  <div style={{ position:"relative", width:440, height:displayH,
                transition:"height 0.2s cubic-bezier(0.16,1,0.3,1), opacity 0.2s cubic-bezier(0.16,1,0.3,1)",
                opacity: contentHidden ? 0 : 1,
                pointerEvents: contentHidden ? "none" : undefined }}>
    <CaptureOverlay
      measureRef={setMeasureEl("capture")}
      captureState={captureState} stepDefs={stepDefs}
      onOpenSettings={() => setView("settings")}
      onOpenVault={() => setView("vault")}
      onOpenInbox={() => setView("inbox")}
      onOpenSearch={() => setView("look")}
      onOpenStats={() => setView("stats")}
      visible={view === "capture"} inboxCount={inboxCount}
      onCollapseToPill={() => setExpanded(false)}   // pill mode only, always defined here
    />
    <SettingsPanel
      measureRef={setMeasureEl("settings")} visible={view === "settings"}
      onClose={() => setView("capture")}
      theme={theme} themeLabel={THEME_LABELS[theme]} onSelectTheme={selectTheme}
      displayMode={displayMode} onSelectDisplayMode={setDisplayMode}
      pillCorner={pillCorner} onSelectPillCorner={setPillCorner}
      pillPinned={pillPinned} onTogglePillPinned={setPillPinned}
      pillAnchor={pillAnchor} onSelectPillAnchor={setPillAnchor}
      pillFanStyle={pillFanStyle} onSelectPillFanStyle={setPillFanStyle}
      pillSnapEnabled={pillSnapEnabled} onTogglePillSnap={setPillSnapEnabled}
      monitors={monitors} selectedMonitorId={selectedMonitorId}
      onSelectMonitor={handleSelectMonitor}
      lookChatPersist={lookChatPersist} onSelectLookChatPersist={setLookChatPersist}
    />
    <VaultManager  measureRef={setMeasureEl("vault")}  visible={view === "vault"}  onClose={() => setView("capture")} />
    <InboxPanel    measureRef={setMeasureEl("inbox")}  visible={view === "inbox"}  onClose={() => setView("capture")} onCountChange={setInboxCount} />
    <StatsPanel    measureRef={setMeasureEl("stats")}  visible={view === "stats"}  onClose={() => setView("capture")} />
    <LookPanel
      measureRef={setMeasureEl("look")} visible={view === "look"}
      mode={lookMode} onSelectMode={setLookMode} onClose={() => setView("capture")}
      lookChat={lookChat} lookChatPersist={lookChatPersist}
    />
  </div>
  <DevTuner />
  {/* ToastHost — keep current placement */}
</div>
```

`handleMenuSelect` needs **no change** — once the stack keys off `view` again,
its existing `setView(...)` resolves to the right panel.

---

## 4. Things to verify against the current file (don't assume the old props match)

The pre-refactor block is the template, but prop signatures may have drifted
since `9cc9338`. Before wiring, confirm each panel's current prop names:

1. `CaptureOverlay` — confirm it still accepts `measureRef`, the five
   `onOpen*` handlers, `onCollapseToPill`, `inboxCount`, `visible`,
   `captureState`, `stepDefs`. (It's in the modified set in git status.)
2. `SettingsPanel` — currently used by `FullWindow` with `embedded`. For the
   standalone pill use, render **without** `embedded` (full panel chrome +
   `onClose`). Confirm the non-embedded path still exists.
3. `LookPanel` — `FullWindow` passes `hideToggle embedded`. Standalone pill use
   wants neither (its own toggle + close). Confirm.
4. `VaultManager`, `InboxPanel`, `StatsPanel` — confirm `measureRef` / `onClose`
   / `onCountChange` props still exist (all three are in git status as
   modified).

If any prop was renamed/removed, adapt the call site — do **not** reintroduce a
deleted prop into the panel.

---

## 5. No-regression checks (Full Window Mode must be untouched)

- `FullWindow` JSX is **moved, not edited**. Its internal nav, rail, settings
  forwarding stay byte-identical.
- Confirm the `settingsProps` object currently passed to `FullWindow` still
  feeds it in the `displayMode === "full"` branch.
- Switching `displayMode` full ⇄ capsule/minimal from inside either Settings
  surface must still work: the `return` now branches on `displayMode`, so a
  mid-session switch re-renders the correct system on the next commit. The
  window-resize effect (App.tsx:1009) already handles `enteringFullMode` /
  `enteringPill` geometry — no geometry change needed.
- Window sizing already differentiates: full → `FULL_WIN_W/H` (920×560),
  pill-expanded → 480×(`displayH`+`V_MARGIN`). The restored 440-wide inner box
  fits the 480 window exactly as before the refactor. No `pillBox*` edits.

---

## 6. Required check (CLAUDE.md hard rule: one runnable check per change)

This is routing logic across `displayMode` × `view`, so it needs a guard.

- **Build gate (mandatory):** `cd gui && npm run build` — tsc strict
  (`noUnusedLocals`/`noUnusedParameters`) will fail if any re-added import is
  unused or any prop is wrong. This is the primary correctness check.
- **Smoke matrix (manual, `npm run dev`):**
  - Minimal mode: pill → each of vault / settings / look / inbox / stats opens
    that panel (not the dashboard); `onClose`/Esc returns to the pill.
  - Capsule mode: same five picks.
  - Full mode: tray/hotkey opens the `FullWindow` dashboard; rail nav unchanged.
  - Toggle `displayMode` in Settings both directions; confirm the correct
    system renders after each switch.
- **Optional pure unit:** if a `routeForMode(displayMode, view)` selector is
  extracted, add `App.routing.test.ts` asserting
  `full → "fullwindow"` and `capsule/minimal+view → view`. Only worth it if the
  branch is extracted into a `lib/` pure function; otherwise the build gate +
  smoke matrix suffice (YAGNI).

---

## 7. Out of scope / explicitly NOT doing

- No edits to `FullWindow.tsx`, `DashboardView.tsx`, `LibraryView.tsx`.
- No new abstraction layer over the two systems — a single `displayMode`
  branch in `return` is the whole isolation. (Don't build a router.)
- No Python/Rust/Tauri capability changes; the bug is pure React routing.
