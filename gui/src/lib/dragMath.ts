/**
 * dragMath.ts
 * -----------
 * Pure logical-position math for custom pointer-driven pill drag. Everything
 * here stays in LOGICAL px end-to-end: `PointerEvent.screenX/screenY` are
 * already logical/CSS px, not physical, so mixing them with a physical
 * `outerPosition()` value would need a division that only applies to one
 * side of the sum (the recurring CLAUDE.md physical/logical bug class).
 * Convert `outerPosition()` to logical once at drag start, then add logical
 * deltas with no further scale division.
 */

export interface Point {
  x: number;
  y: number;
}

/** Next window top-left in LOGICAL px: the window's LOGICAL top-left at drag
 *  start plus the LOGICAL cursor delta since then (current - start, from
 *  PointerEvent.screenX/screenY). Single-monitor-per-gesture: the start is
 *  expressed once in its starting monitor's logical space and never
 *  re-scaled mid-drag. */
export function nextWindowTopLeft(startTopLeftLogical: Point, cursorDeltaLogical: Point): Point {
  return {
    x: startTopLeftLogical.x + cursorDeltaLogical.x,
    y: startTopLeftLogical.y + cursorDeltaLogical.y,
  };
}

/** Exponential moving average velocity estimate (px/s), blending the latest
 *  instantaneous sample with the running estimate. Used to seed the
 *  fling spring with a release velocity that isn't just one noisy pointer
 *  event's delta. `alpha` close to 1 favors the newest sample. */
export function emaVelocity(prevVelocity: Point, deltaPhysical: Point, dt: number, alpha = 0.35): Point {
  if (dt <= 0) return prevVelocity;
  const instant: Point = { x: deltaPhysical.x / dt, y: deltaPhysical.y / dt };
  return {
    x: prevVelocity.x + (instant.x - prevVelocity.x) * alpha,
    y: prevVelocity.y + (instant.y - prevVelocity.y) * alpha,
  };
}

/** After clamping a fling/drag step to the monitor edge (R3), the velocity
 *  component normal to whichever axis got clamped must be zeroed — otherwise
 *  the spring keeps "pushing" into the edge every subsequent step and the
 *  position oscillates instead of resting flush against it. */
export function zeroVelocityAtClamp(rawPos: Point, clampedPos: Point, vel: Point): Point {
  return {
    x: rawPos.x !== clampedPos.x ? 0 : vel.x,
    y: rawPos.y !== clampedPos.y ? 0 : vel.y,
  };
}

/** Drag-start baseline (window top-left, LOGICAL px). When a menu close is
 *  still settling, the live `outerPosition()` read is the stale open-state
 *  window top-left; the authoritative value is the known settled idle
 *  top-left captured on menu-open. Prefer it when present. */
export function dragStartBaseline(
  settledIdleTopLeft: Point | null,
  liveWindowTopLeft: Point,
): Point {
  return settledIdleTopLeft ?? liveWindowTopLeft;
}
