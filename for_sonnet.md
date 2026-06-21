# for_sonnet.md — Pill / window behavior fixes (Round 2)

> **Audience:** the implementing model (Sonnet).
> **Scope:** five interrelated bugs in the Capsule/Minimal pill overlay and the
> Tauri window that hosts it. They all touch the same window-geometry layer
> (`gui/src/App.tsx`), the fan math (`gui/src/lib/fanLayout.ts`), the anchor
> math (`gui/src/lib/pillAnchor.ts`), and the Rust window/tray
> (`gui/src-tauri/src/lib.rs` + `tauri.conf.json`). Do them in the order below —
> Task 0 is a shared primitive the rest depend on.
>
> **Note on older `for_sonnet.md §…` references in code comments:** existing
> comments (e.g. `RadialMenu.tsx`, `useDragCloseOnMove.ts`) cite section numbers
> from a *previous* round of this file. Those describe already-shipped behavior
> (drag-closes-menu, the unified fan law) and are unrelated to the five fixes
> here. Do **not** renumber or "reconcile" them; this document is a fresh batch.

---

## Mental model after these fixes

- **Stay Pinned is the master switch for whether the app ever hides itself.** It
  applies to **every** display mode (Full, Capsule, Minimal).
  - **Pinned ON** → the window/pill **never** leaves on its own. The *only* ways
    to send it to the tray are the **Hide** button in the pill menu and a **new
    Hide item in the tray menu**.
  - **Pinned OFF** → the app **auto-hides** (a) after a capture finishes
    processing, and (b) when a secondary panel (Settings/Vault/Inbox/Stats) is
    closed back to the capture view/pill. It does **not** persist on screen.
- **Escape never hides** anymore. It still closes an open menu → search → panel,
  in that priority, but the final "nothing left to close, so hide" step is gone.
- **The global hotkey only shows/focuses.** It never toggles to hidden.
- **The tray left-click only shows/focuses** (it used to toggle-hide). Hiding is
  now always an *explicit* action (pill Hide, tray Hide).
- **All on-screen geometry is computed against the monitor the window is
  currently on**, using its **work area** (taskbar excluded) — never the
  primary monitor's `window.screen.*`.

---

## Task 0 — Shared primitive: active-monitor work area

**Why:** Problems 3 and 5 both fail for the same root reason — every geometry
calculation reads `window.screen.availWidth/availHeight`, which is **always the
primary monitor**, regardless of which display the window sits on. Tauri v2
exposes `Monitor.workArea` (`{ position, size }`, physical px, taskbar excluded)
plus `monitorFromPoint()` and `currentMonitor()`. Build one helper and route all
geometry through it.

**New file:** `gui/src/lib/monitor.ts`

```ts
import { getCurrentWindow, monitorFromPoint, currentMonitor } from "@tauri-apps/api/window";

export interface WorkArea {
  /** logical-px top-left of the monitor's work area */
  x: number;
  y: number;
  /** logical-px work-area size (taskbar excluded) */
  w: number;
  h: number;
  scale: number;
}

/**
 * Work area (taskbar excluded) of the monitor the window currently sits on,
 * in LOGICAL px. Resolves the monitor by the window's physical CENTER point so
 * a window straddling two displays picks the one it's mostly on. Falls back to
 * currentMonitor(), then to a primary-screen guess, so callers always get a
 * usable rect.
 */
export async function getActiveWorkArea(): Promise<WorkArea> {
  const win = getCurrentWindow();
  try {
    const pos = await win.outerPosition();   // physical
    const size = await win.outerSize();      // physical
    const cx = pos.x + size.width / 2;
    const cy = pos.y + size.height / 2;
    const mon = (await monitorFromPoint(cx, cy)) ?? (await currentMonitor());
    if (mon) {
      const s = mon.scaleFactor;
      return {
        x: mon.workArea.position.x / s,
        y: mon.workArea.position.y / s,
        w: mon.workArea.size.width / s,
        h: mon.workArea.size.height / s,
        scale: s,
      };
    }
  } catch { /* fall through */ }
  return { x: 0, y: 0, w: window.screen.availWidth, h: window.screen.availHeight, scale: 1 };
}
```

**Coordinate-space rule (state it; it is the #1 source of two-monitor bugs):**
work-area `x/y` are an **origin offset**, not zero. On a secondary monitor to the
right of primary, `x` might be `1920`. Any anchor/snap/center math must add this
origin — e.g. a top-left anchor is `(area.x + margin, area.y + margin)`, *not*
`(margin, margin)`. Every `window.screen.availWidth/Height` reference removed in
the tasks below is replaced by `area.w/area.h` **with `area.x/area.y` applied**.

**Audit (replace every one of these):**
- `gui/src/lib/pillAnchor.ts` → `anchorPosition()` reads `window.screen.*`.
- `gui/src/App.tsx` → snap-to-edge block inside the `onMoved` listener; the
  `leavingPill` "center on screen" branch; the `openingMenu` capsule grow + the
  `radialGeometry` `sw/sh`.

> Because `getActiveWorkArea()` is async and several of these sites are already
> inside `async` blocks, prefer passing the resolved `WorkArea` in. For the one
> pure/synchronous consumer (`anchorPosition`) change its signature to **accept**
> a `WorkArea` argument instead of reading globals — callers already `await` the
> area nearby.

**Manual test:** drag the pill to the secondary monitor; confirm later tasks'
behaviors (anchor, snap, fan, expand-center) all use *that* monitor.

---

## Problem 1 — Capsule does not open wide enough; trailing icons are clipped

**Symptom:** clicking the capsule morphs it open, but the open bar is too narrow
and the last icon(s) are cut off by `overflow: hidden`.

**Root cause:** `CapsuleMenu.tsx`:
```
export const CAPSULE_OPEN_W = ALL_TARGETS.length * CAPSULE_ICON_W + 16; // 6*36+16 = 232
```
This counts only the icon boxes plus a flat 16px. But the actual open layout
(`.capsule-menu` in `index.css`) also has **inter-item `gap: var(--space-2)`**,
**`padding: 0 var(--space-3)`** on each side, and **`margin-left:auto` on the
Hide item** (which demands extra slack). Real required width ≈
`6*36 + 5*gap + 2*pad` ≈ **280px**, so a 232px bar clips. The width is *not*
truly a function of icon count + padding the way the comment claims.

**Fix:** make the open width an exact function of the rendered layout, and make
CSS + TS share the same numbers so they cannot drift.

1. In `CapsuleMenu.tsx` define explicit shared constants and compute from them:
   ```ts
   export const CAPSULE_ICON_W = 36;   // per-item hit box
   export const CAPSULE_GAP    = 8;    // must equal --space-2 used by .capsule-menu
   export const CAPSULE_PAD_X  = 12;   // must equal --space-3 (left & right)
   export const CAPSULE_OPEN_W =
     ALL_TARGETS.length * CAPSULE_ICON_W
     + (ALL_TARGETS.length - 1) * CAPSULE_GAP
     + CAPSULE_PAD_X * 2;
   ```
   (Verify `--space-2`/`--space-3` actual values in `index.css`/`:root` and set
   `CAPSULE_GAP`/`CAPSULE_PAD_X` to match. If they differ from 8/12, use the real
   values — the invariant is *TS equals CSS*, not the specific number.)
2. **Remove `margin-left:auto` from `.capsule-item-hide`** in `index.css`. With a
   fixed, exactly-sized bar it only fights the layout and inflates the needed
   width. Hide stays last in DOM order, so it's already rightmost; keep its
   reduced-opacity styling.
3. Leave `index.css`'s open-state rule (`.capsule-menu.open .capsule-item { width:36px }`)
   as is — it already matches `CAPSULE_ICON_W`.

**Downstream:** `App.tsx` derives `menuBoxW = CAPSULE_OPEN_W + PILL_MARGIN*2`, so
the OS window grows to the corrected width automatically. No App change needed
for #1 beyond rebuild.

**Manual test:** Capsule mode → click pill → all 6 icons (Search, Vault,
Settings, Inbox, Stats, Hide) fully visible with even spacing; none clipped at
either end; closing morphs back to the dot+label cleanly.

---

## Problem 2 — Double-click maximizes to full-screen window

**Symptom:** double-clicking the pill (or the expanded window's drag bar) snaps
the window to a maximized full-screen state. Must be **off completely.**

**Root cause:** the OS treats any `-webkit-app-region: drag` surface like a title
bar, and Windows' default title-bar gesture is double-click-to-maximize. The
window config never disables `maximizable`.

**Fix (config + guard):**
1. `gui/src-tauri/tauri.conf.json`, the `main` window object — add:
   ```json
   "maximizable": false,
   "maximized": false
   ```
   (Keep existing `resizable: false`, `decorations: false`.)
2. Belt-and-suspenders in `gui/src-tauri/src/lib.rs` `on_window_event` — if a
   maximize still sneaks through (driver/OS quirks), immediately undo it:
   ```rust
   if let tauri::WindowEvent::Resized(_) = event {
       if window.is_maximized().unwrap_or(false) {
           let _ = window.unmaximize();
       }
   }
   ```
   Add this alongside the existing `CloseRequested` arm (don't replace it).

**Manual test:** double-click the pill and the expanded drag bar repeatedly →
window never maximizes, never changes size from its content-driven size.

---

## Problem 3 — Pill slides toward center when opened near a screen edge

**Symptom:** in Minimal mode, with the pill near a left/right edge, clicking it
makes the pill **move toward screen center before the radial menu appears**.

**Root cause (`App.tsx`, the size effect's `openingMenu` branch):** on open the
window grows to a large square (`RADIAL_MENU_BOX`) **centered on the pill**, then:
```
const clampedX = Math.max(0, Math.min(sw - targetWinW, growX));
```
clamps the window fully on-screen. But the pill is **flex-centered inside the
window** (`App.tsx` render: `display:flex; justify-content:center`). So when the
clamp shoves the window inward to keep it on-screen, the pill — pinned to the
window's center — visibly travels inward with it. The fan geometry
(`fanLayout.availableArc`) already knows how to open into only the available
space; the window move is fighting it.

**Fix — keep the pill's screen center fixed; let the fan adapt:**
1. Compute the pill's **true current screen center** (you already do this in the
   `openingMenu` branch via `outerPosition`+`outerSize`). Set the grown window's
   top-left to `center - box/2` for **both** axes and **do not clamp in a way
   that moves that center.** The window may extend past the work area; it is
   transparent and nothing is rendered out there, so off-area overhang is
   invisible and harmless.
2. Feed `radialGeometry` the real center and the **active monitor's work area**
   (Task 0), expressed in the window-local coordinate space the spokes use:
   ```ts
   const area = await getActiveWorkArea();
   setRadialGeometry({
     cx: centerX,          // pill center, logical screen px
     cy: centerY,
     sw: area.w,           // work-area extent…
     sh: area.h,
     originX: area.x,      // …with origin offset (see note)
     originY: area.y,
   });
   ```
   `availableArc()` in `fanLayout.ts` currently treats bounds as `[m, sw-m]` with
   an implicit origin of 0. Generalize it to `[originX+m, originX+sw-m]` and
   likewise for y (add `originX/originY` params defaulting to 0 so existing tests
   keep passing). Update `PillGeometry`/`FanParams` accordingly.
3. Keep the capsule "grow toward the interior" pin (decision carried over from
   the prior round) but recompute `sw`/screen-half against the **active work
   area**, not `window.screen`.

**Why this is correct:** the fan's job is to never draw off-screen; with the
pill fixed and the arc fed the right monitor bounds, a pill in the left edge
simply fans to the right (and up/down), the pill itself never moving. This also
removes the only reason the window needed an inward clamp.

**Manual tests:**
- Minimal pill flush against the **left** edge → click → pill stays put, fan
  opens to the right. Repeat at right/top/bottom edges and all four corners.
- Same on the **secondary monitor** (combined with Task 0).

---

## Problem 4 — App should only leave the screen on an explicit Hide

**Desired behavior** (master switch = Stay Pinned, applies to **all** display
modes including Full):

| Stay Pinned | After capture done | Closing a panel | Escape | Hotkey / tray click | Pill "Hide" | Tray "Hide" |
|-------------|--------------------|-----------------|--------|---------------------|-------------|-------------|
| **ON**      | stays              | stays           | stays  | show/focus only     | **hides**   | **hides**   |
| **OFF**     | **auto-hides**     | **auto-hides**  | stays  | show/focus only     | hides       | hides       |

### 4a. Hold-open logic (`App.tsx`)
- Current:
  ```ts
  holdOpenRef.current = displayMode !== "full" && (pillPinned || expanded);
  ```
  **Remove the `displayMode !== "full"` gate** — Stay Pinned now governs Full mode
  too:
  ```ts
  holdOpenRef.current = pillPinned || expanded;
  ```
- `useCapture` already consults `holdOpenRef` to decide the post-capture
  auto-hide. With the gate gone: pinned ⇒ holds in every mode; unpinned ⇒
  post-capture hide fires in every mode. Confirm `useCapture`'s hide path is
  reached for Full mode (it previously could not be, because the ref was always
  false there).

### 4b. Remove the "unpin ⇒ hide immediately" path (`App.tsx`)
Delete the `pendingHideRef`/`prevPillPinnedRef` effect that hides when Stay
Pinned flips from on→off while sitting idle. Turning Stay Pinned **off** must
only change *future* auto-hide behavior, not yank the window away in the moment.
(The whole `pendingHide` dance, including its "fires once when idleAtPill" guard,
goes away.)

### 4c. Auto-hide on panel close when unpinned (`App.tsx`)
"Closing any settings/vault/etc. tab" while unpinned must auto-hide. Add a small
effect: when `view` transitions **to `"capture"`** from a secondary view, and
`!pillPinned`, and `captureState.phase === "idle"`, call
`getCurrentWindow().hide()`. Guard against hiding mid-capture or when `expanded`
was set by a deliberate action you want to keep open — simplest correct rule:
hide only when `!pillPinned && phase==="idle"` at the moment of return to
capture. Each panel's `onClose` already does `setView("capture")`, so this is a
single `useEffect` keyed on `[view, pillPinned, captureState.phase]` comparing
against a `prevViewRef`.

### 4d. Escape no longer hides (`App.tsx` keydown handler)
Current Escape ladder ends with `getCurrentWindow().hide()`. Keep the
menu→search→panel close ladder; **delete the final `hide()`**. Pressing Escape
at the bare idle pill now does nothing (correct — hiding is explicit only).

### 4e. Hotkey is show-only (verify `lib.rs`)
`show_window_emit_debounced` already only shows/focuses/emits — it never hides.
No change needed; just confirm there is no toggle-hide on the registered
shortcut path.

### 4f. Tray: add "Hide", make left-click show-only (`lib.rs`)
- In `setup_tray`, add a `hide` menu item and include it in the menu (suggest
  ordering: Vault, Settings, Inbox, Stats, **Hide**, Quit). Handle it:
  ```rust
  "hide" => {
      if let Some(window) = app.get_webview_window("main") {
          let _ = window.hide();
      }
  }
  ```
- In `on_tray_icon_event` left-click handler: **remove the `if is_visible { hide }`
  toggle.** Left-click should always `show_window_emit(app, "trigger-capture")`
  (show + focus). This makes Hide the only explicit hide gesture, consistent with
  the pill menu.

### 4g. Exact-position memory
Position is already persisted to `localStorage["omni-window-pos"]` on
`onMoved`, and restored on mount before the window is shown. Two things to verify
after Task 0 lands:
- The saved coordinate is **physical px** (it is — `payload.x/y` from `onMoved`,
  restored via `PhysicalPosition`). Keep it physical end-to-end so a monitor with
  a different scale factor restores to the same pixel. Do **not** route this
  through the logical work-area helper.
- Re-showing via hotkey/tray must **not** reposition. `show_window_emit` only
  calls `show()`/`set_focus()` — confirm nothing in the show path calls
  `setPosition`/`center`. The window must reappear exactly where it was hidden.

### 4h. Settings copy
"Stay Pinned" stays in Settings (it is now the master switch). Update its
helper/description text to: *"When on, the window stays on screen until you
choose Hide (from the menu or tray). When off, it hides itself after a capture
and when you close a panel."* No structural Settings change.

**Manual tests:**
- Pinned ON, all three modes: capture completes → stays. Open & close
  Settings → stays. Press Escape at idle → stays. Pill **Hide** → goes to tray.
  Tray **Hide** → goes to tray. Re-show via hotkey → reappears at the same spot.
- Pinned OFF: capture completes → auto-hides. Open Settings, close it →
  auto-hides. Escape still doesn't hide directly (closes panel first; second
  Escape at idle does nothing).

---

## Problem 5 — Two displays must not introduce bugs

This is **resolved by Task 0** plus the per-site replacements it lists. There is
no separate code beyond auditing that **every** geometry computation uses
`getActiveWorkArea()` (with origin offset) instead of `window.screen.*`.

**Explicit checklist of sites that must be monitor-correct:**
1. `pillAnchor.anchorPosition()` — corners/edges relative to the active work
   area, including origin `x/y`.
2. `App.tsx` snap-to-edge in `onMoved` — `nearLeft/Right/Top/Bottom` compared to
   the active work area; snapped coords include origin.
3. `App.tsx` `leavingPill` expand-center — center within the active monitor, not
   primary.
4. `App.tsx` `openingMenu` capsule interior-grow + `radialGeometry` — Problem 3.
5. Restore-on-mount position — stays physical, unchanged (4g).

**Two-monitor manual test pass (run after all tasks):**
- Move pill to secondary monitor; set anchor "top-right" → snaps to that
  monitor's top-right, not primary's.
- Drag near that monitor's edges → snap magnet engages against that monitor.
- Open radial menu near that monitor's edges → fan opens inward, pill fixed.
- Expand to a panel → centers on that monitor.
- Hide (pinned: tray Hide) and re-show → reappears on the secondary monitor at
  the same pixel.
- Different scale factors (e.g. primary 150%, secondary 100%) → no drift on
  hide/restore.

---

## Files touched (summary)

| File | Tasks |
|------|-------|
| `gui/src/lib/monitor.ts` *(new)* | 0 |
| `gui/src/lib/fanLayout.ts` | 0/3 (origin params on `availableArc`/`unifiedFan`) |
| `gui/src/lib/pillAnchor.ts` | 0/5 (accept `WorkArea`) |
| `gui/src/components/PillMenu/CapsuleMenu.tsx` | 1 |
| `gui/src/index.css` | 1 (remove `margin-left:auto`) |
| `gui/src/components/PillMenu/RadialMenu.tsx` | 3 (`PillGeometry` origin fields) |
| `gui/src/App.tsx` | 0/3/4/5 (geometry, hold-open, panel-close hide, escape, snap/center) |
| `gui/src-tauri/tauri.conf.json` | 2 |
| `gui/src-tauri/src/lib.rs` | 2 (unmaximize guard), 4f (tray Hide + left-click) |

## Sequencing & verification
1. Task 0 first (everything else builds on it).
2. Problems 1 and 2 are independent — do them anytime.
3. Problem 3 depends on Task 0 (origin-aware arc).
4. Problem 4 is mostly `App.tsx` + `lib.rs`, independent of geometry.
5. Problem 5 is the audit/verification that Task 0 reached every site.

After each task: `cd gui && npm run build` (tsc + vite) must pass. Run
`npx vitest run` (or the project's test command) for `fanLayout.test.ts` after
the origin-param change — existing cases must still pass with origin defaulting
to 0. Finish with the two-monitor manual pass in Problem 5.
