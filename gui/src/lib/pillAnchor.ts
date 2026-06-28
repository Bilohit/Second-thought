/**
 * pillAnchor.ts
 * -------------
 * Where the pill (Capsule/Minimal Display Mode) sits on screen. "custom"
 * means "don't reposition it" — it stays wherever the window was last
 * dragged/placed, which is the literal behavior of never calling
 * setPosition for that anchor.
 */

import type { WorkArea } from "./monitor";

export type PillAnchor = "tl" | "tc" | "tr" | "lc" | "custom" | "rc" | "bl" | "bc" | "br";

/** Row-major 3x3 order, matching the Settings anchor-grid layout. */
export const ANCHOR_ORDER: PillAnchor[] = ["tl", "tc", "tr", "lc", "custom", "rc", "bl", "bc", "br"];

const MARGIN = 12;

/** Returns the top-left screen position for a pill of size (w, h) at the
 *  given anchor, or null for "custom" (caller should leave the window alone).
 *  Positions are in logical px, relative to the work area's origin (including
 *  its x/y offset for multi-monitor setups). */
export function anchorPosition(anchor: PillAnchor, w: number, h: number, area: WorkArea): { x: number; y: number } | null {
  if (anchor === "custom") return null;

  const x = anchor === "tl" || anchor === "lc" || anchor === "bl" ? area.x + MARGIN
          : anchor === "tc" || anchor === "bc"                    ? area.x + (area.w - w) / 2
          : area.x + area.w - w - MARGIN; // tr | rc | br

  const y = anchor === "tl" || anchor === "tc" || anchor === "tr" ? area.y + MARGIN
          : anchor === "lc" || anchor === "rc"                    ? area.y + (area.h - h) / 2
          : area.y + area.h - h - MARGIN; // bl | bc | br

  return { x: Math.round(x), y: Math.round(y) };
}

/** Position for a pill whose window is `box` sized, honoring a fixed anchor;
 *  returns null for custom (caller keeps live-read/restore path). Used by the
 *  menu open/close reconcile so anchored pills never depend on a live geometry
 *  read (the drift source). */
export function anchoredMenuPosition(
  anchor: PillAnchor, boxW: number, boxH: number, area: WorkArea,
): { x: number; y: number } | null {
  return anchorPosition(anchor, boxW, boxH, area);
}

/** Pill movability matrix (for_sonnet.md Problem 2): only the "custom"
 *  anchor is ever draggable, and only while the menu is closed — an anchored
 *  pill snaps back via `anchorPosition` anyway, and a dragging gesture while
 *  the menu is open would fight the open-menu window geometry. */
export function isPillDraggable(anchor: PillAnchor, menuOpen: boolean): boolean {
  return anchor === "custom" && !menuOpen;
}
