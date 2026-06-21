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
import { type PillGeometry } from "./components/PillMenu/RadialMenu";
import { CAPSULE_OPEN_W } from "./components/PillMenu/CapsuleMenu";
import DevTuner from "./components/PillMenu/DevTuner";
import type { MenuTarget } from "./components/PillMenu/icons";
import { useRadialTuning } from "./lib/devTuning";
import SettingsPanel from "./components/SettingsPanel";
import VaultManager from "./components/VaultManager";
import InboxPanel from "./components/InboxPanel";
import StatsPanel from "./components/StatsPanel";
import SearchModal, { type SearchAction } from "./components/SearchModal";
import { useCapture } from "./hooks/useCapture";
import { getInbox } from "./lib/api";
import { type PillAnchor, anchorPosition } from "./lib/pillAnchor";
import { getActiveWorkArea } from "./lib/monitor";

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

function getInitialTheme(): Theme {
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
  // True once the user clicks the pill (or it's irrelevant because Display
  // Mode is Full) — shows the full overlay instead of the small pill. Never
  // toggled automatically by the capture lifecycle, only by explicit clicks.
  const [expanded, setExpanded] = useState(false);

  // The on-click pill menu (radial fan / capsule morph) — see for_sonnet.md
  // §5/§6/§8. Clicking the pill toggles this instead of `expanded` directly;
  // selecting a nav item closes the menu *and* sets `expanded`.
  const [menuOpen, setMenuOpen] = useState(false);
  // Populated for displayMode === "minimal" any time the menu opens (every
  // anchor, not just "custom" — a pinned anchor is just a known center fed
  // into the same unifiedFan geometry; see for_sonnet.md "Problem 2 + 3").
  // Computed fresh each time the menu opens (see the resize effect below).
  const [radialGeometry, setRadialGeometry] = useState<PillGeometry | null>(null);

  useEffect(() => { try { localStorage.setItem(DISPLAY_MODE_KEY, displayMode); } catch { /* ignore */ } }, [displayMode]);
  useEffect(() => { try { localStorage.setItem(PILL_CORNER_KEY, pillCorner); } catch { /* ignore */ } }, [pillCorner]);
  useEffect(() => { try { localStorage.setItem(PILL_PINNED_KEY, pillPinned ? "1" : "0"); } catch { /* ignore */ } }, [pillPinned]);
  useEffect(() => { try { localStorage.setItem(PILL_ANCHOR_KEY, pillAnchor); } catch { /* ignore */ } }, [pillAnchor]);
  useEffect(() => { try { localStorage.setItem(PILL_FAN_STYLE_KEY, pillFanStyle); } catch { /* ignore */ } }, [pillFanStyle]);
  useEffect(() => { try { localStorage.setItem(PILL_SNAP_KEY, pillSnapEnabled ? "1" : "0"); } catch { /* ignore */ } }, [pillSnapEnabled]);

  // Read via a ref inside useCapture so its dismiss-timer closures always see
  // the latest pin state without re-subscribing every render. An explicit
  // manual expand (clicking the pill) holds the window open the same way
  // Stay Pinned does, so a deliberately-opened full view never gets yanked
  // away by the post-capture auto-hide regardless of the Stay Pinned setting.
  const holdOpenRef = useRef(false);
  useEffect(() => {
    holdOpenRef.current = pillPinned || expanded;
  }, [pillPinned, expanded]);

  const { state: captureState, stepDefs } = useCapture(holdOpenRef);

  // Apply theme on mount and whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);

  const selectTheme = useCallback((t: Theme) => setTheme(t), []);

  // Only Capsule/Minimal ever collapse to a pill, and only in the capture
  // view — Settings/Vault/Inbox/Stats always show full-size regardless.
  const showPill = displayMode !== "full" && view === "capture" && !expanded;

  // The menu only ever exists while the pill is showing; leaving pill mode
  // for any reason (expand, view switch, display-mode switch) always closes it.
  useEffect(() => { if (!showPill) setMenuOpen(false); }, [showPill]);

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

  // Auto-hide when a panel closes while unpinned: if returning to capture
  // view while not pinned and idle, hide immediately.
  const prevViewRef = useRef(view);
  useEffect(() => {
    if (prevViewRef.current !== "capture" && view === "capture" && !pillPinned && captureState.phase === "idle") {
      getCurrentWindow().hide();
    }
    prevViewRef.current = view;
  }, [view, pillPinned, captureState.phase]);

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
        if (menuOpen)            { setMenuOpen(false); return; }
        if (search)             { setSearch(false); return; }
        if (view !== "capture"){ setView("capture"); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [view, search, menuOpen]);

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

  // Breathing room around the pill so the rotating-ring overlay (inset -2px)
  // never gets clipped by the OS window edge.
  const PILL_MARGIN = 6;
  const pillBoxW = showPill ? PILL_DIMS[displayMode as PillMode].w + PILL_MARGIN * 2 : 480;
  const pillBoxH = showPill ? PILL_DIMS[displayMode as PillMode].h + PILL_MARGIN * 2 : displayH + V_MARGIN;

  // While the pill menu is open, the OS window must grow to contain it (it's
  // sized tightly around the idle pill otherwise — see for_sonnet.md §5.5,
  // "the window-clipping problem"). Radial needs room in every direction (a
  // custom-position fan can open as a near-full wheel); capsule only grows
  // wider, same height.
  const RADIAL_MENU_BOX = Math.round((radialTuning.radius + radialTuning.chipMax / 2 + PILL_MARGIN) * 2);
  const menuBoxW = displayMode === "minimal" ? RADIAL_MENU_BOX : CAPSULE_OPEN_W + PILL_MARGIN * 2;
  const menuBoxH = displayMode === "minimal" ? RADIAL_MENU_BOX : PILL_DIMS.capsule.h + PILL_MARGIN * 2;
  const targetWinW = showPill && menuOpen ? menuBoxW : pillBoxW;
  const targetWinH = showPill && menuOpen ? menuBoxH : pillBoxH;

  // Remember window position across restarts. The window is created hidden
  // (tauri.conf.json `visible: false`) and only ever shown via the global
  // hotkey/tray click, so this restore always lands before the user can see
  // it -- no flash. Header bars (drag-region) in every panel and both pill
  // shapes make the window freely draggable, so this isn't just the pill's
  // anchor system: it also covers the full expanded view, which the anchor
  // effect below never positions at all.
  const WINDOW_POS_KEY = "omni-window-pos";

  // Guards every programmatic setPosition (pill-anchor snap, secondary-panel
  // recenter, Custom-position restore) so the onMoved listener below never
  // mistakes one of those for a real user drag and overwrites the saved
  // Custom position with a centered/anchored coordinate.
  const programmaticMove = useRef(false);
  const markProgrammaticMove = () => {
    programmaticMove.current = true;
    setTimeout(() => { programmaticMove.current = false; }, 350);
  };

  // Refs mirroring render-time values the onMoved listener (mounted once,
  // below) needs to read live without re-subscribing every render.
  const snapStateRef = useRef({ anchor: pillAnchor, snapEnabled: pillSnapEnabled, showPill, menuOpen, w: pillBoxW, h: pillBoxH });
  useEffect(() => {
    snapStateRef.current = { anchor: pillAnchor, snapEnabled: pillSnapEnabled, showPill, menuOpen, w: pillBoxW, h: pillBoxH };
  }, [pillAnchor, pillSnapEnabled, showPill, menuOpen, pillBoxW, pillBoxH]);

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
          if (programmaticMove.current) return;
          clearTimeout(saveTimer);
          saveTimer = setTimeout(() => {
            void (async () => {
              let { x, y } = payload;
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
                    markProgrammaticMove();
                    await win.setPosition(new LogicalPosition(snappedX, snappedY));
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
        });
      } catch { /* ignore */ }
    })();
    return () => { clearTimeout(saveTimer); unlisten?.(); };
  }, []);

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
  useEffect(() => {
    const pillModeActive = displayMode !== "full";
    const prevShowPill = prevShowPillRef.current;
    const leavingPill = pillModeActive && prevShowPill && !showPill;   // pill -> full
    const enteringPill = pillModeActive && !prevShowPill && showPill; // full -> pill
    const prevMenuOpen = prevMenuOpenRef.current;
    const openingMenu = pillModeActive && showPill && prevShowPill && menuOpen && !prevMenuOpen;
    const closingMenu = pillModeActive && showPill && prevShowPill && !menuOpen && prevMenuOpen;

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
          const pos = await getCurrentWindow().outerPosition();
          prePanelPos.current = { x: pos.x, y: pos.y };
        } catch { /* ignore */ }
      }

      let targetPos: { x: number; y: number } | null = null;
      if (pillAnchor !== "custom") {
        const area = await getActiveWorkArea();
        targetPos = anchorPosition(pillAnchor, targetWinW, targetWinH, area);
      } else if (enteringPill && prePanelPos.current) {
        const restore = prePanelPos.current;
        prePanelPos.current = null;
        try {
          const scale = await getCurrentWindow().scaleFactor();
          targetPos = { x: restore.x / scale, y: restore.y / scale };
        } catch { /* ignore */ }
      } else if (leavingPill) {
        const area = await getActiveWorkArea();
        targetPos = { x: Math.round(area.x + (area.w - targetWinW) / 2), y: Math.round(area.y + (area.h - targetWinH) / 2) };
      } else if (openingMenu) {
        // Keep the pill's visual center fixed while the window grows around
        // it — otherwise the fan/morph would grow from the window's current
        // top-left instead of from the pill (for_sonnet.md §5.5).
        try {
          const area = await getActiveWorkArea();
          const scale = await getCurrentWindow().scaleFactor();
          const pos = await getCurrentWindow().outerPosition();
          const size = await getCurrentWindow().outerSize();
          const curPos = { x: pos.x / scale, y: pos.y / scale };
          const curSize = { w: size.width / scale, h: size.height / scale };
          pillBoxBeforeMenuRef.current = curPos;
          if (displayMode === "minimal") {
            setRadialGeometry({
              cx: curPos.x + curSize.w / 2,
              cy: curPos.y + curSize.h / 2,
              sw: area.w,
              sh: area.h,
              originX: area.x,
              originY: area.y,
            });
          }
          const centerX = curPos.x + curSize.w / 2;
          const centerY = curPos.y + curSize.h / 2;
          const sw = area.w;
          // Capsule grows toward the screen interior (for_sonnet.md "Problem
          // 5" decision #5c): pin whichever edge is nearer the screen edge
          // and grow the other way, instead of growing symmetrically from
          // center (which would clip a right-anchored capsule). Radial mode
          // needs room on every side for the fan, so it keeps the pill's true
          // screen center fixed and grows unclamped — the fan geometry itself
          // (fed the active monitor's work area above) is responsible for
          // never drawing outside the visible bounds, so the window growing
          // past the work-area edge here is invisible/harmless overhang
          // rather than something that needs to shove the pill inward.
          const growX = displayMode === "capsule"
            ? (curPos.x + curSize.w / 2 > area.x + sw / 2 ? curPos.x + curSize.w - targetWinW : curPos.x)
            : centerX - targetWinW / 2;
          const clampedX = displayMode === "capsule"
            ? Math.max(area.x, Math.min(area.x + sw - targetWinW, growX))
            : growX;
          targetPos = { x: Math.round(clampedX), y: Math.round(centerY - targetWinH / 2) };
        } catch { /* ignore */ }
      } else if (closingMenu && pillBoxBeforeMenuRef.current) {
        targetPos = pillBoxBeforeMenuRef.current;
        pillBoxBeforeMenuRef.current = null;
        setRadialGeometry(null);
      }

      if (targetPos) markProgrammaticMove();
      // Menu open/close: single atomic instant step (no rAF tween) — see
      // setWindowGeometryInstant above. Every other transition keeps the
      // existing animated tween.
      if (openingMenu || closingMenu) await setWindowGeometryInstant({ w: targetWinW, h: targetWinH }, targetPos);
      else await animateWindowAndSizeTo({ w: targetWinW, h: targetWinH }, targetPos);

      // Reveal only after the window has actually finished resizing/moving —
      // the whole point being the window never shows a clipped 440px card
      // mid-grow, and never shrinks out from under still-visible content.
      if (leavingPill) setContentHidden(false);
      else if (enteringPill) setRenderPill(true);

      prevSize.current = { w: targetWinW, h: targetWinH };
      prevShowPillRef.current = showPill;
      prevMenuOpenRef.current = menuOpen;
    };
    if (growing) {
      apply();
    } else {
      const t = setTimeout(apply, 220);
      return () => clearTimeout(t);
    }
  }, [targetWinW, targetWinH, showPill, pillAnchor, displayMode, menuOpen]);

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
    return (
      <div
        onClick={() => { if (menuOpen) setMenuOpen(false); }}
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
        <PillOverlay
          mode={displayMode as PillMode}
          corner={pillCorner}
          captureState={captureState}
          stepDefs={stepDefs}
          menuOpen={menuOpen}
          onToggleMenu={() => setMenuOpen((o) => !o)}
          onMenuDragClose={() => setMenuOpen(false)}
          pillGeometry={radialGeometry}
          fanStyle={pillFanStyle}
          inboxCount={inboxCount}
          onSelect={handleMenuSelect}
          onHide={handleMenuHide}
        />
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
