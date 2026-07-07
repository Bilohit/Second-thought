// Pure decision helpers for the pill reconcile effect's apply() (App.tsx).
// Mirrors reconcileEdges.ts's role: App owns every ref read, every Tauri call,
// and every setState commit; these functions only derive a value from the
// inputs handed to them, so the *decision* of what apply() is about to do is
// unit-testable without a DOM or a live Tauri window.
//
// Deliberately NOT extracted: the geometry math itself (anchorPosition,
// computeCapsuleMenuGeometry, computeMinimalMenuWindow, computeCapsulePanelGeometry,
// computeIslandMorphRects, clampPillWindowToMonitor, ...) already lives in
// menuGeometry.ts/compactPanel.ts/pillAnchor.ts and is already pure+tested there.
// What's left inside apply() itself is (a) which of those branches fires, given
// the edge flags reconcileEdges.ts already computed, and (b) a couple of small
// timing/growth decisions — both pure, both extracted here. Everything else in
// apply() — live scaleFactor()/outerPosition() reads, setWindowBoundsAtomic,
// setState calls — stays in App.tsx by design; it is genuine side effect, not
// computation.

import type { ReconcileDisplayMode } from "./reconcileEdges";
import type { PillAnchor } from "./pillAnchor";

/** Pure: "expanding" vs "shrinking" classification for the content-hide timing
 *  decision above apply() — expanding out of the pill always counts as growing
 *  (no outgoing full-size content to protect from shearing yet). */
export function computeGrowing(i: {
  leavingPill: boolean;
  targetWinH: number;
  prevH: number;
}): boolean {
  return i.leavingPill || i.targetWinH >= i.prevH;
}

export interface MoveTimingInputs {
  closingMenu: boolean;
  closingPanel: boolean;
  displayMode: ReconcileDisplayMode;
  openingMenu: boolean;
  openingPanel: boolean;
  panelModeSwitch: boolean;
  /** CAPSULE_EXIT_MS */
  capsuleExitMs: number;
  /** RADIAL_EXIT_DURATION_MS */
  radialExitMs: number;
  /** PANEL_EXIT_MS */
  panelExitMs: number;
}

export interface MoveTiming {
  preMoveDelayMs: number;
  moveKind: "instant" | "animate";
}

/** Pure: how long to hold the pre-existing (full) window size before the OS
 *  move actually happens, and whether that move should be an instant snap vs
 *  an animated tween — both derived only from which edges fired and the
 *  current display mode. */
export function computeMoveTiming(i: MoveTimingInputs): MoveTiming {
  const preMoveDelayMs =
    i.closingMenu && i.displayMode === "capsule" ? i.capsuleExitMs :
    i.closingMenu && i.displayMode === "minimal" ? i.radialExitMs :
    i.closingPanel ? i.panelExitMs : 0;
  const moveKind: "instant" | "animate" =
    i.openingMenu || i.closingMenu || i.openingPanel || i.closingPanel || i.panelModeSwitch
      ? "instant" : "animate";
  return { preMoveDelayMs, moveKind };
}

/**
 * Which of apply()'s reposition branches should run this pass. This is
 * exactly the condition ladder that used to gate the `if (...) targetPos = ...
 * else if (...) ... else if (...) ...` chain in App.tsx — pulled out as a
 * discriminant so App.tsx can `switch` on it (bodies unchanged, still full of
 * live Tauri reads and setState calls) while the *choice itself* gets a
 * regression suite here.
 */
export type ApplyBranch =
  | "skip-full"             // full mode, already initialized, not (re-)entering — apply() no-ops
  | "anchored"               // fixed anchor, no menu edge in flight — snap to anchorPosition
  | "restore-enter-pill"     // full -> pill with a saved pre-panel position to restore
  | "leaving-pill-center"    // pill -> full — center in the work area
  | "opening-menu-minimal"   // radial fan growing out of a minimal pill
  | "opening-menu-capsule"   // capsule bar growing open
  | "closing-menu"           // menu/capsule collapsing back to the idle pill
  | "opening-panel"          // compact panel opening, or a capsule<->minimal switch with one open
  | "closing-panel"          // compact panel closing
  | "plain-pill-resize"      // custom-anchor pill resizing in place (e.g. minimal -> capsule)
  | "none";                  // nothing this pass — targetPos stays wherever it already was

export interface ApplyBranchInputs {
  displayMode: ReconcileDisplayMode;
  shouldInitFullSize: boolean;
  pillAnchor: PillAnchor;
  openingMenu: boolean;
  closingMenu: boolean;
  openingPanel: boolean;
  closingPanel: boolean;
  panelModeSwitch: boolean;
  enteringPill: boolean;
  leavingPill: boolean;
  /** prePanelPos.current !== null, read at the same point apply() used to. */
  hasPrePanelPos: boolean;
  showPill: boolean;
  prevShowPill: boolean;
  targetWinW: number;
  targetWinH: number;
  prevW: number;
  prevH: number;
}

export function computeApplyBranch(i: ApplyBranchInputs): ApplyBranch {
  if (i.displayMode === "full" && !i.shouldInitFullSize) return "skip-full";

  if (i.pillAnchor !== "custom" && !i.openingMenu && !i.closingMenu) return "anchored";
  if (i.enteringPill && i.hasPrePanelPos) return "restore-enter-pill";
  if (i.leavingPill) return "leaving-pill-center";
  if (i.openingMenu && i.displayMode === "minimal") return "opening-menu-minimal";
  if (i.openingMenu) return "opening-menu-capsule";
  if (i.closingMenu) return "closing-menu";
  if (i.openingPanel || i.panelModeSwitch) return "opening-panel";
  if (i.closingPanel) return "closing-panel";
  if (
    i.pillAnchor === "custom" && i.showPill && i.prevShowPill &&
    !i.openingMenu && !i.closingMenu && !i.openingPanel && !i.closingPanel &&
    !i.enteringPill && !i.leavingPill &&
    (i.targetWinW !== i.prevW || i.targetWinH !== i.prevH)
  ) return "plain-pill-resize";

  return "none";
}
