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
 */
export async function getActiveWorkArea(): Promise<WorkArea> {
  const win = getCurrentWindow();
  try {
    const pos = await win.outerPosition();   // physical
    const size = await win.outerSize();      // physical
    const cx = pos.x + size.width / 2;
    const cy = pos.y + size.height / 2;
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
