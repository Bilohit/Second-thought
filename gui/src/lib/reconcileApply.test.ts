import { describe, expect, it } from "vitest";
import {
  computeGrowing,
  computeMoveTiming,
  computeApplyBranch,
  type ApplyBranchInputs,
} from "./reconcileApply";

describe("computeGrowing", () => {
  it("is true whenever leavingPill, regardless of height", () => {
    expect(computeGrowing({ leavingPill: true, targetWinH: 10, prevH: 999 })).toBe(true);
  });

  it("is true when the target is taller than or equal to the previous height", () => {
    expect(computeGrowing({ leavingPill: false, targetWinH: 200, prevH: 100 })).toBe(true);
    expect(computeGrowing({ leavingPill: false, targetWinH: 100, prevH: 100 })).toBe(true);
  });

  it("is false when shrinking and not leaving the pill", () => {
    expect(computeGrowing({ leavingPill: false, targetWinH: 80, prevH: 100 })).toBe(false);
  });
});

describe("computeMoveTiming", () => {
  const base = {
    closingMenu: false,
    closingPanel: false,
    displayMode: "capsule" as const,
    openingMenu: false,
    openingPanel: false,
    panelModeSwitch: false,
    capsuleExitMs: 260,
    radialExitMs: 340,
    panelExitMs: 360,
  };

  it("delays by capsuleExitMs when closing the capsule menu", () => {
    const t = computeMoveTiming({ ...base, closingMenu: true, displayMode: "capsule" });
    expect(t.preMoveDelayMs).toBe(260);
    expect(t.moveKind).toBe("instant");
  });

  it("delays by radialExitMs when closing the minimal (radial) menu", () => {
    const t = computeMoveTiming({ ...base, closingMenu: true, displayMode: "minimal" });
    expect(t.preMoveDelayMs).toBe(340);
  });

  it("delays by panelExitMs when closing a panel", () => {
    const t = computeMoveTiming({ ...base, closingPanel: true });
    expect(t.preMoveDelayMs).toBe(360);
    expect(t.moveKind).toBe("instant");
  });

  it("has no delay and animates for a plain move", () => {
    const t = computeMoveTiming(base);
    expect(t.preMoveDelayMs).toBe(0);
    expect(t.moveKind).toBe("animate");
  });

  it("is instant for every opening/closing edge, not just closing ones", () => {
    expect(computeMoveTiming({ ...base, openingMenu: true }).moveKind).toBe("instant");
    expect(computeMoveTiming({ ...base, openingPanel: true }).moveKind).toBe("instant");
    expect(computeMoveTiming({ ...base, panelModeSwitch: true }).moveKind).toBe("instant");
  });
});

describe("computeApplyBranch", () => {
  const base: ApplyBranchInputs = {
    displayMode: "capsule",
    shouldInitFullSize: false,
    pillAnchor: "tl",
    openingMenu: false,
    closingMenu: false,
    openingPanel: false,
    closingPanel: false,
    panelModeSwitch: false,
    enteringPill: false,
    leavingPill: false,
    hasPrePanelPos: false,
    showPill: true,
    prevShowPill: true,
    targetWinW: 100,
    targetWinH: 40,
    prevW: 100,
    prevH: 40,
  };

  function branch(overrides: Partial<ApplyBranchInputs>) {
    return computeApplyBranch({ ...base, ...overrides });
  }

  it("skips full mode once already initialized and not (re-)entering", () => {
    expect(branch({ displayMode: "full", shouldInitFullSize: false })).toBe("skip-full");
  });

  it("does not skip full mode while shouldInitFullSize is true", () => {
    expect(branch({ displayMode: "full", shouldInitFullSize: true })).not.toBe("skip-full");
  });

  it("anchors a fixed-anchor pill with no menu edge in flight", () => {
    expect(branch({ pillAnchor: "tr" })).toBe("anchored");
  });

  it("does not take the anchored branch mid menu open/close even with a fixed anchor", () => {
    expect(branch({ pillAnchor: "tr", openingMenu: true })).not.toBe("anchored");
    expect(branch({ pillAnchor: "tr", closingMenu: true })).not.toBe("anchored");
  });

  it("restores the saved pre-panel position on full -> pill", () => {
    expect(branch({ pillAnchor: "custom", enteringPill: true, hasPrePanelPos: true })).toBe("restore-enter-pill");
  });

  it("falls through past restore-enter-pill when nothing was saved", () => {
    expect(branch({ pillAnchor: "custom", enteringPill: true, hasPrePanelPos: false })).not.toBe("restore-enter-pill");
  });

  it("centers on pill -> full", () => {
    expect(branch({ pillAnchor: "custom", leavingPill: true })).toBe("leaving-pill-center");
  });

  it("distinguishes the minimal vs capsule menu-open branch by displayMode", () => {
    expect(branch({ pillAnchor: "custom", openingMenu: true, displayMode: "minimal" })).toBe("opening-menu-minimal");
    expect(branch({ pillAnchor: "custom", openingMenu: true, displayMode: "capsule" })).toBe("opening-menu-capsule");
  });

  it("takes the closing-menu branch", () => {
    expect(branch({ pillAnchor: "custom", closingMenu: true })).toBe("closing-menu");
  });

  it("takes the opening-panel branch for both openingPanel and panelModeSwitch", () => {
    expect(branch({ pillAnchor: "custom", openingPanel: true })).toBe("opening-panel");
    expect(branch({ pillAnchor: "custom", panelModeSwitch: true })).toBe("opening-panel");
  });

  it("takes the closing-panel branch", () => {
    expect(branch({ pillAnchor: "custom", closingPanel: true })).toBe("closing-panel");
  });

  it("resizes a custom-anchor pill in place when only its size changed", () => {
    expect(branch({ pillAnchor: "custom", targetWinW: 200, prevW: 100 })).toBe("plain-pill-resize");
  });

  it("does not resize when nothing changed", () => {
    expect(branch({ pillAnchor: "custom" })).toBe("none");
  });

  it("does not resize while showPill/prevShowPill disagree (that's an entering/leaving edge instead)", () => {
    expect(branch({ pillAnchor: "custom", showPill: false, targetWinW: 200, prevW: 100 })).toBe("none");
  });
});
