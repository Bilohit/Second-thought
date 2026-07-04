import { describe, expect, it } from "vitest";
import {
  PANEL_W,
  PANEL_H,
  PANEL_GAP,
  PANEL_ANIM_MS,
  PANEL_EXIT_MS,
  resolveVerticalZone,
  computeCapsulePanelGeometry,
  computeIslandMorphRects,
} from "./compactPanel";

describe("constants", () => {
  it("exports the agreed panel constants", () => {
    expect(PANEL_W).toBe(288);
    expect(PANEL_H).toBe(320);
    expect(PANEL_GAP).toBe(0);
    expect(PANEL_ANIM_MS).toBe(300);
    expect(PANEL_EXIT_MS).toBe(360);
  });
});

describe("resolveVerticalZone", () => {
  const workArea = { y: 0, h: 900 };

  it("classifies 10% of work area as top", () => {
    expect(resolveVerticalZone(90, workArea)).toBe("top");
  });

  it("classifies 50% of work area as middle", () => {
    expect(resolveVerticalZone(450, workArea)).toBe("middle");
  });

  it("classifies 90% of work area as bottom", () => {
    expect(resolveVerticalZone(810, workArea)).toBe("bottom");
  });

  it("treats the exact 1/3 boundary as top", () => {
    expect(resolveVerticalZone(300, workArea)).toBe("top");
  });

  it("treats the exact 2/3 boundary as middle", () => {
    expect(resolveVerticalZone(600, workArea)).toBe("middle");
  });

  it("respects a non-zero work area origin", () => {
    const wa = { y: 100, h: 900 };
    expect(resolveVerticalZone(190, wa)).toBe("top"); // 10% of 900 + 100
    expect(resolveVerticalZone(550, wa)).toBe("middle");
    expect(resolveVerticalZone(910, wa)).toBe("bottom");
  });
});

describe("computeCapsulePanelGeometry", () => {
  const monitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
  const base = {
    idlePillBoxW: 240,
    idlePillBoxH: 44,
    barH: 44,
    panelW: PANEL_W,
    panelH: PANEL_H,
    gap: PANEL_GAP,
    margin: 8,
    monitorBounds,
  };

  it("top zone: keeps the bar at its idle on-screen Y and grows downward", () => {
    const idleTopLeftLogical = { x: 500, y: 200 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "top",
    });

    const idleBarY = idleTopLeftLogical.y + base.margin;
    const barScreenY = result.windowTopLeftLogical.y + result.barOffsetY;
    expect(barScreenY).toBe(idleBarY);
    expect(result.windowH).toBe(base.margin + base.barH + base.gap + base.panelH + base.margin);
    expect(result.panelOffsetY).toBe(base.margin + base.barH + base.gap);
  });

  it("bottom zone: window bottom equals bar bottom + margin", () => {
    const idleTopLeftLogical = { x: 500, y: 700 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "bottom",
    });

    const idleBarY = idleTopLeftLogical.y + base.margin;
    const barBottom = idleBarY + base.barH;
    const windowBottom = result.windowTopLeftLogical.y + result.windowH;
    expect(windowBottom).toBe(barBottom + base.margin);

    const barScreenY = result.windowTopLeftLogical.y + result.barOffsetY;
    expect(barScreenY).toBe(idleBarY);
  });

  it("middle zone: bar center coincides with window center", () => {
    const idleTopLeftLogical = { x: 500, y: 500 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "middle",
    });

    const barCenterInWindow = result.barOffsetY + base.barH / 2;
    expect(barCenterInWindow).toBeCloseTo(result.windowH / 2, 5);
  });

  it("top zone clamped at screen bottom: window pulled up, barOffsetY grows by the same delta", () => {
    // Idle bar sits near the very bottom of the monitor so the grown window
    // (bar + gap + panel) would overhang past monitorBounds.h.
    const idleTopLeftLogical = { x: 500, y: 1060 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "top",
    });

    const unclampedWindowY = idleTopLeftLogical.y + base.margin - base.margin; // = idleTopLeftLogical.y
    const unclampedWindowH = base.margin + base.barH + base.gap + base.panelH + base.margin;
    const unclampedBottom = unclampedWindowY + unclampedWindowH;
    const overhang = unclampedBottom - (monitorBounds.y + monitorBounds.h);
    expect(overhang).toBeGreaterThan(0);

    const delta = result.windowTopLeftLogical.y - unclampedWindowY; // negative: pulled up
    expect(delta).toBeLessThan(0);
    expect(result.barOffsetY).toBeCloseTo(base.margin - delta, 5);

    // Bar's absolute screen position is unaffected by the clamp shift.
    const idleBarY = idleTopLeftLogical.y + base.margin;
    const barScreenY = result.windowTopLeftLogical.y + result.barOffsetY;
    expect(barScreenY).toBe(idleBarY);
  });

  it("horizontal clamp near the right edge: bar keeps its on-screen X", () => {
    // idlePillBoxW (240) < panelW + margin*2 (304), so windowW = 304. Placing
    // the idle box near the right edge forces the window to be pulled left,
    // which must not visibly shift the bar sideways.
    const idleTopLeftLogical = { x: 1919 - base.idlePillBoxW, y: 200 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "top",
    });

    const unclampedWindowX = idleTopLeftLogical.x;
    const overhang = unclampedWindowX + result.windowW - (monitorBounds.x + monitorBounds.w);
    expect(overhang).toBeGreaterThan(0);

    const idleBarX = idleTopLeftLogical.x + base.margin;
    const barScreenX = result.windowTopLeftLogical.x + result.barOffsetX;
    expect(barScreenX).toBe(idleBarX);
  });

  it("horizontal clamp near the left edge: bar keeps its on-screen X", () => {
    const idleTopLeftLogical = { x: -50, y: 200 };
    const result = computeCapsulePanelGeometry({
      ...base,
      idleTopLeftLogical,
      zone: "bottom",
    });

    expect(idleTopLeftLogical.x).toBeLessThan(monitorBounds.x);

    const idleBarX = idleTopLeftLogical.x + base.margin;
    const barScreenX = result.windowTopLeftLogical.x + result.barOffsetX;
    expect(barScreenX).toBe(idleBarX);
  });
});

describe("computeIslandMorphRects", () => {
  const monitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
  const base = {
    pillW: 36,
    pillH: 36,
    panelW: PANEL_W,
    panelH: PANEL_H,
    margin: 8,
    monitorBounds,
  };

  it("pill at monitor center: endRect is centered on the pill", () => {
    const pillTopLeftLogical = { x: 942, y: 522 }; // roughly centered
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    const pillCenter = {
      x: pillTopLeftLogical.x + base.pillW / 2,
      y: pillTopLeftLogical.y + base.pillH / 2,
    };
    const endCenter = {
      x: result.endRect.x + result.endRect.w / 2,
      y: result.endRect.y + result.endRect.h / 2,
    };
    expect(endCenter.x).toBeCloseTo(pillCenter.x, 5);
    expect(endCenter.y).toBeCloseTo(pillCenter.y, 5);
  });

  it("pill 10px from right edge: endRect clamps to the right edge, startRect unchanged", () => {
    const pillTopLeftLogical = { x: monitorBounds.w - base.pillW - 10, y: 500 };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    expect(result.endRect.x + result.endRect.w).toBe(monitorBounds.x + monitorBounds.w - base.margin);
    expect(result.startRect).toEqual({
      x: pillTopLeftLogical.x,
      y: pillTopLeftLogical.y,
      w: base.pillW,
      h: base.pillH,
    });
  });

  it("pill in bottom-right corner (margin-inset boundary): both axes clamp, startRect is contained in endRect", () => {
    // Pill sits right at the margin-inset boundary (the same inset the
    // clamped endRect respects) — the worst case that still keeps the pill
    // fully containable within the grown panel.
    const pillTopLeftLogical = {
      x: monitorBounds.w - base.pillW - base.margin,
      y: monitorBounds.h - base.pillH - base.margin,
    };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    expect(result.endRect.x + result.endRect.w).toBe(monitorBounds.x + monitorBounds.w - base.margin);
    expect(result.endRect.y + result.endRect.h).toBe(monitorBounds.y + monitorBounds.h - base.margin);

    expect(result.startRect.x).toBeGreaterThanOrEqual(result.endRect.x);
    expect(result.startRect.y).toBeGreaterThanOrEqual(result.endRect.y);
    expect(result.startRect.x + result.startRect.w).toBeLessThanOrEqual(result.endRect.x + result.endRect.w);
    expect(result.startRect.y + result.startRect.h).toBeLessThanOrEqual(result.endRect.y + result.endRect.h);
  });

  it("pill flush against the TRUE monitor corner (no margin gap): startRect still fully contained in endRect", () => {
    // A legal pill position can overhang the transparent margin entirely,
    // i.e. sit flush against monitorBounds' true edge with zero margin gap.
    // GATE-2 zero-drift contract requires startRect (the pill) to be fully
    // contained in endRect on both axes regardless — otherwise the reverse
    // morph would not land back on the pill.
    const pillTopLeftLogical = {
      x: monitorBounds.x + monitorBounds.w - base.pillW,
      y: monitorBounds.y + monitorBounds.h - base.pillH,
    };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    expect(result.startRect.x).toBeGreaterThanOrEqual(result.endRect.x);
    expect(result.startRect.y).toBeGreaterThanOrEqual(result.endRect.y);
    expect(result.startRect.x + result.startRect.w).toBeLessThanOrEqual(result.endRect.x + result.endRect.w);
    expect(result.startRect.y + result.startRect.h).toBeLessThanOrEqual(result.endRect.y + result.endRect.h);

    expect(result.endRect.x).toBeGreaterThanOrEqual(monitorBounds.x);
    expect(result.endRect.y).toBeGreaterThanOrEqual(monitorBounds.y);
    expect(result.endRect.x + result.endRect.w).toBeLessThanOrEqual(monitorBounds.x + monitorBounds.w);
    expect(result.endRect.y + result.endRect.h).toBeLessThanOrEqual(monitorBounds.y + monitorBounds.h);
  });

  it("pill on a secondary monitor with non-zero origin: endRect stays inside that monitor", () => {
    const secondaryBounds = { x: 1920, y: 0, w: 1920, h: 1080 };
    const pillTopLeftLogical = { x: 1920 + 10, y: 10 };
    const result = computeIslandMorphRects({ ...base, monitorBounds: secondaryBounds, pillTopLeftLogical });

    expect(result.endRect.x).toBeGreaterThanOrEqual(secondaryBounds.x);
    expect(result.endRect.y).toBeGreaterThanOrEqual(secondaryBounds.y);
    expect(result.endRect.x + result.endRect.w).toBeLessThanOrEqual(secondaryBounds.x + secondaryBounds.w);
    expect(result.endRect.y + result.endRect.h).toBeLessThanOrEqual(secondaryBounds.y + secondaryBounds.h);
  });

  it("pillOffset consistency: windowTopLeft + pillOffset === pillTopLeft", () => {
    const pillTopLeftLogical = { x: 300, y: 400 };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    expect(result.windowTopLeftLogical.x + result.pillOffset.x).toBeCloseTo(pillTopLeftLogical.x, 5);
    expect(result.windowTopLeftLogical.y + result.pillOffset.y).toBeCloseTo(pillTopLeftLogical.y, 5);
  });
});
