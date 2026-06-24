import { describe, expect, it } from "vitest";
import { computeMenuGeometry, clampPillWindowToMonitor, computeCapsuleMenuGeometry, computeProportionalMonitorMove, computeMinimalMenuWindow } from "./menuGeometry";

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

describe("computeProportionalMonitorMove", () => {
  const winW = 48, winH = 48;

  it("centre stays at the new monitor's centre when the old position was dead-center", () => {
    const oldWorkArea = { x: 0, y: 0, w: 1920, h: 1080 };
    const newWorkArea = { x: 2000, y: 0, w: 1280, h: 720 };
    const oldCenterLogical = { x: 960, y: 540 }; // exact center of oldWorkArea
    const result = computeProportionalMonitorMove({ oldCenterLogical, oldWorkArea, newWorkArea, winW, winH });
    // new center = (2000+640, 360) = (2640, 360); window top-left = center - win/2
    expect(result).toEqual({ x: 2640 - winW / 2, y: 360 - winH / 2 });
  });

  it("preserves a corner-ish proportional offset across differently-sized monitors", () => {
    const oldWorkArea = { x: 0, y: 0, w: 1920, h: 1080 };
    const newWorkArea = { x: 2000, y: 100, w: 960, h: 540 };
    // 25% of the way from center to the right/bottom edge on the old monitor
    const oldCenterLogical = { x: 960 + 0.25 * 960, y: 540 + 0.25 * 540 };
    const result = computeProportionalMonitorMove({ oldCenterLogical, oldWorkArea, newWorkArea, winW, winH });
    const newCenterX = 2000 + 480, newCenterY = 100 + 270;
    const expectedCenterX = newCenterX + 0.25 * 480;
    const expectedCenterY = newCenterY + 0.25 * 270;
    expect(result.x).toBe(Math.round(expectedCenterX - winW / 2));
    expect(result.y).toBe(Math.round(expectedCenterY - winH / 2));
  });

  it("clamps fully inside the new monitor when the new monitor is too small for the proportional offset", () => {
    const oldWorkArea = { x: 0, y: 0, w: 1920, h: 1080 };
    const newWorkArea = { x: 0, y: 0, w: 200, h: 200 };
    // far toward the old monitor's right/bottom edge
    const oldCenterLogical = { x: 1900, y: 1060 };
    const result = computeProportionalMonitorMove({ oldCenterLogical, oldWorkArea, newWorkArea, winW, winH });
    // window must stay fully inside [0, 200]
    expect(result.x).toBeLessThanOrEqual(200 - winW);
    expect(result.y).toBeLessThanOrEqual(200 - winH);
    expect(result.x).toBeGreaterThanOrEqual(0);
    expect(result.y).toBeGreaterThanOrEqual(0);
  });
});

describe("computeMinimalMenuWindow", () => {
  const monitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
  const base = {
    idlePillBoxW: 48,
    idlePillBoxH: 48,
    pillW: 36,
    pillH: 36,
    menuBoxW: 260,
    menuBoxH: 260,
    margin: 6,
    monitorBounds,
  };

  it("closed: window sits exactly at idle top-left, wrapper offset is the margin", () => {
    const idleTopLeftLogical = { x: 500, y: 400 };
    const { windowTopLeftLogical, wrapperOffset } = computeMinimalMenuWindow({
      open: false, idleTopLeftLogical, ...base,
    });
    expect(windowTopLeftLogical).toEqual(idleTopLeftLogical);
    expect(wrapperOffset).toEqual({ x: 6, y: 6 });
  });

  it("open away from any edge: pill center stays fixed, wrapper offset centers it", () => {
    const idleTopLeftLogical = { x: 500, y: 400 };
    const { windowTopLeftLogical, wrapperOffset } = computeMinimalMenuWindow({
      open: true, idleTopLeftLogical, ...base,
    });
    // pillCenter = (524, 424); window centered on it = (524-130, 424-130)
    expect(windowTopLeftLogical).toEqual({ x: 394, y: 294 });
    const pillCenter = { x: windowTopLeftLogical.x + wrapperOffset.x + base.pillW / 2, y: windowTopLeftLogical.y + wrapperOffset.y + base.pillH / 2 };
    expect(pillCenter.x).toBeCloseTo(524, 5);
    expect(pillCenter.y).toBeCloseTo(424, 5);
  });

  it("open near a corner: window clamps but wrapper offset keeps the pill center unchanged", () => {
    const idleTopLeftLogical = { x: 2, y: 2 };
    const { windowTopLeftLogical, wrapperOffset } = computeMinimalMenuWindow({
      open: true, idleTopLeftLogical, ...base,
    });
    expect(windowTopLeftLogical.x).toBeGreaterThanOrEqual(0);
    expect(windowTopLeftLogical.y).toBeGreaterThanOrEqual(0);
    const pillCenter = { x: windowTopLeftLogical.x + wrapperOffset.x + base.pillW / 2, y: windowTopLeftLogical.y + wrapperOffset.y + base.pillH / 2 };
    expect(pillCenter.x).toBeCloseTo(2 + base.idlePillBoxW / 2, 5);
    expect(pillCenter.y).toBeCloseTo(2 + base.idlePillBoxH / 2, 5);
  });

  it("round-trips: open then closed returns the exact original idle top-left, including at edges", () => {
    for (const idleTopLeftLogical of [{ x: 500, y: 400 }, { x: 0, y: 0 }, { x: 1900, y: 1050 }, { x: -5, y: -5 }]) {
      const opened = computeMinimalMenuWindow({ open: true, idleTopLeftLogical, ...base });
      const closed = computeMinimalMenuWindow({ open: false, idleTopLeftLogical, ...base });
      expect(closed.windowTopLeftLogical).toEqual(idleTopLeftLogical);
      expect(opened).toBeTruthy();
    }
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

  // for_sonnet.md §3 acceptance: App.tsx's closingMenu/capsule branch uses
  // the stored idle top-left directly as its close target (not
  // computeMenuGeometry's re-center math) — so open and close share the
  // exact same pinned-edge x for either nearEdge, with no jump between them.
  it.each(["left", "right"] as const)(
    "open-top-left and close-top-left (the idle top-left) share the pinned edge x (nearEdge=%s)",
    (nearEdge) => {
      const open = computeCapsuleMenuGeometry({ ...base, nearEdge });
      const closeTarget = base.idleTopLeftLogical; // App.tsx's actual close target
      if (nearEdge === "left") {
        expect(open.windowTopLeftLogical.x).toBe(closeTarget.x);
      } else {
        expect(open.windowTopLeftLogical.x + open.windowW).toBe(closeTarget.x + base.idlePillBoxW);
      }
    },
  );
});
