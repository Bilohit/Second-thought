# for_sonnet.md — Pill containment, hitbox, and click-to-close

Plan for three related fixes to the pill overlay (Capsule + Minimal modes).
Context lives in `gui/src/App.tsx`, `gui/src/lib/monitor.ts`,
`gui/src/lib/menuGeometry.ts`, `gui/src/components/PillOverlay.tsx`,
`gui/src/components/PillMenu/CapsuleMenu.tsx`, `gui/src/lib/useDragCloseOnMove.ts`,
and `gui/src/index.css`.

Read this whole file before touching code. The three problems share one piece
of groundwork (full-monitor bounds) and interact at the edges — do them in the
order below.

---

## Decisions already made (do not re-litigate)

1. **Boundary = full physical monitor, applied to the *visible pill*.** The
   visible pill may sit over the taskbar but never past the physical monitor
   edge. The transparent window margin (`PILL_MARGIN`, 6px) is allowed to
   overhang — it's invisible and harmless.
2. **Closed pill is draggable; open pill is NOT.** When the menu is open the
   pill cannot be grabbed/moved at all.
3. **Cursor:** closed pill surface = `grab` (→ `grabbing` on press); open-menu
   icons = `pointer`. (Minor; tune if it feels off, but default to this.)
4. **Click-to-close padding = Option A:** bar pinned to the near screen edge,
   transparent close-padding grows toward screen center. Additionally, clicking
   **anywhere** off the bar closes the menu (the existing outer-wrapper
   `onClick` already does this — keep it).

---

## Groundwork — full-monitor bounds helper

`monitor.ts` currently only exposes `getActiveWorkArea` (taskbar-excluded work
area). The clamp in Problem 1 needs the **full** monitor rect.

- Add `getActiveMonitorBounds(atPoint?)` (or extend `WorkArea` with `fullX/fullY/fullW/fullH`)
  that returns `mon.position` / `mon.size` instead of `mon.workArea.*`, divided
  by `scaleFactor`, in logical px. Mirror the existing fallback chain
  (`monitorFromPoint` → `currentMonitor` → screen guess).
- Keep `getActiveWorkArea` as-is; anchors and the snap magnet still use the work
  area (they should respect the taskbar). Only the hard containment clamp uses
  full bounds.

---

## Problem 1 — the pill can never leave the monitor

**Goal:** the visible pill rect always stays fully inside the current monitor's
full bounds, during live drag, snap, anchor repositioning, and menu open.

### 1a. Live clamp during drag (the main fix)

Dragging is OS-level (`-webkit-app-region: drag`), so we can't intercept frames;
instead clamp in the `onMoved` listener (`App.tsx`, currently ~528–567).

Today that handler only does a **debounced (300ms)** snap+save. Add an
**immediate, non-debounced** clamp step that runs on *every* `onMoved` payload,
before the debounce:

1. Skip if `programmaticMove.current` (our own moves).
2. Read `scaleFactor`; convert payload `x/y` to logical.
3. Compute the **visible pill rect** in logical px: the window top-left plus
   `PILL_MARGIN` inset on each side; size = `PILL_DIMS[mode] ` (the visible
   pill, not the window). Use `snapStateRef` for the live mode/size.
4. Get `getActiveMonitorBounds()` for the monitor under the pill center.
5. If the visible pill's left/right/top/bottom exceeds the monitor bounds,
   compute the corrected window top-left so the visible pill is flush inside the
   edge (allowing the transparent margin to overhang past the monitor edge),
   `markProgrammaticMove()` and `setPosition` to it.

Clamp should be cheap enough to run on every event. Keep the existing debounced
snap+save afterwards (snap still only on Custom anchor, menu closed; it operates
on the already-clamped position). Persist the clamped position, not the raw one.

### 1b. Menu-open geometry no longer overhangs

`menuGeometry.ts`'s header says "deliberately no clamp — overhang is fine." That
was the old priority. Now the near edge is *pinned* (Problem 3), so the open
menu is on-screen by construction for capsule. For the radial/minimal fan,
`radialGeometry` is already edge-aware (it resolves the monitor from the pill's
stable center) — leave it, it already keeps chips on-screen.

Update the `menuGeometry.ts` header comment to reflect the new containment
priority instead of the old "overhang is fine" rationale.

### 1c. Anchors / snap

`anchorPosition()` and the snap magnet already keep the window inside the work
area — leave their bounds source (work area) alone. Just make sure the new live
clamp (1a) is a no-op when a programmatic anchor/snap move is in flight (the
`programmaticMove` guard handles this).

---

## Problem 2 — clear hitbox, reliable cursor, drag-lock when open

**Goal:** closed pill = obvious, grabbable, draggable; open pill = locked, no
drag; no ambiguous "dead transparent zone."

### 2a. Closed = whole tight window is the grab surface

The idle window is already tight (`PILL_DIMS[mode] + PILL_MARGIN*2`). Make the
*entire* idle surface read as the pill:

- In `App.tsx` `renderPill` branch (~752), when the menu is **closed**, give the
  outer wrapper the `drag-region` class (and `cursor: grab`) so the 6px margin
  isn't a dead non-draggable ring. Since the menu is closed, a click on the
  margin can be a no-op (the pill button handles opening); keep it simple.
- `.drag-region` in `index.css` (line ~364) currently sets no cursor. Add
  `cursor: grab;` and a `.drag-region:active { cursor: grabbing; }` rule so the
  grab affordance is reliable everywhere the drag region applies.
- The pill button itself (minimal `cursor: pointer`, capsule `.capsule-menu`
  `cursor: pointer`): when closed, prefer `grab` to signal "draggable." A click
  with no movement still toggles the menu (OS drag only fires on real movement).

### 2b. Open = not draggable

When the menu is **open**:

- Remove the `drag-region` class from the capsule bar / minimal button and dot
  (make the class conditional on `!menuOpen`). With no `-webkit-app-region:
  drag`, the pill can't be moved.
- Remove the `drag-region` from the outer wrapper too (it's the close-zone now,
  see Problem 3) — it must receive clicks, not drag the window.

### 2c. Retire drag-to-close

`useDragCloseOnMove` (decision #4b from the old plan) closed the menu when you
dragged it. That behavior is gone — the pill is simply not draggable while open.

- Delete `useDragCloseOnMove.ts` and its usages in `PillOverlay.tsx` and
  `CapsuleMenu.tsx` (the `onMenuDragClose` / `onDragClose` props and the
  `onPointerDown/Move/Up` wiring). Closing is now click-off (Problem 3).
- Remove the now-unused `onMenuDragClose` prop threading in `App.tsx`
  (`onMenuDragClose={() => setMenuOpen(false)}`).

### 2d. Click-through note

Tauri can't make *part* of a window click-through; full-window
`setIgnoreCursorEvents` is all-or-nothing, so we don't use it. Keeping the idle
window tight (2a) is what removes the dead-zone feeling — there's almost no
transparent area around the closed pill. When open, the surrounding area is
*intentionally* clickable (close-zone), so click-through is not wanted there.

---

## Problem 3 — click-to-close padding (Option A), capsule mode

**Goal:** when the capsule menu is open, the icon bar hugs the near screen edge
and a transparent close-padding region grows toward screen center; clicking the
padding (or anywhere off the bar) closes the menu.

### 3a. Edge-aware open geometry

Replace the symmetric centering done by `computeMenuGeometry` (for the capsule
open case only) with edge-aware placement. Add e.g.
`computeCapsuleMenuGeometry(input, nearEdge)` in `menuGeometry.ts`, or branch
inside the `openingMenu` handler in `App.tsx` (~647):

1. Determine `nearEdge`: compare the pill's stable center X to the monitor's
   horizontal midpoint (`getActiveMonitorBounds` from the pill center). Center on
   right half → `nearEdge = "right"`; else `"left"`.
2. Open window width `W = CAPSULE_OPEN_W + PILL_MARGIN*2 + CLOSE_PAD_W`. Define
   `CLOSE_PAD_W` (suggest ~64px — comfortable click target; tune visually).
   Height unchanged (`menuBoxH`).
3. Position the window so the **bar's near edge stays aligned with the closed
   pill's near edge** (the pill's near edge doesn't jump on open). i.e. for
   `nearEdge="right"`, the window's right inner edge (right margin + bar right)
   lands where the closed pill's right edge was; padding fills the left. Mirror
   for left.
4. On close, restore exactly to the idle pill top-left (same as today via
   `pillBoxBeforeMenuRef`), so repeated open/close never drifts.

Keep using the pill's **stable center** (not a live grown-window read) for the
monitor resolution, exactly as the current `openingMenu` branch does — that
guard against monitor-flip mid-grow must survive.

### 3b. Bar alignment inside the window

The open capsule window is wider than the bar. Push the bar to the near-edge
side and leave the free space (the padding) on the inner side:

- In `App.tsx` `renderPill` wrapper, when capsule + menu open, set
  `justifyContent` to `flex-end` (nearEdge right) or `flex-start` (nearEdge
  left) instead of `center`. Thread the resolved `nearEdge` down (state set in
  the `openingMenu` branch, similar to `radialGeometry`).
- `CapsuleMenu` keeps its "never measures or anchors itself" contract — it just
  renders the bar at its natural `CAPSULE_OPEN_W`. Alignment is the wrapper's job.

### 3c. Click-to-close

The outer wrapper already has `onClick={() => { if (menuOpen) setMenuOpen(false); }}`
(App.tsx ~755). That satisfies "click anywhere off the bar closes," including
the padding. Just ensure (per 2b) the wrapper is NOT a drag-region when open so
the click lands. The bar's own click (toggle) still closes via re-click.

### 3d. Minimal/radial mode

No change to radial geometry — it already opens a fan with surrounding space and
the outer wrapper click closes it. Problem 3's asymmetric padding is
capsule-only.

---

## Testing

Existing pure-math tests live in `gui/src/lib/menuGeometry.test.ts`. Follow TDD:

- **menuGeometry / capsule geometry:** unit-test `computeCapsuleMenuGeometry`:
  near-right pins the bar's right edge and puts padding on the left; near-left
  mirrors; the pill's near-edge X is preserved across open; close restores the
  idle top-left.
- **Clamp math:** extract the visible-pill clamp into a pure function (input:
  window top-left, mode dims, margin, monitor bounds → corrected top-left) and
  unit-test it: pill pushed past each of the four edges clamps flush; transparent
  margin overhang is allowed; fully-inside is a no-op.
- **Manual / verify:** drag the pill hard into every edge and corner on each
  monitor (incl. a non-primary / different-DPI monitor) — visible pill never
  crosses. Open the menu with the pill near the left edge and near the right edge
  — padding appears on the inner side, bar hugs the edge, clicking padding closes.
  Confirm closed pill shows grab cursor and drags; open pill cannot be dragged.

## Out of scope

- No change to anchor placement options, snap threshold, or the radial fan math
  beyond what's stated.
- No Tauri-side (Rust) changes expected; this is all frontend geometry + CSS.
