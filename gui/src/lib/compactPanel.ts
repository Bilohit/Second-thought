/**
 * compactPanel.ts
 * ----------------
 * Pure math for two geometry concerns of the compact-mode capsule panel:
 *
 *  - Task 0.1: the vertical "zone" (top/middle/bottom third of the work
 *    area) the capsule sits in, and the resulting window/bar/panel geometry
 *    when the capsule grows a vertical panel underneath/above/around itself.
 *  - Task 0.2: the "island morph" rects for minimal-mode — the pill grows
 *    directly into the panel, always starting its morph exactly at the
 *    pill's own on-screen rect (never adjusted) and clamping only where it
 *    grows to.
 *
 * Both follow the same discipline as `computeMinimalMenuWindow` in
 * `menuGeometry.ts`: an anchor (the bar / the pill) that must never visibly
 * move, a computed window that may need clamping to the monitor, and an
 * offset that absorbs whatever the clamp does so the anchor holds still.
 *
 * Pure module: no Tauri imports, no side effects, logical px throughout.
 */

export const PANEL_W = 288; // = CAPSULE_OPEN_W
export const PANEL_H = 320;
export const PANEL_GAP = 0; // GATE-1 resolved: option A, fused border
export const PANEL_ANIM_MS = 300;
export const PANEL_EXIT_MS = PANEL_ANIM_MS + 60;

export interface Point {
  x: number;
  y: number;
}

export interface MonitorBounds {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type VerticalZone = "top" | "middle" | "bottom";

/**
 * Task 2.2: the two zones the capsule-panel chrome/geometry actually
 * renders. `resolveVerticalZone` still classifies three thirds of the work
 * area (used to pick which side has room), but with bar-as-header the
 * "middle" classification resolves to this same top-style downward
 * extrusion — callers map `"middle" -> "top"` before calling
 * `computeCapsulePanelGeometry`/`computePanelWindowBox` (capsule mode) or
 * feeding `CompactShell`'s `zone` prop.
 */
export type PanelExtrudeZone = Exclude<VerticalZone, "middle">;

/**
 * Viewport-thirds zone for the capsule panel, split by the capsule's own
 * center Y within the work area. Boundaries are inclusive on the lower
 * zone: exactly 1/3 is still "top", exactly 2/3 is still "middle".
 */
export function resolveVerticalZone(
  pillCenterY: number,
  workArea: { y: number; h: number }
): VerticalZone {
  const oneThird = workArea.h / 3;
  const relative = pillCenterY - workArea.y;

  if (relative <= oneThird) return "top";
  if (relative <= 2 * oneThird) return "middle";
  return "bottom";
}

export interface PanelWindowBox {
  w: number;
  h: number;
}

/**
 * Task 0.1: the OS window size when a compact panel is open. Sizes only —
 * never positions — so this is a pure function of displayMode/panelZone and
 * safe to read at render time (the clamp inside computeCapsulePanelGeometry/
 * computeIslandMorphRects only ever adjusts the window's top-left, never its
 * w/h, for a fixed zone). Single source of truth so the render-time
 * targetWinW/H selection and the reconcile apply() geometry can never
 * diverge (kills RC-5(a)).
 */
export function computePanelWindowBox(i: {
  mode: "capsule" | "minimal";
  /** Ignored: minimal mode doesn't use it; capsule mode's top/bottom
   *  extrusions are the same total height (bar + gap + panel), so the zone
   *  no longer changes the result (Task 2.2 deleted the middle-float
   *  variant, which used to need a shorter, bar-overlapping height here). */
  zone: VerticalZone;
  pillBoxW: number;
  pillBoxH: number;
  barH: number; // capsule only
  margin: number;
  /**
   * Task 0.3: floor for the computed width, fed in by the caller as the
   * menu-open box width (menuBoxW) so the OS window's width is identical at
   * the menuOpen -> compactPanel handoff — only height changes. Kept as an
   * external input rather than duplicating the menu-box math here.
   */
  minW?: number;
}): PanelWindowBox {
  if (i.mode === "minimal") {
    return { w: Math.max(PANEL_W + i.margin * 2, i.minW ?? 0), h: PANEL_H + i.margin * 2 };
  }

  const w = Math.max(i.pillBoxW, PANEL_W + i.margin * 2, i.minW ?? 0);
  const h = i.margin + i.barH + PANEL_GAP + PANEL_H + i.margin;
  return { w, h };
}

export interface CapsulePanelGeometryInput {
  /** Capsule window top-left at menu-open time (pillBoxBeforeMenuRef). */
  idleTopLeftLogical: Point;
  /** pillBoxW/H — bar size plus its surrounding margins. */
  idlePillBoxW: number;
  idlePillBoxH: number;
  /** CAPSULE_H — the bar's own (unmargined) height. */
  barH: number;
  panelW: number;
  panelH: number;
  gap: number;
  margin: number;
  /** Middle-float variant deleted (Task 2.2) — callers map
   *  `resolveVerticalZone`'s "middle" result to "top" before calling. */
  zone: PanelExtrudeZone;
  monitorBounds: MonitorBounds;
  /** Task 0.3: see computePanelWindowBox's minW — pass menuBoxW here so the
   *  panel-open window is never narrower than the menu-open window. */
  minW?: number;
  /** RC-2: which screen edge the OPEN bar is pinned to (capsuleZone). The
   *  panel-open window must keep the bar exactly where the menu-open window
   *  put it — computeCapsuleMenuGeometry pins x by this same edge. */
  nearEdge: "left" | "right" | "center";
}

export interface CapsulePanelGeometryResult {
  windowTopLeftLogical: Point;
  windowW: number;
  windowH: number;
  /** Bar's x within the grown window (keeps bar visually fixed under horizontal clamp). */
  barOffsetX: number;
  /** Bar's y within the grown window (keeps bar visually fixed). */
  barOffsetY: number;
  /** Panel's x within the grown window. */
  panelOffsetX: number;
  /** Panel's y within the grown window. */
  panelOffsetY: number;
}

/** Clamp an arbitrary window rect fully inside monitorBounds (no margin inset —
 *  the whole window is the hard-bounded entity here, unlike the pill's
 *  transparent-margin overhang allowance in `clampPillWindowToMonitor`). */
function clampWindowToMonitor(
  topLeft: Point,
  w: number,
  h: number,
  monitorBounds: MonitorBounds
): Point {
  const minX = monitorBounds.x;
  const maxX = monitorBounds.x + monitorBounds.w - w;
  const minY = monitorBounds.y;
  const maxY = monitorBounds.y + monitorBounds.h - h;

  return {
    x: Math.min(Math.max(topLeft.x, minX), maxX),
    y: Math.min(Math.max(topLeft.y, minY), maxY),
  };
}

export function computeCapsulePanelGeometry(
  i: CapsulePanelGeometryInput
): CapsulePanelGeometryResult {
  const { idleTopLeftLogical, idlePillBoxW, barH, panelW, panelH, gap, margin, zone, monitorBounds, minW, nearEdge } = i;

  const { w: windowW, h: windowH } = computePanelWindowBox({
    mode: "capsule",
    zone,
    pillBoxW: idlePillBoxW,
    pillBoxH: 0, // unused for capsule mode
    barH,
    margin,
    minW,
  });

  // Bar's on-screen position before any growth: idle window top-left plus
  // the idle box's own margin inset.
  const barY = idleTopLeftLogical.y + margin;

  let windowY: number;
  let barOffsetY: number;
  let panelOffsetY: number;

  // RC-2: horizontal placement mirrors computeCapsuleMenuGeometry's pinning
  // exactly, evaluated at the panel window's width. Bar offset mirrors the
  // flex justify App uses while the menu is open (left: flex-start = 0,
  // right: flex-end = windowW - barW, center: centered), so the bar's
  // on-screen rect is bit-identical across the menuOpen -> panelOpen
  // handoff. panelW === CAPSULE_OPEN_W (bar's open width) by design — see
  // the PANEL_W comment at the top of this file.
  const barW = panelW;
  const windowX =
    nearEdge === "right" ? idleTopLeftLogical.x + idlePillBoxW - windowW :
    nearEdge === "center" ? idleTopLeftLogical.x + idlePillBoxW / 2 - windowW / 2 :
    idleTopLeftLogical.x;
  const barOffsetXUnclamped =
    nearEdge === "right" ? windowW - barW :
    nearEdge === "center" ? (windowW - barW) / 2 :
    0;
  const panelOffsetXUnclamped = barOffsetXUnclamped;

  if (zone === "top") {
    windowY = barY - margin;
    barOffsetY = margin;
    panelOffsetY = margin + barH + gap;
  } else {
    // bottom: bar sits below the panel — window grows upward.
    windowY = barY + barH + margin - windowH;
    panelOffsetY = margin;
    barOffsetY = margin + panelH + gap;
  }

  const clamped = clampWindowToMonitor({ x: windowX, y: windowY }, windowW, windowH, monitorBounds);
  const deltaX = clamped.x - windowX;
  const deltaY = clamped.y - windowY;
  barOffsetY -= deltaY;

  return {
    windowTopLeftLogical: clamped,
    windowW,
    windowH,
    barOffsetX: barOffsetXUnclamped - deltaX,
    barOffsetY,
    panelOffsetX: panelOffsetXUnclamped - deltaX,
    panelOffsetY,
  };
}

// ---------------------------------------------------------------------------
// Task 0.2: minimal-mode island-morph geometry (GATE-2 resolved = M2)
// ---------------------------------------------------------------------------

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface IslandMorphInput {
  /** Idle pill's on-screen top-left (from pillBoxBeforeMenuRef + margin). */
  pillTopLeftLogical: Point;
  pillW: number;
  pillH: number;
  panelW: number;
  panelH: number;
  margin: number;
  /** Work area = hard boundary. */
  monitorBounds: MonitorBounds;
}

export interface IslandMorphResult {
  /** ALWAYS === the pill's exact on-screen rect (morph origin, never adjusted). */
  startRect: Rect;
  /** Final panel rect, fully inside monitorBounds inset by margin. */
  endRect: Rect;
  /** Grown OS window = endRect expanded by margin. */
  windowTopLeftLogical: Point;
  windowW: number;
  windowH: number;
  /** Pill's position INSIDE the grown window (keeps pill visually fixed
   *  during grow + after close). */
  pillOffset: Point;
}

/**
 * `endRect` starts centered on the pill's center, then each axis clamps into
 * `[monitorBounds + margin, monitorBounds + size - panel - margin]` — the
 * "growth point adjusts near edges" requirement. `startRect` is never moved:
 * the morph always begins at the pill and the clamp redirects growth inward.
 *
 * ponytail: no partial-fit branch — panel (288x320) fitting inside any real
 * monitor's work area is assumed as a precondition. If a future panel ever
 * outgrows a work area, shrink endRect then.
 *
 * ponytail: the containment-expansion pass below assumes its precondition
 * always holds (pill fully inside monitorBounds; panel size >= pill size on
 * each axis) — if a future caller ever passes a panel smaller than the pill,
 * revisit this, since containment could then force endRect outside monitorBounds.
 */
export function computeIslandMorphRects(i: IslandMorphInput): IslandMorphResult {
  const { pillTopLeftLogical, pillW, pillH, panelW, panelH, margin, monitorBounds } = i;

  const startRect: Rect = { x: pillTopLeftLogical.x, y: pillTopLeftLogical.y, w: pillW, h: pillH };

  const pillCenter: Point = {
    x: pillTopLeftLogical.x + pillW / 2,
    y: pillTopLeftLogical.y + pillH / 2,
  };

  const rawEndX = pillCenter.x - panelW / 2;
  const rawEndY = pillCenter.y - panelH / 2;

  const minX = monitorBounds.x + margin;
  const maxX = monitorBounds.x + monitorBounds.w - panelW - margin;
  const minY = monitorBounds.y + margin;
  const maxY = monitorBounds.y + monitorBounds.h - panelH - margin;

  let endX = Math.min(Math.max(rawEndX, minX), maxX);
  let endY = Math.min(Math.max(rawEndY, minY), maxY);

  // GATE-2 zero-drift contract: startRect (the pill) must always be fully
  // contained in endRect, even when the pill legally overhangs the
  // transparent margin (i.e. sits flush against the true monitor edge, past
  // the margin-inset clamp above). Expand/shift endRect on each axis so it
  // contains startRect, then re-clamp into monitorBounds itself (not the
  // margin inset) — always fits because panelW/H >= pillW/H and the pill is
  // itself inside monitorBounds.
  if (startRect.x < endX) endX = startRect.x;
  if (startRect.x + startRect.w > endX + panelW) endX = startRect.x + startRect.w - panelW;
  if (startRect.y < endY) endY = startRect.y;
  if (startRect.y + startRect.h > endY + panelH) endY = startRect.y + startRect.h - panelH;

  endX = Math.min(Math.max(endX, monitorBounds.x), monitorBounds.x + monitorBounds.w - panelW);
  endY = Math.min(Math.max(endY, monitorBounds.y), monitorBounds.y + monitorBounds.h - panelH);

  const endRect: Rect = { x: endX, y: endY, w: panelW, h: panelH };

  const { w: windowW, h: windowH } = computePanelWindowBox({
    mode: "minimal",
    zone: "top", // ignored for minimal
    pillBoxW: 0, // unused for minimal mode
    pillBoxH: 0, // unused for minimal mode
    barH: 0, // unused for minimal mode
    margin,
  });
  const windowTopLeftLogical = clampWindowToMonitor(
    { x: endRect.x - margin, y: endRect.y - margin },
    windowW,
    windowH,
    monitorBounds
  );

  const pillOffset: Point = {
    x: startRect.x - windowTopLeftLogical.x,
    y: startRect.y - windowTopLeftLogical.y,
  };

  return { startRect, endRect, windowTopLeftLogical, windowW, windowH, pillOffset };
}
