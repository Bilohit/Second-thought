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

export interface Point {
  x: number;
  y: number;
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
  /** Which screen edge the pill is nearer to — the bar hugs this edge and
   *  the close-padding grows toward the screen center. */
  nearEdge: "left" | "right";
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
    : idleTopLeftLogical.x;

  return {
    windowTopLeftLogical: { x: Math.round(x), y: Math.round(idleTopLeftLogical.y) },
    windowW,
    windowH,
  };
}
