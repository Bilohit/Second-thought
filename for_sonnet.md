# for_sonnet.md — Pill Menu: click-away close + multi-monitor geometry fixes

**Audience:** Sonnet, implementing in `gui/`.
**Scope:** Two behavioral/positioning bugs in the on-click pill menu (Minimal/Capsule modes). No new visuals, no mockups. Everything below is logical-px unless stated otherwise.

Read first (you'll be editing/depending on these):
- `gui/src/App.tsx` — owns `menuOpen`, `pillPinned`, the window-geometry effect (lines ~568-690), and the in-window click handler (~717-746).
- `gui/src/lib/monitor.ts` — `getActiveWorkArea()` (monitor resolution).
- `gui/src/components/PillOverlay.tsx`, `PillMenu/RadialMenu.tsx`, `PillMenu/CapsuleMenu.tsx` — render only; do not own geometry.
- `gui/src-tauri/tauri.conf.json` — window is `alwaysOnTop`, `decorations:false`, `skipTaskbar:true`, created hidden.

**Process:** Use `superpowers:systematic-debugging` for Bug 2 (confirm the drift delta with logging before and after — do not assume the numbers). Use `superpowers:test-driven-development` for any pure helper you extract (e.g. the clamp/center math). Run `npm run build` (tsc + vite) before claiming done.

---

## Bug 1 — Menu does not close when clicking away

### Symptom
Open the menu (Minimal or Capsule), click anywhere outside the menu — desktop, another app, the other monitor — and the menu stays open.

### Root cause
On menu open the OS window only grows to *tightly* wrap the menu (`menuBoxW/menuBoxH`, `App.tsx:454-457`). The only close-on-click handler is the in-window wrapper `onClick` at `App.tsx:720`, which fires for DOM clicks **inside** the transparent window. Clicks on the desktop / another app / the other monitor land **outside** the window, so no DOM event is ever produced and the menu never closes.

### Fix
Add a Tauri window focus-loss listener in `App.tsx`. When the window loses focus while `menuOpen` is true, close the menu — and respect Stay Pinned:

- `pillPinned === true`  → `setMenuOpen(false)` only (pill stays where it is).
- `pillPinned === false` → `setMenuOpen(false)` **and** `getCurrentWindow().hide()` (send to tray, same as the Hide action `handleMenuHide`).

Implementation notes:
- Use `getCurrentWindow().onFocusChanged(({ payload: focused }) => { ... })`. It returns a `Promise<UnlistenFn>`; unlisten on cleanup.
- The listener must read **current** `menuOpen` and `pillPinned`. Mount the listener **once** (empty dep array, consistent with the other one-time listeners in this file) and read both values through refs to avoid re-subscribing every render. There is already a `holdOpenRef` (`= pillPinned || expanded`, `App.tsx:272-275`) — but for this you specifically want raw `pillPinned`, so add a small `pillPinnedRef` mirror (and a `menuOpenRef`). Follow the existing `snapStateRef` mirror pattern (`App.tsx:480-483`).
- Only act on `focused === false`. Ignore focus-**gained** events.
- Closing the menu flips `menuOpen`, which fires the existing CSS exit animations (spoke collapse / capsule morph). The geometry effect already waits out the shrink (220ms delay branch at `App.tsx:684-689`), so the animation is preserved. Do **not** add a separate animation.
- Keep the existing in-window wrapper `onClick` close (`App.tsx:720`) as-is — it correctly handles clicks on empty space *inside* the grown window; the focus listener handles everything outside it.

### Edge cases to verify
- Clicking the **tray icon** while the menu is open: focus loss fires → menu closes (pinned) or hides (unpinned). Acceptable.
- Selecting a menu item (`handleMenuSelect`) already sets `menuOpen=false` + `expanded=true` and the window grows to full; the focus listener must not interfere (it only acts while `menuOpen` is still true). Verify no double-close race.
- Re-clicking the pill to toggle closed still works (`onToggleMenu`); the focus listener should not double-fire a hide.

---

## Bug 2 — Pill drifts / disappears on menu open/close (custom positioning)

### Symptoms (from the user)
1. **Single display, Custom anchor:** repeatedly toggling the menu open/close makes the pill **drift downward** ("jumps lower") each cycle. Reproduces with one monitor — so this is **not** multi-monitor-specific.
2. **Dual display (secondary monitor to the LEFT of primary → negative-X coordinate space), Custom anchor, pill on the shared/inner edge:** toggling open/close makes the pill jump; at the **bottom-left** corner the pill **disappears entirely** (not visible on either monitor).

Both originate in the same code: the menu open/close geometry block in the resize effect, `App.tsx:618-665`.

### Root cause analysis
The `openingMenu` branch (`App.tsx:618-660`) and `closingMenu` branch (`App.tsx:661-665`) compute the window's new position by **re-reading live geometry** (`outerPosition()`, `outerSize()`, `scaleFactor()`) at a moment that **races** with the pending async `setSize`/`setPosition` from the same and prior cycles. Specifically:

- The pill's "center" is recomputed every open from `curPos + curSize/2`, where `curSize` is read live. If the window is not exactly at its idle size/position at read time (mid-tween, rounding, a still-settling prior cycle), the recomputed center is slightly off, and that error **accumulates** across open/close cycles → the vertical drift in symptom 1.
- For **Minimal** mode there is **no clamping**: `clampedX = growX` unconditionally (`App.tsx:657-658`), and Y is never clamped at all (`centerY - targetWinH/2`, `App.tsx:659`). So when the grown window's computed top-left goes off the work area (left/top), nothing reins it in.
- The active monitor is resolved from the **grown window's physical center** (`getActiveWorkArea` → `monitorFromPoint`, `monitor.ts:25-27`). As the window grows toward the shared edge, that center can cross onto the **other** monitor, returning the wrong work-area origin. With a secondary monitor at negative X, the wrong-origin math places the window where it is fully off every visible monitor → the disappearance in symptom 2.

### Fix — targeted refactor (single source of truth for the pill center)

**Hard constraint (user):** the pill's on-screen center must **never shift on its own.** It stays exactly where the user placed it, on open and on close, in every mode and on every monitor. We do **not** clamp the pill inward to keep it on-screen. The window may overhang a monitor edge with transparent margin (invisible) — that is fine and expected. The disappearance bug is fixed by computing the fixed center *correctly*, not by moving the pill.

Goal: the pill's on-screen center must be **stable across open/close cycles** and **derived from one authoritative value**, not re-measured live each time.

**1. Authoritative idle position.** When the menu opens in Custom mode, capture the idle window's top-left **once** into `pillBoxBeforeMenuRef` (this ref already exists, `App.tsx:562`). Restore to *exactly* that value on close (the close branch already does this, `App.tsx:661-663`). The drift fix is to make sure the open branch derives the menu-open center from a **known idle size constant**, not from a live `outerSize()` read that may be stale:
   - Idle pill window size is deterministic: `pillBoxW`/`pillBoxH` (`App.tsx:445-446`), i.e. `PILL_DIMS[mode] + PILL_MARGIN*2`. Use these constants for the center math instead of `curSize`.
   - Pill center = `idleTopLeft + {pillBoxW/2, pillBoxH/2}`. Compute `idleTopLeft` from the live `outerPosition()` **once** at open (that read is fine — it's the position, which is settled while idle), store it in `pillBoxBeforeMenuRef`, and use the **constant** sizes for the half-extents. This removes the `curSize` race entirely.

**2. Window position is always `pillCenter − windowSize/2`, with NO clamp that moves the pill.** Replace the minimal branch's `clampedX = growX` and the capsule branch's "pin nearer edge + `Math.max/Math.min` clamp" (`App.tsx:653-658`) with the single rule for both modes:
   - `windowTopLeft = { x: centerX - targetWinW/2, y: centerY - targetWinH/2 }`, rounded.
   - Do **not** clamp to the work area. If this puts the window top-left off a screen edge (negative, or past the right/bottom), that is correct — the extra is transparent margin and the pill stays put. The old capsule "grow toward interior" logic existed to avoid clipping a *non-transparent* bar; since the window is transparent and the pill center is sacred, it is no longer needed. (Confirm the capsule bar itself still renders fully — it's centered in the window, so it will.)

**3. Fix the center computation so it does NOT corrupt on multi-monitor / mixed-DPI.** This is the actual cause of the disappearance:
   - Read the idle window's `outerPosition()` (physical) and `scaleFactor()` **once** at open, while the window is still idle and sitting wholly on one monitor — so the scale factor is unambiguously that monitor's. Convert to logical with that scale and store in `pillBoxBeforeMenuRef`.
   - Derive the pill center purely from `idleTopLeftLogical + {pillBoxW/2, pillBoxH/2}` (constants), never from a live `outerSize()` read.
   - All subsequent math (window top-left in step 2) stays in that **same logical space with that same scale**. Do not re-read `scaleFactor()` after the window has grown/straddled — a second read can return the neighbor monitor's scale and corrupt the logical→physical conversion (the negative-X + different-DPI disappearance).
   - `setWindowGeometryInstant` takes logical px (`LogicalSize`/`LogicalPosition`), so pass the logical values straight through — no manual physical conversion needed.

**4. Resolve the monitor for the FAN geometry from the stable pill center.** The work area fed to `radialGeometry` (`App.tsx:630-639`) is only used so the fan never draws off-screen; it must reflect the monitor the **pill** is on, not the grown window's center.
   - Add an optional `atPoint?: {x:number;y:number}` (physical px) param to `getActiveWorkArea()` so callers can ask "which monitor contains *this* point." Keep the existing no-arg behavior for other callers.
   - Pass the pill center (physical) so the resolved monitor never flips as the window grows. The `radialGeometry.cx/cy` you pass to `RadialMenu` must remain the **unchanged** pill center (we never move the pill, so the fan never re-centers).

**5. Extract the math into a tested pure helper.** Pull the center computation into a small pure function (e.g. `gui/src/lib/menuGeometry.ts`) taking `{ idleTopLeftLogical, mode, targetWinW, targetWinH }` and returning `{ windowTopLeftLogical, pillCenterLogical }` (no `area` input — there is no clamp). Unit-test it (TDD) for: single-monitor center case, an edge pill where the window top-left goes negative (asserting it is allowed to stay negative, pill center unchanged), and round-trip stability (open→close returns identical coordinates). This is where the regression coverage lives — `App.tsx` then just calls it.

### Confirm before/after with logging (do this, don't assume)
Per `superpowers:systematic-debugging`: before changing geometry, add temporary logging of `outerPosition()` (logical) on each open and close, reproduce the drift in single-monitor Custom mode, and record the per-cycle delta. After the fix, the delta across 10 open/close cycles must be **0px** (exact restore). Remove the temporary logging before finishing. For the multi-monitor case, log the resolved `area.{x,y,w,h}` and confirm it matches the monitor the pill is actually on (not the neighbor) at the bottom-left negative-X position.

---

## Test plan / acceptance criteria

Bug 1 (click-away):
- [ ] Minimal + Capsule, Stay Pinned ON: open menu, click desktop → menu animates closed, pill stays in place.
- [ ] Minimal + Capsule, Stay Pinned OFF: open menu, click another app → menu closes and app hides to tray.
- [ ] Clicking empty space inside the grown window still closes the menu (existing behavior intact).
- [ ] Selecting a menu item still routes/expands without the focus listener interfering.

Bug 2 (geometry):
- [ ] Single monitor, Custom anchor: 10× open/close cycles → pill returns to the exact same spot every time (0px drift), verified by logging.
- [ ] Dual monitor (secondary on LEFT, negative X), Custom anchor, pill on shared/inner edge: open/close does not move the pill at all (center unchanged) and does not jump it to the other monitor.
- [ ] Same setup, pill at bottom-left corner: pill never disappears and never shifts; window is allowed to overhang the edge (transparent); fan/capsule renders centered on the pill's fixed position.
- [ ] Re-run the existing edges that already worked (single-monitor edges, dual-monitor outer edge) → no regression.
- [ ] `gui/src/lib/menuGeometry.ts` unit tests pass.

Build/verify:
- [ ] `cd gui && npm run build` passes (tsc typecheck + vite).
- [ ] Existing tests still pass (`gui/src/lib/fanLayout.test.ts` etc.).
- [ ] Temporary debug logging removed.

---

## Out of scope / do not touch
- The `/v1` base-URL invariant and Python pipeline — unrelated.
- The `setWindowGeometryInstant` vs `animateWindowAndSizeTo` split — keep menu open/close on the **instant** path (`App.tsx:671`); the drift fix is about *what position* we pass, not how we tween there.
- Snap-to-edge magnet logic (`App.tsx:511-531`) — unrelated; it's already guarded off while the menu is open.
