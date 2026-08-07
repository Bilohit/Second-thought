import { describe, expect, it } from "vitest";
import {
  clampPan,
  clampScale,
  IDENTITY_VIEWPORT,
  labelCounterScale,
  labelOpacity,
  panBy,
  screenToWorld,
  worldToScreen,
  ZOOM_MAX,
  ZOOM_MIN,
  zoomAt,
  zoomPercent,
} from "./skyViewport";

describe("skyViewport", () => {
  it("clamps scale to the documented range", () => {
    expect(clampScale(0.001)).toBe(ZOOM_MIN);
    expect(clampScale(99)).toBe(ZOOM_MAX);
    expect(clampScale(1)).toBe(1);
    // A pinch handler that divides by a zero-distance touch pair yields NaN. That must resolve to a
    // usable scale, not propagate into every transform on the screen.
    expect(clampScale(Number.NaN)).toBe(1);
  });

  it("zoomAt keeps the point under the cursor fixed — the whole reason it exists", () => {
    const vp = { scale: 1, panX: 0, panY: 0 };
    const anchor = { x: 300, y: 180 };
    const before = screenToWorld(vp, anchor.x, anchor.y);
    const zoomed = zoomAt(vp, 1.25, anchor.x, anchor.y);
    const after = worldToScreen(zoomed, before.x, before.y);
    expect(after.x).toBeCloseTo(anchor.x, 6);
    expect(after.y).toBeCloseTo(anchor.y, 6);
  });

  it("zoomAt cannot escape the scale range, and stops panning once clamped", () => {
    const vp = { scale: ZOOM_MAX, panX: -40, panY: -20 };
    const same = zoomAt(vp, 2, 100, 100);
    expect(same.scale).toBe(ZOOM_MAX);
    expect(same.panX).toBeCloseTo(-40, 6);
    expect(same.panY).toBeCloseTo(-20, 6);
  });

  it("worldToScreen and screenToWorld round-trip", () => {
    const vp = { scale: 1.7, panX: -120, panY: 35 };
    const w = screenToWorld(vp, 410, 260);
    const s = worldToScreen(vp, w.x, w.y);
    expect(s.x).toBeCloseTo(410, 6);
    expect(s.y).toBeCloseTo(260, 6);
  });

  it("clampPan centres content smaller than the viewport and bounds it when larger", () => {
    // At 1x the world is exactly the viewport: there is nothing to pan to, so pan pins to 0.
    const at1 = clampPan({ scale: 1, panX: 90, panY: -40 }, 800, 500, 800, 500);
    expect(at1.panX).toBeCloseTo(0, 6);
    expect(at1.panY).toBeCloseTo(0, 6);
    // Zoomed in, pan is bounded so an edge of the sky can never be dragged inside the viewport.
    const at2 = clampPan({ scale: 2, panX: 500, panY: 500 }, 800, 500, 800, 500);
    expect(at2.panX).toBeCloseTo(0, 6);
    const far = clampPan({ scale: 2, panX: -5000, panY: 0 }, 800, 500, 800, 500);
    expect(far.panX).toBeCloseTo(800 - 1600, 6);
    // Zoomed OUT the content is smaller than the host, so it centres rather than sitting top-left.
    const out = clampPan({ scale: 0.5, panX: 0, panY: 0 }, 800, 500, 800, 500);
    expect(out.panX).toBeCloseTo(200, 6);
    expect(out.panY).toBeCloseTo(125, 6);
  });

  it("labels fade out below the start and are solid at the end", () => {
    expect(labelOpacity(0.4)).toBe(0);
    expect(labelOpacity(0.5)).toBe(0);
    expect(labelOpacity(0.85)).toBe(1);
    expect(labelOpacity(2.5)).toBe(1);
    expect(labelOpacity(0.675)).toBeCloseTo(0.5, 2);
  });

  it("labels counter-scale so they render at a constant pixel size", () => {
    expect(labelCounterScale({ ...IDENTITY_VIEWPORT, scale: 2 })).toBeCloseTo(0.5, 6);
    expect(labelCounterScale({ ...IDENTITY_VIEWPORT, scale: 0.5 })).toBeCloseTo(2, 6);
  });

  it("panBy is relative and zoomPercent is a whole number", () => {
    expect(panBy({ scale: 1, panX: 10, panY: 10 }, -4, 6)).toEqual({ scale: 1, panX: 6, panY: 16 });
    expect(zoomPercent(1.234)).toBe(123);
  });
});
