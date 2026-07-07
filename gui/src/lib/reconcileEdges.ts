// Pure edge truth-table for the pill reconcile effect (App.tsx). Extracted so
// the compact->full regression (leavingPill) is unit-testable without a DOM.
// App owns every ref read and commit; this function only derives booleans from
// the values passed in.

export type ReconcileDisplayMode = "full" | "capsule" | "minimal";

export interface ReconcileEdgeInputs {
  displayMode: ReconcileDisplayMode;
  prevDisplayMode: ReconcileDisplayMode;
  showPill: boolean;
  prevShowPill: boolean;
  menuOpen: boolean;
  prevMenuOpen: boolean;
  compactPanel: string | null;
  prevCompactPanel: string | null;
  fullSizeInitialized: boolean;
}

export interface ReconcileEdges {
  enteringFullMode: boolean;
  shouldInitFullSize: boolean;
  pillModeActive: boolean;
  leavingPill: boolean;
  enteringPill: boolean;
  openingMenu: boolean;
  closingMenu: boolean;
  openingPanel: boolean;
  closingPanel: boolean;
  panelModeSwitch: boolean;
}

export function computeReconcileEdges(i: ReconcileEdgeInputs): ReconcileEdges {
  const enteringFullMode = i.displayMode === "full" && i.prevDisplayMode !== "full";
  const shouldInitFullSize =
    i.displayMode === "full" && (!i.fullSizeInitialized || enteringFullMode);
  const pillModeActive = i.displayMode !== "full";

  // renderPill/full invariant: the gate is intentionally NOT `pillModeActive &&`.
  // A compact->full switch flips displayMode and showPill in the same render, so
  // pillModeActive is already false; gating on it would drop the edge and strand
  // a lone pill in a grown transparent window (Bug A). Dropping the gate routes
  // compact->full through the tested pill->full expand path. Redundant elsewhere:
  // enteringPill requires showPill (implies non-full), and in steady full mode
  // prevShowPill is false so the edge cannot re-fire.
  const leavingPill = i.prevShowPill && !i.showPill; // pill -> full
  const enteringPill = pillModeActive && !i.prevShowPill && i.showPill; // full -> pill

  const openingMenu =
    pillModeActive && i.showPill && i.prevShowPill && i.menuOpen && !i.prevMenuOpen;

  // prevCompactPanel === null additionally excludes the combined panel+menu
  // close (Esc/click-away with a panel open) — that edge must be handled once,
  // by closingPanel below, not double-fire here too.
  const closingMenu =
    pillModeActive && i.showPill && i.prevShowPill && !i.menuOpen && i.prevMenuOpen &&
    i.compactPanel === null && i.prevCompactPanel === null;

  const openingPanel =
    pillModeActive && i.showPill && i.prevShowPill &&
    i.compactPanel !== null && i.prevCompactPanel === null;
  const closingPanel =
    pillModeActive && i.showPill && i.prevShowPill &&
    i.compactPanel === null && i.prevCompactPanel !== null;
  const panelModeSwitch =
    pillModeActive && i.showPill && i.prevShowPill && i.compactPanel !== null &&
    i.prevDisplayMode !== i.displayMode && i.prevDisplayMode !== "full";

  return {
    enteringFullMode, shouldInitFullSize, pillModeActive, leavingPill, enteringPill,
    openingMenu, closingMenu, openingPanel, closingPanel, panelModeSwitch,
  };
}
