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
  computePanelWindowBox,
  type Point,
  type MonitorBounds,
} from "./compactPanel";
import { CAPSULE_OPEN_W } from "../components/PillMenu/CapsuleMenu";

describe("constants", () => {
  it("exports the agreed panel constants", () => {
    expect(PANEL_W).toBe(288);
    expect(PANEL_H).toBe(320);
    expect(PANEL_GAP).toBe(0);
    expect(PANEL_ANIM_MS).toBe(300);
    expect(PANEL_EXIT_MS).toBe(360);
  });

  it("PANEL_W equals CAPSULE_OPEN_W", () => {
    expect(PANEL_W).toBe(CAPSULE_OPEN_W);
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
    // These pre-existing cases test the vertical/clamp mechanics generically,
    // not RC-2's near-edge pinning — "left" reproduces the prior unconditional
    // windowX = idleTopLeftLogical.x behavior (see the two horizontal-clamp
    // cases below, updated for the corrected — no-margin-inset — bar offset).
    nearEdge: "left" as const,
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
    expect(result.panelOffsetX).toBe(result.barOffsetX);
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
    expect(result.panelOffsetX).toBe(result.barOffsetX);
  });

  it("middle zone (Task 2.2): the middle-float variant is deleted — resolveVerticalZone's "
    + "\"middle\" classification maps to top-zone geometry at the call site, not a distinct shape",
  () => {
    const idleTopLeftLogical = { x: 500, y: 500 };
    // A pill at the work area's vertical midpoint resolves to "middle"...
    const resolved = resolveVerticalZone(500, { y: 0, h: 1000 });
    expect(resolved).toBe("middle");

    // ...which the caller maps to "top" before calling
    // computeCapsulePanelGeometry (its `zone` param no longer accepts
    // "middle" at all — see PanelExtrudeZone).
    const mapped = resolved === "middle" ? "top" : resolved;
    const middleMappedResult = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical, zone: mapped });
    const topResult = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical, zone: "top" });

    expect(middleMappedResult).toEqual(topResult);
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

    // RC-2 fix: "left" nearEdge pins the bar flush at the window's x (offset
    // 0), not inset by `margin` — the old margin inset here was itself the
    // latent 6px left-zone jump RC-2 documents, not a real invariant.
    const idleBarX = idleTopLeftLogical.x;
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

    const idleBarX = idleTopLeftLogical.x;
    const barScreenX = result.windowTopLeftLogical.x + result.barOffsetX;
    expect(barScreenX).toBe(idleBarX);
  });
});

describe("computeCapsulePanelGeometry near-edge pinning (RC-2)", () => {
  const base = {
    idlePillBoxW: 166, idlePillBoxH: 48, barH: 36,
    panelW: 288, panelH: 320, gap: 0, margin: 6,
    zone: "top" as const, minW: 364,
    monitorBounds: { x: 0, y: 0, w: 1920, h: 1080 },
  };
  const menuWinW = 364; // CAPSULE_OPEN_W + 2*margin + CLOSE_PAD_W

  it("right zone: bar keeps its menu-open screen x (no +128px jump)", () => {
    const idle = { x: 1400, y: 200 };
    const menuWinX = idle.x + 166 - menuWinW;            // 1202
    const barScreenXOpen = menuWinX + (menuWinW - 288);  // 1278 (flex-end)
    const g = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical: idle, nearEdge: "right" });
    expect(g.windowTopLeftLogical.x + g.barOffsetX).toBe(barScreenXOpen);
    expect(g.windowTopLeftLogical.x + g.panelOffsetX).toBe(barScreenXOpen); // panel under bar
    expect(g.windowW).toBe(364);
  });

  it("center zone: bar keeps its centered menu-open screen x (no +99px window jump)", () => {
    const idle = { x: 800, y: 500 };
    const menuWinX = idle.x + 166 / 2 - menuWinW / 2;         // 701
    const barScreenXOpen = menuWinX + (menuWinW - 288) / 2;   // 739
    const g = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical: idle, nearEdge: "center" });
    expect(g.windowTopLeftLogical.x + g.barOffsetX).toBe(barScreenXOpen);
  });

  it("left zone: bar sits flush at the window edge, matching flex-start (kills latent 6px jump)", () => {
    const idle = { x: 100, y: 200 };
    const g = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical: idle, nearEdge: "left" });
    expect(g.windowTopLeftLogical.x).toBe(100);
    expect(g.barOffsetX).toBe(0);
  });

  it("bottom zone + right edge: vertical formula unchanged, bar screen y preserved", () => {
    const idle = { x: 1400, y: 900 };
    const g = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical: idle, nearEdge: "right", zone: "bottom" });
    expect(g.windowTopLeftLogical.y + g.barOffsetY).toBe(idle.y + 6); // barY invariant
  });

  it("monitor clamp still absorbs into offsets (bar fixed under clamp)", () => {
    // idle near the LEFT monitor edge so the right-zone pinned window would
    // overflow past x=0.
    //
    // Re-derivation note (per the brief's own flag): the brief's original
    // fixture asserted the clamped bar offset via a formula whose two
    // `(menuWinW - 288)` terms cancel unconditionally, so it happened to
    // still evaluate to the right number — but that's an accident of
    // arithmetic, not a derivation. Numerically re-checked here against the
    // OLD implementation (windowX always = idleTopLeftLogical.x,
    // barOffsetXUnclamped always = margin, no nearEdge concept): for
    // idle=(10,200) the OLD code's windowX (10) never overhangs the monitor
    // (windowW=364, monitor 1920 wide) so it never clamps at all — old
    // result: windowX=10, barScreenX=10+6=16. That's a real, large
    // divergence from the correct right-pinned value below (128px, matching
    // RC-2's documented right-zone jump), so this fixture does certify the
    // fix: it fails against the old code and passes against the new one.
    const idle = { x: 10, y: 200 };
    const menuWinX = idle.x + 166 - menuWinW; // -188 (would overhang left of the monitor)
    const barScreenXOpen = menuWinX + (menuWinW - 288); // -112
    const g = computeCapsulePanelGeometry({ ...base, idleTopLeftLogical: idle, nearEdge: "right" });
    // window would sit at 10+166-364 = -188 → clamps to 0; bar offset absorbs the delta
    expect(g.windowTopLeftLogical.x).toBe(0);
    expect(g.windowTopLeftLogical.x + g.barOffsetX).toBe(barScreenXOpen);
  });
});

describe("computePanelWindowBox (Task 0.1: single source of truth)", () => {
  const capsuleMonitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
  const capsuleBase = {
    idlePillBoxW: 240,
    idlePillBoxH: 44,
    barH: 44,
    panelW: PANEL_W,
    panelH: PANEL_H,
    gap: PANEL_GAP,
    margin: 8,
    monitorBounds: capsuleMonitorBounds,
    nearEdge: "left" as const,
  };

  (["top", "bottom"] as const).forEach((zone) => {
    it(`capsule mode, ${zone} zone: matches computeCapsulePanelGeometry's windowW/H (no clamping)`, () => {
      const idleTopLeftLogical = { x: 500, y: 500 };
      const geometry = computeCapsulePanelGeometry({
        ...capsuleBase,
        idleTopLeftLogical,
        zone,
      });

      const box = computePanelWindowBox({
        mode: "capsule",
        zone,
        pillBoxW: capsuleBase.idlePillBoxW,
        pillBoxH: capsuleBase.idlePillBoxH,
        barH: capsuleBase.barH,
        margin: capsuleBase.margin,
      });

      expect(box.w).toBe(geometry.windowW);
      expect(box.h).toBe(geometry.windowH);
    });
  });

  it("minimal mode: matches computeIslandMorphRects's windowW/H (no clamping)", () => {
    const minimalMonitorBounds = { x: 0, y: 0, w: 1920, h: 1080 };
    const pillTopLeftLogical = { x: 942, y: 522 }; // roughly centered, no clamp
    const morph = computeIslandMorphRects({
      pillTopLeftLogical,
      pillW: 36,
      pillH: 36,
      panelW: PANEL_W,
      panelH: PANEL_H,
      margin: 8,
      monitorBounds: minimalMonitorBounds,
    });

    const box = computePanelWindowBox({
      mode: "minimal",
      zone: "top", // ignored for minimal
      pillBoxW: 36,
      pillBoxH: 36,
      barH: 0,
      margin: 8,
    });

    expect(box.w).toBe(morph.windowW);
    expect(box.h).toBe(morph.windowH);
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

  it("grown window stays fully inside monitorBounds (no margin overhang)", () => {
    const pillTopLeftLogical = {
      x: monitorBounds.x + monitorBounds.w - base.pillW,
      y: monitorBounds.y + monitorBounds.h - base.pillH,
    };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    expect(result.windowTopLeftLogical.x).toBeGreaterThanOrEqual(monitorBounds.x);
    expect(result.windowTopLeftLogical.y).toBeGreaterThanOrEqual(monitorBounds.y);
    expect(result.windowTopLeftLogical.x + result.windowW).toBeLessThanOrEqual(monitorBounds.x + monitorBounds.w);
    expect(result.windowTopLeftLogical.y + result.windowH).toBeLessThanOrEqual(monitorBounds.y + monitorBounds.h);
  });

  it("pill flush at the true monitor LEFT edge (x = monitorBounds.x, zero margin gap): containment-expansion pass kicks in", () => {
    // Task 3.1: distinct from the bottom-right/TRUE-corner case above — this
    // exercises the containment-expansion pass (compactPanel.ts ~266-272) on
    // the x axis specifically, anchored at the monitor's left edge rather
    // than a corner, with a mid-screen y so only the x axis is forced.
    const pillTopLeftLogical = { x: monitorBounds.x, y: 500 };
    const result = computeIslandMorphRects({ ...base, pillTopLeftLogical });

    // Without the expansion pass, the margin-inset clamp alone would place
    // endRect.x at monitorBounds.x + margin, which would NOT contain a pill
    // sitting flush at monitorBounds.x (zero margin gap) — confirm the
    // expansion pulled endRect.x back to (or past) the pill's own x.
    expect(result.endRect.x).toBeLessThanOrEqual(pillTopLeftLogical.x);

    expect(result.startRect).toEqual({
      x: pillTopLeftLogical.x,
      y: pillTopLeftLogical.y,
      w: base.pillW,
      h: base.pillH,
    });
    expect(result.startRect.x).toBeGreaterThanOrEqual(result.endRect.x);
    expect(result.startRect.y).toBeGreaterThanOrEqual(result.endRect.y);
    expect(result.startRect.x + result.startRect.w).toBeLessThanOrEqual(result.endRect.x + result.endRect.w);
    expect(result.startRect.y + result.startRect.h).toBeLessThanOrEqual(result.endRect.y + result.endRect.h);
    expect(result.endRect.x).toBeGreaterThanOrEqual(monitorBounds.x);
    expect(result.endRect.y).toBeGreaterThanOrEqual(monitorBounds.y);
    expect(result.endRect.x + result.endRect.w).toBeLessThanOrEqual(monitorBounds.x + monitorBounds.w);
    expect(result.endRect.y + result.endRect.h).toBeLessThanOrEqual(monitorBounds.y + monitorBounds.h);
  });
});

describe("computeIslandMorphRects (Task 3.1: exhaustive edge-position invariants)", () => {
  // Work area matches the plan's exact spec: 1920x1032, margin 6. Pill size
  // is arbitrary (kept consistent with the rest of this file's 36x36 pill).
  const monitorBounds = { x: 0, y: 0, w: 1920, h: 1032 };
  const margin = 6;
  const pillW = 36;
  const pillH = 36;
  const panelW = PANEL_W;
  const panelH = PANEL_H;

  /**
   * The four GATE-2 invariants this whole task exists to pin down:
   *  1. startRect strictly equals the input pill rect (zero-drift contract).
   *  2. endRect fully inside monitorBounds.
   *  3. startRect fully contained in endRect.
   *  4. pillOffset consistency: windowTopLeft + pillOffset === startRect origin.
   */
  function assertInvariants(
    result: ReturnType<typeof computeIslandMorphRects>,
    pillTopLeftLogical: Point,
    bounds: MonitorBounds
  ) {
    // 1. zero-drift contract
    expect(result.startRect).toEqual({ x: pillTopLeftLogical.x, y: pillTopLeftLogical.y, w: pillW, h: pillH });

    // 2. endRect fully inside monitorBounds
    expect(result.endRect.x).toBeGreaterThanOrEqual(bounds.x);
    expect(result.endRect.y).toBeGreaterThanOrEqual(bounds.y);
    expect(result.endRect.x + result.endRect.w).toBeLessThanOrEqual(bounds.x + bounds.w);
    expect(result.endRect.y + result.endRect.h).toBeLessThanOrEqual(bounds.y + bounds.h);

    // 3. startRect fully contained in endRect
    expect(result.startRect.x).toBeGreaterThanOrEqual(result.endRect.x);
    expect(result.startRect.y).toBeGreaterThanOrEqual(result.endRect.y);
    expect(result.startRect.x + result.startRect.w).toBeLessThanOrEqual(result.endRect.x + result.endRect.w);
    expect(result.startRect.y + result.startRect.h).toBeLessThanOrEqual(result.endRect.y + result.endRect.h);

    // 4. pillOffset consistency
    expect(result.windowTopLeftLogical.x + result.pillOffset.x).toBeCloseTo(result.startRect.x, 5);
    expect(result.windowTopLeftLogical.y + result.pillOffset.y).toBeCloseTo(result.startRect.y, 5);
  }

  const maxPillX = monitorBounds.x + monitorBounds.w - pillW;
  const maxPillY = monitorBounds.y + monitorBounds.h - pillH;
  const midPillX = monitorBounds.x + (monitorBounds.w - pillW) / 2;
  const midPillY = monitorBounds.y + (monitorBounds.h - pillH) / 2;

  const positions: Record<string, Point> = {
    "top-left corner": { x: monitorBounds.x, y: monitorBounds.y },
    "top-right corner": { x: maxPillX, y: monitorBounds.y },
    "bottom-left corner": { x: monitorBounds.x, y: maxPillY },
    "bottom-right corner": { x: maxPillX, y: maxPillY },
    "top-edge midpoint": { x: midPillX, y: monitorBounds.y },
    "bottom-edge midpoint": { x: midPillX, y: maxPillY },
    "left-edge midpoint": { x: monitorBounds.x, y: midPillY },
    "right-edge midpoint": { x: maxPillX, y: midPillY },
    center: { x: midPillX, y: midPillY },
  };

  Object.entries(positions).forEach(([label, pillTopLeftLogical]) => {
    it(`9-position matrix: ${label} satisfies all four invariants`, () => {
      const result = computeIslandMorphRects({
        pillTopLeftLogical,
        pillW,
        pillH,
        panelW,
        panelH,
        margin,
        monitorBounds,
      });
      assertInvariants(result, pillTopLeftLogical, monitorBounds);
    });
  });

  /**
   * Tiny inline LCG (Numerical Recipes constants) — no dependency, fixed
   * seed so any failure reproduces deterministically. Returns floats in
   * [0, 1), matching Math.random()'s contract closely enough for a uniform
   * sweep over the work area.
   */
  function makeLcg(seed: number) {
    let state = seed >>> 0;
    return () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 0x100000000;
    };
  }

  it("seeded pseudo-random sweep: 100 uniform pill positions all satisfy the four invariants", () => {
    const rand = makeLcg(0xc0ffee);

    for (let i = 0; i < 100; i++) {
      const pillTopLeftLogical: Point = {
        x: monitorBounds.x + rand() * (monitorBounds.w - pillW),
        y: monitorBounds.y + rand() * (monitorBounds.h - pillH),
      };

      const result = computeIslandMorphRects({
        pillTopLeftLogical,
        pillW,
        pillH,
        panelW,
        panelH,
        margin,
        monitorBounds,
      });

      assertInvariants(result, pillTopLeftLogical, monitorBounds);
    }
  });
});
