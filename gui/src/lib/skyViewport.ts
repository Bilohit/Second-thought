/**
 * skyViewport.ts — the STARS sky's zoom/pan viewport (s156; the user's ask: make the sky navigable,
 * taking ideas from Obsidian's graph view). Pure math, no platform types, so the desktop copy and
 * `Second Thought - Android App/phone/src/lib/skyViewport.ts` are the SAME TEXT — not imported
 * (different repos) but guarded by `tools/parity_edge_model.py`, which compares this file's marked
 * block across the two. That guard was extended to cover this file deliberately: `CLAMP_X` once
 * drifted 26-vs-66 between the two `starsSim.ts` files with every gate green, and `ZOOM_MIN`,
 * `ZOOM_MAX` and the two label-fade thresholds are exactly the same class of constant.
 *
 * The force simulation is NOT viewport-aware and must stay that way: `stepSimulation` keeps running
 * in world coordinates over the host's own width/height, and this module only maps world -> screen
 * for rendering. That separation is what keeps zoom from changing the physics — a sky that settled
 * differently at 2x than at 1x would be a different sky, not a magnified one.
 */

// ══ THE SKY VIEWPORT (s156) — THIS BLOCK IS KEPT IDENTICAL IN THE SIBLING REPO. ═════════════════
export interface Viewport {
  /** Screen pixels per world pixel. */
  scale: number;
  /** Screen offset applied AFTER the scale: screen = world * scale + pan. */
  panX: number;
  panY: number;
}

export const ZOOM_MIN = 0.4;
export const ZOOM_MAX = 2.5;
export const ZOOM_DEFAULT = 1;
/** One button press or one wheel notch. Multiplicative, so zooming out then in returns exactly. */
export const ZOOM_STEP = 1.25;
/** Below this scale a label is fully gone; at or above LABEL_FADE_END it is fully opaque. Labels
 *  render at a CONSTANT pixel size (D3-C, user-ruled), so without this ramp a zoomed-out sky becomes
 *  an unreadable mat of overlapping text rather than a shape. */
export const LABEL_FADE_START = 0.5;
export const LABEL_FADE_END = 0.85;

export const IDENTITY_VIEWPORT: Viewport = { scale: ZOOM_DEFAULT, panX: 0, panY: 0 };

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/** A persisted or gesture-derived scale can be anything, including NaN out of a divide-by-zero in a
 *  pinch handler. NaN resolves to the default rather than propagating into every transform. */
export function clampScale(s: number): number {
  if (!Number.isFinite(s)) return ZOOM_DEFAULT;
  return Math.min(Math.max(s, ZOOM_MIN), ZOOM_MAX);
}

export function worldToScreen(vp: Viewport, x: number, y: number): { x: number; y: number } {
  return { x: x * vp.scale + vp.panX, y: y * vp.scale + vp.panY };
}

export function screenToWorld(vp: Viewport, x: number, y: number): { x: number; y: number } {
  return { x: (x - vp.panX) / vp.scale, y: (y - vp.panY) / vp.scale };
}

/** Zoom by `factor`, keeping whatever world point currently sits under (screenX, screenY) exactly
 *  there. Anchoring on the cursor is the difference between zooming and teleporting. */
export function zoomAt(vp: Viewport, factor: number, screenX: number, screenY: number): Viewport {
  const scale = clampScale(vp.scale * factor);
  if (scale === vp.scale) return vp;
  const world = screenToWorld(vp, screenX, screenY);
  return { scale, panX: screenX - world.x * scale, panY: screenY - world.y * scale };
}

export function panBy(vp: Viewport, dx: number, dy: number): Viewport {
  return { scale: vp.scale, panX: vp.panX + dx, panY: vp.panY + dy };
}

/** Keep the sky on screen. When the scaled world is smaller than the viewport it is centred and pan
 *  is not a user-controllable axis at all; when it is larger, pan is bounded so an edge of the sky
 *  can never be dragged inside the viewport. At 1x the world IS the viewport, so panning does
 *  nothing — which is correct: there is nothing outside it to reach. */
export function clampPan(vp: Viewport, worldW: number, worldH: number, viewW: number, viewH: number): Viewport {
  const axis = (pan: number, world: number, view: number): number => {
    const content = world * vp.scale;
    if (content <= view) return (view - content) / 2;
    return Math.min(Math.max(pan, view - content), 0);
  };
  return { scale: vp.scale, panX: axis(vp.panX, worldW, viewW), panY: axis(vp.panY, worldH, viewH) };
}

/** Labels are drawn inside the scaled layer, so they need the inverse to render at constant px. */
export function labelCounterScale(vp: Viewport): number {
  return 1 / vp.scale;
}

export function labelOpacity(scale: number): number {
  return clamp01((scale - LABEL_FADE_START) / (LABEL_FADE_END - LABEL_FADE_START));
}

export function zoomPercent(scale: number): number {
  return Math.round(scale * 100);
}
// ══ END OF THE SHARED SKY VIEWPORT ═══════════════════════════════════════════════════════════════
