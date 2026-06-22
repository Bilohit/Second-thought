import { describe, expect, it } from "vitest";
import { computeMenuGeometry, clampPillWindowToMonitor, computeCapsuleMenuGeometry } from "./menuGeometry";

describe("computeMenuGeometry", () => {
  it("single-monitor: pill center is the idle box's geometric center", () => {
    const { pillCenterLogical } = computeMenuGeometry({
      idleTopLeftLogical: { x: 500, y: 400 },
      idlePillBoxW: 60,
      idlePillBoxH: 60,
      targetWinW: 60,
      targetWinH: 60,
    });
    expect(pillCenterLogical).toEqual({ x: 530, y: 430 });
  });

  it("window top-left for a larger menu box is centered on the pill, not the idle box", () => {
    const { windowTopLeftLogical, pillCenterLogical } = computeMenuGeometry({
      idleTopLeftLogical: { x: 500, y: 400 },
      idlePillBoxW: 60,
      idlePillBoxH: 60,
      targetWinW: 300,
      targetWinH: 300,
    });
    expect(pillCenterLogical).toEqual({ x: 530, y: 430 });
    expect(windowTopLeftLogical).toEqual({ x: 530 - 150, y: 430 - 150 });
  });

  it("allows the window top-left to go negative at a screen edge (no clamp)", () => {
    const { windowTopLeftLogical } = computeMenuGeometry({
      idleTopLeftLogical: { x: 10, y: 10 },
      idlePillBoxW: 60,
      idlePillBoxH: 60,
      targetWinW: 300,
      targetWinH: 300,
    });
    // pillCenter = (40, 40); window top-left = 40 - 150 = -110
    expect(windowTopLeftLogical.x).toBe(-110);
    expect(windowTopLeftLogical.y).toBe(-110);
  });

  it("allows the window top-left to go negative in negative-X monitor space", () => {
    const { windowTopLeftLogical, pillCenterLogical } = computeMenuGeometry({
      idleTopLeftLogical: { x: -1900, y: 700 },
      idlePillBoxW: 60,
      idlePillBoxH: 60,
      targetWinW: 300,
      targetWinH: 300,
    });
    expect(pillCenterLogical).toEqual({ x: -1870, y: 730 });
    expect(windowTopLeftLogical).toEqual({ x: -1870 - 150, y: 730 - 150 });
  });

  it("round-trips: opening then closing returns the exact original idle top-left", () => {
    const idleTopLeftLogical = { x: 137, y: 842 };
    const idlePillBoxW = 60;
    const idlePillBoxH = 60;

    const opened = computeMenuGeometry({
      idleTopLeftLogical,
      idlePillBoxW,
      idlePillBoxH,
      targetWinW: 320,
      targetWinH: 320,
    });

    // Closing recomputes from the SAME stored idle top-left/box (never from
    // a live re-read of the grown window), so the result must be identical
    // to the original idle position.
    const closed = computeMenuGeometry({
      idleTopLeftLogical,
      idlePillBoxW,
      idlePillBoxH,
      targetWinW: idlePillBoxW,
      targetWinH: idlePillBoxH,
    });

    expect(closed.windowTopLeftLogical).toEqual(idleTopLeftLogical);
    expect(closed.pillCenterLogical).toEqual(opened.pillCenterLogical);
  });

  it("repeated open/close cycles produce zero drift", () => {
    const idleTopLeftLogical = { x: 300, y: 300 };
    const idlePillBoxW = 48;
    const idlePillBoxH = 48;

    for (let i = 0; i < 10; i++) {
      const opened = computeMenuGeometry({
        idleTopLeftLogical, idlePillBoxW, idlePillBoxH,
        targetWinW: 260, targetWinH: 260,
      });
      const closed = computeMenuGeometry({
        idleTopLeftLogical, idlePillBoxW, idlePillBoxH,
        targetWinW: idlePillBoxW, targetWinH: idlePillBoxH,
      });
      expect(closed.windowTopLeftLogical).toEqual(idleTopLeftLogical);
      expect(opened.pillCenterLogical).toEqual({ x: 324, y: 324 });
    }
  });
});

describe("clampPillWindowToMonitor", () => {
  const monitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
  const margin = 6;
  const pillW = 36;
  const pillH = 36;

  it("is a no-op when the pill is fully inside the monitor", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: 500, y: 400 },
      pillW, pillH, margin, monitorBounds,
    });
    expect(result).toEqual({ x: 500, y: 400 });
  });

  it("clamps flush at the left edge, allowing the margin to overhang", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: -20, y: 400 },
      pillW, pillH, margin, monitorBounds,
    });
    // pill left was -20+6=-14; clamped to monitor x=0 -> window x = 0-6=-6
    expect(result).toEqual({ x: -6, y: 400 });
  });

  it("clamps flush at the right edge", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: 1900, y: 400 },
      pillW, pillH, margin, monitorBounds,
    });
    // pill right would be 1900+6+36=1942 > 1920; clamped left = 1920-36=1884 -> window x = 1884-6=1878
    expect(result).toEqual({ x: 1878, y: 400 });
  });

  it("clamps flush at the top edge", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: 500, y: -30 },
      pillW, pillH, margin, monitorBounds,
    });
    expect(result).toEqual({ x: 500, y: -6 });
  });

  it("clamps flush at the bottom edge", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: 500, y: 1050 },
      pillW, pillH, margin, monitorBounds,
    });
    // pill bottom would be 1050+6+36=1092 > 1080; clamped top = 1080-36=1044 -> window y = 1044-6=1038
    expect(result).toEqual({ x: 500, y: 1038 });
  });

  it("clamps both axes at once in a corner", () => {
    const result = clampPillWindowToMonitor({
      windowTopLeftLogical: { x: -50, y: -50 },
      pillW, pillH, margin, monitorBounds,
    });
    expect(result).toEqual({ x: -6, y: -6 });
  });
});

describe("computeCapsuleMenuGeometry", () => {
  const base = {
    idleTopLeftLogical: { x: 1700, y: 400 },
    idlePillBoxW: 180, // PILL_DIMS.capsule.w(168) + margin*2
    idlePillBoxH: 48,  // PILL_DIMS.capsule.h(36) + margin*2
    margin: 6,
    capsuleOpenW: 300,
    closePadW: 64,
  };

  it("near-right: pins the window's right edge to the idle pill's right edge", () => {
    const { windowTopLeftLogical, windowW, windowH } = computeCapsuleMenuGeometry({
      ...base,
      nearEdge: "right",
    });
    const idleRight = base.idleTopLeftLogical.x + base.idlePillBoxW;
    expect(windowTopLeftLogical.x + windowW).toBe(idleRight);
    expect(windowTopLeftLogical.y).toBe(base.idleTopLeftLogical.y);
    expect(windowH).toBe(base.idlePillBoxH);
  });

  it("near-left: pins the window's left edge to the idle pill's left edge", () => {
    const { windowTopLeftLogical } = computeCapsuleMenuGeometry({
      ...base,
      nearEdge: "left",
    });
    expect(windowTopLeftLogical.x).toBe(base.idleTopLeftLogical.x);
    expect(windowTopLeftLogical.y).toBe(base.idleTopLeftLogical.y);
  });

  it("window width equals open bar + margins + close padding", () => {
    const { windowW } = computeCapsuleMenuGeometry({ ...base, nearEdge: "left" });
    expect(windowW).toBe(base.capsuleOpenW + base.margin * 2 + base.closePadW);
  });
});
