/**
 * App.tsx
 * -------
 * Root component — theme system, search modal.
 *
 * Keyboard bindings
 *   Ctrl+K          search vault (toggle)
 *   Ctrl+,          settings
 *   Ctrl+\          vault
 *   Ctrl+I          inbox
 *   Escape          close panel / hide window
 *
 * Themes (persisted to localStorage)
 *   dark            Void        (default, grayscale dark)
 *   light           Paper       (grayscale light)
 *   sage            Sage        (light pastel)
 *   sky             Sky         (light pastel)
 *   bubba-pink      Bubba Pink  (light pastel)
 *   mist            Mist        (dark pastel)
 *   lilac           Lilac       (dark pastel)
 *   sand            Sand        (dark pastel)
 *   wine            Wine        (dark pastel)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize, LogicalPosition, PhysicalPosition } from "@tauri-apps/api/dpi";
import { listen } from "@tauri-apps/api/event";
import CaptureOverlay from "./components/CaptureOverlay";
import PillOverlay, { PILL_DIMS, type PillMode, type PillCorner } from "./components/PillOverlay";
import { CAPSULE_OPEN_W, CAPSULE_EXIT_MS } from "./components/PillMenu/CapsuleMenu";
import { RADIAL_ANIM_MS, RADIAL_STAGGER_MS, type PillGeometry } from "./components/PillMenu/RadialMenu";
import { ALL_TARGETS, type MenuTarget } from "./components/PillMenu/icons";
import { exitDurationMs } from "./lib/menuTiming";
import DevTuner from "./components/PillMenu/DevTuner";
import { useRadialTuning } from "./lib/devTuning";
import SettingsPanel from "./components/SettingsPanel";
import VaultManager from "./components/VaultManager";
import InboxPanel from "./components/InboxPanel";
import StatsPanel from "./components/StatsPanel";
import SearchModal, { type SearchAction } from "./components/SearchModal";
import { useCapture } from "./hooks/useCapture";
import { logger } from "./lib/logger";
import { getInbox } from "./lib/api";
import { type PillAnchor, anchorPosition, anchoredMenuPosition, isPillDraggable } from "./lib/pillAnchor";
import { getActiveWorkArea, getActiveMonitorBounds, listMonitors, resolveTargetMonitor, type MonitorInfo } from "./lib/monitor";
import { computeMenuGeometry, clampPillWindowToMonitor, computeCapsuleMenuGeometry, computeProportionalMonitorMove, computeMinimalMenuWindow } from "./lib/menuGeometry";
import { nextWindowTopLeft, emaVelocity, zeroVelocityAtClamp, dragStartBaseline, type Point } from "./lib/dragMath";
import { createSpring, stepSpring } from "./lib/spring";
import { setWindowNoactivate, armMenuClickAway, disarmMenuClickAway } from "./lib/tauri";
import { geoSnapshot, geoClamp } from "./lib/geoLog";

// ── Theme ──────────────────────────────────────────────────────────────────

export type Theme =
  | "dark" | "light"
  | "sage" | "sky" | "bubba-pink"
  | "mist" | "lilac" | "sand" | "wine";
export const THEMES: Theme[] = [
  "dark", "light",
  "sage", "sky", "bubba-pink",
  "mist", "lilac", "sand", "wine",
];
export const THEME_LABELS: Record<Theme, string> = {
  "dark":       "Void",
  "light":      "Paper",
  "sage":       "Sage",
  "sky":        "Sky",
  "bubba-pink": "Bubba Pink",
  "mist":       "Mist",
  "lilac":      "Lilac",
  "sand":       "Sand",
  "wine":       "Wine",
};
const STORAGE_KEY = "omni-theme";

export function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (saved && (THEMES as string[]).includes(saved)) return saved;
  } catch { /* ignore */ }
  return "dark";
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* ignore */ }
}

// ── Display Mode (Item 2: pill/minimized window) ────────────────────────────
// Client-only preferences, persisted to localStorage exactly like theme —
// these never touch the server config.

type DisplayMode = "full" | PillMode;

const DISPLAY_MODE_KEY    = "omni-pill-mode";
const PILL_CORNER_KEY     = "omni-pill-corner";
const PILL_PINNED_KEY     = "omni-pill-pinned";
const PILL_ANCHOR_KEY     = "omni-pill-anchor";
const PILL_FAN_STYLE_KEY  = "omni-pill-fan-style";
const PILL_SNAP_KEY       = "omni-pill-snap";
const PILL_MONITOR_KEY    = "omni-pill-monitor";
/** Custom-position drag release snaps to the nearest edge/corner within this
 *  many logical px (for_sonnet.md "New Settings" §2). */
const SNAP_THRESHOLD_PX = 24;

function getInitialDisplayMode(): DisplayMode {
  try {
    const saved = localStorage.getItem(DISPLAY_MODE_KEY);
    if (saved === "full" || saved === "capsule" || saved === "minimal") return saved;
  } catch { /* ignore */ }
  return "full";
}
function getInitialPillCorner(): PillCorner {
  try {
    const saved = localStorage.getItem(PILL_CORNER_KEY);
    if (saved === "sharp" || saved === "rounded") return saved;
  } catch { /* ignore */ }
  return "sharp";
}
function getInitialPillPinned(): boolean {
  try { return localStorage.getItem(PILL_PINNED_KEY) !== "0"; } catch { return true; }
}
function getInitialPillAnchor(): PillAnchor {
  try {
    const saved = localStorage.getItem(PILL_ANCHOR_KEY);
    if (saved && ["tl", "tc", "tr", "lc", "custom", "rc", "bl", "bc", "br"].includes(saved)) return saved as PillAnchor;
  } catch { /* ignore */ }
  return "custom";
}
function getInitialPillFanStyle(): "spread" | "capped" {
  try {
    const saved = localStorage.getItem(PILL_FAN_STYLE_KEY);
    if (saved === "spread" || saved === "capped") return saved;
  } catch { /* ignore */ }
  return "spread";
}
function getInitialPillSnap(): boolean {
  try { return localStorage.getItem(PILL_SNAP_KEY) !== "0"; } catch { return true; }
}
function getInitialSelectedMonitorId(): string | null {
  try { return localStorage.getItem(PILL_MONITOR_KEY); } catch { return null; }
}

// ── View ───────────────────────────────────────────────────────────────────

type View = "capture" | "settings" | "vault" | "inbox" | "stats";

// ── Animated window movement ────────────────────────────────────────────────
// Tauri's setPosition is an instant OS-level jump; everything else in this app
// moves on the same cubic-bezier(0.16,1,0.3,1) curve, so pill snaps/recenters
// get this evaluator-driven equivalent instead of a clunky teleport. Kept
// snappy (not the 200ms standard) per the "quick moving to the pinned spot"
// brief for window repositioning specifically.
const MOVE_DURATION_MS = 140;

function cubicBezierEase(p1x: number, p1y: number, p2x: number, p2y: number) {
  const cx = 3 * p1x, bx = 3 * (p2x - p1x) - cx, ax = 1 - cx - bx;
  const cy = 3 * p1y, by = 3 * (p2y - p1y) - cy, ay = 1 - cy - by;
  const sampleX = (t: number) => ((ax * t + bx) * t + cx) * t;
  const sampleY = (t: number) => ((ay * t + by) * t + cy) * t;
  const sampleDX = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  return (x: number) => {
    let t = x;
    for (let i = 0; i < 8; i++) {
      const dx = sampleX(t) - x;
      if (Math.abs(dx) < 1e-4) break;
      const d = sampleDX(t);
      if (Math.abs(d) < 1e-6) break;
      t -= dx / d;
    }
    return sampleY(t);
  };
}
const MOVE_EASE = cubicBezierEase(0.16, 1, 0.3, 1);

// Radial fan exit timing (formerly MenuWindow.tsx's EXIT_DURATION_MS, now
// owned here since the fan lives in this window) — the window must stay
// full-size until the staggered spoke exit finishes, then shrink back to
// the idle pill size (§3.2).
const RADIAL_EXIT_BUFFER_MS = 80;
const RADIAL_EXIT_DURATION_MS = exitDurationMs(ALL_TARGETS.length, RADIAL_ANIM_MS, RADIAL_STAGGER_MS, RADIAL_EXIT_BUFFER_MS);

// Menu open/close (for_sonnet.md "Problem 4") gets a single atomic, instant
// resize+reposition instead of the rAF tween above — the tween's per-frame
// async setSize/setPosition pair landing at slightly different times each
// frame (while the pill is flex-centered in the window) is exactly what
// produced the open/close shake. An instant transparent-window resize is
// invisible; only the spokes/capsule-width morph (CSS) is meant to animate.
async function setWindowGeometryInstant(
  targetSize: { w: number; h: number },
  targetPos: { x: number; y: number } | null,
) {
  const win = getCurrentWindow();
  const tasks = [win.setSize(new LogicalSize(targetSize.w, targetSize.h)).catch(() => {})];
  if (targetPos) tasks.push(win.setPosition(new LogicalPosition(targetPos.x, targetPos.y)).catch(() => {}));
  await Promise.all(tasks);
}

// Animates the window's size AND position together to a *logical*-pixel
// target by sampling MOVE_EASE across requestAnimationFrame ticks. Combining
// both in one loop (instead of an instant setSize followed by an animated
// setPosition) avoids the "snap to full size, then slide to the target spot"
// look — every frame moves and resizes in lockstep on the same curve.
// `targetPos: null` means "keep the window's current position" (size-only
// change). Falls back to an instant jump if reading current geometry fails
// (e.g. window not fully initialized yet).
async function animateWindowAndSizeTo(
  targetSize: { w: number; h: number },
  targetPos: { x: number; y: number } | null,
  cancelled?: () => boolean,
) {
  const win = getCurrentWindow();
  let startLogical: { x: number; y: number };
  let startSize: { w: number; h: number };
  try {
    const scale = await win.scaleFactor();
    const p = await win.outerPosition();
    const s = await win.outerSize();
    startLogical = { x: p.x / scale, y: p.y / scale };
    startSize = { w: s.width / scale, h: s.height / scale };
  } catch {
    await win.setSize(new LogicalSize(targetSize.w, targetSize.h)).catch(() => {});
    if (targetPos) await win.setPosition(new LogicalPosition(targetPos.x, targetPos.y)).catch(() => {});
    return;
  }
  const endPos = targetPos ?? startLogical;
  const dx = endPos.x - startLogical.x;
  const dy = endPos.y - startLogical.y;
  const dw = targetSize.w - startSize.w;
  const dh = targetSize.h - startSize.h;
  if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(dw) < 0.5 && Math.abs(dh) < 0.5) return;

  const startTime = performance.now();
  await new Promise<void>((resolve) => {
    const frame = (now: number) => {
      // A superseded reconcile must not keep driving the window — bail the
      // instant a newer toggle invalidates this run, so a stale grow can't
      // finish after the shrink and leave the window panel-sized under the
      // idle pill (boundary_bug-solution.md Fix B).
      if (cancelled?.()) { resolve(); return; }
      const t = Math.min(1, (now - startTime) / MOVE_DURATION_MS);
      const e = MOVE_EASE(t);
      win.setSize(new LogicalSize(startSize.w + dw * e, startSize.h + dh * e)).catch(() => {});
      win.setPosition(new LogicalPosition(startLogical.x + dx * e, startLogical.y + dy * e)).catch(() => {});
      if (t < 1) requestAnimationFrame(frame);
      else resolve();
    };
    requestAnimationFrame(frame);
  });
}

// ── Component ──────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView]             = useState<View>("capture");
  const [search, setSearch]         = useState(false);
  const [theme, setTheme]           = useState<Theme>(getInitialTheme);
  const [openResult, setOpenResult] = useState<{ category: string; path: string } | null>(null);
  const [inboxCount, setInboxCount] = useState(0);

  // Display Mode (Item 2) state — persisted like theme, applied immediately.
  const [displayMode, setDisplayMode] = useState<DisplayMode>(getInitialDisplayMode);
  const [pillCorner, setPillCorner]   = useState<PillCorner>(getInitialPillCorner);
  const [pillPinned, setPillPinned]   = useState<boolean>(getInitialPillPinned);
  const [pillAnchor, setPillAnchor]   = useState<PillAnchor>(getInitialPillAnchor);
  const [pillFanStyle, setPillFanStyle] = useState<"spread" | "capped">(getInitialPillFanStyle);
  const [pillSnapEnabled, setPillSnapEnabled] = useState<boolean>(getInitialPillSnap);
  const radialTuning = useRadialTuning();

  // Breathing room around the pill so the rotating-ring overlay (inset -2px)
  // never gets clipped by the OS window edge.
  const PILL_MARGIN = 6;

  // Minimal mode only (§3): the radial fan's screen-space geometry, computed
  // once per open from the pill's own window position (no cross-window
  // event needed now that the fan renders in-process). `minimalWrapperOffset`
  // is where the pill+fan wrapper sits *within* the grown window — normally
  // dead-center (matches the idle margin), but shifted off-center when the
  // monitor clamp (§3.3) pushes the window without moving the pill itself.
  const [radialPillGeometry, setRadialPillGeometry] = useState<PillGeometry | null>(null);
  const [minimalWrapperOffset, setMinimalWrapperOffset] = useState<{ x: number; y: number }>({ x: PILL_MARGIN, y: PILL_MARGIN });
  // True only once the window has actually grown to fit the radial fan —
  // gates the fan's render so it can never paint into a still-pill-sized
  // window mid-IPC-grow (pill-fan-clip fix). Pill chrome (glow/aria) keeps
  // reacting to `menuOpen` instantly; only the fan waits on this.
  const [fanReady, setFanReady] = useState(false);

  // Display picker (for_sonnet.md §4) — enumerated once on mount and again
  // whenever Settings is opened (cheap, covers hot-plug without polling).
  // `selectedMonitorId` persists like every other client-only preference;
  // resolveTargetMonitor() falls back to primary silently if it's unplugged,
  // keeping the stored id so a reconnected monitor is picked back up.
  const [monitors, setMonitors] = useState<MonitorInfo[]>([]);
  const [selectedMonitorId, setSelectedMonitorId] = useState<string | null>(getInitialSelectedMonitorId);
  const refreshMonitors = useCallback(() => { listMonitors().then(setMonitors).catch(() => {}); }, []);
  useEffect(() => { refreshMonitors(); }, [refreshMonitors]);
  // True once the user clicks the pill (or it's irrelevant because Display
  // Mode is Full) — shows the full overlay instead of the small pill. Never
  // toggled automatically by the capture lifecycle, only by explicit clicks.
  const [expanded, setExpanded] = useState(false);

  // The on-click pill menu (radial fan / capsule morph) — see for_sonnet.md
  // §5/§6/§8. Clicking the pill toggles this instead of `expanded` directly;
  // selecting a nav item closes the menu *and* sets `expanded`.
  const [menuOpen, setMenuOpen] = useState(false);
  // Capsule-only (for_sonnet.md Problem 3): which screen edge the pill is
  // nearer to when the menu opens. The bar hugs this edge and the
  // transparent click-to-close padding grows toward the screen center.
  const [capsuleNearEdge, setCapsuleNearEdge] = useState<"left" | "right">("left");

  useEffect(() => { try { localStorage.setItem(DISPLAY_MODE_KEY, displayMode); } catch { /* ignore */ } }, [displayMode]);
  useEffect(() => { try { localStorage.setItem(PILL_CORNER_KEY, pillCorner); } catch { /* ignore */ } }, [pillCorner]);
  useEffect(() => { try { localStorage.setItem(PILL_PINNED_KEY, pillPinned ? "1" : "0"); } catch { /* ignore */ } }, [pillPinned]);
  useEffect(() => { try { localStorage.setItem(PILL_ANCHOR_KEY, pillAnchor); } catch { /* ignore */ } }, [pillAnchor]);
  useEffect(() => { try { localStorage.setItem(PILL_FAN_STYLE_KEY, pillFanStyle); } catch { /* ignore */ } }, [pillFanStyle]);
  useEffect(() => { try { localStorage.setItem(PILL_SNAP_KEY, pillSnapEnabled ? "1" : "0"); } catch { /* ignore */ } }, [pillSnapEnabled]);
  useEffect(() => {
    try {
      if (selectedMonitorId) localStorage.setItem(PILL_MONITOR_KEY, selectedMonitorId);
      else localStorage.removeItem(PILL_MONITOR_KEY);
    } catch { /* ignore */ }
  }, [selectedMonitorId]);
  // Re-enumerate on every Settings open so a hot-plugged/removed monitor
  // shows up without restarting the app.
  useEffect(() => { if (view === "settings") refreshMonitors(); }, [view, refreshMonitors]);

  // Read via a ref inside useCapture so its dismiss-timer closures always see
  // the latest pin state without re-subscribing every render. An explicit
  // manual expand (clicking the pill) holds the window open the same way
  // Stay Pinned does, so a deliberately-opened full view never gets yanked
  // away by the post-capture auto-hide regardless of the Stay Pinned setting.
  const holdOpenRef = useRef(false);
  useEffect(() => {
    holdOpenRef.current = pillPinned || expanded;
  }, [pillPinned, expanded]);

  // Mirrors read by the window-focus-loss listener below (mounted once) so it
  // always sees the latest values without re-subscribing every render.
  const menuOpenRef = useRef(menuOpen);
  useEffect(() => { menuOpenRef.current = menuOpen; }, [menuOpen]);
  const pillPinnedRef = useRef(pillPinned);
  useEffect(() => { pillPinnedRef.current = pillPinned; }, [pillPinned]);

  const { state: captureState, stepDefs } = useCapture(holdOpenRef);

  // Apply theme on mount and whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);

  const selectTheme = useCallback((t: Theme) => setTheme(t), []);

  // Only Capsule/Minimal ever collapse to a pill, and only in the capture
  // view — Settings/Vault/Inbox/Stats always show full-size regardless.
  const showPill = displayMode !== "full" && view === "capture" && !expanded;

  // The menu only ever exists while the pill is showing; leaving pill mode
  // for any reason (expand, view switch, display-mode switch) always closes it.
  useEffect(() => {
    if (!showPill) {
      setMenuOpen(false);
      setFanReady(false);
      setRadialPillGeometry(null);
      setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
    }
  }, [showPill]);

  // Drop the fan the instant a close begins (independent of the showPill
  // reset above, which only fires when the pill leaves entirely) — this is
  // what lets the staggered exit start immediately on a normal menu close,
  // while the window itself stays full-size until RADIAL_EXIT_DURATION_MS.
  useEffect(() => {
    if (!menuOpen) setFanReady(false);
  }, [menuOpen]);

  // `renderPill` is what actually picks the early-return branch below — it
  // deliberately *lags* `showPill` by one resize-animation's worth of time
  // when crossing the pill/full boundary, so the full-size content can finish
  // fading out before the window shrinks (collapsing to pill), and the window
  // can finish growing before the content fades in (expanding from pill).
  // Every other transition (switching between full-size views, ordinary pill
  // resizes within pill mode) keeps the two in sync with no extra delay.
  const [renderPill, setRenderPill] = useState(showPill);
  // Gates the opacity of the full-size content box during exactly those two
  // crossings; false (visible) the rest of the time.
  const [contentHidden, setContentHidden] = useState(false);

  // Closing a tab opened from the pill (capsule/minimal) reverts to that
  // exact pill immediately — pinned shows the pill, unpinned hides to tray
  // (for_sonnet.md §7, D3). Reverts even mid-capture: the pill already shows
  // live capture status (pillLabel), so there's nothing to protect by
  // waiting for idle — the prior `captureState.phase === "idle"` gate just
  // stranded the user on the full view while a capture was running.
  const prevViewRef = useRef(view);
  useEffect(() => {
    if (prevViewRef.current !== "capture" && view === "capture" && displayMode !== "full") {
      setExpanded(false);
      if (!pillPinned) getCurrentWindow().hide();
    }
    prevViewRef.current = view;
  }, [view, pillPinned, displayMode]);

  // Poll the inbox count for the unread badge — best-effort, refreshed
  // whenever a capture completes and whenever the inbox view closes.
  const refreshInboxCount = useCallback(() => {
    getInbox().then((res) => setInboxCount(res.count)).catch(() => {});
  }, []);
  useEffect(() => { refreshInboxCount(); }, [refreshInboxCount]);
  useEffect(() => {
    if (captureState.phase === "done") refreshInboxCount();
  }, [captureState.phase, refreshInboxCount]);

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key === "k") {
        e.preventDefault();
        setSearch((o) => !o);
        return;
      }
      if (mod && e.key === ",") {
        e.preventDefault();
        setSearch(false);
        setView((v) => (v === "settings" ? "capture" : "settings"));
        return;
      }
      if (mod && e.key === "\\") {
        e.preventDefault();
        setSearch(false);
        setView((v) => (v === "vault" ? "capture" : "vault"));
        return;
      }
      if (mod && e.key === "i") {
        e.preventDefault();
        setSearch(false);
        setView((v) => (v === "inbox" ? "capture" : "inbox"));
        return;
      }
      if (e.key === "Escape") {
        if (menuOpen) {
          setMenuOpen(false);
          return;
        }
        if (search)             { setSearch(false); return; }
        if (view !== "capture"){ setView("capture"); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [view, search, menuOpen, displayMode]);

  // ── Tauri events ─────────────────────────────────────────────────────────
  useEffect(() => {
    let unlistenSettings: (() => void) | undefined;
    let unlistenVault:    (() => void) | undefined;
    let unlistenInbox:    (() => void) | undefined;
    let unlistenStats:    (() => void) | undefined;
    listen<void>("open-settings", () => setView("settings")).then((fn) => { unlistenSettings = fn; });
    listen<void>("open-vault",    () => setView("vault")).then((fn) => { unlistenVault = fn; });
    listen<void>("open-inbox",    () => setView("inbox")).then((fn) => { unlistenInbox = fn; });
    listen<void>("open-stats",    () => setView("stats")).then((fn) => { unlistenStats = fn; });
    return () => { unlistenSettings?.(); unlistenVault?.(); unlistenInbox?.(); unlistenStats?.(); };
  }, []);

  // Click-away close (for_sonnet.md "Pill Focus-Stealing Fix" Piece B/C): the
  // pill window is non-activating (WS_EX_NOACTIVATE, see the noactivate
  // effect below), so it never fires Tauri's focus-loss event — a global
  // low-level mouse hook (armed only while a menu is open) emits
  // "menu:dismiss" instead when a click lands outside the menu-bearing
  // window. Pinned just closes the menu; unpinned also hides to tray,
  // matching the dedicated Hide action. Now shared by capsule and minimal
  // alike — both grow the same single window, so "outside the window's
  // rect" is a meaningful hit-test for either.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      try {
        unlisten = await listen<void>("menu:dismiss", () => {
          if (!menuOpenRef.current) return;
          setMenuOpen(false);
          if (!pillPinnedRef.current) getCurrentWindow().hide();
        });
      } catch { /* ignore */ }
    })();
    return () => { unlisten?.(); };
  }, []);

  // Arm/disarm the click-away hook exactly while a menu is open.
  useEffect(() => {
    if (!menuOpen) {
      disarmMenuClickAway();
      return;
    }
    armMenuClickAway("main");
    return () => { disarmMenuClickAway(); };
  }, [menuOpen]);

  // Non-activating pill (for_sonnet.md Piece A): the pill and its menu must
  // never steal foreground focus from whatever app was active. Toggled off
  // only for the expanded full view, which needs real keyboard focus for
  // search/settings inputs.
  useEffect(() => {
    if (showPill) {
      setWindowNoactivate(true);
    } else {
      setWindowNoactivate(false).then(() => { getCurrentWindow().setFocus().catch(() => {}); });
    }
  }, [showPill]);

  // ── Dynamic window sizing (B1: content-measured) ──────────────────────────
  // The window height tracks the *real* content height of whichever view is
  // active, measured live via ResizeObserver. This replaces the old fixed
  // VIEW_H table (arbitrary per-tab heights that jawed the window and clipped
  // cross-fades). Because scrollHeight reports full content height even when a
  // panel is clamped + scrolling, panels keep height:100% and still measure
  // correctly; the capture card's ThinkingPanel expand is picked up on the same
  // curve, so there is no more capture 360→520 jump/empty-gap flash.
  const MAX_CONTENT_H = 600;   // cap → window stops growing, capture scrolls internally
  const SECONDARY_H   = 520;   // one canonical height for every list panel (B1.2)
  const V_MARGIN      = 24;    // 12px breathing room top + bottom inside the window

  const measureEls = useRef<Partial<Record<View, HTMLElement | null>>>({});
  const viewRef = useRef(view);
  viewRef.current = view;
  const [contentH, setContentH] = useState(360);
  const [measureTick, setMeasureTick] = useState(0);

  // Callback ref each view hands its root element to. Re-measure immediately
  // when the *active* view (re)attaches so a freshly-mounted panel sizes the
  // window without waiting for the next ResizeObserver tick.
  //
  // Each view's ref callback must keep a *stable identity* across renders —
  // JSX calls setMeasureEl(v) inline, so without caching this would mint a
  // new function every render, which React treats as "ref changed" and
  // re-invokes immediately, triggering setMeasureTick → re-render → new ref
  // → infinite loop (React error #185).
  const measureElCallbacks = useRef<Partial<Record<View, (el: HTMLElement | null) => void>>>({});
  const setMeasureEl = useCallback(
    (v: View) => {
      let cb = measureElCallbacks.current[v];
      if (!cb) {
        cb = (el: HTMLElement | null) => {
          const changed = measureEls.current[v] !== el;
          measureEls.current[v] = el;
          if (changed && v === viewRef.current && el) setMeasureTick((n) => n + 1);
        };
        measureElCallbacks.current[v] = cb;
      }
      return cb;
    },
    [],
  );

  // Only the capture card is content-measured — it grows when the ThinkingPanel
  // expands and must track that exactly. List panels (settings/vault/inbox/
  // stats) use one canonical height so cycling between them never jaws the
  // window, and so flex:1 + internal-scroll panels (VaultManager) have a
  // definite height to fill.
  useEffect(() => {
    if (view !== "capture") return;
    const el = measureEls.current.capture;
    if (!el) return;
    const measure = () => {
      const h = el.scrollHeight;
      if (h > 0) setContentH(h);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [view, measureTick]);

  const displayH =
    view === "capture" ? Math.min(contentH, MAX_CONTENT_H) : SECONDARY_H;

  const pillBoxW = showPill ? PILL_DIMS[displayMode as PillMode].w + PILL_MARGIN * 2 : 480;
  const pillBoxH = showPill ? PILL_DIMS[displayMode as PillMode].h + PILL_MARGIN * 2 : displayH + V_MARGIN;

  // While the pill menu is open, the OS window must grow to contain it (it's
  // sized tightly around the idle pill otherwise — see for_sonnet.md §5.5,
  // "the window-clipping problem"). Radial needs room in every direction (a
  // custom-position fan can open as a near-full wheel); capsule only grows
  // wider, same height.
  const RADIAL_MENU_BOX = Math.round((radialTuning.radius + radialTuning.chipMax / 2 + PILL_MARGIN) * 2);
  // Capsule open width additionally reserves a transparent click-to-close
  // padding strip on the inner side (for_sonnet.md Problem 3, Option A).
  const CLOSE_PAD_W = 64;
  const menuBoxW = displayMode === "minimal" ? RADIAL_MENU_BOX : CAPSULE_OPEN_W + PILL_MARGIN * 2 + CLOSE_PAD_W;
  const menuBoxH = displayMode === "minimal" ? RADIAL_MENU_BOX : PILL_DIMS.capsule.h + PILL_MARGIN * 2;
  const menuOpenGrowsPillWindow = showPill && menuOpen;
  const targetWinW = menuOpenGrowsPillWindow ? menuBoxW : pillBoxW;
  const targetWinH = menuOpenGrowsPillWindow ? menuBoxH : pillBoxH;

  // Remember window position across restarts. The window is created hidden
  // (tauri.conf.json `visible: false`) and only ever shown via the global
  // hotkey/tray click, so this restore always lands before the user can see
  // it -- no flash. Header bars (drag-region) in every panel and both pill
  // shapes make the window freely draggable, so this isn't just the pill's
  // anchor system: it also covers the full expanded view, which the anchor
  // effect below never positions at all.
  const WINDOW_POS_KEY = "omni-window-pos";

  // Guards every programmatic setPosition (pill-anchor snap, secondary-panel
  // recenter, Custom-position restore, menu open/close) so the onMoved
  // listener below never mistakes one of those for a real user drag and
  // overwrites the saved Custom position with a centered/anchored coordinate.
  //
  // A depth counter, not a boolean (for_sonnet_pill_fix.md Phase 1): more
  // than one programmatic move can briefly overlap (menu effect + a
  // monitor-switch re-anchor), and a boolean lets one's expiry clear the
  // other's guard. Each call brackets the *actual* setPosition/setSize only
  // (begin right before, end right after) — never a fixed timeout guessed to
  // outlast an animation, which is what raced the radial fan's longer exit
  // and let onMoved treat the close move as a user drag (Bug A).
  const programmaticMoveDepth = useRef(0);
  const beginProgrammaticMove = () => { programmaticMoveDepth.current++; };
  const endProgrammaticMove = () => {
    // Defer: onMoved for the just-issued setPosition can fire a tick later.
    setTimeout(() => {
      programmaticMoveDepth.current = Math.max(0, programmaticMoveDepth.current - 1);
    }, 120);
  };

  // Refs mirroring render-time values the onMoved listener (mounted once,
  // below) needs to read live without re-subscribing every render.
  const snapStateRef = useRef({
    anchor: pillAnchor, snapEnabled: pillSnapEnabled, showPill, menuOpen, w: pillBoxW, h: pillBoxH,
    pillW: PILL_DIMS[displayMode as PillMode].w, pillH: PILL_DIMS[displayMode as PillMode].h,
  });
  useEffect(() => {
    snapStateRef.current = {
      anchor: pillAnchor, snapEnabled: pillSnapEnabled, showPill, menuOpen, w: pillBoxW, h: pillBoxH,
      pillW: PILL_DIMS[displayMode as PillMode].w, pillH: PILL_DIMS[displayMode as PillMode].h,
    };
  }, [pillAnchor, pillSnapEnabled, showPill, menuOpen, pillBoxW, pillBoxH, displayMode]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let saveTimer: ReturnType<typeof setTimeout> | undefined;
    (async () => {
      try {
        const saved = localStorage.getItem(WINDOW_POS_KEY);
        if (saved) {
          const { x, y } = JSON.parse(saved);
          if (typeof x === "number" && typeof y === "number") {
            await getCurrentWindow().setPosition(new PhysicalPosition(x, y));
          }
        }
      } catch { /* ignore */ }
      try {
        unlisten = await getCurrentWindow().onMoved(({ payload }) => {
          if (programmaticMoveDepth.current > 0) return;
          clearTimeout(saveTimer);
          let { x, y } = payload;
          void (async () => {
            // Hard containment now lives in tickDragFrame/runFling, which
            // clamp every setPosition before it's issued (P0-2) — the pill
            // can no longer leave the monitor in the first place, so the
            // animated correction that used to live here only fought that
            // loop and caused edge oscillation. Removed; save+snap below
            // are unaffected.
            saveTimer = setTimeout(() => {
            void (async () => {
              const { anchor, snapEnabled, showPill: pillShown, menuOpen: isMenuOpen, w, h } = snapStateRef.current;
              // Snap-to-edge/corner magnet (for_sonnet.md "New Settings" §2):
              // only on Custom placement, only while the menu is closed (a
              // drag closes the menu per decision #4b, so by the time motion
              // settles the menu is always closed already), released within
              // SNAP_THRESHOLD_PX of a screen edge.
              if (anchor === "custom" && snapEnabled && pillShown && !isMenuOpen) {
                try {
                  const win = getCurrentWindow();
                  const scale = await win.scaleFactor();
                  const lx = x / scale;
                  const ly = y / scale;
                  const area = await getActiveWorkArea();
                  const margin = 12;
                  const nearLeft   = lx <= area.x + SNAP_THRESHOLD_PX;
                  const nearRight  = area.x + area.w - (lx + w) <= SNAP_THRESHOLD_PX;
                  const nearTop    = ly <= area.y + SNAP_THRESHOLD_PX;
                  const nearBottom = area.y + area.h - (ly + h) <= SNAP_THRESHOLD_PX;
                  const snappedX = nearLeft ? area.x + margin : nearRight ? area.x + area.w - w - margin : lx;
                  const snappedY = nearTop ? area.y + margin : nearBottom ? area.y + area.h - h - margin : ly;
                  if (snappedX !== lx || snappedY !== ly) {
                    beginProgrammaticMove();
                    try {
                      await win.setPosition(new LogicalPosition(snappedX, snappedY));
                    } finally {
                      endProgrammaticMove();
                    }
                    x = Math.round(snappedX * scale);
                    y = Math.round(snappedY * scale);
                  }
                } catch { /* ignore */ }
              }
              try {
                localStorage.setItem(WINDOW_POS_KEY, JSON.stringify({ x, y }));
              } catch { /* ignore */ }
            })();
            }, 300);
          })();
        });
      } catch { /* ignore */ }
    })();
    return () => { clearTimeout(saveTimer); unlisten?.(); };
  }, []);

  // ── §3 Custom pointer-driven pill drag (fling + clamp) ──────────────────
  // Replaces -webkit-app-region: drag for the pill specifically — only a
  // JS-owned gesture can decelerate via spring.ts on release. Live moves
  // reuse the same hard-containment clamp the onMoved listener applies
  // after an OS drag; every setPosition this gesture issues is already
  // clamped, so onMoved's clamp recheck on these synthetic moves is a
  // harmless no-op, and its existing 300ms-debounced save + edge-snap still
  // fire naturally off our own moves — no need to duplicate that logic
  // here (§3.2 "preserve the existing SNAP_THRESHOLD_PX... and snap-
  // disabled setting").
  const [pillGrabbed, setPillGrabbed] = useState(false);
  const dragGestureRef = useRef<{
    pointerId: number;
    startTopLeftLogical: Point;
    startCursorLogical: Point;
    lastCursorLogical: Point;
    velocity: Point;
    lastSampleTime: number;
    scale: number;
    rafPending: boolean;
    // ponytail: read once at gesture start, not re-read per frame — a drag
    // gesture is single-monitor by design (see tickDragFrame), so caching
    // removes a per-frame async Tauri call from the hot path (P1-2).
    monitorBounds: { x: number; y: number; w: number; h: number };
    winLogicalW: number;
    winLogicalH: number;
  } | null>(null);

  const draggedRef = useRef(false);
  const DRAG_CLICK_THRESHOLD_PX = 4; // logical px of movement before a release's synthetic click is swallowed

  const FLING_DAMPING = 6;
  const FLING_REST_VELOCITY = 30; // logical px/s
  const FLING_MIN_SPEED = 80; // logical px/s — below this, release just settles in place

  const tickDragFrame = useCallback(async () => {
    const g = dragGestureRef.current;
    if (!g) return;
    g.rafPending = false;
    const cur = g.lastCursorLogical;
    // ponytail: fixed scale for the whole gesture (single-monitor-per-drag
    // confirmed sufficient — drag-through across monitors isn't required).
    const deltaLogical: Point = { x: cur.x - g.startCursorLogical.x, y: cur.y - g.startCursorLogical.y };
    const next = nextWindowTopLeft(g.startTopLeftLogical, deltaLogical);
    // Hard-stop at the monitor edge during the live gesture itself (P0-2):
    // the drag is JS-pointer-driven and issues its own setPosition every
    // frame, so the window must clamp here rather than relying on onMoved's
    // (now-removed) post-hoc tween, which fought this loop and oscillated.
    const margin = PILL_MARGIN;
    const pillW = g.winLogicalW - margin * 2;
    const pillH = g.winLogicalH - margin * 2;
    const clamped = clampPillWindowToMonitor({ windowTopLeftLogical: next, pillW, pillH, margin, monitorBounds: g.monitorBounds });
    geoClamp("drag.tick", { windowTopLeftLogical: next, monitorBounds: g.monitorBounds, pillW, pillH, margin, result: clamped });
    try { await getCurrentWindow().setPosition(new LogicalPosition(clamped.x, clamped.y)); } catch { /* ignore */ }
  }, []);

  const runFling = useCallback((startLogical: Point, releaseVelocityLogical: Point, monitorBounds: { x: number; y: number; w: number; h: number }, winLogical: { w: number; h: number }) => {
    const win = getCurrentWindow();
    let sx = createSpring(startLogical.x, startLogical.x, releaseVelocityLogical.x);
    let sy = createSpring(startLogical.y, startLogical.y, releaseVelocityLogical.y);
    let last = performance.now();
    const margin = PILL_MARGIN;
    const pillW = winLogical.w - margin * 2;
    const pillH = winLogical.h - margin * 2;

    const step = async () => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      // Target tracks current position every tick, so stepSpring's restoring
      // force is always ~0 and only damping decays velocity — plain momentum
      // decay reusing the spring integrator's math, not a "pull back" spring.
      sx = stepSpring({ ...sx, target: sx.pos }, dt, { stiffness: 0, damping: FLING_DAMPING, restVelocity: FLING_REST_VELOCITY });
      sy = stepSpring({ ...sy, target: sy.pos }, dt, { stiffness: 0, damping: FLING_DAMPING, restVelocity: FLING_REST_VELOCITY });

      const rawPos: Point = { x: sx.pos, y: sy.pos };
      // monitorBounds fixed for the whole fling (captured at release) — the
      // window must never cross onto a different display mid-flight, same
      // lock tickDragFrame already applies during the live drag itself.
      const clamped = clampPillWindowToMonitor({ windowTopLeftLogical: rawPos, pillW, pillH, margin: PILL_MARGIN, monitorBounds });
      geoClamp("fling.step", { windowTopLeftLogical: rawPos, monitorBounds, pillW, pillH, margin: PILL_MARGIN, result: clamped });
      const zeroed = zeroVelocityAtClamp(rawPos, clamped, { x: sx.vel, y: sy.vel });
      sx = { ...sx, pos: clamped.x, vel: zeroed.x };
      sy = { ...sy, pos: clamped.y, vel: zeroed.y };

      try { await win.setPosition(new LogicalPosition(clamped.x, clamped.y)); } catch { /* ignore */ }

      const settled = Math.abs(sx.vel) < FLING_REST_VELOCITY && Math.abs(sy.vel) < FLING_REST_VELOCITY;
      if (!settled) requestAnimationFrame(() => { void step(); });
    };
    void step();
  }, []);

  const handlePillDragPointerDown = useCallback(async (e: React.PointerEvent) => {
    if (menuOpen) return;
    e.preventDefault();
    setPillGrabbed(true);
    draggedRef.current = false;

    const onMove = (ev: PointerEvent) => {
      const g = dragGestureRef.current;
      if (!g || ev.pointerId !== g.pointerId) return;
      const now = performance.now();
      const dt = (now - g.lastSampleTime) / 1000;
      const deltaLogical: Point = { x: ev.screenX - g.lastCursorLogical.x, y: ev.screenY - g.lastCursorLogical.y };
      g.velocity = emaVelocity(g.velocity, deltaLogical, dt);
      g.lastCursorLogical = { x: ev.screenX, y: ev.screenY };
      g.lastSampleTime = now;
      // Bug 3: any real movement during this gesture means the upcoming
      // synthetic `click` on pointerup is a drag artifact, not an intentional
      // tap — swallow it once in the button's onClick.
      if (Math.hypot(ev.screenX - g.startCursorLogical.x, ev.screenY - g.startCursorLogical.y) > DRAG_CLICK_THRESHOLD_PX) {
        draggedRef.current = true;
      }
      if (!g.rafPending) {
        g.rafPending = true;
        requestAnimationFrame(() => { void tickDragFrame(); });
      }
    };

    const onUp = async (ev: PointerEvent) => {
      if (ev.pointerId !== e.pointerId) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      setPillGrabbed(false);

      // Fast-release race: pointerup can fire before the awaited setup below
      // populates dragGestureRef (e.g. a quick tap-and-release) — nothing to
      // fling yet, the click-toggle path handles it instead.
      const g = dragGestureRef.current;
      dragGestureRef.current = null;
      if (!g) return;

      const speed = Math.hypot(g.velocity.x, g.velocity.y);
      if (speed < FLING_MIN_SPEED) return;
      try {
        const win = getCurrentWindow();
        const pos = await win.outerPosition();
        runFling({ x: pos.x / g.scale, y: pos.y / g.scale }, g.velocity, g.monitorBounds, { w: g.winLogicalW, h: g.winLogicalH });
      } catch { /* ignore */ }
    };

    // Registered synchronously, before the awaits below populate gesture
    // state, so a pointerup that fires mid-setup is still caught instead of
    // leaving the pill stuck "grabbed".
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);

    try {
      const win = getCurrentWindow();

      // for_sonnet.md (pill-drag-close-race): if a close is still settling
      // (pillBoxBeforeMenuRef only ever non-null in that window, since the
      // pill is draggable only while menuOpen is false), grabbing the pill
      // finalizes the close immediately instead of racing it — cancel the
      // in-flight reconcile, snap to the known settled geometry, then drag
      // from there. The live outerPosition() read during that tail is the
      // stale open-state window top-left, not where the pill visually is.
      const settledIdleTopLeft = pillBoxBeforeMenuRef.current;
      if (settledIdleTopLeft) {
        ++reconcileToken.current;
        beginProgrammaticMove();
        try {
          await setWindowGeometryInstant({ w: pillBoxW, h: pillBoxH }, settledIdleTopLeft);
        } finally {
          endProgrammaticMove();
        }
        setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
        pillBoxBeforeMenuRef.current = null;
      }

      const [pos, size, scale] = await Promise.all([win.outerPosition(), win.outerSize(), win.scaleFactor()]);
      const liveTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
      // The pill is only draggable while showPill && !menuOpen (isPillDraggable),
      // so the intended window footprint is deterministically the idle pill box
      // (snapStateRef.w/h = pillBoxW/H). A live outerSize() read can momentarily
      // report the full-panel size (480×544) right after returning from a tab —
      // an uncancelled grow rAF finishing after the shrink — which clamps the
      // drag to a phantom boundary short by exactly the panel-minus-pill delta
      // (boundary_bug-solution.md; supersedes the live-footprint approach in
      // for_sonnet_boundary_calibration.md §1). Trust the known box.
      const winLogicalW = snapStateRef.current.w;
      const winLogicalH = snapStateRef.current.h;
      // Belt-and-suspenders: heal the size desync at the source — if the OS
      // window is still panel-sized, snap it back to the pill box before the
      // drag so the transparent window isn't oversized under the visible pill.
      if (Math.abs(size.width / scale - winLogicalW) > 1 || Math.abs(size.height / scale - winLogicalH) > 1) {
        beginProgrammaticMove();
        try { await win.setSize(new LogicalSize(winLogicalW, winLogicalH)); } catch { /* ignore */ }
        finally { endProgrammaticMove(); }
      }
      const startTopLeftLogical = dragStartBaseline(settledIdleTopLeft, liveTopLeftLogical);
      const { pillW, pillH } = snapStateRef.current;
      const centerPhysical = { x: pos.x + (pillW * scale) / 2, y: pos.y + (pillH * scale) / 2 };
      const monitorBounds = await getActiveMonitorBounds(centerPhysical);
      await geoSnapshot("drag.pointerdown", { centerPhysical, monitorBounds, pillW, pillH, scale });
      dragGestureRef.current = {
        pointerId: e.pointerId,
        startTopLeftLogical,
        startCursorLogical: { x: e.screenX, y: e.screenY },
        lastCursorLogical: { x: e.screenX, y: e.screenY },
        velocity: { x: 0, y: 0 },
        lastSampleTime: performance.now(),
        scale,
        rafPending: false,
        monitorBounds,
        winLogicalW,
        winLogicalH,
      };
    } catch {
      setPillGrabbed(false);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    }
  }, [menuOpen, runFling, tickDragFrame]);

  // Whenever the window resizes (pill <-> secondary panel <-> full capture,
  // or Display Mode itself changing), reassert Placement: any fixed anchor
  // (not "custom") always wins and snaps the window — pill-sized, secondary
  // panel, or full capture alike — to that corner, sized for whatever the
  // new targetWinW/targetWinH actually are. This covers Full display mode
  // too (placement used to be a pill-only no-op there).
  //
  // "custom" means "leave it wherever it was dragged" and has no anchor to
  // snap back to, so it instead needs the recenter-to-middle/restore dance:
  // growing out of the pill shape into a much wider panel at the old small
  // pill's corner position would otherwise hang off-screen.
  const prevShowPillRef = useRef(showPill);
  const prePanelPos = useRef<{ x: number; y: number } | null>(null);
  // The monitor the pill was actually on when Settings opened (captured
  // alongside prePanelPos, same moment) — for_sonnet.md §4: if the user
  // picks a *different* monitor while in Settings, comparing this against
  // the now-current selection on close is what tells the restore branch
  // below "the monitor changed, don't just replay the old position."
  const prePanelMonitorRef = useRef<MonitorInfo | null>(null);
  // Logical-px position of the tight pill box, captured the instant the menu
  // opens (custom anchor only — pinned anchors re-derive their position from
  // anchorPosition() on every size change, no memory needed). Restored
  // exactly on close so repeated open/close cycles never drift.
  const prevMenuOpenRef = useRef(menuOpen);
  const pillBoxBeforeMenuRef = useRef<{ x: number; y: number } | null>(null);

  // Grow the OS window immediately (nothing to clip); shrink only after the
  // 200ms cross-fade/collapse has finished, so the outgoing panel's still-
  // fading bottom is never sheared.
  const prevSize = useRef({ w: targetWinW, h: targetWinH });
  // Cancellation token (for_sonnet_pill_fix.md Phase 3, D1): bumped at the
  // top of every effect run. A newer toggle invalidates any in-flight
  // `apply()` the moment it wakes from its next await — that run bails out
  // without touching the window or committing prev-state refs, so a fast
  // double-toggle interrupts and reverses instead of racing/glitching.
  const reconcileToken = useRef(0);
  useEffect(() => {
    const token = ++reconcileToken.current;
    const pillModeActive = displayMode !== "full";
    const prevShowPill = prevShowPillRef.current;
    const leavingPill = pillModeActive && prevShowPill && !showPill;   // pill -> full
    const enteringPill = pillModeActive && !prevShowPill && showPill; // full -> pill
    const prevMenuOpen = prevMenuOpenRef.current;
    const openingMenu = pillModeActive && showPill && prevShowPill && menuOpen && !prevMenuOpen;
    const closingMenu = pillModeActive && showPill && prevShowPill && !menuOpen && prevMenuOpen;

    // Edge detection for menu open/close is pure UI intent — advance the
    // baseline the moment this effect observes a new menuOpen, not at the end
    // of a possibly-deferred/superseded apply(). A fast re-open during the
    // radial exit used to leave this ref stale-true (close's apply bailed at
    // the token check / was cancelled before committing it), so the reopen
    // failed the openingMenu edge and never set fanReady — fan never rendered.
    prevMenuOpenRef.current = menuOpen;

    // Expanding out of the pill is always treated as "growing" (start the
    // grow immediately) even though prevSize/targetWinH comparisons alone
    // might disagree — there's no outgoing full-size content to protect from
    // shearing yet (renderPill is about to flip the tree to the full view).
    // Collapsing into the pill keeps the existing shrink-delay gate, which
    // now doubles as the window for the content fade-out below to play.
    const growing = leavingPill || targetWinH >= prevSize.current.h;

    // Kick off the content hide/tree-swap synchronously, in the same tick
    // the crossing is detected — not inside `apply()` — so the fade-out (or
    // the full tree's hidden-but-mounted grow-in) starts immediately rather
    // than waiting on the shrink-delay timer below.
    if (leavingPill) {
      setRenderPill(false);
      setContentHidden(true);
    } else if (enteringPill) {
      setContentHidden(true);
    }

    const apply = async () => {
      if (pillAnchor === "custom" && leavingPill) {
        try {
          // Store the pill's LOGICAL top-left. Logical is the only persisted
          // coordinate convention (CLAUDE.md hard rule); round-tripping through
          // physical and dividing by a scale re-read on a *different* monitor
          // (Settings centers on primary) mis-scales the restore on mixed-DPI
          // multi-monitor setups (for_sonnet_boundary_calibration.md §1).
          if (prevMenuOpen && pillBoxBeforeMenuRef.current) {
            // Already logical — store as-is, no scale conversion.
            prePanelPos.current = {
              x: pillBoxBeforeMenuRef.current.x,
              y: pillBoxBeforeMenuRef.current.y,
            };
          } else {
            const scale = await getCurrentWindow().scaleFactor(); // pill's own monitor, settled
            const pos = await getCurrentWindow().outerPosition();
            prePanelPos.current = { x: pos.x / scale, y: pos.y / scale };
          }
          prePanelMonitorRef.current = resolveTargetMonitor(monitors, selectedMonitorId);
        } catch { /* ignore */ }
        await geoSnapshot("leavePill.save");
      }

      // for_sonnet.md §4: an explicit display-picker selection overrides
      // "whichever monitor the window happens to be on" for every anchored
      // placement — not just the one-off move-now click — so a pinned pill
      // stays on the chosen monitor across mode/view switches too.
      const pickedMonitor = resolveTargetMonitor(monitors, selectedMonitorId);

      let targetPos: { x: number; y: number } | null = null;
      if (pillAnchor !== "custom" && !openingMenu && !closingMenu) {
        const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
        targetPos = anchorPosition(pillAnchor, targetWinW, targetWinH, area);
      } else if (enteringPill && prePanelPos.current) {
        const restore = prePanelPos.current;
        const oldMonitor = prePanelMonitorRef.current;
        prePanelPos.current = null;
        prePanelMonitorRef.current = null;
        const monitorChanged = oldMonitor && pickedMonitor && oldMonitor.id !== pickedMonitor.id;
        if (monitorChanged && oldMonitor && pickedMonitor) {
          // §4 user decision: land at the same proportional position
          // relative to the new monitor's centre, not a flat re-centre and
          // not a literal pixel-offset carry-over.
          try {
            const oldCenterLogical = {
              x: restore.x + targetWinW / 2,   // restore is LOGICAL now
              y: restore.y + targetWinH / 2,
            };
            targetPos = computeProportionalMonitorMove({
              oldCenterLogical,
              oldWorkArea: oldMonitor.workArea,
              newWorkArea: pickedMonitor.workArea,
              winW: targetWinW,
              winH: targetWinH,
            });
          } catch { /* ignore */ }
        } else {
          try {
            const restoreLogical = { x: restore.x, y: restore.y }; // already logical
            // Resolve the clamp monitor from the pill's OWN monitor scale (saved
            // at leave time), never the post-Settings window scale.
            const s = oldMonitor?.workArea.scale ?? await getCurrentWindow().scaleFactor();
            // Belt-and-suspenders: a bad/stale saved position must never push the
            // pill off the monitor (for_sonnet_capsule_offscreen.md §2). Same hard
            // clamp the live-drag gesture uses.
            const pillCenterPhysical = {
              x: (restoreLogical.x + targetWinW / 2) * s,
              y: (restoreLogical.y + targetWinH / 2) * s,
            };
            const bounds = await getActiveMonitorBounds(pillCenterPhysical);
            targetPos = clampPillWindowToMonitor({
              windowTopLeftLogical: restoreLogical,
              pillW: PILL_DIMS[displayMode as PillMode].w,
              pillH: PILL_DIMS[displayMode as PillMode].h,
              margin: PILL_MARGIN,
              monitorBounds: bounds,
            });
            geoClamp("restore", { windowTopLeftLogical: restoreLogical, monitorBounds: bounds, pillW: PILL_DIMS[displayMode as PillMode].w, pillH: PILL_DIMS[displayMode as PillMode].h, margin: PILL_MARGIN, result: targetPos });
          } catch { /* ignore */ }
        }
      } else if (leavingPill) {
        const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
        targetPos = { x: Math.round(area.x + (area.w - targetWinW) / 2), y: Math.round(area.y + (area.h - targetWinH) / 2) };
      } else if (openingMenu && displayMode === "minimal") {
        // Single-window collapse (for_sonnet.md §3): the pill window itself
        // grows to RADIAL_MENU_BOX, centred on the pill's stable visual
        // center, exactly like capsule's grow below — RadialMenu now renders
        // in-process (PillOverlay), so there is no overlay window to
        // position/emit to anymore. Keep the pill's visual center fixed
        // while the window grows around it, same discipline as capsule.
        if (pillAnchor !== "custom") {
          // Fixed anchor: derive position deterministically — no live read,
          // no drift. The grown window is anchored to the same corner as the
          // idle pill; fan geometry uses the window center as pill center
          // (wrapper offset stays at PILL_MARGIN, i.e. the pill sits inside
          // the top-left of the grown window at its own corner).
          try {
            const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
            targetPos = anchoredMenuPosition(pillAnchor, targetWinW, targetWinH, area);
            if (token !== reconcileToken.current) return;
            if (targetPos) {
              setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
              const cx = targetPos.x + targetWinW / 2, cy = targetPos.y + targetWinH / 2;
              if (token !== reconcileToken.current) return;
              setRadialPillGeometry({ cx, cy, sw: area.w, sh: area.h, originX: area.x, originY: area.y });
            }
          } catch { /* ignore */ }
        } else {
          try {
            // Reuse the stored idle top-left if a prior close was interrupted
            // before it cleared it (fast re-open) — that ref is the pill's
            // true idle position, a fresh live read mid-resize would not be.
            let idleTopLeftLogical = pillBoxBeforeMenuRef.current;
            const scale = await getCurrentWindow().scaleFactor();
            if (!idleTopLeftLogical) {
              const pos = await getCurrentWindow().outerPosition();
              idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
            }
            pillBoxBeforeMenuRef.current = idleTopLeftLogical;
            logger.info("menu", "menu opened", { displayMode, pos: idleTopLeftLogical });

            const pillCenterLogical = {
              x: idleTopLeftLogical.x + pillBoxW / 2,
              y: idleTopLeftLogical.y + pillBoxH / 2,
            };

            // Resolve the monitor from the pill's own (stable) center, not the
            // grown window's center — same convention as capsule below.
            const pillCenterPhysical = { x: pillCenterLogical.x * scale, y: pillCenterLogical.y * scale };
            const monitorBounds = await getActiveMonitorBounds(pillCenterPhysical);

            // §3.3 user decision: the monitor the pill is assigned to is a
            // hard boundary — the grown window must never overhang onto a
            // neighbor monitor; that edge behaves exactly like any other
            // screen edge. computeMinimalMenuWindow reuses the same clamp the
            // live-drag gesture already applies to the idle pill, sized to
            // the full grown window instead of the bare pill, and is the same
            // pure function the close path below calls — open and close can
            // no longer drift apart (Phase 2).
            const { windowTopLeftLogical, wrapperOffset } = computeMinimalMenuWindow({
              open: true,
              idleTopLeftLogical,
              idlePillBoxW: pillBoxW,
              idlePillBoxH: pillBoxH,
              pillW: PILL_DIMS.minimal.w,
              pillH: PILL_DIMS.minimal.h,
              menuBoxW: targetWinW,
              menuBoxH: targetWinH,
              margin: PILL_MARGIN,
              monitorBounds,
            });
            targetPos = windowTopLeftLogical;

            // for_sonnet.md (pill-fan-clip): a superseded reconcile must not
            // write stale offset/geometry into state — the only check below
            // (after preMoveDelayMs) runs too late to stop *this* write, since
            // it already happened. Bail here, before either setState, the
            // instant a newer reconcile has taken over.
            if (token !== reconcileToken.current) return;

            // The pill+fan wrapper's position *within* the window: normally
            // dead-center (matches the idle margin), but shifted off-center
            // exactly when the clamp above moved the window without moving
            // the pill's own on-screen position.
            setMinimalWrapperOffset(wrapperOffset);

            // unifiedFan's screen-edge containment math needs the pill's
            // absolute center plus the monitor work area it's on — independent
            // of the window's own (possibly clamped) position.
            const area = await getActiveWorkArea(pillCenterPhysical);
            if (token !== reconcileToken.current) return;
            setRadialPillGeometry({
              cx: pillCenterLogical.x, cy: pillCenterLogical.y,
              sw: area.w, sh: area.h, originX: area.x, originY: area.y,
            });
          } catch { /* ignore */ }
        }
      } else if (openingMenu) {
        // Capsule (single-window edge-aware grow). Keep the pill's
        // visual center fixed while the window grows around it (for_sonnet.md
        // Bug 2). The idle top-left is read live here — that's safe, the
        // window is settled and wholly on one monitor while idle — but
        // everything downstream uses the known-constant idle box size
        // (pillBoxW/H) instead of a live outerSize() re-read, and that same
        // scale factor is never re-read after the window grows, so the math
        // can't get corrupted mid-grow.
        if (pillAnchor !== "custom") {
          // Fixed anchor: anchor the grown capsule window deterministically,
          // derive nearEdge from the anchor itself (no live read needed).
          try {
            const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
            targetPos = anchoredMenuPosition(pillAnchor, targetWinW, targetWinH, area);
            const nearEdge: "left" | "right" =
              (pillAnchor === "tr" || pillAnchor === "rc" || pillAnchor === "br") ? "right" : "left";
            setCapsuleNearEdge(nearEdge);
          } catch { /* ignore */ }
        } else {
          try {
            const scale = await getCurrentWindow().scaleFactor();
            const pos = await getCurrentWindow().outerPosition();
            const idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
            pillBoxBeforeMenuRef.current = idleTopLeftLogical;
            logger.info("menu", "menu opened", { displayMode, pos: idleTopLeftLogical });

            const { pillCenterLogical } = computeMenuGeometry({
              idleTopLeftLogical,
              idlePillBoxW: pillBoxW,
              idlePillBoxH: pillBoxH,
              targetWinW,
              targetWinH,
            });

            // Resolve the monitor from the pill's own (stable) center, not the
            // grown window's center — otherwise a pill near a shared edge can
            // have its geometry flip to the neighbor monitor as the window
            // grows past the boundary.
            const pillCenterPhysical = { x: pillCenterLogical.x * scale, y: pillCenterLogical.y * scale };

            // Capsule edge-aware open (for_sonnet.md Problem 3): the bar
            // hugs whichever screen edge the pill is nearer to, and the
            // close-padding grows toward the screen center.
            const monitorBounds = await getActiveMonitorBounds(pillCenterPhysical);
            const monitorMidX = monitorBounds.x + monitorBounds.w / 2;
            const nearEdge: "left" | "right" = pillCenterLogical.x > monitorMidX ? "right" : "left";
            setCapsuleNearEdge(nearEdge);

            const capsuleGeom = computeCapsuleMenuGeometry({
              idleTopLeftLogical,
              idlePillBoxW: pillBoxW,
              idlePillBoxH: pillBoxH,
              margin: PILL_MARGIN,
              capsuleOpenW: CAPSULE_OPEN_W,
              closePadW: CLOSE_PAD_W,
              nearEdge,
            });
            targetPos = capsuleGeom.windowTopLeftLogical;
          } catch { /* ignore */ }
        }
      } else if (closingMenu) {
        if (pillAnchor !== "custom") {
          // Fixed anchor: restore to the anchored idle position deterministically
          // — same pure math as open, no stale live-read ref needed.
          try {
            const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
            targetPos = anchoredMenuPosition(pillAnchor, pillBoxW, pillBoxH, area);
          } catch { /* ignore */ }
        } else if (pillBoxBeforeMenuRef.current) {
          // for_sonnet_pill_fix.md §3: close must mirror open exactly, not
          // re-center. For capsule, computeCapsuleMenuGeometry's pinned-edge
          // formula evaluated at the closed (idle) width collapses to the
          // literal idle top-left for either edge (see menuGeometry.test.ts).
          // For minimal, computeMinimalMenuWindow's `open: false` case is
          // exactly the idle top-left by construction (Phase 2) — close can
          // no longer drift from open because it's the same pure function.
          targetPos = pillBoxBeforeMenuRef.current;
          logger.info("menu", "menu closed", { displayMode, pos: targetPos });
          // NOTE: pillBoxBeforeMenuRef is deliberately NOT cleared here — it's
          // cleared as a post-move side effect below, only once the close has
          // actually completed and wasn't superseded by a fast re-open. The
          // minimal wrapper offset is likewise NOT reset here: the pill must
          // stay visually fixed for the whole close, and resetting it to the
          // idle margin now (while the window is still full-size for the exit
          // animation) would throw the pill to the window's corner until the
          // shrink lands. Both resets happen with the shrink instead.
        }
      } else if (
        pillAnchor === "custom" && showPill && prevShowPill &&
        !openingMenu && !closingMenu && !enteringPill && !leavingPill &&
        (targetWinW !== prevSize.current.w || targetWinH !== prevSize.current.h)
      ) {
        // Plain pill resize within pill mode (e.g. minimal -> capsule). Keep
        // the pill's visual CENTER fixed instead of its top-left, so the bar
        // doesn't lurch sideways when the window width changes (root cause A).
        // Then clamp to the pill's own monitor so the wider capsule can't land
        // straddling a multi-monitor boundary (root cause C).
        try {
          const scale = await getCurrentWindow().scaleFactor();
          const pos = await getCurrentWindow().outerPosition();
          const idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
          const { windowTopLeftLogical } = computeMenuGeometry({
            idleTopLeftLogical,
            idlePillBoxW: prevSize.current.w,
            idlePillBoxH: prevSize.current.h,
            targetWinW,
            targetWinH,
          });
          const pillCenterPhysical = {
            x: (windowTopLeftLogical.x + targetWinW / 2) * scale,
            y: (windowTopLeftLogical.y + targetWinH / 2) * scale,
          };
          const bounds = await getActiveMonitorBounds(pillCenterPhysical);
          targetPos = clampPillWindowToMonitor({
            windowTopLeftLogical,
            pillW: PILL_DIMS[displayMode as PillMode].w,
            pillH: PILL_DIMS[displayMode as PillMode].h,
            margin: PILL_MARGIN,
            monitorBounds: bounds,
          });
        } catch { /* ignore */ }
      }

      const preMoveDelayMs =
        closingMenu && displayMode === "capsule" ? CAPSULE_EXIT_MS :
        closingMenu && displayMode === "minimal" ? RADIAL_EXIT_DURATION_MS : 0;
      const moveKind: "instant" | "animate" =
        openingMenu && displayMode === "capsule" ? "animate" :
        openingMenu || closingMenu ? "instant" : "animate";

      // Capsule close must stay full-size while the DOM morph (icons
      // collapsing) plays, and the radial fan's staggered exit needs the
      // same — otherwise the window shrink clips the exit mid-animation
      // (for_sonnet.md §4.3.2/§3.2). The delay lives outside the
      // programmatic-move guard: the pill is draggable again the instant
      // the menu closes, and a real user drag during the exit window must
      // still be saved by onMoved.
      if (preMoveDelayMs > 0) await new Promise((r) => setTimeout(r, preMoveDelayMs));
      if (token !== reconcileToken.current) return; // superseded — bail without moving or committing

      beginProgrammaticMove();
      try {
        if (moveKind === "animate") await animateWindowAndSizeTo({ w: targetWinW, h: targetWinH }, targetPos, () => token !== reconcileToken.current);
        else await setWindowGeometryInstant({ w: targetWinW, h: targetWinH }, targetPos);
      } finally {
        endProgrammaticMove();
      }
      await geoSnapshot("apply.afterMove", { showPill, menuOpen, targetWinW, targetWinH });

      // Only now has the window actually finished growing to fit the fan —
      // reveal it here, never earlier, so it can't paint into a still-pill-
      // sized window mid-IPC-grow regardless of latency or fast re-open races.
      if (openingMenu && displayMode === "minimal") setFanReady(true);

      if (closingMenu && displayMode === "minimal") {
        // Reset-after-shrink: there is never a frame pairing the full-size
        // window with the idle offset (which is what made the pill jump to
        // the corner). At worst leaves the pill clipped for under a frame,
        // identical to open's path.
        setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
      }
      if (closingMenu) pillBoxBeforeMenuRef.current = null;

      // Reveal only after the window has actually finished resizing/moving —
      // the whole point being the window never shows a clipped 440px card
      // mid-grow, and never shrinks out from under still-visible content.
      if (leavingPill) setContentHidden(false);
      else if (enteringPill) setRenderPill(true);

      prevSize.current = { w: targetWinW, h: targetWinH };
      prevShowPillRef.current = showPill;
    };
    if (growing) {
      apply();
    } else {
      const t = setTimeout(apply, 220);
      return () => clearTimeout(t);
    }
  }, [targetWinW, targetWinH, showPill, pillAnchor, displayMode, menuOpen, monitors, selectedMonitorId]);

  // Display picker selection (for_sonnet.md §4). Single owner of the actual
  // move: this only updates state — the resize effect above is the sole
  // place that ever calls setSize/setPosition for a monitor switch (anchored
  // re-derives via resolveTargetMonitor on its next run; custom is handled
  // by the enteringPill branch's monitor-changed check when Settings
  // closes). Driving the move from here too would race that effect's own
  // animation, which was for_sonnet.md §2.3's root cause.
  const handleSelectMonitor = useCallback((id: string) => {
    setSelectedMonitorId(id);
  }, []);

  // ── Search action handler ────────────────────────────────────────────────
  const handleSearchAction = useCallback((action: SearchAction) => {
    if (action.kind === "openResult") {
      setOpenResult({ category: action.category, path: action.path });
      setView("vault");
    }
  }, []);

  // ── Pill menu routing (for_sonnet.md §5.1/§8.5) ─────────────────────────
  // Selecting a nav item closes the menu and expands to the full window on
  // that view; "search" opens the search modal instead of switching views.
  const handleMenuSelect = useCallback((target: Exclude<MenuTarget, "hide">) => {
    setMenuOpen(false);
    setExpanded(true);
    if (target === "search") { setSearch(true); return; }
    setView(target);
  }, []);

  // D1: a dedicated Hide item sends the app to the tray even when pinned,
  // distinct from re-clicking the pill (which only dismisses the menu).
  const handleMenuHide = useCallback(() => {
    setMenuOpen(false);
    getCurrentWindow().hide();
  }, []);

  if (renderPill) {
    // Capsule open: push the bar to whichever edge it's pinned to, leaving
    // the free space (the click-to-close padding) on the inner side
    // (for_sonnet.md Problem 3b). Minimal mode is positioned explicitly via
    // minimalWrapperOffset instead (it needs pixel-precise placement so a
    // monitor-clamp shift of the window doesn't also shift the visible
    // pill); every other state centers as before.
    const capsuleOpenJustify =
      displayMode === "capsule" && menuOpen
        ? (capsuleNearEdge === "right" ? "flex-end" : "flex-start")
        : "center";

    const pillOverlay = (
      <PillOverlay
        mode={displayMode as PillMode}
        corner={pillCorner}
        captureState={captureState}
        stepDefs={stepDefs}
        menuOpen={menuOpen}
        fanOpen={fanReady}
        nearEdge={capsuleNearEdge}
        draggable={isPillDraggable(pillAnchor, menuOpen)}
        dragging={pillGrabbed}
        onDragPointerDown={handlePillDragPointerDown}
        onToggleMenu={() => {
          // Bug 3: a drag's pointerup still fires a synthetic click on the
          // same button — swallow exactly that one click here, the shared
          // choke point both PillOverlay and CapsuleMenu route through.
          if (draggedRef.current) { draggedRef.current = false; return; }
          logger.debug("menu", "pill clicked", { wasOpen: menuOpen, displayMode });
          setMenuOpen((o) => !o);
        }}
        inboxCount={inboxCount}
        onSelect={handleMenuSelect}
        onHide={handleMenuHide}
        pillGeometry={radialPillGeometry}
        fanStyle={pillFanStyle}
      />
    );

    return (
      <div
        onClick={() => { if (menuOpen) setMenuOpen(false); }}
        style={{
          width: "100vw",
          height: "100vh",
          position: displayMode === "minimal" ? "relative" : undefined,
          display: displayMode === "minimal" ? undefined : "flex",
          alignItems: displayMode === "minimal" ? undefined : "center",
          justifyContent: displayMode === "minimal" ? undefined : capsuleOpenJustify,
          background: "transparent",
          overflow: "hidden",
        }}
      >
        {displayMode === "minimal" ? (
          <div style={{ position: "absolute", left: minimalWrapperOffset.x, top: minimalWrapperOffset.y }}>
            {pillOverlay}
          </div>
        ) : pillOverlay}
      </div>
    );
  }

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "transparent",
        overflow: "hidden",
      }}
    >
      {/*
        Explicit measured height (B1): the container is exactly as tall as the
        active view's content, so the absolutely-positioned secondary panels
        (height:100%) anchor to the true content box — Save buttons and last
        rows always visible — and the window follows on the same curve. The
        height transition keeps content + window moving together.
      */}
      <div
        style={{
          position: "relative",
          width: 440,
          height: displayH,
          transition: "height 0.2s cubic-bezier(0.16,1,0.3,1), opacity 0.2s cubic-bezier(0.16,1,0.3,1)",
          opacity: contentHidden ? 0 : 1,
          pointerEvents: contentHidden ? "none" : undefined,
        }}
      >
        <CaptureOverlay
          measureRef={setMeasureEl("capture")}
          captureState={captureState}
          stepDefs={stepDefs}
          onOpenSettings={() => setView("settings")}
          onOpenVault={() => setView("vault")}
          onOpenInbox={() => setView("inbox")}
          onOpenSearch={() => setSearch(true)}
          onOpenStats={() => setView("stats")}
          visible={view === "capture"}
          inboxCount={inboxCount}
          onCollapseToPill={displayMode !== "full" ? () => setExpanded(false) : undefined}
        />
        <SettingsPanel
          measureRef={setMeasureEl("settings")}
          visible={view === "settings"}
          onClose={() => setView("capture")}
          theme={theme}
          themeLabel={THEME_LABELS[theme]}
          onSelectTheme={selectTheme}
          displayMode={displayMode}
          onSelectDisplayMode={setDisplayMode}
          pillCorner={pillCorner}
          onSelectPillCorner={setPillCorner}
          pillPinned={pillPinned}
          onTogglePillPinned={setPillPinned}
          pillAnchor={pillAnchor}
          onSelectPillAnchor={setPillAnchor}
          pillFanStyle={pillFanStyle}
          onSelectPillFanStyle={setPillFanStyle}
          pillSnapEnabled={pillSnapEnabled}
          onTogglePillSnap={setPillSnapEnabled}
          monitors={monitors}
          selectedMonitorId={selectedMonitorId}
          onSelectMonitor={handleSelectMonitor}
        />
        <VaultManager
          measureRef={setMeasureEl("vault")}
          visible={view === "vault"}
          onClose={() => setView("capture")}
          openResult={openResult}
          onConsumeOpenResult={() => setOpenResult(null)}
        />
        <InboxPanel
          measureRef={setMeasureEl("inbox")}
          visible={view === "inbox"}
          onClose={() => setView("capture")}
          onCountChange={setInboxCount}
        />
        <StatsPanel
          measureRef={setMeasureEl("stats")}
          visible={view === "stats"}
          onClose={() => setView("capture")}
        />
      </div>

      {/* Search modal — sits above everything */}
      <SearchModal
        open={search}
        onClose={() => setSearch(false)}
        onAction={handleSearchAction}
      />

      {/* Hidden dev-only troubleshooting tuner (Ctrl+Shift+Alt+G) */}
      <DevTuner />
    </div>
  );
}
