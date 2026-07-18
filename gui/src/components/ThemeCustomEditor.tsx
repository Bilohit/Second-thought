/**
 * ThemeCustomEditor.tsx
 * ----------------------
 * Desktop custom-theme editor (Wave 3 T9). Matches
 * `final batch mockups/02-theming-custom-editor.html`'s DESKTOP pane: 9
 * editable slots (hex text + native color picker + live contrast meter),
 * two LOCKED identity rows, a live-updating preview card, Save/Reset, and
 * portable `st1:` theme-code copy/paste.
 *
 * All WCAG math is reused from the pure modules — this file writes no
 * contrast/snap/derive/encode logic of its own, only glue:
 *   - lib/themeContrast.ts  → contrast(), hardFails(), luminance(), snapToPass()
 *   - lib/themeDerive.ts    → deriveCustom() (9 edited slots → full Palette)
 *   - lib/themeCode.ts      → EDITABLE_ORDER, encodeTheme(), decodeTheme()
 *
 * Per-slot meter guardrails (OF-27 applied: text-3 is 4.5 HARD, not the
 * stale 3:1 soft the mockup's code comment still shows):
 *   bg→text1/bg ≥7 soft · surface→text1/surface ≥4.5 soft ·
 *   surface2→text1/surface2 ≥4.5 soft · border→border/bg ≥1.5 soft ·
 *   text1→text1/bg ≥7 HARD · text2→text2/bg ≥4.5 HARD ·
 *   text3→text3/bg ≥4.5 HARD · accent→accent/bg ≥3 HARD ·
 *   glassBg→text1/glassBg ≥4.5 soft.
 * The four HARD rows are exactly lib/themeContrast.ts's GUARDRAILS (minus
 * the soft border row) — so `hardFails(deriveCustom(draft))` is both the
 * Save-gate and this file's own per-row `hard` flags, never duplicated.
 */
import { useCallback, useMemo, useState, type CSSProperties } from "react";
import { EDITABLE_ORDER, encodeTheme, decodeTheme, type EditableSlot } from "../lib/themeCode";
import { contrast, hardFails, luminance, snapToPass } from "../lib/themeContrast";
import { deriveCustom } from "../lib/themeDerive";
import { CUSTOM_THEME_DEFAULTS } from "../App";
import { LockIcon } from "./PillMenu/icons";
import { INPUT_STYLE, BTN_PRIMARY, BTN_SECONDARY } from "./ui/styles";

interface Props {
  /** Last-saved custom palette (App.tsx's persisted state) — the editor's
   *  working draft initializes from this and only commits back on Save. */
  savedSlots: Record<EditableSlot, string>;
  onSave: (slots: Record<EditableSlot, string>) => void;
  /** Capsule/288px context — narrower grid + smaller type, no control lost. */
  compact?: boolean;
}

const SLOT_LABELS: Record<EditableSlot, string> = {
  bg: "bg", surface: "surface", surface2: "surface-2", border: "border",
  text1: "text-1", text2: "text-2", text3: "text-3", accent: "accent", glassBg: "glass-bg",
};

type MeterCfg = { fg: EditableSlot; bg: EditableSlot; min: number; hard: boolean; label: string };
// Row → which pair its meter checks. `fg`/`bg` point at draft slot keys; the
// row's OWN slot is always one side of the pair, `other` (for snap) is
// whichever side that isn't.
const METERS: Record<EditableSlot, MeterCfg> = {
  bg:       { fg: "text1", bg: "bg",       min: 7,   hard: false, label: "text-1/bg" },
  surface:  { fg: "text1", bg: "surface",  min: 4.5, hard: false, label: "text-1/surface" },
  surface2: { fg: "text1", bg: "surface2", min: 4.5, hard: false, label: "text-1/surface-2" },
  border:   { fg: "border", bg: "bg",      min: 1.5, hard: false, label: "border/bg" },
  text1:    { fg: "text1", bg: "bg",       min: 7,   hard: true,  label: "text-1/bg" },
  text2:    { fg: "text2", bg: "bg",       min: 4.5, hard: true,  label: "text-2/bg" },
  text3:    { fg: "text3", bg: "bg",       min: 4.5, hard: true,  label: "text-3/bg" },
  accent:   { fg: "accent", bg: "bg",      min: 3,   hard: true,  label: "accent/bg" },
  glassBg:  { fg: "text1", bg: "glassBg",  min: 4.5, hard: false, label: "text-1/glass" },
};

function normalizeHex(raw: string): string | null {
  let h = raw.trim();
  if (!h.startsWith("#")) h = "#" + h;
  if (/^#[0-9a-fA-F]{3}$/.test(h)) {
    h = "#" + h.slice(1).split("").map((c) => c + c).join("");
  }
  return /^#[0-9a-fA-F]{6}$/.test(h) ? h.toLowerCase() : null;
}

export default function ThemeCustomEditor({ savedSlots, onSave, compact }: Props) {
  const [draft, setDraft] = useState<Record<EditableSlot, string>>(() => ({ ...savedSlots }));
  const [hexText, setHexText] = useState<Record<EditableSlot, string>>(() => ({ ...savedSlots }));
  const [invalid, setInvalid] = useState<Partial<Record<EditableSlot, boolean>>>({});
  const [pasteValue, setPasteValue] = useState("");
  const [pasteInvalid, setPasteInvalid] = useState(false);
  const [codeOutput, setCodeOutput] = useState("");
  const [saveFlash, setSaveFlash] = useState(false);

  const setSlot = useCallback((k: EditableSlot, hex: string) => {
    setDraft((d) => ({ ...d, [k]: hex }));
    setHexText((t) => ({ ...t, [k]: hex }));
    setInvalid((v) => ({ ...v, [k]: false }));
  }, []);

  const handleHexChange = useCallback((k: EditableSlot, raw: string) => {
    setHexText((t) => ({ ...t, [k]: raw }));
    const norm = normalizeHex(raw);
    if (norm) {
      setDraft((d) => ({ ...d, [k]: norm }));
      setInvalid((v) => ({ ...v, [k]: false }));
    } else {
      setInvalid((v) => ({ ...v, [k]: true }));
    }
  }, []);

  const handleHexBlur = useCallback((k: EditableSlot) => {
    setHexText((t) => ({ ...t, [k]: draft[k] }));
    setInvalid((v) => ({ ...v, [k]: false }));
  }, [draft]);

  const derived = useMemo(() => deriveCustom(draft), [draft]);
  const fails = useMemo(() => hardFails(derived), [derived]);
  const canSave = fails.length === 0;
  const light = luminance(draft.bg) > 0.5;

  const reset = useCallback(() => {
    setDraft({ ...CUSTOM_THEME_DEFAULTS });
    setHexText({ ...CUSTOM_THEME_DEFAULTS });
    setInvalid({});
  }, []);

  const save = useCallback(() => {
    if (!canSave) return;
    onSave(draft);
    setSaveFlash(true);
    setTimeout(() => setSaveFlash(false), 1400);
  }, [canSave, draft, onSave]);

  const copyCode = useCallback(() => {
    const code = encodeTheme(draft);
    setCodeOutput(code);
    if (navigator.clipboard) navigator.clipboard.writeText(code).catch(() => { /* ignore */ });
  }, [draft]);

  const applyPasted = useCallback(() => {
    const decoded = decodeTheme(pasteValue);
    if (!decoded) { setPasteInvalid(true); return; }
    setPasteInvalid(false);
    setDraft(decoded);
    setHexText(decoded);
    setInvalid({});
  }, [pasteValue]);

  const fontSize = compact ? 10 : 11;
  const gridCols = compact ? "56px 70px 24px minmax(0,1fr)" : "68px 82px 26px minmax(0,1fr)";
  const sectionLabel: CSSProperties = {
    fontSize: 10, letterSpacing: "0.08em", color: "var(--text-3)",
    margin: "14px 0 6px", borderBottom: "1px solid var(--border-2)", paddingBottom: 3,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 16 : 20 }}>
      {/* ── editor ─────────────────────────────────────────────────────── */}
      <div>
        <div style={sectionLabel}>SLOTS</div>
        {EDITABLE_ORDER.map((k) => {
          const cfg = METERS[k];
          const ratio = contrast(draft[cfg.fg], draft[cfg.bg]);
          const pass = ratio >= cfg.min;
          const otherKey = cfg.fg === k ? cfg.bg : cfg.fg;
          return (
            <div
              key={k}
              style={{
                display: "grid", gridTemplateColumns: gridCols,
                gap: compact ? 6 : 8, alignItems: "center", padding: "4px 0",
              }}
            >
              <label htmlFor={`ct-hex-${k}`} style={{ fontSize, color: "var(--text-2)" }}>
                {SLOT_LABELS[k]}
              </label>
              <input
                id={`ct-hex-${k}`}
                type="text"
                spellCheck={false}
                aria-label={`${SLOT_LABELS[k]} hex value`}
                value={hexText[k]}
                onChange={(e) => handleHexChange(k, e.target.value)}
                onBlur={() => handleHexBlur(k)}
                style={{
                  ...INPUT_STYLE,
                  padding: "4px 6px",
                  fontSize,
                  borderColor: invalid[k] ? "var(--red)" : "var(--border)",
                }}
              />
              <input
                type="color"
                aria-label={`${SLOT_LABELS[k]} color picker`}
                value={draft[k]}
                onChange={(e) => setSlot(k, e.target.value)}
                style={{
                  width: 26, height: 24, padding: 1, border: "1px solid var(--border)",
                  background: "var(--glass-bg)", borderRadius: 0, cursor: "pointer",
                }}
              />
              <span
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0,
                  fontSize: fontSize - 1, color: "var(--text-3)",
                  border: `1px solid ${pass ? "var(--border-2)" : "var(--red)"}`,
                  padding: "3px 6px", whiteSpace: "nowrap", justifySelf: "start", maxWidth: "100%",
                }}
              >
                <span style={{ width: 7, height: 7, flex: "0 0 auto", background: pass ? "var(--green)" : "var(--red)" }} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  {cfg.label} {ratio.toFixed(1)}:1
                </span>
                <span style={{ color: pass ? "var(--green)" : "var(--red)" }}>{pass ? "PASS" : "FAIL"}</span>
                {!pass && (
                  <button
                    type="button"
                    className="btn-hover"
                    aria-label={`snap ${SLOT_LABELS[k]} to nearest passing value`}
                    onClick={() => setSlot(k, snapToPass(draft[k], draft[otherKey], cfg.min))}
                    style={{
                      font: "inherit", fontSize: 9, letterSpacing: "0.05em", cursor: "pointer",
                      color: "var(--text-2)", background: "var(--surface)", border: "1px solid var(--border)",
                      padding: "1px 6px",
                    }}
                  >
                    snap
                  </button>
                )}
              </span>
            </div>
          );
        })}

        {/* ── locked identity rows ────────────────────────────────────── */}
        <div style={sectionLabel}>LOCKED</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", opacity: 0.45, fontSize: 11, color: "var(--text-2)" }}>
          <LockIcon />
          <span style={{ width: 7, height: 7, background: "var(--green)" }} />
          <span style={{ width: 7, height: 7, background: "var(--yellow)" }} />
          <span style={{ width: 7, height: 7, background: "var(--red)" }} />
          <span>state colors — locked</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", opacity: 0.45, fontSize: 11, color: "var(--text-2)" }}>
          <LockIcon />
          <span>radius 0 · Geist Mono · motion — identity — locked</span>
        </div>

        <div style={{ fontSize: 10, color: "var(--red)", minHeight: 15, marginTop: 6 }}>
          {fails.length > 0
            ? `hard fail — ${fails.map((f) => `${f.key} ${f.ratio.toFixed(1)}:1 < ${f.min}:1`).join(" · ")}`
            : <span style={{ color: "var(--green)" }}>all hard checks pass</span>}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <button type="button" className="btn-hover" onClick={save} disabled={!canSave} aria-disabled={!canSave}
            style={{ ...BTN_PRIMARY, opacity: canSave ? 1 : 0.4, cursor: canSave ? "pointer" : "not-allowed" }}>
            {saveFlash ? "Saved" : "Save theme"}
          </button>
          <button type="button" className="btn-hover" onClick={reset} style={BTN_SECONDARY}>Reset</button>
        </div>

        {/* ── theme code ───────────────────────────────────────────────── */}
        <div style={sectionLabel}>THEME CODE</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="btn-hover" onClick={copyCode} style={BTN_SECONDARY}>Copy theme code</button>
          <input
            type="text" readOnly value={codeOutput} aria-label="theme code output"
            style={{ ...INPUT_STYLE, flex: 1, minWidth: 160, fontSize: 10 }}
          />
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
          <input
            type="text" placeholder="paste st1:… code" aria-label="paste theme code"
            value={pasteValue}
            onChange={(e) => { setPasteValue(e.target.value); setPasteInvalid(false); }}
            style={{
              ...INPUT_STYLE, flex: 1, minWidth: 160, fontSize: 10,
              borderColor: pasteInvalid ? "var(--red)" : "var(--border)",
            }}
          />
          <button type="button" className="btn-hover" onClick={applyPasted} style={BTN_SECONDARY}>Apply</button>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 6 }}>
          <b style={{ color: "var(--text-2)", fontWeight: 600 }}>{light ? "light" : "dark"} scheme derivations</b>
          {" — "}hover dim {light ? "0.10" : "0.18"}, {light ? "light" : "dark"} state colors, {light ? "light" : "dark"} scrim
        </div>
      </div>

      {/* ── live preview ───────────────────────────────────────────────── */}
      <div>
        <div style={sectionLabel}>LIVE PREVIEW</div>
        <div style={{ border: `1px solid ${derived.border}`, background: derived.bg, fontSize: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderBottom: `1px solid ${derived.border2}` }}>
            <span style={{ width: 7, height: 7, flex: "0 0 auto", background: derived.green }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: derived.text1, fontSize: 12.5 }}>reading list — attention</div>
              <div style={{ color: derived.text3, fontSize: 11 }}>synced · 14:02</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, padding: "10px 12px", borderBottom: `1px solid ${derived.border2}`, flexWrap: "wrap" }}>
            <span style={{ border: `1px solid ${derived.border}`, color: derived.text2, fontSize: 10, padding: "2px 7px", background: derived.surface }}>idea</span>
            <span style={{ border: `1px solid ${derived.border}`, color: derived.text2, fontSize: 10, padding: "2px 7px", background: derived.surface }}>reading</span>
            <span style={{ border: `1px dashed ${derived.border}`, color: derived.text2, fontSize: 10, padding: "2px 7px" }}>+ tag</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px" }}>
            <button type="button" disabled style={{ font: "inherit", fontSize: 11, color: derived.text2, background: derived.surface, border: `1px solid ${derived.border}`, padding: "4px 10px", cursor: "default" }}>
              Sync now
            </button>
            <span style={{ width: 7, height: 7, background: derived.green }} />
            <span style={{ width: 7, height: 7, background: derived.yellow }} />
            <span style={{ width: 7, height: 7, background: derived.red }} />
          </div>
          <div style={{ padding: "8px 12px 12px", borderTop: `1px solid ${derived.border2}` }}>
            <div style={{ color: derived.text1, fontSize: 12.5 }}>text-1 · primary copy sample</div>
            <div style={{ color: derived.text2, fontSize: 11.5 }}>text-2 · secondary copy sample</div>
            <div style={{ color: derived.text3, fontSize: 11 }}>text-3 · meta copy sample</div>
          </div>
        </div>
      </div>
    </div>
  );
}
