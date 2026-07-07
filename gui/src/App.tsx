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
import { LogicalSize, LogicalPosition } from "@tauri-apps/api/dpi";
import { listen } from "@tauri-apps/api/event";
import PillOverlay, { PILL_DIMS, type PillMode, type PillCorner } from "./components/PillOverlay";
import { CAPSULE_OPEN_W, CAPSULE_EXIT_MS } from "./components/PillMenu/CapsuleMenu";
import { RADIAL_ANIM_MS, RADIAL_STAGGER_MS, type PillGeometry } from "./components/PillMenu/RadialMenu";
import { ALL_TARGETS, type MenuTarget } from "./components/PillMenu/icons";
import {
  type VerticalZone,
  type PanelExtrudeZone,
  resolveVerticalZone,
  computeCapsulePanelGeometry,
  computeIslandMorphRects,
  computePanelWindowBox,
  PANEL_EXIT_MS,
  PANEL_W,
  PANEL_H,
  PANEL_GAP,
} from "./lib/compactPanel";
import { exitDurationMs } from "./lib/menuTiming";
import { computeReconcileEdges } from "./lib/reconcileEdges";
import { computeGrowing, computeMoveTiming, computeApplyBranch } from "./lib/reconcileApply";
import DevTuner from "./components/PillMenu/DevTuner";
import { useRadialTuning } from "./lib/devTuning";
import FullWindow from "./components/FullWindow/FullWindow";
import { useCapture } from "./hooks/useCapture";
import { useVoiceRecording } from "./hooks/useVoiceRecording";
import { useLookChat } from "./hooks/useLookChat";
import { useLlmStatus } from "./hooks/useLlmStatus";
import { logger } from "./lib/logger";
import { getInbox, openFilePath, createReminder, deleteReminder } from "./lib/api";
import { makeReminderUndoState, reminderUndoRemainingMs, type ReminderUndoState } from "./lib/reminderUndoToast";
import { formatWhen } from "./lib/reminderFormat";
import { type PillAnchor, anchorPosition, anchoredMenuPosition, capsuleZoneFromPillAnchor, isPillDraggable } from "./lib/pillAnchor";
import { getActiveWorkArea, getActiveMonitorBounds, listMonitors, resolveTargetMonitor, type MonitorInfo } from "./lib/monitor";
import { computeMenuGeometry, clampPillWindowToMonitor, computeCapsuleMenuGeometry, computeProportionalMonitorMove, computeMinimalMenuWindow, resolveCapsuleZone } from "./lib/menuGeometry";
import { nextWindowTopLeft, emaVelocity, zeroVelocityAtClamp, dragStartBaseline, type Point } from "./lib/dragMath";
import { createSpring, stepSpring } from "./lib/spring";
import { setWindowNoactivate, armMenuClickAway, disarmMenuClickAway, setWindowBoundsAtomic } from "./lib/tauri";
import { geoSnapshot, geoClamp } from "./lib/geoLog";
import { useToasts } from "./hooks/useToasts";
import ToastHost from "./components/ToastHost";

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

const LOOK_MODE_KEY = "omni-look-mode";
export function getInitialLookMode(): "search" | "chat" {
  try { const s = localStorage.getItem(LOOK_MODE_KEY); if (s === "search" || s === "chat") return s; } catch { /* ignore */ }
  return "search";
}

const LOOK_CHAT_PERSIST_KEY = "omni-look-chat-persist";
export type LookChatPersist = "preserve" | "clear";
export function getInitialLookChatPersist(): LookChatPersist {
  try { const s = localStorage.getItem(LOOK_CHAT_PERSIST_KEY); if (s === "preserve" || s === "clear") return s; } catch { /* ignore */ }
  return "preserve";
}

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

type View = "capture" | "settings" | "vault" | "inbox" | "stats" | "look";

// Legacy pill-menu targets → FullWindow rail views (branch C purge).
const VIEW_TO_RAIL: Record<string, "dashboard" | "look" | "library" | "settings" | "inbox"> = {
  capture: "dashboard", look: "look", vault: "library", settings: "settings", inbox: "inbox", stats: "library",
};

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
// RC-2 watchdog ceiling: exceeds the worst legitimate open (instant move +
// island double-rAF ≈ 32ms) so it can never pre-empt the morph reveal.
const PANEL_READY_WATCHDOG_MS = 1000;

// Menu open/close (for_sonnet.md "Problem 4") gets a single atomic, instant
// resize+reposition instead of the rAF tween above — the tween's per-frame
// async setSize/setPosition pair landing at slightly different times each
// frame (while the pill is flex-centered in the window) is exactly what
// produced the open/close shake. An instant transparent-window resize is
// invisible; only the spokes/capsule-width morph (CSS) is meant to animate.
// ponytail: WS_EX_NOACTIVATE windows defer webview layout until the next input
// event, so a programmatic move looks stale until the user clicks. Force a
// synchronous reflow after the move so the pill snaps to its new spot at once.
// Upgrade path: if this ever proves insufficient, trigger a Rust-side
// window.request_redraw() instead.
function forcePillReflow() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      void document.body.getBoundingClientRect();
    });
  });
}

async function setWindowGeometryInstant(
  targetSize: { w: number; h: number } | null,
  targetPos: { x: number; y: number } | null,
) {
  const win = getCurrentWindow();
  // Atomic-first: a single Win32 SetWindowPos avoids the two-IPC-call
  // setSize+setPosition tear (visible as a two-phase snap at fractional
  // DPI). Falls back to the pre-existing two-call path on non-Windows or
  // when there's no live Tauri context (setWindowBoundsAtomic throws).
  try {
    const scale = await win.scaleFactor();
    let pos = targetPos;
    let size = targetSize;
    if (!pos || !size) {
      const [p, s] = await Promise.all([win.outerPosition(), win.outerSize()]);
      if (!pos) pos = { x: p.x / scale, y: p.y / scale };
      if (!size) size = { w: s.width / scale, h: s.height / scale };
    }
    await setWindowBoundsAtomic(pos, size, scale);
    return;
  } catch {
    // fall through to the two-call path below
  }
  const tasks: Promise<unknown>[] = [];
  if (targetSize) tasks.push(win.setSize(new LogicalSize(targetSize.w, targetSize.h)).catch(() => {}));
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
  targetSize: { w: number; h: number } | null,
  targetPos: { x: number; y: number } | null,
  cancelled?: () => boolean,
) {
  const win = getCurrentWindow();
  let startLogical: { x: number; y: number };
  let startSize: { w: number; h: number };
  let scale: number;
  try {
    scale = await win.scaleFactor();
    const p = await win.outerPosition();
    const s = await win.outerSize();
    startLogical = { x: p.x / scale, y: p.y / scale };
    startSize = { w: s.width / scale, h: s.height / scale };
  } catch {
    await setWindowGeometryInstant(targetSize, targetPos);
    return;
  }
  const endPos = targetPos ?? startLogical;
  const endSize = targetSize ?? startSize;
  const dx = endPos.x - startLogical.x;
  const dy = endPos.y - startLogical.y;
  const dw = endSize.w - startSize.w;
  const dh = endSize.h - startSize.h;
  if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(dw) < 0.5 && Math.abs(dh) < 0.5) return;

  // Atomic-first per frame: one Win32 SetWindowPos instead of the two
  // separate IPC calls (setSize then setPosition), which shear apart on the
  // pill-resize branch (visible per-frame split at fractional DPI). A failed
  // atomic call (non-Windows / no live Tauri context) permanently drops this
  // animation to the two-call fallback — no point retrying every frame.
  // `targetPos: null` collapses dx/dy to 0 above, so x/y just interpolate to
  // the constant current position — harmless to send every frame.
  let atomicOk = true;
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
      const w = startSize.w + dw * e;
      const h = startSize.h + dh * e;
      const x = startLogical.x + dx * e;
      const y = startLogical.y + dy * e;
      if (atomicOk) {
        setWindowBoundsAtomic({ x, y }, { w, h }, scale).catch(() => { atomicOk = false; });
      } else {
        if (targetSize) win.setSize(new LogicalSize(w, h)).catch(() => {});
        if (targetPos) win.setPosition(new LogicalPosition(x, y)).catch(() => {});
      }
      if (t < 1) requestAnimationFrame(frame);
      else resolve();
    };
    requestAnimationFrame(frame);
  });
}

// ── Component ──────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView]                   = useState<View>("capture");
  const [lookMode, setLookMode]           = useState<"search" | "chat">(getInitialLookMode);
  const [lookChatPersist, setLookChatPersist] = useState<LookChatPersist>(getInitialLookChatPersist);
  const [theme, setTheme]                 = useState<Theme>(getInitialTheme);
  const [inboxCount, setInboxCount]       = useState(0);
  const lookChat = useLookChat();

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
  const [capsuleExiting, setCapsuleExiting] = useState(false);
  // C2: brief red tint on the pill after a compact panel's ErrorBoundary
  // auto-collapses it (user decision). Transient — cleared by its own
  // timeout, not tied to any other lifecycle state.
  const [pillError, setPillError] = useState(false);
  const pillErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlePanelError = useCallback((_error: unknown) => {
    setPillError(true);
    if (pillErrorTimerRef.current) clearTimeout(pillErrorTimerRef.current);
    pillErrorTimerRef.current = setTimeout(() => setPillError(false), 1200);
  }, []);
  useEffect(() => () => { if (pillErrorTimerRef.current) clearTimeout(pillErrorTimerRef.current); }, []);
  // Task 2.4/M4 (combined close ONLY, pick b — overlapped stagger): armed
  // synchronously by closeCompactPanel (same discipline as capsuleExiting
  // above), cleared inside the reconcile effect's closingPanel branch after
  // the same PANEL_EXIT_MS settle wait that branch already awaits — no new
  // timer. Drives `.capsule-menu`'s width-transition delay in index.css via
  // a `data-panel-closing` attribute on the wrapper below; must never be set
  // for a stage-1-only close (bar-open -> closed, no panel), which keeps its
  // immediate 260ms shrink untouched.
  const [panelClosing, setPanelClosing] = useState(false);
  /** Capsule morph gate — same contract as fanReady: window must finish
   *  growing before the bar width morph starts, or center-zone opens paint
   *  a full-width bar into a pill-sized window (rounded corners clip square). */
  const [capsuleReady, setCapsuleReady] = useState(false);
  // Capsule-only (for_sonnet.md Problem 3): which screen edge the pill is
  // nearer to when the menu opens. The bar hugs this edge and the
  // transparent click-to-close padding grows toward the screen center.
  const [capsuleZone, setCapsuleZone] = useState<"left" | "right" | "center">("left");
  // Synchronous mirror of capsuleZone for the one consumer that runs behind
  // awaits inside apply() (the nearEdge read below) — prefetchCapsuleZone's
  // setCapsuleZone commits are batched/deferred, so a fast click can still
  // observe the stale state value there even though it's set before menuOpen
  // flips. Render sites keep reading the state, not this ref.
  const capsuleZoneRef = useRef<"left" | "right" | "center">("left");
  // Capsule visibility gate — distinct from capsuleReady (width morph) and
  // capsuleExiting. Only ever flipped false to hide the WebView2 stale-frame
  // during an origin-shifting window move (right/center zones). See
  // CAPSULE_OPEN_FLICKER_PLAN.md.
  const [capsuleShown, setCapsuleShown] = useState(true);
  // Compact-mode in-pill panel (Task 1.1): clicking a menu item in
  // Capsule/Minimal mode opens this instead of routing into FullWindow.
  // `panelReady` mirrors the capsuleReady contract (gates the panel's
  // render until the window has actually grown to fit it — wired by Task
  // 1.2's geometry work, unused visually until then). `panelZone` is the
  // vertical third the panel grows into.
  const [compactPanel, setCompactPanel] = useState<Exclude<MenuTarget, "hide"> | null>(null);
  const [panelReady, setPanelReady] = useState(false);
  // RC-2: a panel may never end blank-but-grown. Only ever forces TRUE — the
  // only setPanelReady(false) sites are synchronous edge sites (panel close in
  // closeCompactPanel, closingPanel/panelModeSwitch in the reconcile effect),
  // never async, so this can never fight a legitimate close.
  useEffect(() => {
    if (compactPanel === null || panelReady) return;
    const t = setTimeout(() => setPanelReady(true), PANEL_READY_WATCHDOG_MS);
    return () => clearTimeout(t);
  }, [compactPanel, panelReady]);
  const [panelZone, setPanelZone] = useState<VerticalZone>("top");
  // Task 2.2: the middle-float chrome variant is deleted — with bar-as-
  // header, "middle" resolves to the same top-style downward extrusion as
  // "top" (the monitor clamp inside computeCapsulePanelGeometry already
  // redirects growth if the lower half lacks room). `panelZone` itself stays
  // three-valued (resolveVerticalZone still classifies thirds), this is the
  // single mapping point feeding every geometry call and prop downstream.
  const panelExtrudeZone: PanelExtrudeZone = panelZone === "middle" ? "top" : panelZone;
  // Geometry for the compact panel's open footprint, memoized at the moment
  // the panel opens (openingPanel / panelModeSwitch edges below). State, not
  // a ref — PillOverlay must re-render when geometry is recomputed (mode
  // switch with panel open, same contract as islandMorphGeom below).
  const [capsulePanelGeom, setCapsulePanelGeom] = useState<ReturnType<typeof computeCapsulePanelGeometry> | null>(null);
  // Minimal-mode island-morph rects (Task 0.2's computeIslandMorphRects),
  // committed at the moment the panel opens (openingPanel edge below).
  // Deliberately state — the island's CSS rect-morph needs an intermediate
  // render at `startRect` (pill-sized, geometry just committed, window not
  // yet grown) BEFORE `panelReady` flips true and the CSS transition kicks
  // the rect out to `endRect`. A ref wouldn't force that extra render, and
  // both values would appear to PillOverlay in the same frame, skipping the
  // grow animation entirely.
  const [islandMorphGeom, setIslandMorphGeom] = useState<ReturnType<typeof computeIslandMorphRects> | null>(null);
  // The island DOM element must stay mounted through the whole close morph
  // (reverse rect animation + fade), even though `compactPanel` itself
  // already flips to null the instant the user clicks close (that's what
  // drives the pill's own fade-back-in and the reconcile effect's
  // closingPanel edge). This tracks "last non-null target while in minimal
  // mode" so the island keeps rendering its last content until
  // islandMorphGeom is cleared (closingPanel block above, after
  // PANEL_EXIT_MS) — mirrors, without touching, the reconcile effect itself.
  const lastMinimalPanelTargetRef = useRef<Exclude<MenuTarget, "hide"> | null>(null);
  useEffect(() => {
    if (displayMode === "minimal" && compactPanel) lastMinimalPanelTargetRef.current = compactPanel;
  }, [displayMode, compactPanel]);
  // RC-3: capsule twin of lastMinimalPanelTargetRef above — keeps CompactShell +
  // the absolute bar/panel offsets mounted through the whole PANEL_EXIT_MS
  // close, so the bar never re-centers in the still-panel-sized window.
  const lastCapsulePanelTargetRef = useRef<Exclude<MenuTarget, "hide"> | null>(null);
  useEffect(() => {
    if (displayMode === "capsule" && compactPanel) lastCapsulePanelTargetRef.current = compactPanel;
  }, [displayMode, compactPanel]);
  useEffect(() => { try { localStorage.setItem(DISPLAY_MODE_KEY, displayMode); } catch { /* ignore */ } }, [displayMode]);
  // Flash hardening: leaving Full mode always resets to the capture/dashboard
  // view and collapses the expanded window, so a later re-entry into Full
  // never briefly shows a stale non-dashboard rail view.
  const prevModeRef = useRef(displayMode);
  useEffect(() => {
    if (prevModeRef.current === "full" && displayMode !== "full") {
      setView("capture");
      setExpanded(false);
    }
    prevModeRef.current = displayMode;
  }, [displayMode]);
  useEffect(() => { try { localStorage.setItem(PILL_CORNER_KEY, pillCorner); } catch { /* ignore */ } }, [pillCorner]);
  useEffect(() => { try { localStorage.setItem(PILL_PINNED_KEY, pillPinned ? "1" : "0"); } catch { /* ignore */ } }, [pillPinned]);
  // Window starts hidden (tauri.conf.json `visible: false`) and only the tray/
  // hotkey show() it. If Stay Pinned was left on last session, restore that
  // state on launch instead of leaving the app stuck in the tray.
  useEffect(() => {
    if (getInitialPillPinned()) {
      getCurrentWindow().show().catch(() => { /* ignore */ });
    }
  }, []);
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
  const compactPanelRef = useRef(compactPanel);
  useEffect(() => { compactPanelRef.current = compactPanel; }, [compactPanel]);

  const { state: captureState, stepDefs, captureFile, captureAudio } = useCapture(holdOpenRef);
  const voice = useVoiceRecording(captureAudio);
  const llmStatus = useLlmStatus();
  const { toasts, pushToast, dismiss: dismissToast } = useToasts();

  // Pill-mode reminder-consent parity (P2): pill modes auto-create the
  // reminder (no room for the full-mode "Set reminder" toast) and instead
  // show a brief undo affordance in the pill/capsule bar itself — see the
  // reminderOffer effect below. reminderUndoTimerRef holds the auto-dismiss
  // timer so Undo can cancel it (no stray dismiss after the reminder's
  // already deleted) and so a second offer arriving mid-toast replaces it
  // cleanly instead of stacking timers.
  const [reminderUndo, setReminderUndo] = useState<ReminderUndoState | null>(null);
  const reminderUndoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearReminderUndoTimer = useCallback(() => {
    if (reminderUndoTimerRef.current !== null) {
      clearTimeout(reminderUndoTimerRef.current);
      reminderUndoTimerRef.current = null;
    }
  }, []);
  const undoReminderCreate = useCallback(() => {
    setReminderUndo((current) => {
      if (current) void Promise.all(current.ids.map((id) => deleteReminder(id).catch(() => {})));
      return null;
    });
    clearReminderUndoTimer();
  }, [clearReminderUndoTimer]);
  // Arms (or re-arms) the auto-dismiss timer whenever a new toast lands;
  // reminderUndoRemainingMs (lib/reminderUndoToast.ts) does the actual
  // countdown math so it's covered by that module's own unit tests instead
  // of only being exercised by a live setTimeout here.
  useEffect(() => {
    if (!reminderUndo) return;
    clearReminderUndoTimer();
    reminderUndoTimerRef.current = setTimeout(() => setReminderUndo(null), reminderUndoRemainingMs(reminderUndo, Date.now()));
    return clearReminderUndoTimer;
  }, [reminderUndo, clearReminderUndoTimer]);

  // Apply theme on mount and whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => { try { localStorage.setItem(LOOK_MODE_KEY, lookMode); } catch { /* ignore */ } }, [lookMode]);
  useEffect(() => { try { localStorage.setItem(LOOK_CHAT_PERSIST_KEY, lookChatPersist); } catch { /* ignore */ } }, [lookChatPersist]);

  const selectTheme = useCallback((t: Theme) => setTheme(t), []);

  // Only Capsule/Minimal ever collapse to a pill, and only in the capture
  // view — Settings/Vault/Inbox/Stats always show full-size regardless.
  const showPill = displayMode !== "full" && view === "capture" && !expanded;

  // Close synchronously arms capsuleExiting before menuOpen flips — the
  // reconcile effect's closingMenu edge runs after paint, one frame too late
  // for justify/margin, which made right-zone exits snap toward center.
  const closePillMenu = useCallback(() => {
    if (displayMode === "capsule") setCapsuleExiting(true);
    setMenuOpen(false);
  }, [displayMode]);
  const closePillMenuRef = useRef(closePillMenu);
  useEffect(() => { closePillMenuRef.current = closePillMenu; }, [closePillMenu]);

  // Task 2.1 step 4: with the bar staying open (menuOpen=true) for the whole
  // time a compact panel is out, Esc/click-away must collapse BOTH in the
  // same tick — the reconcile effect's combined edge is closingPanel alone
  // (closingMenu is guarded off by prevCompactPanel !== null, see the
  // reconcile effect below), one shrink straight to the closed-pill box, not
  // two sequential ones. Same capsuleExiting-before-flip discipline as
  // closePillMenu, for the same right/center-zone justify reason.
  const closeCompactPanel = useCallback(() => {
    if (displayMode === "capsule") { setCapsuleExiting(true); setPanelClosing(true); }
    setCompactPanel(null);
    setMenuOpen(false);
  }, [displayMode]);
  const closeCompactPanelRef = useRef(closeCompactPanel);
  useEffect(() => { closeCompactPanelRef.current = closeCompactPanel; }, [closeCompactPanel]);

  // The menu only ever exists while the pill is showing; leaving pill mode
  // for any reason (expand, view switch, display-mode switch) always closes it.
  useEffect(() => {
    if (!showPill) {
      setMenuOpen(false);
      setCapsuleExiting(false);
      setPanelClosing(false);
      setFanReady(false);
      setCapsuleReady(false);
      setRadialPillGeometry(null);
      setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
      setCompactPanel(null);
      setPanelReady(false);
      setPanelZone("top");
      // reminder-undo toast lives in the pill bar; drop it (and its dangling
      // auto-dismiss timer) when we leave pill mode so it can't fire setState
      // into a hidden bar.
      clearReminderUndoTimer();
      setReminderUndo(null);
    }
  }, [showPill, clearReminderUndoTimer]);

  // Drop the fan the instant a close begins (independent of the showPill
  // reset above, which only fires when the pill leaves entirely) — this is
  // what lets the staggered exit start immediately on a normal menu close,
  // while the window itself stays full-size until RADIAL_EXIT_DURATION_MS.
  useEffect(() => {
    if (!menuOpen) {
      setFanReady(false);
      setCapsuleReady(false);
    }
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

  // Fire toasts on phase transitions to done/error.
  const prevPhaseRef = useRef(captureState.phase);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    const curr = captureState.phase;
    prevPhaseRef.current = curr;
    if (prev !== "done" && curr === "done") {
      const short = captureState.result?.path
        ? captureState.result.path.split(/[\\/]/).slice(-2).join("/")
        : null;
      pushToast({ tone: "success", message: short ? `Saved to ${short}` : "Saved" });
    }
    if (prev !== "error" && curr === "error") {
      const msg = (captureState.errorMsg ?? "Capture failed").split("\n")[0];
      pushToast({ tone: "error", message: msg.length > 60 ? msg.slice(0, 57) + "…" : msg });
    }
  }, [captureState.phase, captureState.result, captureState.errorMsg, pushToast]);

  // Offer to set reminders for future date/time mentions detected in the
  // note just written — one glance + one click, never a form.
  const prevReminderOfferRef = useRef(captureState.reminderOffer);
  useEffect(() => {
    const offer = captureState.reminderOffer;
    if (offer && offer !== prevReminderOfferRef.current) {
      const { events, note_path } = offer;
      if (events.length > 0) {
        if (displayMode !== "full") {
          // Pill modes have no room for the full toast (window is
          // pill-sized) — auto-create instead, but show a brief undo
          // affordance in the pill/capsule bar itself (reminderUndo state
          // above) so consent stays opt-out-with-a-visible-escape-hatch
          // rather than silent. Windows notification also confirms it.
          void (async () => {
            try {
              const ids: number[] = [];
              for (const e of events) ids.push(await createReminder(note_path, e.label, e.when_iso, true));
              setReminderUndo(makeReminderUndoState(ids, events.map((e) => e.label), Date.now()));
            } catch { /* server notification path already reports; nothing to render here */ }
          })();
        } else {
          const more = events.length > 1 ? ` (+${events.length - 1} more)` : "";
          pushToast({
            tone: "info",
            message: `⏰ ${events[0].label} — ${formatWhen(events[0].when_iso, new Date())}${more}`,
            ttlMs: 12000,
            action: {
              label: "Set reminder",
              run: () => {
                void (async () => {
                  try {
                    for (const e of events) await createReminder(note_path, e.label, e.when_iso);
                    pushToast({ tone: "success", message: "Reminder set" });
                  } catch (err) {
                    pushToast({ tone: "error", message: `Reminder failed — ${err instanceof Error ? err.message : "server error"}` });
                  }
                })();
              },
            },
          });
        }
      }
    }
    prevReminderOfferRef.current = offer;
  }, [captureState.reminderOffer, pushToast, displayMode]);

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key === "k") {
        e.preventDefault();
        setView((v) => (v === "look" ? "capture" : "look"));
        return;
      }
      if (mod && e.key === ",") {
        e.preventDefault();
        setView((v) => (v === "settings" ? "capture" : "settings"));
        return;
      }
      if (mod && e.key === "\\") {
        e.preventDefault();
        setView((v) => (v === "vault" ? "capture" : "vault"));
        return;
      }
      if (mod && e.key === "i") {
        e.preventDefault();
        setView((v) => (v === "inbox" ? "capture" : "inbox"));
        return;
      }
      if (e.key === "Escape") {
        if (voice.phase === "recording") {
          voice.cancel();
          return;
        }
        if (compactPanel !== null) {
          closeCompactPanel();
          return;
        }
        if (menuOpen) {
          closePillMenu();
          return;
        }
        if (view === "look")    { setView("capture"); return; }
        if (view !== "capture"){ setView("capture"); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [view, menuOpen, compactPanel, displayMode, closePillMenu, closeCompactPanel, voice.phase, voice.cancel]);

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
          if (compactPanelRef.current !== null) {
            // Combined close (Task 2.1 step 4): both compactPanel and
            // menuOpen collapse in the same tick, so — unlike before — the
            // bar is never left stranded open underneath a hidden panel.
            closeCompactPanelRef.current();
            if (!pillPinnedRef.current) getCurrentWindow().hide();
            return;
          }
          if (!menuOpenRef.current) return;
          closePillMenuRef.current();
          if (!pillPinnedRef.current) getCurrentWindow().hide();
        });
      } catch { /* ignore */ }
    })();
    return () => { unlisten?.(); };
  }, []);

  // Arm/disarm the click-away hook while a menu or a compact panel is open.
  useEffect(() => {
    if (!menuOpen && compactPanel === null) {
      disarmMenuClickAway();
      return;
    }
    armMenuClickAway("main");
    return () => { disarmMenuClickAway(); };
  }, [menuOpen, compactPanel]);

  // Non-activating pill (for_sonnet.md Piece A): the pill and its menu must
  // never steal foreground focus from whatever app was active. Toggled off
  // only for the expanded full view, which needs real keyboard focus for
  // search/settings inputs.
  useEffect(() => {
    let alive = true;
    const panelOpen = compactPanel !== null;
    (async () => {
      // Sequential and awaited: noactivate must actually clear before we ask
      // for focus, or the focus call can win the race and land on a window
      // the OS still treats as non-activating (RC-4: dead text inputs).
      if (panelOpen || !showPill) {
        await setWindowNoactivate(false);
        if (!alive) return;
        // Panels with inputs (Look, Settings) need real keyboard focus to
        // type; a plain pill/menu never should (must not steal foreground
        // focus from whatever app was active).
        await getCurrentWindow().setFocus().catch(() => {});
      } else {
        await setWindowNoactivate(true);
      }
    })();
    return () => { alive = false; };
  }, [showPill, compactPanel]);

  // "full" has no pill; fall back so geometry math stays defined.
  const pillDims = PILL_DIMS[displayMode as PillMode] ?? PILL_DIMS.minimal;
  const FULL_WIN_W = 920;
  const FULL_WIN_H = 560;
  const FULL_WIN_MIN_W = 640;
  const FULL_WIN_MIN_H = 400;
  const pillBoxW = showPill ? pillDims.w + PILL_MARGIN * 2 : FULL_WIN_W;
  const pillBoxH = showPill ? pillDims.h + PILL_MARGIN * 2 : FULL_WIN_H;

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

  // Compact-mode panel box (Task 0.1): single source of truth for the OS
  // window size when a compact panel is open, shared with
  // computeCapsulePanelGeometry/computeIslandMorphRects so targetWinW/H
  // below (and thus the growing/shrinking edges) can never diverge from
  // what the reconcile effect's openingPanel branch actually sets.
  // Task 0.3: floor the panel window's width at the menu-open box width
  // (capsule only — CLOSE_PAD_W is a capsule-menu affordance) so the
  // OS window's width never shrinks at the menuOpen -> compactPanel handoff;
  // only height changes there.
  const panelBox = computePanelWindowBox({
    mode: displayMode === "minimal" ? "minimal" : "capsule",
    zone: panelExtrudeZone,
    pillBoxW,
    pillBoxH,
    barH: PILL_DIMS.capsule.h,
    margin: PILL_MARGIN,
    minW: displayMode === "minimal" ? undefined : menuBoxW,
  });
  const panelBoxW = panelBox.w;
  const panelBoxH = panelBox.h;
  // Task 2.1 step 2: capsule keeps the bar chrome open (menuOpen) while the
  // panel is out, so this can no longer require `!menuOpen` — the panel box
  // must win whenever a panel is open, regardless of the bar's own state.
  const panelOpenGrowsPillWindow = showPill && compactPanel !== null;

  const targetWinW = panelOpenGrowsPillWindow ? panelBoxW : menuOpenGrowsPillWindow ? menuBoxW : pillBoxW;
  const targetWinH = panelOpenGrowsPillWindow ? panelBoxH : menuOpenGrowsPillWindow ? menuBoxH : pillBoxH;

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
    pillW: pillDims.w, pillH: pillDims.h,
  });
  useEffect(() => {
    snapStateRef.current = {
      anchor: pillAnchor, snapEnabled: pillSnapEnabled, showPill, menuOpen, w: pillBoxW, h: pillBoxH,
      pillW: pillDims.w, pillH: pillDims.h,
    };
  }, [pillAnchor, pillSnapEnabled, showPill, menuOpen, pillBoxW, pillBoxH, displayMode]);

  // Full mode: OS resize on; pill modes stay fixed-size.
  useEffect(() => {
    const win = getCurrentWindow();
    if (displayMode === "full") {
      void win.setResizable(true);
      void win.setMinSize(new LogicalSize(FULL_WIN_MIN_W, FULL_WIN_MIN_H));
    } else {
      void win.setResizable(false);
      void win.setMinSize(null);
    }
  }, [displayMode]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let saveTimer: ReturnType<typeof setTimeout> | undefined;
    (async () => {
      try {
        const saved = localStorage.getItem(WINDOW_POS_KEY);
        if (saved) {
          const { x, y } = JSON.parse(saved);
          if (typeof x === "number" && typeof y === "number") {
            // Stored value is physical (raw onMoved payload) — convert to the
            // logical convention (Hard rule: only Logical* in setPosition)
            // using the scale of the monitor that actually contains the
            // stored physical point, so mixed-DPI restores land correctly.
            const { scale } = await getActiveMonitorBounds({ x, y });
            await getCurrentWindow().setPosition(new LogicalPosition(x / scale, y / scale));
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
  // Same "prev" convention as prevMenuOpenRef, for the compact panel's own
  // open/close edges (Task 1.2).
  const prevCompactPanelRef = useRef(compactPanel);

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
  const prevDisplayModeRef = useRef(displayMode);
  const fullSizeInitializedRef = useRef(false);
  // Boot visibility (persistence): the OS window starts hidden (tauri.conf
  // visible:false) and is normally shown only by the hotkey/tray. But if the
  // last session left Stay Pinned on, the pill should reappear on launch at its
  // persisted position/mode — shown here, after the first reconcile has put the
  // window at the right place, so it never flashes at the default coordinate.
  const bootShownRef = useRef(false);
  useEffect(() => {
    const token = ++reconcileToken.current;
    const prevShowPill = prevShowPillRef.current;
    const prevMenuOpen = prevMenuOpenRef.current;
    // Edge truth-table extracted to lib/reconcileEdges.ts (pure, unit-tested
    // there — including the compact->full leavingPill regression). This effect
    // keeps every ref read/commit; the function only derives booleans.
    const {
      shouldInitFullSize, leavingPill, enteringPill, openingMenu, closingMenu,
      openingPanel, closingPanel, panelModeSwitch,
    } = computeReconcileEdges({
      displayMode,
      prevDisplayMode: prevDisplayModeRef.current,
      showPill,
      prevShowPill,
      menuOpen,
      prevMenuOpen,
      compactPanel,
      prevCompactPanel: prevCompactPanelRef.current,
      fullSizeInitialized: fullSizeInitializedRef.current,
    });
    // Same "prev" edge-detection discipline as prevMenuOpenRef immediately
    // below: advance the baseline the moment this effect observes a new
    // compactPanel, not at the end of a possibly-deferred/superseded apply().
    prevCompactPanelRef.current = compactPanel;

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
    const growing = computeGrowing({ leavingPill, targetWinH, prevH: prevSize.current.h });

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

    // Panel close (mirrors panelReady's own contract): flip it false the
    // instant the close is observed, not inside `apply()` — this is what
    // starts the panel's CSS exit-clip morph immediately, same tick the
    // shrink-delay countdown below begins.
    if (closingPanel) setPanelReady(false);
    if (panelModeSwitch) setPanelReady(false);

    const apply = async () => {
      // Which reposition branch this pass takes — pure decision, extracted to
      // lib/reconcileApply.ts (computeApplyBranch) and unit-tested there.
      // hasPrePanelPos is read here, before the leavingPill-save block below
      // can write it, matching the point apply() used to read it at (the
      // enteringPill/leavingPill edges are mutually exclusive, so read-before
      // vs read-after makes no difference).
      const applyBranch = computeApplyBranch({
        displayMode, shouldInitFullSize, pillAnchor,
        openingMenu, closingMenu, openingPanel, closingPanel, panelModeSwitch,
        enteringPill, leavingPill,
        hasPrePanelPos: prePanelPos.current !== null,
        showPill, prevShowPill,
        targetWinW, targetWinH,
        prevW: prevSize.current.w, prevH: prevSize.current.h,
      });

      // Full mode: set default size once on boot/enter; user resize after that.
      if (applyBranch === "skip-full") {
        prevShowPillRef.current = showPill;
        return;
      }

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
      // applyBranch is the pure discriminant (lib/reconcileApply.ts,
      // computeApplyBranch) for which of these reposition strategies fires —
      // same condition ladder as before, unit-tested there. Bodies below are
      // untouched: every live Tauri read and setState call stays right here.
      switch (applyBranch) {
      case "anchored": {
        const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
        targetPos = anchorPosition(pillAnchor, targetWinW, targetWinH, area);
        break;
      }
      case "restore-enter-pill": {
        // applyBranch already confirmed prePanelPos.current was non-null when
        // chosen; re-check so TS can narrow it (it can't have been cleared
        // since — leavingPill, the only writer, and enteringPill can't both
        // be true in the same reconcile pass).
        const restore = prePanelPos.current;
        if (!restore) break;
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
              pillW: pillDims.w,
              pillH: pillDims.h,
              margin: PILL_MARGIN,
              monitorBounds: bounds,
            });
            geoClamp("restore", { windowTopLeftLogical: restoreLogical, monitorBounds: bounds, pillW: pillDims.w, pillH: pillDims.h, margin: PILL_MARGIN, result: targetPos });
          } catch { /* ignore */ }
        }
        break;
      }
      case "leaving-pill-center": {
        const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
        targetPos = { x: Math.round(area.x + (area.w - targetWinW) / 2), y: Math.round(area.y + (area.h - targetWinH) / 2) };
        break;
      }
      case "opening-menu-minimal": {
        // Single-window collapse (for_sonnet.md §3): the pill window itself
        // grows to RADIAL_MENU_BOX, centred on the pill's stable visual
        // center, exactly like capsule's grow below — RadialMenu now renders
        // in-process (PillOverlay), so there is no overlay window to
        // position/emit to anymore. Keep the pill's visual center fixed
        // while the window grows around it, same discipline as capsule.
        if (pillAnchor !== "custom") {
          // Fixed anchor: derive the idle pill's anchored top-left
          // deterministically (no live read, no drift), then run the SAME
          // geometry as the custom branch below. The old code centred the fan
          // on the grown window and parked the pill in the window's top-left
          // corner — for a corner/edge anchor the grown window is anchored to
          // that corner, so the pill jumped ~200px inward on open and the fan
          // (centred on the window, not the visible pill) was partially clipped.
          try {
            const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
            const idleTopLeftLogical = anchorPosition(pillAnchor, pillBoxW, pillBoxH, area);
            if (token !== reconcileToken.current) return;
            if (idleTopLeftLogical) {
              logger.info("menu", "menu opened", { displayMode, pos: idleTopLeftLogical });
              const pillCenterLogical = {
                x: idleTopLeftLogical.x + pillBoxW / 2,
                y: idleTopLeftLogical.y + pillBoxH / 2,
              };
              // Same pure function the custom branch and the close path call —
              // keeps the pill's visual centre fixed under the monitor clamp,
              // and the wrapper offset shifts only when the clamp moves the
              // window without moving the pill. monitorBounds = work area is a
              // hard boundary (anchored idle pill already sits inside it).
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
                monitorBounds: area,
              });
              targetPos = windowTopLeftLogical;
              setMinimalWrapperOffset(wrapperOffset);
              // Fan anchored to the real pill centre (not the window centre);
              // unifiedFan's edge-aware arc keeps it on-screen.
              setRadialPillGeometry({
                cx: pillCenterLogical.x, cy: pillCenterLogical.y,
                sw: area.w, sh: area.h, originX: area.x, originY: area.y,
              });
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
        break;
      }
      case "opening-menu-capsule": {
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
          } catch { /* ignore */ }
        } else {
          try {
            const scale = await getCurrentWindow().scaleFactor();
            const pos = await getCurrentWindow().outerPosition();
            const idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
            pillBoxBeforeMenuRef.current = idleTopLeftLogical;
            logger.info("menu", "menu opened", { displayMode, pos: idleTopLeftLogical });

            // Zone already resolved in prefetchCapsuleZone before menuOpen
            // flipped — don't re-read/re-set here or center demotion can flip
            // data-near mid-morph (rounded corners clip → looks sharp).
            const capsuleGeom = computeCapsuleMenuGeometry({
              idleTopLeftLogical,
              idlePillBoxW: pillBoxW,
              idlePillBoxH: pillBoxH,
              margin: PILL_MARGIN,
              capsuleOpenW: CAPSULE_OPEN_W,
              closePadW: CLOSE_PAD_W,
              nearEdge: capsuleZoneRef.current,
            });
            targetPos = capsuleGeom.windowTopLeftLogical;
          } catch { /* ignore */ }
        }
        break;
      }
      case "closing-menu": {
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
        break;
      }
      case "opening-panel": {
        // Compact-mode panel grow (Task 1.2): same discipline as capsule's
        // openingMenu branch above — keep the pill's visual position fixed
        // (pillBoxBeforeMenuRef, the same idle box the menu open/close edges
        // already established and never re-read live) while the window grows
        // to fit the panel underneath/around it. panelZone was already
        // resolved synchronously by prefetchPanelZone before compactPanel
        // committed (mirrors prefetchCapsuleZone/capsuleZone), so it's safe
        // to read here without re-deriving it mid-morph.
        //
        // panelModeSwitch reuses this path when displayMode flips between
        // capsule and minimal while a panel stays open — clears the outgoing
        // mode's geometry and recomputes for the incoming mode so PillOverlay
        // never renders capsule offsets in an island-sized window (or vice
        // versa).
        try {
          // Task 1.2 (RC-3): pillBoxBeforeMenuRef can be null here if a
          // superseded/cleared menu path left it unset before the panel
          // opened directly. Never skip the reposition on that — synthesize
          // the idle box from a live read, same fallback pattern as the
          // menu-open branch above (~App.tsx:1373-1377).
          let idleTopLeftLogical = pillBoxBeforeMenuRef.current;
          const scale = await getCurrentWindow().scaleFactor();
          if (!idleTopLeftLogical) {
            if (pillAnchor !== "custom") {
              // Anchored pill: pillBoxBeforeMenuRef is only ever set by the
              // custom-anchor menu paths — derive the idle box
              // deterministically, same as every other anchored branch.
              const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
              idleTopLeftLogical = anchorPosition(pillAnchor, pillBoxW, pillBoxH, area);
            }
            if (!idleTopLeftLogical) {
              // anchorPosition only returns null for "custom" (already
              // excluded above), but keep the live-read as a fallback so a
              // future anchor kind can never leave this unset.
              const pos = await getCurrentWindow().outerPosition();
              idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
            }
            pillBoxBeforeMenuRef.current = idleTopLeftLogical;
          }
          {
            const pillCenterPhysical = {
              x: (idleTopLeftLogical.x + pillBoxW / 2) * scale,
              y: (idleTopLeftLogical.y + pillBoxH / 2) * scale,
            };
            const area = await getActiveWorkArea(pillCenterPhysical);
            if (token !== reconcileToken.current) return;
            if (displayMode === "capsule") {
              const geom = computeCapsulePanelGeometry({
                idleTopLeftLogical,
                idlePillBoxW: pillBoxW,
                idlePillBoxH: pillBoxH,
                barH: PILL_DIMS.capsule.h,
                panelW: PANEL_W,
                panelH: PANEL_H,
                gap: PANEL_GAP,
                margin: PILL_MARGIN,
                zone: panelExtrudeZone,
                nearEdge: pillAnchor !== "custom"
                  ? capsuleZoneFromPillAnchor(pillAnchor)
                  : capsuleZoneRef.current,
                monitorBounds: area,
                // Task 0.3: keep the panel-open window exactly as wide as the
                // menu-open window (menuBoxW) — width must not change here,
                // only height.
                minW: menuBoxW,
              });
              setCapsulePanelGeom(geom);
              setIslandMorphGeom(null);
              targetPos = geom.windowTopLeftLogical;
            } else {
              // Minimal mode: the pill grows directly into the panel —
              // island-morph geometry.
              // RC-4: the pill's on-screen top-left is ALWAYS the idle
              // window's top-left inset by the margin — that is
              // computeMinimalMenuWindow's own invariant (the pill never
              // moves while the menu window grows/clamps around it).
              // idleTopLeft + minimalWrapperOffset mixed the idle-window and
              // grown-menu-window coordinate spaces, displacing the morph
              // origin by up to (menuBox − pillBox)/2 per axis and making
              // the island appear to grow from a random point near edges.
              const pillTopLeftLogical = {
                x: idleTopLeftLogical.x + PILL_MARGIN,
                y: idleTopLeftLogical.y + PILL_MARGIN,
              };
              const morph = computeIslandMorphRects({
                pillTopLeftLogical,
                pillW: PILL_DIMS.minimal.w,
                pillH: PILL_DIMS.minimal.h,
                panelW: PANEL_W,
                panelH: PANEL_H,
                margin: PILL_MARGIN,
                monitorBounds: area,
              });
              setIslandMorphGeom(morph);
              setCapsulePanelGeom(null);
              setMinimalWrapperOffset({ x: morph.pillOffset.x, y: morph.pillOffset.y });
              targetPos = morph.windowTopLeftLogical;
            }
          }
        } catch (e) {
          logger.warn("panel", "panel-open geometry failed", e);
        }
        break;
      }
      case "closing-panel": {
        // Mirror closingMenu: restore to wherever the menu's own close would
        // have restored to — pillBoxBeforeMenuRef is the single source of
        // truth for "where the idle pill was," whether or not the menu
        // chrome was still open when the panel took over (it wasn't, by
        // construction, but the ref is never re-read live either way).
        if (pillAnchor !== "custom") {
          try {
            const area = pickedMonitor?.workArea ?? await getActiveWorkArea();
            targetPos = anchoredMenuPosition(pillAnchor, pillBoxW, pillBoxH, area);
          } catch { /* ignore */ }
        } else if (pillBoxBeforeMenuRef.current) {
          targetPos = pillBoxBeforeMenuRef.current;
          logger.info("menu", "panel closed", { displayMode, pos: targetPos });
          // NOTE: pillBoxBeforeMenuRef deliberately NOT cleared here — same
          // reasoning as closingMenu: cleared as a post-move side effect
          // below, only once this close actually completes.
        }
        break;
      }
      case "plain-pill-resize": {
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
            pillW: pillDims.w,
            pillH: pillDims.h,
            margin: PILL_MARGIN,
            monitorBounds: bounds,
          });
        } catch { /* ignore */ }
      }
      }

      const { preMoveDelayMs, moveKind } = computeMoveTiming({
        closingMenu, closingPanel, displayMode, openingMenu, openingPanel, panelModeSwitch,
        capsuleExitMs: CAPSULE_EXIT_MS, radialExitMs: RADIAL_EXIT_DURATION_MS, panelExitMs: PANEL_EXIT_MS,
      });

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
        // Capsule open/close (union-bounds fix): the move is always a single
        // atomic SetWindowPos (setWindowBoundsAtomic), never the two-IPC-call
        // setSize+setPosition setWindowGeometryInstant uses. It moves ONCE to
        // the open-footprint rect *before* the CSS width-morph starts
        // (capsuleReady flips only after this await, below) and — on close —
        // ONLY shrinks back after CAPSULE_EXIT_MS, once the morph has fully
        // settled. Either way the geometry snap lands while nothing on
        // screen is CSS-animating, so a WM_MOVE/WM_SIZE compositor frame
        // split has no visible content difference to split (verified fix for
        // the right/center-zone open+close flicker — investigated via
        // geoLog's traceCapsuleMorph). Scoped to capsule only; every other
        // mode keeps the pre-existing animate/instant paths untouched.
        if (displayMode === "capsule" && moveKind === "instant" && targetPos) {
          const scale = await getCurrentWindow().scaleFactor();
          // Origin actually moving? Compare current logical top-left to targetPos.
          const cur = await getCurrentWindow().outerPosition();      // physical
          const originMoves = Math.round(cur.x / scale) !== Math.round(targetPos.x) // targetPos is logical
            || Math.round(cur.y / scale) !== Math.round(targetPos.y);
          if (originMoves) {
            setCapsuleShown(false);                                  // hide the stale frame
            // ponytail: rAF wait so the hidden frame actually paints before
            // the OS move — without this the hide never reaches the screen
            // and the stale-frame ghost still shows. Drop if a future
            // WebView2 build repaints synchronously on SetWindowPos.
            await new Promise<void>((r) => requestAnimationFrame(() => r()));
          }
          await setWindowBoundsAtomic(targetPos, { w: targetWinW, h: targetWinH }, scale);
          if (originMoves) {
            await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
            setCapsuleShown(true);
          }
        } else if (moveKind === "animate") {
          await animateWindowAndSizeTo({ w: targetWinW, h: targetWinH }, targetPos, () => token !== reconcileToken.current);
        } else {
          await setWindowGeometryInstant({ w: targetWinW, h: targetWinH }, targetPos);
        }
      } finally {
        endProgrammaticMove();
      }
      await geoSnapshot("apply.afterMove", { showPill, menuOpen, targetWinW, targetWinH });
      forcePillReflow();

      // Boot: reveal the pill once, after it's correctly positioned, only if
      // the last session left Stay Pinned on. Otherwise the window stays hidden
      // until a hotkey/tray trigger (unchanged behavior).
      if (!bootShownRef.current) {
        bootShownRef.current = true;
        if (pillPinned && showPill) {
          try { await getCurrentWindow().show(); } catch { /* ignore */ }
        }
      }

      // Only now has the window actually finished growing to fit the fan —
      // reveal it here, never earlier, so it can't paint into a still-pill-
      // sized window mid-IPC-grow regardless of latency or fast re-open races.
      if (openingMenu && displayMode === "minimal") setFanReady(true);
      if (openingMenu && displayMode === "capsule") setCapsuleReady(true);

      // Only now has the window actually finished growing to fit the panel —
      // same contract as fanReady/capsuleReady above, and the same reason:
      // it can't paint into a still-pill-sized window mid-IPC-grow.
      // Island morph (minimal only): the CSS rect-morph needs a style recalc
      // with the pill-sized startRect committed BEFORE panelReady flips, or it
      // pops in at end-rect. Two rAFs guarantee the intermediate paint (mirrors
      // the capsuleShown double-rAF above). Capsule mounts many frames before
      // its .open flip and needs no wait.
      if ((openingPanel || panelModeSwitch) && displayMode === "minimal") {
        await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
        if (token !== reconcileToken.current) return; // watchdog owns recovery past here
      }
      if (openingPanel || panelModeSwitch) setPanelReady(true);

      if (closingMenu && displayMode === "minimal") {
        // Reset-after-shrink: there is never a frame pairing the full-size
        // window with the idle offset (which is what made the pill jump to
        // the corner). At worst leaves the pill clipped for under a frame,
        // identical to open's path.
        setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
      }
      if (closingMenu) pillBoxBeforeMenuRef.current = null;
      if (closingMenu && displayMode === "capsule") setCapsuleExiting(false);

      if (closingPanel) {
        // Mirror closingMenu's reset-after-shrink discipline exactly. In
        // capsule mode, closingPanel now always doubles as the combined
        // panel+menu close (Task 2.1 step 4 — closingMenu no longer fires
        // alongside it), so this also owns clearing the capsuleExiting guard
        // that closeCompactPanel armed synchronously at click time.
        if (displayMode === "minimal") setMinimalWrapperOffset({ x: PILL_MARGIN, y: PILL_MARGIN });
        if (displayMode === "capsule") { setCapsuleExiting(false); setPanelClosing(false); }
        pillBoxBeforeMenuRef.current = null;
        setCapsulePanelGeom(null);
        setIslandMorphGeom(null);
      }

      // Reveal only after the window has actually finished resizing/moving —
      // the whole point being the window never shows a clipped 440px card
      // mid-grow, and never shrinks out from under still-visible content.
      if (leavingPill) setContentHidden(false);
      else if (enteringPill) setRenderPill(true);

      prevSize.current = { w: targetWinW, h: targetWinH };
      prevShowPillRef.current = showPill;
      if (displayMode === "full") fullSizeInitializedRef.current = true;
    };
    // Commit the display-mode baseline BEFORE the branch below: the shrinking
    // `else` returns its cleanup, so anything after the branch never runs on a
    // shrinking switch and these refs went stale (misfiring panelModeSwitch /
    // enteringFullMode next run). Safe here: apply() reads only locals captured
    // at edge-detection time above, never these refs.
    if (displayMode !== "full") fullSizeInitializedRef.current = false;
    prevDisplayModeRef.current = displayMode;
    if (growing) {
      apply();
    } else if (closingPanel) {
      // closingPanel already waits the full PANEL_EXIT_MS (360ms) inside
      // apply() via preMoveDelayMs before it moves anything (Task 1.5/RC-5c)
      // — stacking the usual 220ms outer defer on top double-counts the
      // close tail past the 360ms CSS exit. Defer 0 here; apply() owns the
      // whole delay for this case.
      apply();
    } else {
      const t = setTimeout(apply, 220);
      return () => clearTimeout(t);
    }
    // RC-5b: minimalWrapperOffset is intentionally excluded from this dep
    // array. It's an OUTPUT of apply() (set at the island-morph branch above
    // and on menu/panel close reset), not an input — keeping it as a dep
    // makes this effect re-run on its own writes, self-retriggering the
    // reconcile.
  }, [targetWinW, targetWinH, showPill, pillAnchor, displayMode, menuOpen, capsuleZone, compactPanel, panelZone, monitors, selectedMonitorId]);

  // Display picker selection (for_sonnet.md §4). Update state (drives the
  // persist effect + the reconcile effect's later re-anchors) AND jump the
  // currently-visible window to the picked display right now, so the move is
  // felt on pick instead of only on Settings close.
  //
  // Race caveat (formerly L1928-1934): the reconcile effect above is still
  // the owner of *animated* monitor-switch moves (anchored re-derives via
  // resolveTargetMonitor on its next run; custom via the enteringPill
  // monitor-changed branch when Settings closes). We deliberately do NOT
  // call animateWindowAndSizeTo here — an instant setPosition bracketed by
  // beginProgrammaticMove/endProgrammaticMove is the sanctioned path: the
  // guard stops onMoved from mistaking the jump for a user drag, and an
  // instant (non-animated) move can't fight the effect's own tween. When a
  // panel is open the reconcile branch that runs doesn't re-anchor to the
  // new monitor at all (that's the "moves only on Settings close" bug), so
  // this direct move is what actually relocates; for the anchored idle-pill
  // case the effect would land on the same anchorPosition anyway (idempotent).
  //
  // Sizing: we read the live outer size rather than the render-scope
  // targetWinW/targetWinH so the move matches whatever the window ACTUALLY
  // is right now — a grown compact Settings panel, or a user-resized full
  // window — instead of assuming the idle-pill box. LogicalPosition only;
  // every monitor read is a lib/monitor.ts workArea (already scale-divided).
  const handleSelectMonitor = useCallback((id: string) => {
    const prevSelectedId = selectedMonitorId; // captured before the state swap
    setSelectedMonitorId(id);
    void (async () => {
      try {
        const newMon = resolveTargetMonitor(monitors, id);
        if (!newMon) return; // monitors not loaded yet — reconcile handles it
        const win = getCurrentWindow();
        const [pos, size, scale] = await Promise.all([
          win.outerPosition(), win.outerSize(), win.scaleFactor(),
        ]);
        const wLogical = size.width / scale;
        const hLogical = size.height / scale;
        const curTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };

        let targetPos: { x: number; y: number } | null = null;
        if (pillAnchor !== "custom") {
          // Same derivation as the reconcile effect's anchored branch (L1379).
          targetPos = anchorPosition(pillAnchor, wLogical, hLogical, newMon.workArea);
        } else {
          // Custom placement: land at the same proportional offset from the
          // new monitor's centre (reconcile enteringPill branch, L1387-1404).
          const oldMon = resolveTargetMonitor(monitors, prevSelectedId);
          if (oldMon && oldMon.id !== newMon.id) {
            targetPos = computeProportionalMonitorMove({
              oldCenterLogical: {
                x: curTopLeftLogical.x + wLogical / 2,
                y: curTopLeftLogical.y + hLogical / 2,
              },
              oldWorkArea: oldMon.workArea,
              newWorkArea: newMon.workArea,
              winW: wLogical,
              winH: hLogical,
            });
          }
        }
        if (!targetPos) return; // custom + same monitor, or nothing to do

        beginProgrammaticMove();
        try {
          await win.setPosition(new LogicalPosition(targetPos.x, targetPos.y));
        } finally {
          endProgrammaticMove();
        }
      } catch { /* ignore — reconcile effect is the fallback owner */ }
    })();
  }, [monitors, selectedMonitorId, pillAnchor]);

  // Panel zone must be correct before the first open frame, same reasoning
  // and same call pattern as prefetchCapsuleZone below: resolved from the
  // pill's saved idle position (pillBoxBeforeMenuRef — the live window is
  // still menu-open-sized at this point, not idle-pill-sized) synchronously
  // before compactPanel commits, so the reconcile effect's openingPanel edge
  // never has to re-derive it mid-morph.
  const prefetchPanelZone = useCallback(async () => {
    try {
      const idleTopLeftLogical = pillBoxBeforeMenuRef.current;
      if (!idleTopLeftLogical) return;
      const pillCenterLogical = {
        x: idleTopLeftLogical.x + pillBoxW / 2,
        y: idleTopLeftLogical.y + pillBoxH / 2,
      };
      const scale = await getCurrentWindow().scaleFactor();
      const pillCenterPhysical = { x: pillCenterLogical.x * scale, y: pillCenterLogical.y * scale };
      const area = await getActiveWorkArea(pillCenterPhysical);
      setPanelZone(resolveVerticalZone(pillCenterLogical.y, area));
    } catch { /* reconcile effect will use the stale zone */ }
  }, [pillBoxW, pillBoxH]);

  // ── Pill menu routing (for_sonnet.md §5.1/§8.5) ─────────────────────────
  // Selecting a nav item closes the menu and expands to the full window on
  // that view; "search" routes to the look view instead of a modal.
  const handleMenuSelect = useCallback((target: Exclude<MenuTarget, "hide">) => {
    if (displayMode === "full") {
      closePillMenu();
      setExpanded(true);
      setView(target === "search" ? "look" : target);
      return;
    }
    // Compact modes (Capsule/Minimal): stay in pill land — the menu morphs
    // into the in-context panel instead of routing into FullWindow.
    if (compactPanel !== null) {
      // Icon click while the panel is already open (Task 2.1 step 5): same
      // target is a no-op, a different target swaps content only — panelZone
      // is unchanged so no prefetch/geometry work runs, and the openingPanel/
      // panelModeSwitch reconcile edges correctly stay dark (prevCompactPanel
      // was already non-null).
      if (target !== compactPanel) setCompactPanel(target);
      return;
    }
    // Capsule: the bar chrome stays open (menuOpen stays true) while the
    // panel extrudes underneath it — no capsuleExiting, no width re-morph.
    // Minimal: unchanged, the fan still closes and the island replaces the
    // pill.
    if (displayMode !== "capsule") setMenuOpen(false);
    void prefetchPanelZone().then(() => setCompactPanel(target));
  }, [displayMode, closePillMenu, prefetchPanelZone, compactPanel]);

  // D1: a dedicated Hide item sends the app to the tray even when pinned,
  // distinct from re-clicking the pill (which only dismisses the menu).
  const handleMenuHide = useCallback(() => {
    closePillMenu();
    getCurrentWindow().hide();
  }, [closePillMenu]);

  // Zone must be correct before the first open frame — justify/stagger/CSS all
  // read capsuleZone synchronously when menuOpen flips true. The reconcile
  // effect used to set it only after several awaits, so right-third opens
  // briefly morphed with the stale default "left" (flex-start).
  const prefetchCapsuleZone = useCallback(async () => {
    if (pillAnchor !== "custom") {
      const z = capsuleZoneFromPillAnchor(pillAnchor);
      capsuleZoneRef.current = z;
      setCapsuleZone(z);
      return;
    }
    try {
      const scale = await getCurrentWindow().scaleFactor();
      const pos = await getCurrentWindow().outerPosition();
      const idleTopLeftLogical = { x: pos.x / scale, y: pos.y / scale };
      const pillCenterLogical = {
        x: idleTopLeftLogical.x + pillBoxW / 2,
        y: idleTopLeftLogical.y + pillBoxH / 2,
      };
      const pillCenterPhysical = { x: pillCenterLogical.x * scale, y: pillCenterLogical.y * scale };
      const monitorBounds = await getActiveMonitorBounds(pillCenterPhysical);
      const z = resolveCapsuleZone({
        pillCenterLogical,
        monitorBounds,
        idleTopLeftLogical,
        idlePillBoxW: pillBoxW,
        capsuleOpenW: CAPSULE_OPEN_W,
        margin: PILL_MARGIN,
        closePadW: CLOSE_PAD_W,
      });
      capsuleZoneRef.current = z;
      setCapsuleZone(z);
    } catch { /* reconcile effect will retry */ }
  }, [pillAnchor, pillBoxW, pillBoxH, PILL_MARGIN, CLOSE_PAD_W]);

  // Hoisted so both the pill (compact panel) and full-window branches below
  // can supply the exact same settings state/handlers — CompactSettings
  // (Task 2.4) needs full parity with FullWindow's Settings tab.
  const settingsProps = {
    theme,
    onSelectTheme: selectTheme,
    displayMode,
    onSelectDisplayMode: setDisplayMode,
    pillCorner,
    onSelectPillCorner: setPillCorner,
    pillPinned,
    onTogglePillPinned: setPillPinned,
    pillAnchor,
    onSelectPillAnchor: setPillAnchor,
    pillFanStyle,
    onSelectPillFanStyle: setPillFanStyle,
    pillSnapEnabled,
    onTogglePillSnap: setPillSnapEnabled,
    monitors,
    selectedMonitorId,
    onSelectMonitor: handleSelectMonitor,
    lookChatPersist,
    onSelectLookChatPersist: setLookChatPersist,
  };

  if (renderPill) {
    // Capsule open: push the bar to whichever edge it's pinned to, leaving
    // the free space (the click-to-close padding) on the inner side
    // (for_sonnet.md Problem 3b). Minimal mode is positioned explicitly via
    // minimalWrapperOffset instead (it needs pixel-precise placement so a
    // monitor-clamp shift of the window doesn't also shift the visible
    // pill); every other state centers as before.
    // Keep the bar pinned to its near edge for the WHOLE exit (menuOpen flips
    // false immediately but the window stays full-size for CAPSULE_EXIT_MS).
    // Reverting to center here is what made the bar collapse toward screen center.
    const capsuleOpenJustify =
      displayMode === "capsule" && (menuOpen || capsuleExiting)
        ? (capsuleZone === "right" ? "flex-end" : capsuleZone === "left" ? "flex-start" : "center")
        : "center";

    const compactPanelOpen = compactPanel !== null;
    // RC-3: capsulePanelGeom lingers until the reconcile's closingPanel tail
    // clears it; panelClosing spans that same window. Keep absolute layout
    // for the whole exit so the bar/panel hold their offsets while the OS
    // window is still panel-sized.
    const capsulePanelLingering = displayMode === "capsule" && panelClosing && capsulePanelGeom !== null;
    // Mirrors capsulePanelLingering for minimal mode: while compactPanel has
    // flipped to null but islandMorphGeom hasn't been cleared yet (cleared
    // only in apply()'s post-delay tail), the close-morph is still animating
    // and the wrapper must keep treating the window as panel-grown — see
    // Current-State Facts in 2026-07-05-compact-density-polish.md Task 5.
    const minimalPanelLingering =
      displayMode === "minimal" && !compactPanelOpen && islandMorphGeom !== null;
    const useAbsolutePillLayout =
      displayMode === "minimal" || (displayMode === "capsule" && (compactPanelOpen || capsulePanelLingering));

    // Minimal-mode island rects, in the same in-window coordinate space the
    // island DOM element renders in: startRect = pillOffset (where the pill
    // itself sits inside the already-grown window — never recomputed, so
    // this is exactly the morph's zero-drift origin), endRect = the panel's
    // own offset within that same window (always {margin, margin} by
    // construction of computeIslandMorphRects's windowTopLeftLogical).
    const islandGeom = displayMode === "minimal" && islandMorphGeom
      ? {
          startRect: {
            left: islandMorphGeom.pillOffset.x,
            top: islandMorphGeom.pillOffset.y,
            width: islandMorphGeom.startRect.w,
            height: islandMorphGeom.startRect.h,
          },
          endRect: {
            left: islandMorphGeom.endRect.x - islandMorphGeom.windowTopLeftLogical.x,
            top: islandMorphGeom.endRect.y - islandMorphGeom.windowTopLeftLogical.y,
            width: islandMorphGeom.endRect.w,
            height: islandMorphGeom.endRect.h,
          },
        }
      : null;
    // Lingers past `compactPanel` flipping to null so the island keeps
    // rendering its last content through the whole close morph — see
    // lastMinimalPanelTargetRef above.
    const islandTarget = displayMode === "minimal" ? (compactPanel ?? lastMinimalPanelTargetRef.current) : null;

    const pillOverlay = (
      <PillOverlay
        mode={displayMode as PillMode}
        corner={pillCorner}
        captureState={captureState}
        stepDefs={stepDefs}
        llmStatus={llmStatus}
        menuOpen={menuOpen}
        capsuleMorphOpen={(menuOpen && capsuleReady) || compactPanel !== null}
        capsuleExiting={capsuleExiting}
        capsuleShown={capsuleShown}
        fanOpen={fanReady}
        nearEdge={capsuleZone}
        draggable={isPillDraggable(pillAnchor, menuOpen)}
        dragging={pillGrabbed}
        onDragPointerDown={handlePillDragPointerDown}
        onToggleMenu={() => {
          // Bug 3: a drag's pointerup still fires a synthetic click on the
          // same button — swallow exactly that one click here, the shared
          // choke point both PillOverlay and CapsuleMenu route through.
          if (draggedRef.current) { draggedRef.current = false; return; }
          logger.debug("menu", "pill clicked", { wasOpen: menuOpen, displayMode });
          // Clicking the bar background while a compact panel is open must
          // collapse both together (same combined edge as Esc/click-away) —
          // after Task 2.1 step 1, menuOpen stays true the whole time a
          // capsule panel is out, so falling into the plain `closePillMenu`
          // branch below would strand compactPanel non-null under a
          // collapsed bar.
          if (compactPanel !== null) {
            closeCompactPanel();
            return;
          }
          if (menuOpen) {
            closePillMenu();
            return;
          }
          if (displayMode === "capsule") {
            setCapsuleExiting(false);
            void prefetchCapsuleZone().then(() => setMenuOpen(true));
            return;
          }
          setMenuOpen(true);
        }}
        inboxCount={inboxCount}
        onSelect={handleMenuSelect}
        onHide={handleMenuHide}
        pillGeometry={radialPillGeometry}
        fanStyle={pillFanStyle}
        voicePhase={voice.phase}
        voiceElapsedMs={voice.elapsedMs}
        readWaveform={voice.readWaveform}
        readSpectrum={voice.readSpectrum}
        sampleRate={voice.sampleRate}
        onVoiceToggle={voice.toggle}
        onVoiceCancel={voice.cancel}
        compactPanel={compactPanel}
        capsulePanelTarget={displayMode === "capsule"
          ? (compactPanel ?? (capsulePanelLingering ? lastCapsulePanelTargetRef.current : null))
          : null}
        panelReady={panelReady}
        panelZone={panelExtrudeZone}
        panelGeom={displayMode === "capsule" ? capsulePanelGeom : null}
        islandGeom={islandGeom}
        islandTarget={islandTarget}
        onClosePanel={closeCompactPanel}
        onPanelError={handlePanelError}
        lookMode={lookMode}
        onSelectLookMode={setLookMode}
        lookChat={lookChat}
        lookChatPersist={lookChatPersist}
        settingsProps={settingsProps}
        onOpenFile={(path) => openFilePath(path).catch(() => {})}
        reminderToast={reminderUndo ? { message: reminderUndo.message, onUndo: undoReminderCreate } : null}
      />
    );

    return (
      <div
        // C2: brief red-tinted glow while a compact panel just auto-collapsed
        // from a render throw — this wrapper is sized to exactly the pill's
        // OS window (100vw/100vh), so tinting it reads as tinting the pill.
        className={pillError ? "pill-error" : undefined}
        onClick={(e) => {
          // Task 0.3: the panel window is now floored at the same width as
          // the menu window (CLOSE_PAD_W's click-to-close slack), so that
          // dead space exists in panel state too — closing the panel there
          // mirrors closing the menu there.
          // Compact panel first (Task 2.1 step 4's combined edge): after step
          // 1, menuOpen stays true the whole time a capsule panel is open, so
          // checking `menuOpen` first here would always take the bar-only
          // close branch and strand the panel open underneath a collapsed bar.
          //
          // FIX #4 (capsule click-away): this wrapper is the single bubble
          // target for every capsule dismiss-region click. Because capsule
          // inflates its window rect by CLOSE_PAD_W, near-clicks land INSIDE
          // the OS rect and never trigger the Rust click-away hook's
          // menu:dismiss, so we mirror that handler's unpinned-hide here — but
          // ONLY for the transparent close-pad, never for the visible bar.
          // Clicking the bar/controls must merely collapse (like the minimal
          // pill), not hide the app. `onBar` = the click landed inside
          // `.capsule-menu` (the bar and everything in it). We use closest()
          // rather than `e.target === e.currentTarget` because the panel-open
          // layout nests a full-size relative div (PillOverlay) between this
          // wrapper and the bar, so a pad click's target is that inner div —
          // not this wrapper — and the identity check would misfire. Real
          // panel controls stopPropagation (CompactShell) and never reach
          // here; minimal stops propagation on its own pill. Capsule only,
          // pinned stays visible, exactly like menu:dismiss (App.tsx ~788/793).
          const wasOpen = compactPanel !== null || menuOpen;
          const onBar = e.target instanceof Element && e.target.closest(".capsule-menu") !== null;
          if (compactPanel !== null) closeCompactPanel();
          else if (menuOpen) closePillMenu();
          if (wasOpen && !onBar && displayMode === "capsule" && !pillPinnedRef.current) {
            getCurrentWindow().hide();
          }
        }}
        // data-panel-* exposed here (not consumed by any CSS/logic yet) so
        // panelReady/panelZone — driven by the reconcile effect's
        // openingPanel/closingPanel edges — stay inspectable in devtools
        // ahead of the compact-panel component itself landing.
        data-panel-target={compactPanel ?? undefined}
        data-panel-ready={compactPanel ? panelReady : undefined}
        data-panel-zone={compactPanel ? panelZone : undefined}
        // Task 2.4/M4: scopes the capsule bar's delayed width-shrink
        // (index.css `[data-panel-closing] .capsule-menu`) to exactly the
        // combined panel+bar close, for its PANEL_EXIT_MS duration.
        data-panel-closing={panelClosing ? "true" : undefined}
        style={{
          width: "100vw",
          height: "100vh",
          position: useAbsolutePillLayout ? "relative" : undefined,
          display: useAbsolutePillLayout ? undefined : "flex",
          alignItems: useAbsolutePillLayout ? undefined : "center",
          justifyContent: useAbsolutePillLayout ? undefined : (displayMode === "capsule" && (menuOpen || capsuleExiting) ? capsuleOpenJustify : "center"),
          background: "transparent",
          overflow: "hidden",
        }}
      >
        {displayMode === "minimal" ? (
          <div style={{
            position: "absolute",
            left: (compactPanelOpen || minimalPanelLingering) ? 0 : minimalWrapperOffset.x,
            top: (compactPanelOpen || minimalPanelLingering) ? 0 : minimalWrapperOffset.y,
            width: (compactPanelOpen || minimalPanelLingering) ? "100%" : undefined,
            height: (compactPanelOpen || minimalPanelLingering) ? "100%" : undefined,
          }}>
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
          position: "relative",
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            transition: "opacity 0.2s cubic-bezier(0.16,1,0.3,1)",
            opacity: contentHidden ? 0 : 1,
            pointerEvents: contentHidden ? "none" : undefined,
          }}
        >
          <FullWindow
            captureState={captureState}
            stepDefs={stepDefs}
            llmStatus={llmStatus}
            lookMode={lookMode}
            onSelectLookMode={setLookMode}
            lookChat={lookChat}
            lookChatPersist={lookChatPersist}
            onOpenFile={(path) => openFilePath(path).catch(() => {})}
            initialView={VIEW_TO_RAIL[view] ?? "dashboard"}
            onHideToTray={displayMode === "full"
              ? () => getCurrentWindow().hide()
              : () => setView("capture")}
            onCaptureFile={captureFile}
            pillCorner={pillCorner}
            voicePhase={voice.phase}
            voiceElapsedMs={voice.elapsedMs}
            readWaveform={voice.readWaveform}
            readSpectrum={voice.readSpectrum}
            sampleRate={voice.sampleRate}
            onVoiceToggle={voice.toggle}
            onVoiceCancel={voice.cancel}
            settingsProps={settingsProps}
          />
        </div>

        {/* Hidden dev-only troubleshooting tuner (Ctrl+Shift+Alt+G) */}
        <DevTuner />
        {/* Toast notifications */}
        <div style={{ position: "absolute", bottom: 14, left: "50%", transform: "translateX(-50%)", width: 408, pointerEvents: "none" }}>
          <div style={{ pointerEvents: "all" }}>
            <ToastHost toasts={toasts} onDismiss={dismissToast} />
          </div>
        </div>
      </div>
    );
}
