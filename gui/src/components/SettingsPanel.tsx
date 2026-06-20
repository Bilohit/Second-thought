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

import { type ReactNode, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { getConfig, patchConfig, formatHotkey, DEFAULT_HOTKEY } from "../lib/config";
import { setHotkey as setHotkeyRust, setLogLevel } from "../lib/tauri";
import { getVaultCategories } from "../lib/api";
import { logger, LogLevel } from "../lib/logger";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  INPUT_STYLE, BTN_SECONDARY, BTN_PRIMARY,
} from "./ui/styles";

interface Props {
  visible:      boolean;
  onClose:      () => void;
  theme?:       string;
  themeLabel?:  string;
  onCycleTheme?: () => void;
  measureRef?:  (el: HTMLDivElement | null) => void;
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
        style={BTN_SECONDARY}
        onClick={() => setRecording((r) => !r)}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.background = "var(--surface-2)";
          (e.currentTarget as HTMLElement).style.color = "var(--text-1)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.background = BTN_SECONDARY.background as string;
          (e.currentTarget as HTMLElement).style.color = BTN_SECONDARY.color as string;
        }}
      >
        {recording ? "Cancel" : "Record"}
      </button>
    </div>
  );
}

// ── Main settings panel ──────────────────────────────────────────────────────

export default function SettingsPanel({ visible, onClose, theme, themeLabel, onCycleTheme, measureRef }: Props) {
  const [vaultRoot, setVaultRoot] = useState("");
  const [model, setModel] = useState("llama3.2");
  const [hotkey, setHotkey] = useState(DEFAULT_HOTKEY);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hotkeyError, setHotkeyError] = useState<string | null>(null);
  const [logLevel, setLogLevelState] = useState<LogLevel>(logger.getLevel());
  const [confidence, setConfidence] = useState(0.6);
  const [scrutiny, setScrutiny] = useState<"relaxed" | "balanced" | "strict">("balanced");

  // Load config when panel opens
  useEffect(() => {
    if (!visible) return;
    getConfig()
      .then(async (cfg) => {
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
        setVaultRoot(root ?? "");
        setModel(cfg.ollama?.model ?? "llama3.2");
        setHotkey(cfg.gui?.hotkey ?? DEFAULT_HOTKEY);
        setConfidence(cfg.capture?.confidence_threshold ?? 0.6);
        setScrutiny(cfg.capture?.llm_scrutiny ?? "balanced");
      })
      .catch(() => {/* server may not be up yet — use defaults */});
  }, [visible]);

  const handlePickFolder = async () => {
    const selected = await openDialog({ directory: true, multiple: false });
    if (selected && typeof selected === "string") {
      setVaultRoot(selected);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setHotkeyError(null);
    try {
      await patchConfig({
        vault_root: vaultRoot,
        ollama_model: model,
        hotkey,
        confidence_threshold: confidence,
        llm_scrutiny: scrutiny,
      });
      await setHotkeyRust(hotkey);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setHotkeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

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
        <button
          className="no-drag"
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 4,
            borderRadius: "var(--radius-sm)",
            color: "var(--text-3)",
            display: "flex",
            transition: "color 0.15s, background 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.color = "var(--text-1)";
            (e.currentTarget as HTMLElement).style.background = "var(--surface-2)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.color = "var(--text-3)";
            (e.currentTarget as HTMLElement).style.background = "none";
          }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="2" y1="2" x2="12" y2="12" />
            <line x1="12" y1="2" x2="2" y2="12" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div
        className="no-drag"
        style={{ padding: "16px 16px 14px", display: "flex", flexDirection: "column", gap: 16 }}
      >
        {/* Vault path */}
        <Field label="Obsidian Vault">
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={vaultRoot}
              onChange={(e) => setVaultRoot(e.target.value)}
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
              style={BTN_SECONDARY}
              onClick={handlePickFolder}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--surface-2)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = BTN_SECONDARY.background as string;
              }}
            >
              Browse
            </button>
          </div>
        </Field>

        {/* Hotkey */}
        <Field label="Global Hotkey">
          <HotkeyRecorder value={hotkey} onChange={setHotkey} />
          {hotkeyError && (
            <span style={{ fontSize: 11, color: "var(--red)" }}>{hotkeyError}</span>
          )}
        </Field>

        {/* Theme */}
        {onCycleTheme && (
          <Field label="Theme">
            <button
              onClick={onCycleTheme}
              style={{
                ...BTN_SECONDARY,
                width: "100%",
                textAlign: "left",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "7px 10px",
              }}
              aria-label={`Current theme: ${themeLabel ?? theme}. Click to cycle.`}
            >
              <span style={{ fontFamily: "monospace", letterSpacing: "0.04em" }}>
                {themeLabel ?? theme}
              </span>
              <span style={{ fontSize: 10, opacity: 0.5 }}>click to cycle</span>
            </button>
          </Field>
        )}

        {/* Ollama model */}
        <Field label="Ollama Model">
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
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
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
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
                  onClick={() => setScrutiny(level)}
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
            {(["TRACE", "DEBUG", "INFO", "WARN", "ERROR"] as const).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </Field>
      </div>

      {/* Save button — momentary var(--green) on success is the one
          documented exception to "no colored CTAs" (DESIGN.md §5 Components,
          Buttons/Primary): green here is semantic success state, not button
          branding, and it reverts to --accent after the 2s timeout below. */}
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
    </div>
  );
}
