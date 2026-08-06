/**
 * captureRadial.ts
 * -----------------
 * Pure geometry for the NOTES tab's capture-pane radial (P3-B) — a small,
 * fixed 5-satellite fan (blank note / voice / clipboard / screenshot /
 * calendar) that opens from a center "pill" button inside the 280px capture
 * pane.
 *
 * This is a NEW, unrelated radial from the pill's own minimal-mode
 * `RadialMenu`/`unifiedFan` (measured-geometry, corner-aware, arbitrary
 * item count) — the capture pane's radial always has a small fixed set of
 * satellites in a small fixed-size box, so a simple static upward fan is
 * enough and doesn't need `unifiedFan`'s corner/collision math. It also has
 * nothing to do with `CapsuleMenu`/`compactPanel.ts`'s frozen pill morph —
 * this mounts only in the full window's NOTES tab, which has never hosted
 * any radial before now.
 *
 * CAL-D added the 5th ("calendar") satellite — rather than hand-placing a
 * fifth arm at an arbitrary angle, the fan widens its SPAN by one more 40°
 * slot (the original 4-item fan's own spacing), so any future satellite
 * count keeps the identical density instead of accumulating one-off angles.
 */

export type CaptureSatelliteId = "note" | "voice" | "clip" | "shot" | "calendar";

export const CAPTURE_SATELLITE_IDS: CaptureSatelliteId[] = ["note", "voice", "clip", "shot", "calendar"];

export interface CaptureSatellitePosition {
  id: CaptureSatelliteId;
  x: number;
  y: number;
}

// Satellites spread across an upward arc, centered straight up (-90°, screen
// space: 0°=east, negative=up), evenly spaced ANGLE_STEP_DEG apart -- the
// original 4-item fan's own 40° spacing. Order matches CAPTURE_SATELLITE_IDS
// so the fan reads left-to-right.
const ANGLE_STEP_DEG = 40;
const ANGLE_CENTER_DEG = -90;

function satelliteAngles(count: number): number[] {
  const span = ANGLE_STEP_DEG * (count - 1);
  const start = ANGLE_CENTER_DEG - span / 2;
  return Array.from({ length: count }, (_, i) => start + i * ANGLE_STEP_DEG);
}

/** Satellite offsets (from the center pill) for the given radius, in CSS px. */
export function captureRadialFan(radius: number): CaptureSatellitePosition[] {
  const angles = satelliteAngles(CAPTURE_SATELLITE_IDS.length);
  return CAPTURE_SATELLITE_IDS.map((id, i) => {
    const rad = (angles[i] * Math.PI) / 180;
    return { id, x: Math.cos(rad) * radius, y: Math.sin(rad) * radius };
  });
}
