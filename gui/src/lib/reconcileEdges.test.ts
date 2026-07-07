import { describe, expect, it } from "vitest";
import { computeReconcileEdges, type ReconcileEdgeInputs } from "./reconcileEdges";

// Steady-state baseline: idle pill in capsule mode, nothing open, no edges.
const base: ReconcileEdgeInputs = {
  displayMode: "capsule",
  prevDisplayMode: "capsule",
  showPill: true,
  prevShowPill: true,
  menuOpen: false,
  prevMenuOpen: false,
  compactPanel: null,
  prevCompactPanel: null,
  fullSizeInitialized: true,
};

function edges(overrides: Partial<ReconcileEdgeInputs>) {
  return computeReconcileEdges({ ...base, ...overrides });
}

describe("computeReconcileEdges", () => {
  it("fires no edges in steady pill state", () => {
    const e = edges({});
    expect(e.leavingPill).toBe(false);
    expect(e.enteringPill).toBe(false);
    expect(e.openingMenu).toBe(false);
    expect(e.closingMenu).toBe(false);
    expect(e.openingPanel).toBe(false);
    expect(e.closingPanel).toBe(false);
    expect(e.panelModeSwitch).toBe(false);
    expect(e.shouldInitFullSize).toBe(false);
    expect(e.pillModeActive).toBe(true);
  });

  describe("leavingPill (Bug A regression)", () => {
    it("fires when compact Settings picks Full — displayMode and showPill flip together", () => {
      // The regression: pillModeActive is already false in this render; the
      // old gate (pillModeActive && ...) dropped the edge and stranded a lone
      // pill in the grown transparent window.
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "capsule",
        showPill: false,
        prevShowPill: true,
      });
      expect(e.leavingPill).toBe(true);
      expect(e.enteringPill).toBe(false);
      expect(e.enteringFullMode).toBe(true);
      expect(e.shouldInitFullSize).toBe(true);
    });

    it("fires from minimal too", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "minimal",
        showPill: false,
        prevShowPill: true,
      });
      expect(e.leavingPill).toBe(true);
    });

    it("still fires on the classic pill->full path (showPill flips first, mode still compact)", () => {
      const e = edges({ showPill: false, prevShowPill: true });
      expect(e.leavingPill).toBe(true);
    });

    it("cannot re-fire in steady full mode (prevShowPill already false)", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "full",
        showPill: false,
        prevShowPill: false,
      });
      expect(e.leavingPill).toBe(false);
    });
  });

  describe("enteringPill", () => {
    it("fires on full -> pill", () => {
      const e = edges({
        displayMode: "capsule",
        prevDisplayMode: "full",
        showPill: true,
        prevShowPill: false,
      });
      expect(e.enteringPill).toBe(true);
      expect(e.leavingPill).toBe(false);
    });

    it("requires pill mode — no edge while displayMode is full", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "full",
        showPill: true,
        prevShowPill: false,
      });
      expect(e.enteringPill).toBe(false);
    });
  });

  describe("menu edges", () => {
    it("openingMenu on menuOpen rising edge with pill shown", () => {
      const e = edges({ menuOpen: true, prevMenuOpen: false });
      expect(e.openingMenu).toBe(true);
      expect(e.closingMenu).toBe(false);
    });

    it("closingMenu on menuOpen falling edge with no panel involved", () => {
      const e = edges({ menuOpen: false, prevMenuOpen: true });
      expect(e.closingMenu).toBe(true);
    });

    it("closingMenu suppressed when a panel was open (combined close is closingPanel's)", () => {
      const e = edges({
        menuOpen: false,
        prevMenuOpen: true,
        compactPanel: null,
        prevCompactPanel: "settings",
      });
      expect(e.closingMenu).toBe(false);
      expect(e.closingPanel).toBe(true);
    });

    it("no menu edges while pill hidden", () => {
      const e = edges({ showPill: false, prevShowPill: false, menuOpen: true, prevMenuOpen: false });
      expect(e.openingMenu).toBe(false);
    });
  });

  describe("panel edges", () => {
    it("openingPanel on compactPanel null -> non-null", () => {
      const e = edges({ compactPanel: "settings", prevCompactPanel: null });
      expect(e.openingPanel).toBe(true);
      expect(e.closingPanel).toBe(false);
    });

    it("closingPanel on compactPanel non-null -> null", () => {
      const e = edges({ compactPanel: null, prevCompactPanel: "settings" });
      expect(e.closingPanel).toBe(true);
      expect(e.openingPanel).toBe(false);
    });

    it("no panel edges when panel target merely changes (non-null -> non-null)", () => {
      const e = edges({ compactPanel: "inbox", prevCompactPanel: "settings" });
      expect(e.openingPanel).toBe(false);
      expect(e.closingPanel).toBe(false);
    });
  });

  describe("panelModeSwitch", () => {
    it("fires only on capsule <-> minimal with a panel open", () => {
      const capsuleToMinimal = edges({
        displayMode: "minimal",
        prevDisplayMode: "capsule",
        compactPanel: "settings",
        prevCompactPanel: "settings",
      });
      expect(capsuleToMinimal.panelModeSwitch).toBe(true);

      const minimalToCapsule = edges({
        displayMode: "capsule",
        prevDisplayMode: "minimal",
        compactPanel: "settings",
        prevCompactPanel: "settings",
      });
      expect(minimalToCapsule.panelModeSwitch).toBe(true);
    });

    it("does not fire without a panel open", () => {
      const e = edges({ displayMode: "minimal", prevDisplayMode: "capsule" });
      expect(e.panelModeSwitch).toBe(false);
    });

    it("does not fire when the previous mode was full", () => {
      const e = edges({
        displayMode: "capsule",
        prevDisplayMode: "full",
        showPill: true,
        prevShowPill: true,
        compactPanel: "settings",
        prevCompactPanel: "settings",
      });
      expect(e.panelModeSwitch).toBe(false);
    });

    it("does not fire when the mode did not change", () => {
      const e = edges({ compactPanel: "settings", prevCompactPanel: "settings" });
      expect(e.panelModeSwitch).toBe(false);
    });
  });

  describe("shouldInitFullSize", () => {
    it("true on entering full mode even if previously initialized", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "capsule",
        showPill: false,
        prevShowPill: false,
        fullSizeInitialized: true,
      });
      expect(e.shouldInitFullSize).toBe(true);
    });

    it("true in full mode when never initialized", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "full",
        showPill: false,
        prevShowPill: false,
        fullSizeInitialized: false,
      });
      expect(e.shouldInitFullSize).toBe(true);
    });

    it("false in steady initialized full mode", () => {
      const e = edges({
        displayMode: "full",
        prevDisplayMode: "full",
        showPill: false,
        prevShowPill: false,
        fullSizeInitialized: true,
      });
      expect(e.shouldInitFullSize).toBe(false);
    });
  });
});
