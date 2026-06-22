import { getCurrentWindow, monitorFromPoint, currentMonitor } from "@tauri-apps/api/window";

export interface WorkArea {
  /** logical-px top-left of the monitor's work area */
  x: number;
  y: number;
  /** logical-px work-area size (taskbar excluded) */
  w: number;
  h: number;
  scale: number;
}

/**
 * Work area (taskbar excluded) of the monitor the window currently sits on,
 * in LOGICAL px. Resolves the monitor by the window's physical CENTER point so
 * a window straddling two displays picks the one it's mostly on. Falls back to
 * currentMonitor(), then to a primary-screen guess, so callers always get a
 * usable rect.
 *
 * Pass `atPoint` (physical px) to resolve the monitor for a specific point
 * instead — e.g. the pill's stable center, so the menu-open fan geometry
 * never flips to the neighbor monitor as the window grows toward a shared
 * edge (for_sonnet.md Bug 2 step 4).
 */
export async function getActiveWorkArea(atPoint?: { x: number; y: number }): Promise<WorkArea> {
  const win = getCurrentWindow();
  try {
    let cx: number, cy: number;
    if (atPoint) {
      cx = atPoint.x;
      cy = atPoint.y;
    } else {
      const pos = await win.outerPosition();   // physical
      const size = await win.outerSize();      // physical
      cx = pos.x + size.width / 2;
      cy = pos.y + size.height / 2;
    }
    const mon = (await monitorFromPoint(cx, cy)) ?? (await currentMonitor());
    if (mon) {
      const s = mon.scaleFactor;
      return {
        x: mon.workArea.position.x / s,
        y: mon.workArea.position.y / s,
        w: mon.workArea.size.width / s,
        h: mon.workArea.size.height / s,
        scale: s,
      };
    }
  } catch { /* fall through */ }
  return { x: 0, y: 0, w: window.screen.availWidth, h: window.screen.availHeight, scale: 1 };
}

/**
 * Full physical bounds (taskbar included) of the monitor the window — or
 * `atPoint` — currently sits on, in LOGICAL px. Same resolution/fallback
 * chain as `getActiveWorkArea`, but reads `mon.position`/`mon.size` instead
 * of `mon.workArea.*`. Used by the hard pill-containment clamp (for_sonnet.md
 * Problem 1): the visible pill may sit over the taskbar but must never cross
 * the physical monitor edge, so that clamp needs the full rect, not the
 * work-area rect that anchors/snap use.
 */
export async function getActiveMonitorBounds(atPoint?: { x: number; y: number }): Promise<WorkArea> {
  const win = getCurrentWindow();
  try {
    let cx: number, cy: number;
    if (atPoint) {
      cx = atPoint.x;
      cy = atPoint.y;
    } else {
      const pos = await win.outerPosition();   // physical
      const size = await win.outerSize();      // physical
      cx = pos.x + size.width / 2;
      cy = pos.y + size.height / 2;
    }
    const mon = (await monitorFromPoint(cx, cy)) ?? (await currentMonitor());
    if (mon) {
      const s = mon.scaleFactor;
      return {
        x: mon.position.x / s,
        y: mon.position.y / s,
        w: mon.size.width / s,
        h: mon.size.height / s,
        scale: s,
      };
    }
  } catch { /* fall through */ }
  return { x: 0, y: 0, w: window.screen.width, h: window.screen.height, scale: 1 };
}
