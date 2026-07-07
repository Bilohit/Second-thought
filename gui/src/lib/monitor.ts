import { getCurrentWindow, monitorFromPoint, currentMonitor, availableMonitors, primaryMonitor, type Monitor } from "@tauri-apps/api/window";

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

export interface MonitorInfo {
  /** Stable id for `omni-pill-monitor` — the monitor's name when the OS
   *  reports one, else its index in `availableMonitors()` (best-effort: a
   *  name-less monitor losing its index slot on reconnect just falls back
   *  to primary like an unplugged one would). */
  id: string;
  /** "<name> WxH (primary)" for the Settings list. */
  label: string;
  isPrimary: boolean;
  /** Logical-px work area (taskbar excluded), same convention as
   *  `getActiveWorkArea`. */
  workArea: WorkArea;
}

/** Pure mapping (physical->logical, primary detection) — the part of
 *  `listMonitors` worth a unit check; everything else is a direct Tauri call. */
export function monitorToInfo(m: Monitor, index: number, primary: Monitor | null): MonitorInfo {
  const s = m.scaleFactor;
  const isPrimary = !!primary && primary.position.x === m.position.x && primary.position.y === m.position.y;
  const wLogical = Math.round(m.size.width / s);
  const hLogical = Math.round(m.size.height / s);
  return {
    id: m.name ?? `monitor-${index}`,
    label: `${m.name ?? `Monitor ${index + 1}`} ${wLogical}x${hLogical}${isPrimary ? " (primary)" : ""}`,
    isPrimary,
    workArea: {
      x: m.workArea.position.x / s,
      y: m.workArea.position.y / s,
      w: m.workArea.size.width / s,
      h: m.workArea.size.height / s,
      scale: s,
    },
  };
}

/** Enumerates every connected monitor for the Settings display picker
 *  (for_sonnet.md §4). Logical units throughout, same discipline as
 *  `getActiveWorkArea`/`getActiveMonitorBounds`. */
export async function listMonitors(): Promise<MonitorInfo[]> {
  const [monitors, primary] = await Promise.all([availableMonitors(), primaryMonitor()]);
  return monitors.map((m, i) => monitorToInfo(m, i, primary));
}

/** Resolves which monitor the display picker's selection actually targets
 *  (for_sonnet.md §4 unplug decision): the selected id if it's still
 *  present, else primary — silently, without clearing the stored id, so a
 *  reconnected monitor is picked back up automatically. `null` only when
 *  `monitors` itself hasn't loaded yet (caller should fall back to
 *  `getActiveWorkArea()`). */
export function resolveTargetMonitor(monitors: MonitorInfo[], selectedId: string | null): MonitorInfo | null {
  if (monitors.length === 0) return null;
  const chosen = selectedId ? monitors.find((m) => m.id === selectedId) : undefined;
  return chosen ?? monitors.find((m) => m.isPrimary) ?? monitors[0];
}

/**
 * Converts a logical rect (`pos`+`size`) to physical px at `scale`, rounding
 * the right/bottom edge from the absolute logical coordinate instead of
 * rounding x/w (or y/h) independently. `round(x·s) + round(w·s)` can drift
 * 1px from `round((x+w)·s)` at fractional scale factors (125%/150% DPI),
 * which shivers a pinned edge across a morph (T4). This is the ONE
 * sanctioned physical-coordinate conversion, consumed by
 * `tauri.ts:setWindowBoundsAtomic` — every other call site stays
 * `Logical*` only.
 */
export function logicalToPhysicalRect(
  pos: { x: number; y: number },
  size: { w: number; h: number },
  scale: number,
): { x: number; y: number; w: number; h: number } {
  const x = Math.round(pos.x * scale);
  const y = Math.round(pos.y * scale);
  return {
    x,
    y,
    w: Math.round((pos.x + size.w) * scale) - x,
    h: Math.round((pos.y + size.h) * scale) - y,
  };
}
