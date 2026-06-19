/**
 * App.tsx
 * -------
 * Root component — theme system, command palette, focus mode.
 *
 * Keyboard bindings
 *   Ctrl+K          command palette (toggle)
 *   Ctrl+,          settings
 *   Ctrl+\          vault
 *   Ctrl+I          inbox
 *   Ctrl+Shift+F    focus mode toggle
 *   Escape          close panel / hide window
 *
 * Themes (persisted to localStorage)
 *   dark            Void  (default)
 *   dark-ash        Ash   (warmer dark)
 *   light           Paper
 *   light-stone     Stone (cooler light)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { listen } from "@tauri-apps/api/event";
import CaptureOverlay from "./components/CaptureOverlay";
import SettingsPanel from "./components/SettingsPanel";
import VaultManager from "./components/VaultManager";
import InboxPanel from "./components/InboxPanel";
import StatsPanel from "./components/StatsPanel";
import CommandPalette, { type PaletteAction } from "./components/CommandPalette";
import { useCapture } from "./hooks/useCapture";
import { getVaultCategories, getInbox } from "./lib/api";

// ── Theme ──────────────────────────────────────────────────────────────────

export type Theme = "dark" | "dark-ash" | "light" | "light-stone";
export const THEMES: Theme[] = ["dark", "dark-ash", "light", "light-stone"];
const THEME_LABELS: Record<Theme, string> = {
  "dark":        "Void",
  "dark-ash":    "Ash",
  "light":       "Paper",
  "light-stone": "Stone",
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

// ── View ───────────────────────────────────────────────────────────────────

type View = "capture" | "settings" | "vault" | "inbox" | "stats";

// ── Component ──────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView]             = useState<View>("capture");
  const [palette, setPalette]       = useState(false);
  const [focusMode, setFocusMode]   = useState(false);
  const [theme, setTheme]           = useState<Theme>(getInitialTheme);
  const [categories, setCategories] = useState<string[]>([]);
  const [openResult, setOpenResult] = useState<{ category: string; path: string } | null>(null);
  const [inboxCount, setInboxCount] = useState(0);

  const { state: captureState, stepDefs } = useCapture();

  // Apply theme on mount and whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);

  const cycleTheme = useCallback(() => {
    setTheme((t) => THEMES[(THEMES.indexOf(t) + 1) % THEMES.length]);
  }, []);

  // Fetch vault categories for the command palette (best-effort)
  useEffect(() => {
    getVaultCategories()
      .then((res) => setCategories(res.categories.map((c) => c.name)))
      .catch(() => {});
  }, []);

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
        setPalette((o) => !o);
        return;
      }
      if (mod && e.key === ",") {
        e.preventDefault();
        setPalette(false);
        setView((v) => (v === "settings" ? "capture" : "settings"));
        return;
      }
      if (mod && e.key === "\\") {
        e.preventDefault();
        setPalette(false);
        setView((v) => (v === "vault" ? "capture" : "vault"));
        return;
      }
      if (mod && e.key === "i") {
        e.preventDefault();
        setPalette(false);
        setView((v) => (v === "inbox" ? "capture" : "inbox"));
        return;
      }
      if (mod && e.shiftKey && (e.key === "f" || e.key === "F")) {
        e.preventDefault();
        setFocusMode((f) => !f);
        return;
      }
      if (e.key === "Escape") {
        if (palette)           { setPalette(false); return; }
        if (focusMode)         { setFocusMode(false); return; }
        if (view !== "capture"){ setView("capture"); return; }
        getCurrentWindow().hide();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [view, palette, focusMode]);

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
  const targetWinH = displayH + V_MARGIN;

  // Grow the OS window immediately (nothing to clip); shrink only after the
  // 200ms cross-fade/collapse has finished, so the outgoing panel's still-
  // fading bottom is never sheared.
  const prevH = useRef(targetWinH);
  useEffect(() => {
    const growing = targetWinH >= prevH.current;
    const apply = () => {
      getCurrentWindow()
        .setSize(new LogicalSize(480, targetWinH))
        .catch(() => {/* ignore if window not yet ready */});
      prevH.current = targetWinH;
    };
    if (growing) {
      apply();
    } else {
      const t = setTimeout(apply, 220);
      return () => clearTimeout(t);
    }
  }, [targetWinH]);

  // ── Palette action handler ───────────────────────────────────────────────
  const handlePaletteAction = useCallback((action: PaletteAction) => {
    if (action === "settings") {
      setView("settings");
    } else if (action === "vault") {
      setView("vault");
    } else if (action === "inbox") {
      setView("inbox");
    } else if (action === "stats") {
      setView("stats");
    } else if (typeof action === "object" && action.kind === "category") {
      setView("vault");
    } else if (typeof action === "object" && action.kind === "openResult") {
      setOpenResult({ category: action.category, path: action.path });
      setView("vault");
    }
  }, []);

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
          transition: "height 0.2s cubic-bezier(0.16,1,0.3,1)",
        }}
      >
        <CaptureOverlay
          measureRef={setMeasureEl("capture")}
          captureState={captureState}
          stepDefs={stepDefs}
          onOpenSettings={() => setView("settings")}
          onOpenVault={() => setView("vault")}
          onOpenInbox={() => setView("inbox")}
          onOpenPalette={() => setPalette(true)}
          visible={view === "capture"}
          focusMode={focusMode}
          onToggleFocus={() => setFocusMode((f) => !f)}
          inboxCount={inboxCount}
        />
        <SettingsPanel
          measureRef={setMeasureEl("settings")}
          visible={view === "settings"}
          onClose={() => setView("capture")}
          theme={theme}
          themeLabel={THEME_LABELS[theme]}
          onCycleTheme={cycleTheme}
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

      {/* Command palette — sits above everything */}
      <CommandPalette
        open={palette}
        categories={categories}
        onClose={() => setPalette(false)}
        onAction={handlePaletteAction}
      />
    </div>
  );
}
