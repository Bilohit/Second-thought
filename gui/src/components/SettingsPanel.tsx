/**
 * SettingsPanel.tsx
 * -----------------
 * Minimal settings view — slides in from the right over the CaptureOverlay.
 *
 * Sections
 *   · Vault path  — text field + folder-picker button (Tauri dialog)
 *   · Hotkey      — display field + "Record" button
 *   · Ollama model — text field
 *   · Save / Close
 */

import { type CSSProperties, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { getConfig, patchConfig, formatHotkey, DEFAULT_HOTKEY } from "../lib/config";
import { setHotkey as setHotkeyRust, setLogLevel } from "../lib/tauri";
import { getVaultCategories } from "../lib/api";
import { logger, LogLevel } from "../lib/logger";
import { isGeoDebugEnabled, setGeoDebugEnabled } from "../lib/geoLog";
import { THEMES, THEME_LABELS, type Theme } from "../App";
import type { PillMode, PillCorner } from "./PillOverlay";
import type { PillAnchor } from "../lib/pillAnchor";
import { ANCHOR_ORDER } from "../lib/pillAnchor";
import type { MonitorInfo } from "../lib/monitor";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  INPUT_STYLE, BTN_SECONDARY, BTN_PRIMARY,
} from "./ui/styles";
import { Tabs } from "./ui/Tabs";

interface Props {
  visible:      boolean;
  onClose:      () => void;
  theme?:       Theme;
  themeLabel?:  string;
  onSelectTheme?: (theme: Theme) => void;
  measureRef?:  (el: HTMLDivElement | null) => void;

  // Display Mode (Item 2: pill/minimized window) — client-only preferences,
  // persisted to localStorage by App.tsx, same pattern as theme.
  displayMode?:      "full" | PillMode;
  onSelectDisplayMode?: (mode: "full" | PillMode) => void;
  pillCorner?:       PillCorner;
  onSelectPillCorner?: (corner: PillCorner) => void;
  pillPinned?:       boolean;
  onTogglePillPinned?: (pinned: boolean) => void;
  pillAnchor?:       PillAnchor;
  onSelectPillAnchor?: (anchor: PillAnchor) => void;
  pillFanStyle?:     "spread" | "capped";
  onSelectPillFanStyle?: (style: "spread" | "capped") => void;
  pillSnapEnabled?:  boolean;
  onTogglePillSnap?: (enabled: boolean) => void;

  // Display picker (for_sonnet.md §4) — which monitor the pill/window lives
  // on. App.tsx owns the monitor list (refreshed on open) and the move-now
  // logic; this panel only renders the list and reports a selection.
  monitors?:          MonitorInfo[];
  selectedMonitorId?: string | null;
  onSelectMonitor?:   (id: string) => void;
}

// ── Theme swatch picker ──────────────────────────────────────────────────────

function ThemeSwatchPicker({ theme, onSelectTheme }: { theme: Theme; onSelectTheme: (t: Theme) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
    >
      {THEMES.map((t) => {
        const active = t === theme;
        return (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={THEME_LABELS[t]}
            title={THEME_LABELS[t]}
            onClick={() => onSelectTheme(t)}
            data-theme={t}
            className="btn-hover"
            style={{
              width: 26,
              height: 26,
              padding: 0,
              border: active ? "2px solid var(--accent)" : "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              background: "var(--surface)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <span
              style={{
                width: 14,
                height: 14,
                background: "var(--accent)",
                border: "1px solid var(--border)",
              }}
            />
          </button>
        );
      })}
    </div>
  );
}

// ── Pill placement anchor grid ───────────────────────────────────────────────
// "custom" (center cell) leaves the pill wherever the window was last
// dragged/placed instead of snapping it anywhere.

const ANCHOR_CELL = 30;

function AnchorGrid({ anchor, onSelect }: { anchor: PillAnchor; onSelect: (a: PillAnchor) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Pill placement"
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(3, ${ANCHOR_CELL}px)`,
        gridTemplateRows: `repeat(3, ${ANCHOR_CELL}px)`,
        gap: 4,
        width: "fit-content",
      }}
    >
      {ANCHOR_ORDER.map((a) => {
        const active = a === anchor;
        const isCustom = a === "custom";
        return (
          <button
            key={a}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={isCustom ? "Custom (last position)" : a}
            title={isCustom ? "Custom — keep last position" : a}
            onClick={() => onSelect(a)}
            className="btn-hover"
            style={{
              width: ANCHOR_CELL,
              height: ANCHOR_CELL,
              padding: 0,
              background: active ? "var(--surface-2)" : "var(--surface)",
              border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
              borderStyle: isCustom ? "dashed" : "solid",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              position: "relative",
            }}
          >
            {isCustom ? (
              <span aria-hidden="true" style={{ width: 6, height: 6, background: active ? "var(--accent)" : "var(--text-3)" }} />
            ) : (
              <AnchorGlyph anchor={a} active={active} />
            )}
          </button>
        );
      })}
    </div>
  );
}

function AnchorGlyph({ anchor, active }: { anchor: PillAnchor; active: boolean }) {
  const color = active ? "var(--accent)" : "var(--text-3)";
  if (anchor === "tc" || anchor === "bc") {
    return <span aria-hidden="true" style={{ width: 16, height: 2, background: color }} />;
  }
  if (anchor === "lc" || anchor === "rc") {
    return <span aria-hidden="true" style={{ width: 2, height: 16, background: color }} />;
  }
  // Corner brackets
  const styleFor: Record<string, CSSProperties> = {
    tl: { borderTop: `2px solid ${color}`, borderLeft: `2px solid ${color}`, top: 6, left: 6 },
    tr: { borderTop: `2px solid ${color}`, borderRight: `2px solid ${color}`, top: 6, right: 6 },
    bl: { borderBottom: `2px solid ${color}`, borderLeft: `2px solid ${color}`, bottom: 6, left: 6 },
    br: { borderBottom: `2px solid ${color}`, borderRight: `2px solid ${color}`, bottom: 6, right: 6 },
  };
  return <span aria-hidden="true" style={{ position: "absolute", width: 9, height: 9, ...styleFor[anchor] }} />;
}

// ── Small labelled input row ─────────────────────────────────────────────────

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <label
        style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-3)",
        }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}

// ── Hotkey recorder ─────────────────────────────────────────────────────────

function HotkeyRecorder({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [recording, setRecording] = useState(false);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (!recording) return;
    e.preventDefault();

    const parts: string[] = [];
    if (e.ctrlKey)  parts.push("ctrl");
    if (e.metaKey)  parts.push("cmd");
    if (e.altKey)   parts.push("alt");
    if (e.shiftKey) parts.push("shift");

    // Prefer e.code for letters/digits so Shift+1 records "1", not the
    // shifted symbol "!" that parse_shortcut on the Rust side can't map.
    let key: string;
    if (e.code.startsWith("Key")) key = e.code.slice(3).toLowerCase();
    else if (e.code.startsWith("Digit")) key = e.code.slice(5);
    else if (e.code === "Space") key = "space";
    else if (e.code === "Enter") key = "enter";
    else if (e.code === "Tab") key = "tab";
    else if (e.code === "Backspace") key = "backspace";
    else key = e.key.toLowerCase();

    if (!["control", "meta", "alt", "shift"].includes(key)) {
      parts.push(key);
      onChange(parts.join("+"));
      setRecording(false);
    }
  };

  useEffect(() => {
    if (recording) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [recording]);

  return (
    <div style={{ display: "flex", gap: 8 }}>
      <div
        style={{
          ...INPUT_STYLE,
          flex: 1,
          cursor: "default",
          fontFamily: "monospace",
          letterSpacing: "0.04em",
          border: recording ? "1px solid color-mix(in srgb, var(--accent) 50%, transparent)" : INPUT_STYLE.border,
          boxShadow: recording ? "0 0 0 2px color-mix(in srgb, var(--accent) 15%, transparent)" : "none",
        }}
      >
        {recording ? (
          <span style={{ color: "var(--accent)", animation: "pulse 1s ease-in-out infinite" }}>
            Press keys…
          </span>
        ) : (
          <span>{formatHotkey(value || DEFAULT_HOTKEY)}</span>
        )}
      </div>
      <button
        className="btn-hover"
        style={BTN_SECONDARY}
        onClick={() => setRecording((r) => !r)}
      >
        {recording ? "Cancel" : "Record"}
      </button>
    </div>
  );
}

// ── Main settings panel ──────────────────────────────────────────────────────

export default function SettingsPanel({
  visible, onClose, theme, themeLabel, onSelectTheme, measureRef,
  displayMode, onSelectDisplayMode,
  pillCorner, onSelectPillCorner,
  pillPinned, onTogglePillPinned,
  pillAnchor, onSelectPillAnchor,
  pillFanStyle, onSelectPillFanStyle,
  pillSnapEnabled, onTogglePillSnap,
  monitors, selectedMonitorId, onSelectMonitor,
}: Props) {
  const [vaultRoot, setVaultRoot] = useState("");
  const [model, setModel] = useState("llama3.2");
  const [hotkey, setHotkey] = useState(DEFAULT_HOTKEY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hotkeyError, setHotkeyError] = useState<string | null>(null);
  const [logLevel, setLogLevelState] = useState<LogLevel>(logger.getLevel());
  const [geoDebug, setGeoDebugState] = useState<boolean>(isGeoDebugEnabled());
  const [confidence, setConfidence] = useState(0.6);
  const [scrutiny, setScrutiny] = useState<"relaxed" | "balanced" | "strict">("balanced");
  const [autoDescribe, setAutoDescribe] = useState(false);

  // Form (look/placement) vs Function (behavior) tabs. Always reopens on
  // Form so returning to Settings doesn't strand the user on Function.
  const [tab, setTab] = useState<"form" | "function">("form");
  useEffect(() => { if (visible) setTab("form"); }, [visible]);

  // Auto-save: any change to a server-persisted field marks the panel dirty;
  // a short debounce flushes it, and closing the panel (visible -> false,
  // which also covers Escape — both routes just flip the parent's `view`)
  // flushes immediately rather than waiting out the debounce.
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // True once a GET /config has actually succeeded. The Python server can
  // still be starting up (a few seconds after launch) when this panel is
  // first opened; if we let edits mark the panel dirty before a real load
  // has landed, the debounced auto-save would flush hardcoded fallback
  // values (e.g. scrutiny: "balanced") over whatever the user actually has
  // saved on disk -- silently "reverting" a real setting. Gate dirty-marking
  // on a successful load so that can never happen.
  const loadedRef = useRef(false);
  const markDirty = () => {
    if (!loadedRef.current) return;
    setDirty(true);
  };

  // Last server-confirmed values, restored if a save attempt is rejected
  // (e.g. an invalid hotkey) instead of silently leaving a bad value live.
  const lastGoodRef = useRef<{
    vaultRoot: string; model: string; hotkey: string;
    confidence: number; scrutiny: "relaxed" | "balanced" | "strict"; autoDescribe: boolean;
  }>({
    vaultRoot: "", model: "llama3.2", hotkey: DEFAULT_HOTKEY,
    confidence: 0.6, scrutiny: "balanced", autoDescribe: false,
  });

  // Load config when panel opens. Retries with backoff: right after launch
  // the Python server may still be a couple of seconds from being ready, and
  // a single failed attempt must NOT leave this panel stuck showing (and,
  // via auto-save, eventually persisting) hardcoded fallback values instead
  // of what's really on disk.
  useEffect(() => {
    if (!visible) return;
    loadedRef.current = false;
    let cancelled = false;
    const delays = [0, 500, 1000, 2000, 4000];

    const attempt = async (i: number) => {
      try {
        const cfg = await getConfig();
        if (cancelled) return;
        let root = cfg.vault?.root;
        if (!root) {
          // No vault root configured yet -- show the server's actual resolved
          // default rather than a client-side guess (which previously drifted
          // from omni_capture/config.py's DEFAULT_VAULT_ROOT).
          try {
            root = (await getVaultCategories()).vault_root;
          } catch {
            root = "";
          }
        }
        if (cancelled) return;
        const loaded = {
          vaultRoot: root ?? "",
          model: cfg.ollama?.model ?? "llama3.2",
          hotkey: cfg.gui?.hotkey ?? DEFAULT_HOTKEY,
          confidence: cfg.capture?.confidence_threshold ?? 0.6,
          scrutiny: cfg.capture?.llm_scrutiny ?? "balanced",
          autoDescribe: cfg.capture?.auto_describe_new_folders ?? false,
        };
        setVaultRoot(loaded.vaultRoot);
        setModel(loaded.model);
        setHotkey(loaded.hotkey);
        setConfidence(loaded.confidence);
        setScrutiny(loaded.scrutiny);
        setAutoDescribe(loaded.autoDescribe);
        lastGoodRef.current = loaded;
        setDirty(false);
        loadedRef.current = true;
      } catch {
        if (cancelled) return;
        if (i + 1 < delays.length) {
          setTimeout(() => attempt(i + 1), delays[i + 1]);
        }
        // else: server still not reachable -- leave loadedRef false so no
        // edit in this session can auto-save over the real on-disk config.
      }
    };
    void attempt(0);

    return () => { cancelled = true; };
  }, [visible]);

  const handlePickFolder = async () => {
    const selected = await openDialog({ directory: true, multiple: false });
    if (selected && typeof selected === "string") {
      setVaultRoot(selected);
      markDirty();
    }
  };

  const flush = useCallback(async (opts: { silent: boolean }) => {
    setHotkeyError(null);
    if (!opts.silent) setSaving(true);
    try {
      await patchConfig({
        vault_root: vaultRoot,
        ollama_model: model,
        hotkey,
        confidence_threshold: confidence,
        llm_scrutiny: scrutiny,
        auto_describe_new_folders: autoDescribe,
      });
      await setHotkeyRust(hotkey);
      lastGoodRef.current = { vaultRoot, model, hotkey, confidence, scrutiny, autoDescribe };
      setDirty(false);
      if (!opts.silent) {
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
    } catch (err) {
      setHotkeyError(err instanceof Error ? err.message : String(err));
      // Don't leave a rejected value live — revert to what the server last
      // actually accepted.
      const g = lastGoodRef.current;
      setVaultRoot(g.vaultRoot);
      setModel(g.model);
      setHotkey(g.hotkey);
      setConfidence(g.confidence);
      setScrutiny(g.scrutiny);
      setAutoDescribe(g.autoDescribe);
      setDirty(false);
    } finally {
      if (!opts.silent) setSaving(false);
    }
  }, [vaultRoot, model, hotkey, confidence, scrutiny, autoDescribe]);

  const handleSave = () => { void flush({ silent: false }); };

  // Debounced auto-save while the panel stays open and dirty.
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => { void flush({ silent: true }); }, 900);
    return () => clearTimeout(t);
  }, [dirty, flush]);

  // Flush immediately when the panel closes (Escape and the X button both
  // just flip the parent's `view` away from "settings", which flows back
  // here as `visible` turning false) instead of waiting out the debounce.
  useEffect(() => {
    if (!visible && dirtyRef.current) {
      void flush({ silent: true });
    }
  }, [visible, flush]);

  return (
    <div
      ref={measureRef}
      style={{
        ...PANEL_FRAME,
        ...panelTransform(visible),
        overflowY: "auto",
      }}
    >
      {/* Header */}
      <div style={PANEL_HEADER} className="drag-region">
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
          Settings
        </span>
        <button className="no-drag icon-close-btn" onClick={onClose} title="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="2" y1="2" x2="12" y2="12" />
            <line x1="12" y1="2" x2="2" y2="12" />
          </svg>
        </button>
      </div>

      {/* Tabs */}
      <Tabs
        tabs={[{ id: "form", label: "Form" }, { id: "function", label: "Function" }]}
        active={tab}
        onChange={setTab}
      />

      {/* Body */}
      <div
        className="no-drag"
        style={{ padding: "16px 16px 14px", display: "flex", flexDirection: "column", gap: 16 }}
      >
        {tab === "form" && (
          <>
            {/* Theme */}
            {onSelectTheme && theme && (
              <Field label="Theme">
                <ThemeSwatchPicker theme={theme} onSelectTheme={onSelectTheme} />
                <span style={{ fontSize: 10, color: "var(--text-3)", marginTop: 4 }}>
                  {themeLabel ?? theme}
                </span>
              </Field>
            )}

            {/* Display Mode (Item 2: pill/minimized window) */}
            {onSelectDisplayMode && displayMode && (
              <Field label="Display Mode">
                <div style={{ display: "flex", gap: 4 }}>
                  {([
                    { v: "full" as const,    label: "Full" },
                    { v: "capsule" as const, label: "Capsule" },
                    { v: "minimal" as const, label: "Minimal" },
                  ]).map(({ v, label }) => {
                    const active = displayMode === v;
                    return (
                      <button
                        key={v}
                        onClick={() => onSelectDisplayMode(v)}
                        className="btn-hover"
                        style={{
                          ...BTN_SECONDARY,
                          flex: 1,
                          background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                          color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                          borderColor: active ? "var(--accent)" : "var(--border)",
                        }}
                        aria-pressed={active}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Full is the current overlay. Capsule/Minimal shrink to a small pill that shows the live pipeline stage — click it (or the hotkey) to expand.
                </span>
              </Field>
            )}

            {onSelectPillCorner && pillCorner && (
              <Field label="Corner Style">
                <div style={{ display: "flex", gap: 4 }}>
                  {([{ v: "sharp" as const, label: "Sharp" }, { v: "rounded" as const, label: "Rounded" }]).map(({ v, label }) => {
                    const active = pillCorner === v;
                    return (
                      <button
                        key={v}
                        onClick={() => onSelectPillCorner?.(v)}
                        className="btn-hover"
                        style={{
                          ...BTN_SECONDARY,
                          flex: 1,
                          background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                          color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                          borderColor: active ? "var(--accent)" : "var(--border)",
                        }}
                        aria-pressed={active}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Rounded turns Capsule into a true pill/oval and Minimal into a circle. Only affects the pill — everything else stays sharp.
                </span>
              </Field>
            )}

            {onTogglePillPinned && pillPinned !== undefined && (
              <Field label="Stay Pinned">
                <div style={{ display: "flex", gap: 4 }}>
                  {([{ v: true, label: "On" }, { v: false, label: "Off" }] as const).map(({ v, label }) => {
                    const active = pillPinned === v;
                    return (
                      <button
                        key={label}
                        onClick={() => onTogglePillPinned?.(v)}
                        className="btn-hover"
                        style={{
                          ...BTN_SECONDARY,
                          flex: 1,
                          background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                          color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                          borderColor: active ? "var(--accent)" : "var(--border)",
                        }}
                        aria-pressed={active}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-3)", display: "block" }}>
                  On: stays on screen until you choose Hide (menu or tray).
                </span>
                <span style={{ fontSize: 10, color: "var(--text-3)", display: "block" }}>
                  Off: hides itself after a capture and when you close a panel.
                </span>
              </Field>
            )}

            {onSelectPillAnchor && pillAnchor && (
              <Field label="Placement">
                <AnchorGrid anchor={pillAnchor} onSelect={(a) => onSelectPillAnchor?.(a)} />
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Pick a corner/edge to snap there always, or leave on Custom (center) for wherever you last positioned it.
                </span>
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Center ("Custom") keeps the pill wherever you drag it.
                </span>
              </Field>
            )}

            {onSelectMonitor && monitors && monitors.length > 1 && (
              <Field label="Display">
                <div role="radiogroup" aria-label="Display" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {monitors.map((m) => {
                    const active = m.id === selectedMonitorId;
                    return (
                      <button
                        key={m.id}
                        role="radio"
                        aria-checked={active}
                        onClick={() => onSelectMonitor(m.id)}
                        className="btn-hover"
                        style={{
                          ...BTN_SECONDARY,
                          textAlign: "left",
                          background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                          color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                          borderColor: active ? "var(--accent)" : "var(--border)",
                        }}
                        aria-pressed={active}
                      >
                        {m.label}
                      </button>
                    );
                  })}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Moves the pill there immediately and remembers the choice.
                </span>
              </Field>
            )}

            {onSelectPillFanStyle && pillFanStyle && (
              <Field label="Fan Style">
                <div style={{ display: "flex", gap: 4 }}>
                  {([
                    { v: "spread" as const, label: "Spread" },
                    { v: "capped" as const, label: "Capped" },
                  ]).map(({ v, label }) => {
                    const active = pillFanStyle === v;
                    return (
                      <button
                        key={v}
                        onClick={() => onSelectPillFanStyle(v)}
                        className="btn-hover"
                        style={{
                          ...BTN_SECONDARY,
                          flex: 1,
                          background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                          color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                          borderColor: active ? "var(--accent)" : "var(--border)",
                        }}
                        aria-pressed={active}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                  Spread lets the radial menu open as wide as the screen allows. Capped keeps spoke spacing tight and even, even when more room is available.
                </span>
              </Field>
            )}

            {onTogglePillSnap && pillSnapEnabled !== undefined && (() => {
              const snapApplicable = pillAnchor === "custom";
              return (
                <Field label="Snap to Edge & Corner">
                  <div style={{ display: "flex", gap: 4, opacity: snapApplicable ? 1 : 0.4 }}>
                    {([{ v: true, label: "On" }, { v: false, label: "Off" }] as const).map(({ v, label }) => {
                      const active = pillSnapEnabled === v;
                      return (
                        <button
                          key={label}
                          disabled={!snapApplicable}
                          onClick={() => snapApplicable && onTogglePillSnap(v)}
                          className={snapApplicable ? "btn-hover" : undefined}
                          style={{
                            ...BTN_SECONDARY,
                            flex: 1,
                            background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                            color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                            borderColor: active ? "var(--accent)" : "var(--border)",
                            cursor: snapApplicable ? "pointer" : "not-allowed",
                          }}
                          aria-pressed={active}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                    {snapApplicable
                      ? "Releasing the pill near a screen edge or corner snaps it there."
                      : "Edge-snapping only applies to the Custom position."}
                  </span>
                </Field>
              );
            })()}
          </>
        )}

        {tab === "function" && (
          <>
            {/* Vault path */}
            <Field label="Obsidian Vault">
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={vaultRoot}
                  onChange={(e) => { setVaultRoot(e.target.value); markDirty(); }}
                  placeholder="~/Documents/Obsidian Vault"
                  style={{ ...INPUT_STYLE, flex: 1 }}
                  onFocus={(e) => {
                    (e.target as HTMLInputElement).style.borderColor = "color-mix(in srgb, var(--accent) 50%, transparent)";
                    (e.target as HTMLInputElement).style.boxShadow = "0 0 0 2px color-mix(in srgb, var(--accent) 15%, transparent)";
                  }}
                  onBlur={(e) => {
                    (e.target as HTMLInputElement).style.borderColor = "var(--border)";
                    (e.target as HTMLInputElement).style.boxShadow = "none";
                  }}
                />
                <button
                  className="btn-hover"
                  style={BTN_SECONDARY}
                  onClick={handlePickFolder}
                >
                  Browse
                </button>
              </div>
            </Field>

            {/* Hotkey */}
            <Field label="Global Hotkey">
              <HotkeyRecorder value={hotkey} onChange={(v) => { setHotkey(v); markDirty(); }} />
              {hotkeyError && (
                <span style={{ fontSize: 11, color: "var(--red)" }}>{hotkeyError}</span>
              )}
            </Field>

            {/* Ollama model */}
            <Field label="Ollama Model">
              <input
                value={model}
                onChange={(e) => { setModel(e.target.value); markDirty(); }}
                placeholder="llama3.2"
                style={INPUT_STYLE}
                onFocus={(e) => {
                  (e.target as HTMLInputElement).style.borderColor = "color-mix(in srgb, var(--accent) 50%, transparent)";
                  (e.target as HTMLInputElement).style.boxShadow = "0 0 0 2px color-mix(in srgb, var(--accent) 15%, transparent)";
                }}
                onBlur={(e) => {
                  (e.target as HTMLInputElement).style.borderColor = "var(--border)";
                  (e.target as HTMLInputElement).style.boxShadow = "none";
                }}
              />
            </Field>

            {/* Inbox sensitivity (confidence threshold) */}
            <Field label="Inbox Sensitivity">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={confidence}
                  onChange={(e) => { setConfidence(parseFloat(e.target.value)); markDirty(); }}
                  style={{ flex: 1, accentColor: "var(--accent)", cursor: "pointer" }}
                  aria-label="Inbox sensitivity (confidence threshold)"
                />
                <span style={{
                  fontFamily: "monospace", fontSize: 12, color: "var(--text-2)",
                  minWidth: 36, textAlign: "right",
                }}>
                  {confidence.toFixed(2)}
                </span>
              </div>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                Higher = more captures sent to the inbox for review.
              </span>
            </Field>

            {/* Classification strictness (llm_scrutiny) */}
            <Field label="Classification Strictness">
              <div style={{ display: "flex", gap: 4 }}>
                {(["relaxed", "balanced", "strict"] as const).map((level) => {
                  const active = scrutiny === level;
                  return (
                    <button
                      key={level}
                      onClick={() => { setScrutiny(level); markDirty(); }}
                      className="btn-hover"
                      style={{
                        ...BTN_SECONDARY,
                        flex: 1,
                        textTransform: "capitalize",
                        background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                        color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                        borderColor: active ? "var(--accent)" : "var(--border)",
                      }}
                      aria-pressed={active}
                    >
                      {level}
                    </button>
                  );
                })}
              </div>
            </Field>

            {/* Auto-describe new folders */}
            <Field label="Auto-describe New Folders">
              <div style={{ display: "flex", gap: 4 }}>
                {([{ v: true, label: "On" }, { v: false, label: "Off" }] as const).map(({ v, label }) => {
                  const active = autoDescribe === v;
                  return (
                    <button
                      key={label}
                      onClick={() => { setAutoDescribe(v); markDirty(); }}
                      className="btn-hover"
                      style={{
                        ...BTN_SECONDARY,
                        flex: 1,
                        background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                        color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                        borderColor: active ? "var(--accent)" : "var(--border)",
                      }}
                      aria-pressed={active}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                Generates a routing description automatically when a new folder is created.
              </span>
            </Field>

            {/* Log level — runtime toggle, no rebuild required */}
            <Field label="Log Level">
              <select
                value={LogLevel[logLevel]}
                onChange={(e) => {
                  const next = LogLevel[e.target.value as keyof typeof LogLevel] as LogLevel;
                  setLogLevelState(next);
                  void setLogLevel(next);
                }}
                style={{ ...INPUT_STYLE, cursor: "pointer" }}
              >
                {(["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "OFF"] as const).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </Field>

            {/* Geometry debug logging — on by default; logs window/monitor/
                scale geometry to the same log file via geoLog (scope "geo"),
                for diagnosing pill drag/clamp boundary issues. */}
            <Field label="Geometry Debug Logging">
              <div style={{ display: "flex", gap: 4 }}>
                {([{ v: true, label: "On" }, { v: false, label: "Off" }] as const).map(({ v, label }) => {
                  const active = geoDebug === v;
                  return (
                    <button
                      key={label}
                      onClick={() => { setGeoDebugState(v); setGeoDebugEnabled(v); }}
                      className="btn-hover"
                      style={{
                        ...BTN_SECONDARY,
                        flex: 1,
                        background: active ? "var(--accent)" : (BTN_SECONDARY.background as string),
                        color: active ? "var(--on-accent)" : (BTN_SECONDARY.color as string),
                        borderColor: active ? "var(--accent)" : "var(--border)",
                      }}
                      aria-pressed={active}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>
                Logs pill window/monitor geometry (scope "geo") to the log file for diagnosing drag/boundary bugs.
              </span>
            </Field>
          </>
        )}
      </div>

      {/* Save button — momentary var(--green) on success is the one
          documented exception to "no colored CTAs" (DESIGN.md §5 Components,
          Buttons/Primary): green here is semantic success state, not button
          branding, and it reverts to --accent after the 2s timeout below.
          Only shown on Function — Form's settings are client-only/instant. */}
      {tab === "function" && (
        <div style={{ padding: "0 16px 16px", display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              ...BTN_PRIMARY,
              background: saved ? "var(--green)" : "var(--accent)",
              cursor: saving ? "not-allowed" : "pointer",
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? "Saving…" : saved ? "Saved ✓" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
