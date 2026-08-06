/**
 * captureRadial.ts
 * -----------------
 * Pure geometry for the NOTES tab's capture-pane radial (P3-B) — a small,
 * fixed 4-satellite fan (blank note / voice / clipboard / screenshot) that
 * opens from a center "pill" button inside the 280px capture pane.
 *
 * This is a NEW, unrelated radial from the pill's own minimal-mode
 * `RadialMenu`/`unifiedFan` (measured-geometry, corner-aware, arbitrary
 * item count) — the capture pane's radial always has exactly 4 fixed
 * satellites in a small fixed-size box, so a simple static upward fan is
 * enough and doesn't need `unifiedFan`'s corner/collision math. It also has
 * nothing to do with `CapsuleMenu`/`compactPanel.ts`'s frozen pill morph —
 * this mounts only in the full window's NOTES tab, which has never hosted
 * any radial before now.
 */

export type CaptureSatelliteId = "note" | "voice" | "clip" | "shot";

export const CAPTURE_SATELLITE_IDS: CaptureSatelliteId[] = ["note", "voice", "clip", "shot"];

export interface CaptureSatellitePosition {
  id: CaptureSatelliteId;
  x: number;
  y: number;
}

// Four satellites spread across a 120° upward arc, centered straight up
// (-90°, screen space: 0°=east, negative=up), evenly spaced 40° apart.
// Order matches CAPTURE_SATELLITE_IDS so the fan reads left-to-right.
const ANGLES_DEG = [-150, -110, -70, -30];

/** Satellite offsets (from the center pill) for the given radius, in CSS px. */
export function captureRadialFan(radius: number): CaptureSatellitePosition[] {
  return CAPTURE_SATELLITE_IDS.map((id, i) => {
    const rad = (ANGLES_DEG[i] * Math.PI) / 180;
    return { id, x: Math.cos(rad) * radius, y: Math.sin(rad) * radius };
  });
}
