/**
 * menuGeometry.ts
 * ---------------
 * Pure math for the pill-menu open/close window geometry (for_sonnet.md
 * Bug 2). The pill's on-screen center must never move on its own: it is
 * derived once from the idle window's top-left + the idle pill box's known
 * (constant) half-extents, never from a live re-read of window size while
 * the menu is open/animating.
 *
 * Containment priority (for_sonnet.md Problem 1/3): the *visible pill* must
 * never cross the physical monitor edge. The open-menu window itself is
 * no longer expected to overhang — capsule's near edge is pinned in place
 * by `computeCapsuleMenuGeometry` (Problem 3) and the radial fan already
 * resolves its own on-screen bounds — so this module's open/close math
 * doesn't need its own clamp. The hard clamp lives in
 * `clampPillWindowToMonitor`, applied to the idle (closed) pill during
 * live drag.
 */

import type { WorkArea } from "./monitor";

export interface Point {
  x: number;
  y: number;
}

export interface ResolveCapsuleZoneInput {
  pillCenterLogical: Point;
  monitorBounds: WorkArea;
  idleTopLeftLogical: Point;
  idlePillBoxW: number;
  capsuleOpenW: number;
  margin: number;
  closePadW: number;
}

/** Viewport thirds zone for custom-position capsules, with center demotion when
 *  symmetric grow would overflow the monitor (CAPSULE_DIRECTIONAL_MORPH_PLAN). */
export function resolveCapsuleZone(input: ResolveCapsuleZoneInput): "left" | "right" | "center" {
  const { pillCenterLogical, monitorBounds, idleTopLeftLogical, idlePillBoxW, capsuleOpenW, margin, closePadW } = input;

  const oneThird = monitorBounds.w / 3;
  let zone: "left" | "right" | "center";
  if (pillCenterLogical.x < monitorBounds.x + oneThird) zone = "left";
  else if (pillCenterLogical.x > monitorBounds.x + 2 * oneThird) zone = "right";
  else zone = "center";

  if (zone === "center") {
    const winW = capsuleOpenW + margin * 2 + closePadW;
    const centeredX = idleTopLeftLogical.x + idlePillBoxW / 2 - winW / 2;
    if (centeredX < monitorBounds.x || centeredX + winW > monitorBounds.x + monitorBounds.w) {
      zone = pillCenterLogical.x - monitorBounds.x < monitorBounds.w / 2 ? "left" : "right";
    }
  }
  return zone;
}

export interface MenuGeometryInput {
  /** Logical-px top-left of the idle (unexpanded) pill window, read once
   *  while the window is settled and known to be on a single monitor. */
  idleTopLeftLogical: Point;
  /** Logical-px size of the idle pill box (PILL_DIMS[mode] + margins). */
  idlePillBoxW: number;
  idlePillBoxH: number;
  /** Logical-px size the window must grow/shrink to for this open/close
   *  state (menu-open box size, or back to the idle box size on close). */
  targetWinW: number;
  targetWinH: number;
}

export interface MenuGeometryResult {
  /** Logical-px top-left the window should be moved to. Not clamped. */
  windowTopLeftLogical: Point;
  /** Logical-px screen center of the pill itself — stable input to this
   *  function's idle box, unaffected by targetWin* or clamping. */
  pillCenterLogical: Point;
}

export function computeMenuGeometry(input: MenuGeometryInput): MenuGeometryResult {
  const { idleTopLeftLogical, idlePillBoxW, idlePillBoxH, targetWinW, targetWinH } = input;

  const pillCenterLogical: Point = {
    x: idleTopLeftLogical.x + idlePillBoxW / 2,
    y: idleTopLeftLogical.y + idlePillBoxH / 2,
  };

  const windowTopLeftLogical: Point = {
    x: Math.round(pillCenterLogical.x - targetWinW / 2),
    y: Math.round(pillCenterLogical.y - targetWinH / 2),
  };

  return { windowTopLeftLogical, pillCenterLogical };
}

export interface MonitorBounds {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ClampPillInput {
  /** Logical-px top-left of the (idle) pill window before clamping. */
  windowTopLeftLogical: Point;
  /** Logical-px size of the visible pill itself — PILL_DIMS[mode], not the
   *  window (which is `margin` px larger on every side). */
  pillW: number;
  pillH: number;
  margin: number;
  /** Full physical monitor bounds (taskbar included), logical px. */
  monitorBounds: MonitorBounds;
}

/**
 * Clamps the *visible pill* (window top-left + margin inset, sized
 * PILL_DIMS[mode]) so it never crosses the monitor's full bounds — the
 * transparent margin is allowed to overhang past the edge (for_sonnet.md
 * Problem 1, decision #1). Returns the corrected window top-left; a no-op
 * input (pill already fully inside) returns the same coordinates.
 */
export function clampPillWindowToMonitor(input: ClampPillInput): Point {
  const { windowTopLeftLogical, pillW, pillH, margin, monitorBounds } = input;

  const pillLeft = windowTopLeftLogical.x + margin;
  const pillTop = windowTopLeftLogical.y + margin;

  const minLeft = monitorBounds.x;
  const maxLeft = monitorBounds.x + monitorBounds.w - pillW;
  const minTop = monitorBounds.y;
  const maxTop = monitorBounds.y + monitorBounds.h - pillH;

  const clampedLeft = Math.min(Math.max(pillLeft, minLeft), maxLeft);
  const clampedTop = Math.min(Math.max(pillTop, minTop), maxTop);

  return {
    x: clampedLeft - margin,
    y: clampedTop - margin,
  };
}

/**
 * for_sonnet.md §4 (monitor-switch, custom anchor): when the user picks a
 * different monitor while the pill is on a custom (manually-dragged)
 * position, it lands at the same proportional offset from the new
 * monitor's centre as it had from the old monitor's centre — not a flat
 * re-centre, not a literal pixel-offset carry-over. The result is clamped
 * fully inside the new monitor's work area (assigned monitor is a hard
 * boundary, same rule as `clampPillWindowToMonitor`).
 */
export interface ProportionalMonitorMoveInput {
  /** Logical-px centre of the window on the OLD monitor. */
  oldCenterLogical: Point;
  oldWorkArea: MonitorBounds;
  newWorkArea: MonitorBounds;
  winW: number;
  winH: number;
}

export function computeProportionalMonitorMove(input: ProportionalMonitorMoveInput): Point {
  const { oldCenterLogical, oldWorkArea, newWorkArea, winW, winH } = input;

  const oldMonitorCenter: Point = {
    x: oldWorkArea.x + oldWorkArea.w / 2,
    y: oldWorkArea.y + oldWorkArea.h / 2,
  };
  const propX = (oldCenterLogical.x - oldMonitorCenter.x) / (oldWorkArea.w / 2);
  const propY = (oldCenterLogical.y - oldMonitorCenter.y) / (oldWorkArea.h / 2);

  const newMonitorCenter: Point = {
    x: newWorkArea.x + newWorkArea.w / 2,
    y: newWorkArea.y + newWorkArea.h / 2,
  };
  const targetCenter: Point = {
    x: newMonitorCenter.x + propX * (newWorkArea.w / 2),
    y: newMonitorCenter.y + propY * (newWorkArea.h / 2),
  };

  const clampedCenter: Point = {
    x: Math.min(Math.max(targetCenter.x, newWorkArea.x + winW / 2), newWorkArea.x + newWorkArea.w - winW / 2),
    y: Math.min(Math.max(targetCenter.y, newWorkArea.y + winH / 2), newWorkArea.y + newWorkArea.h - winH / 2),
  };

  return {
    x: Math.round(clampedCenter.x - winW / 2),
    y: Math.round(clampedCenter.y - winH / 2),
  };
}

export interface MinimalMenuWindowInput {
  /** Whether the menu is open (true) or closed (false) — closed is the
   *  identity case: the window sits exactly back at the idle top-left. */
  open: boolean;
  /** Logical-px top-left of the idle (closed) pill window, captured once on
   *  the closed→open edge. */
  idleTopLeftLogical: Point;
  idlePillBoxW: number;
  idlePillBoxH: number;
  pillW: number;
  pillH: number;
  menuBoxW: number;
  menuBoxH: number;
  margin: number;
  monitorBounds: MonitorBounds;
}

export interface MinimalMenuWindowResult {
  windowTopLeftLogical: Point;
  /** Pill position within the window. */
  wrapperOffset: Point;
}

/**
 * Single pure function for the minimal pill's open *and* close window
 * geometry (for_sonnet_pill_fix.md Phase 2). `open: false` is the identity
 * case — same idle top-left, same margin-only wrapper offset — so close can
 * never drift from open: it's the same function, not a separately replayed
 * path.
 */
export function computeMinimalMenuWindow(input: MinimalMenuWindowInput): MinimalMenuWindowResult {
  const { open, idleTopLeftLogical, idlePillBoxW, idlePillBoxH, pillW, pillH, menuBoxW, menuBoxH, margin, monitorBounds } = input;

  if (!open) {
    return {
      windowTopLeftLogical: idleTopLeftLogical,
      wrapperOffset: { x: margin, y: margin },
    };
  }

  const pillCenterLogical: Point = {
    x: idleTopLeftLogical.x + idlePillBoxW / 2,
    y: idleTopLeftLogical.y + idlePillBoxH / 2,
  };
  const windowTopLeftLogical: Point = {
    x: Math.round(pillCenterLogical.x - menuBoxW / 2),
    y: Math.round(pillCenterLogical.y - menuBoxH / 2),
  };
  const clamped = clampPillWindowToMonitor({
    windowTopLeftLogical,
    pillW: menuBoxW,
    pillH: menuBoxH,
    margin: 0,
    monitorBounds,
  });

  return {
    windowTopLeftLogical: clamped,
    wrapperOffset: {
      x: pillCenterLogical.x - clamped.x - pillW / 2,
      y: pillCenterLogical.y - clamped.y - pillH / 2,
    },
  };
}

export interface CapsuleMenuGeometryInput {
  /** Logical-px top-left of the idle (closed) capsule window. */
  idleTopLeftLogical: Point;
  /** Logical-px size of the idle capsule window (includes margins). */
  idlePillBoxW: number;
  idlePillBoxH: number;
  margin: number;
  /** Natural width of the open capsule bar (CAPSULE_OPEN_W). */
  capsuleOpenW: number;
  /** Width of the transparent click-to-close padding (for_sonnet.md
   *  Problem 3, Option A). */
  closePadW: number;
  /** Which zone the pill is in — left third anchors left, right third anchors
   *  right, center third grows symmetrically from the pill's own center. */
  nearEdge: "left" | "right" | "center";
}

export interface CapsuleMenuGeometryResult {
  windowTopLeftLogical: Point;
  windowW: number;
  windowH: number;
}

/**
 * Edge-aware open geometry for the capsule menu (for_sonnet.md Problem 3,
 * decision #4: Option A). The window grows only toward the screen center —
 * the edge nearer the screen border keeps the same window edge position the
 * idle pill had, so the pill's near edge never jumps on open. Height is
 * unchanged (capsule only grows wider), so the top edge never moves either.
 */
export function computeCapsuleMenuGeometry(input: CapsuleMenuGeometryInput): CapsuleMenuGeometryResult {
  const { idleTopLeftLogical, idlePillBoxW, idlePillBoxH, margin, capsuleOpenW, closePadW, nearEdge } = input;

  const windowW = capsuleOpenW + margin * 2 + closePadW;
  const windowH = idlePillBoxH;

  const x = nearEdge === "right"
    ? idleTopLeftLogical.x + idlePillBoxW - windowW
    : nearEdge === "center"
    ? idleTopLeftLogical.x + idlePillBoxW / 2 - windowW / 2
    : idleTopLeftLogical.x;

  return {
    windowTopLeftLogical: { x: Math.round(x), y: Math.round(idleTopLeftLogical.y) },
    windowW,
    windowH,
  };
}
