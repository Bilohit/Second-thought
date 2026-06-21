/**
 * pillAnchor.ts
 * -------------
 * Where the pill (Capsule/Minimal Display Mode) sits on screen. "custom"
 * means "don't reposition it" — it stays wherever the window was last
 * dragged/placed, which is the literal behavior of never calling
 * setPosition for that anchor.
 */

export type PillAnchor = "tl" | "tc" | "tr" | "lc" | "custom" | "rc" | "bl" | "bc" | "br";

/** Row-major 3x3 order, matching the Settings anchor-grid layout. */
export const ANCHOR_ORDER: PillAnchor[] = ["tl", "tc", "tr", "lc", "custom", "rc", "bl", "bc", "br"];

const MARGIN = 12;

/** Returns the top-left screen position for a pill of size (w, h) at the
 *  given anchor, or null for "custom" (caller should leave the window alone). */
export function anchorPosition(anchor: PillAnchor, w: number, h: number): { x: number; y: number } | null {
  if (anchor === "custom") return null;

  const sw = window.screen.availWidth;
  const sh = window.screen.availHeight;

  const x = anchor === "tl" || anchor === "lc" || anchor === "bl" ? MARGIN
          : anchor === "tc" || anchor === "bc"                    ? (sw - w) / 2
          : sw - w - MARGIN; // tr | rc | br

  const y = anchor === "tl" || anchor === "tc" || anchor === "tr" ? MARGIN
          : anchor === "lc" || anchor === "rc"                    ? (sh - h) / 2
          : sh - h - MARGIN; // bl | bc | br

  return { x: Math.round(x), y: Math.round(y) };
}
