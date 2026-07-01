/**
 * geoLog.ts — OBSERVE-ONLY geometry instrumentation for the pill-window
 * boundary investigation (for_sonnet_boundary_calibration.md).
 *
 * Pure diagnostics: every function here only READS Tauri window/monitor state
 * and writes a structured line through the existing `logger` (scope "geo").
 * Nothing here ever calls setPosition/setSize — dropping every call in this
 * module changes ZERO behavior. Safe to leave wired in; ON BY DEFAULT (logs
 * to the same file sink as everything else via `logger`, scope "geo") so a
 * repro can be captured with zero setup. Toggle off via Settings -> Function
 * -> "Geometry Debug Logging", which sets
 * `localStorage["second-thought:geo-debug"] = "0"`.
 *
 * Why it exists: the boundary bug is a multi-monitor / mixed-DPI coordinate
 * problem. The clamp mixes a window-scale-derived logical position with a
 * monitor-scale-derived logical bounds rect; when those two scale factors
 * disagree (mixed DPI, or a lagging WM_DPICHANGED right after the full window
 * crossed monitors) the origins don't line up and both edges translate. To
 * SEE that, you must capture — at one instant — the window's reported scale,
 * the resolved monitor's scale, the raw physical numbers, and which monitor
 * `monitorFromPoint` actually picks. That's exactly what `geoSnapshot` dumps.
 */

import {
  getCurrentWindow,
  availableMonitors,
  monitorFromPoint,
} from "@tauri-apps/api/window";
import { logger } from "./logger";

const GEO_DEBUG_KEY = "second-thought:geo-debug";

// drag.tick / fling.step fire per pointermove/animation-frame — throttle those
// hot tags so the log doesn't flood. Other tags (pointerdown, leavePill, etc.)
// are already low-frequency and stay unthrottled.
const THROTTLE_MS = 150;
const lastLogged = new Map<string, number>();
function throttled(tag: string): boolean {
  const now = Date.now();
  const last = lastLogged.get(tag) ?? 0;
  if (now - last < THROTTLE_MS) return true;
  lastLogged.set(tag, now);
  return false;
}

// Off by default — boundary-calibration investigation is resolved; opt in
// via Settings → "Geometry Debug Logging", which sets the key to "1".
function geoEnabled(): boolean {
  try {
    return typeof localStorage !== "undefined"
      && localStorage.getItem(GEO_DEBUG_KEY) === "1";
  } catch {
    return false;
  }
}

export function isGeoDebugEnabled(): boolean {
  return geoEnabled();
}

export function setGeoDebugEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(GEO_DEBUG_KEY, enabled ? "1" : "0");
  } catch { /* ignore */ }
}

interface MonRow {
  name: string | null;
  scale: number;
  posPhysical: { x: number; y: number };
  sizePhysical: { w: number; h: number };
  workAreaPhysical: { x: number; y: number; w: number; h: number };
  /** logical origin = physical / this monitor's own scale (what
   *  getActiveMonitorBounds divides by) — the value the clamp actually uses. */
  posLogical: { x: number; y: number };
  sizeLogical: { w: number; h: number };
}

/**
 * One full geometry snapshot at a tagged call-site. Logs:
 *   • window: outerPosition (physical), outerSize (physical), scaleFactor
 *   • every monitor: physical + per-monitor-scale logical rects
 *   • which monitor monitorFromPoint(windowCenterPhysical) resolves to
 *   • windowScale vs resolvedMonitorScale — the smoking gun when they differ
 *
 * `extra` carries call-site context (e.g. the clamp input/output, the gesture
 * phase). Never throws; on any failure logs a "geo-fail" line instead.
 */
export async function geoSnapshot(tag: string, extra?: Record<string, unknown>): Promise<void> {
  if (!geoEnabled()) return;
  try {
    const win = getCurrentWindow();
    const [posPhys, sizePhys, winScale, mons] = await Promise.all([
      win.outerPosition(),
      win.outerSize(),
      win.scaleFactor(),
      availableMonitors(),
    ]);

    const centerPhysical = {
      x: posPhys.x + sizePhys.width / 2,
      y: posPhys.y + sizePhys.height / 2,
    };

    let resolved: { name: string | null; scale: number } | null = null;
    try {
      const m = await monitorFromPoint(centerPhysical.x, centerPhysical.y);
      if (m) resolved = { name: m.name, scale: m.scaleFactor };
    } catch { /* ignore */ }

    const rows: MonRow[] = mons.map((m) => {
      const s = m.scaleFactor;
      return {
        name: m.name,
        scale: s,
        posPhysical: { x: m.position.x, y: m.position.y },
        sizePhysical: { w: m.size.width, h: m.size.height },
        workAreaPhysical: {
          x: m.workArea.position.x, y: m.workArea.position.y,
          w: m.workArea.size.width, h: m.workArea.size.height,
        },
        posLogical: { x: m.position.x / s, y: m.position.y / s },
        sizeLogical: { w: m.size.width / s, h: m.size.height / s },
      };
    });

    logger.info("geo", tag, {
      window: {
        posPhysical: { x: posPhys.x, y: posPhys.y },
        sizePhysical: { w: sizePhys.width, h: sizePhys.height },
        scaleFactor: winScale,
        // the logical top-left the drag handler computes (pos / windowScale)
        topLeftLogicalViaWindowScale: { x: posPhys.x / winScale, y: posPhys.y / winScale },
        centerPhysical,
      },
      resolvedMonitor: resolved,
      // THE smoking gun: if these differ, clamp mixes two logical spaces.
      scaleMismatch: resolved ? winScale !== resolved.scale : "unresolved",
      monitors: rows,
      ...extra,
    });
  } catch (err) {
    try { logger.warn("geo", `${tag} geo-fail`, err); } catch { /* ignore */ }
  }
}

/**
 * Capsule-morph frame tracer — samples the window's inner width and the
 * capsule bar's rect once per animation frame for `durationMs`, then logs the
 * whole timeline as one line. Purpose: prove/disprove the right-zone "jumps
 * out too fast" jerk — compare when `winW` jumps to full (webview actually
 * presented the resized/moved window) against when `barW`/`barL` start moving
 * (CSS width morph begins). If the bar's left edge grows leftward BEFORE winW
 * jumps, the morph is racing ahead of the window present = the jerk.
 * Pure diagnostics, gated on the same geo-debug flag. No-op when disabled.
 */
export function traceCapsuleMorph(zone: string, durationMs = 500): void {
  // ponytail: TEMP always-on (not gated on geoEnabled) — right-zone morph
  // investigation. Restore the `if (!geoEnabled()) return;` guard once fixed.
  const t0 = performance.now();
  const samples: Array<{ t: number; sx: number; winW: number; barW: number; barL: number; barR: number; items: string }> = [];
  const frame = (now: number) => {
    const dt = now - t0;
    const bar = document.querySelector<HTMLElement>(".capsule-menu");
    const r = bar?.getBoundingClientRect();
    // Per-item ground truth of the unfurl: which icon has width first, and at
    // what x. Reveal order = order items cross w>2. l relative to bar-left so
    // right-zone/left-zone are directly comparable. Compact "idx:l/w" string
    // per visible item keeps one frame on one line.
    const items = Array.from(document.querySelectorAll<HTMLElement>(".capsule-item"))
      .map((el, i) => {
        const ir = el.getBoundingClientRect();
        return ir.width > 2 ? `${i}:${Math.round(ir.left - (r?.left ?? 0))}/${Math.round(ir.width)}` : "";
      })
      .filter(Boolean)
      .join(" ");
    samples.push({
      t: Math.round(dt),
      // screen-space window left (synchronous) — catches the window itself
      // jumping left then snapping back on right-zone open, which the
      // window-relative bar rect below cannot see.
      sx: typeof window.screenX === "number" ? window.screenX : (window.screenLeft ?? -1),
      winW: window.innerWidth,
      barW: r ? Math.round(r.width) : -1,
      barL: r ? Math.round(r.left) : -1,
      barR: r ? Math.round(r.right) : -1,
      items,
    });
    if (dt < durationMs) requestAnimationFrame(frame);
    else logger.info("geo", `capsuleMorph.${zone}`, { samples });
  };
  requestAnimationFrame(frame);
}

/**
 * Synchronous clamp in/out logger — call right where clampPillWindowToMonitor
 * is invoked, passing its input and output, plus the monitorBounds it used.
 * Pairs with a nearby geoSnapshot so you can see whether the bounds rect's
 * origin matches the resolved monitor's logical origin (it won't, if the scale
 * factors mismatched). Pure logging.
 */
export function geoClamp(
  tag: string,
  data: {
    windowTopLeftLogical: { x: number; y: number };
    monitorBounds: { x: number; y: number; w: number; h: number };
    pillW: number;
    pillH: number;
    margin: number;
    result: { x: number; y: number };
  },
): void {
  if (!geoEnabled()) return;
  if ((tag === "drag.tick" || tag === "fling.step") && throttled(tag)) return;
  try {
    const { windowTopLeftLogical: tl, monitorBounds: b, pillW, pillH, margin, result } = data;
    logger.info("geo", `${tag} clamp`, {
      in: tl,
      bounds: b,
      // window-space edges (clampPillWindowToMonitor allows the margin to
      // overhang past the monitor edge by design — see menuGeometry.ts —
      // so out.x legitimately goes negative down to -margin, not 0).
      derivedEdges: {
        minLeft: b.x - margin,
        maxLeft: b.x + b.w - pillW - margin,
        minTop: b.y - margin,
        maxTop: b.y + b.h - pillH - margin,
      },
      pill: { pillW, pillH, margin },
      out: result,
      movedX: result.x - tl.x,
      movedY: result.y - tl.y,
    });
  } catch { /* ignore */ }
}
