// Custom-theme derivation (Wave 3 T9/T10). VENDORED PARITY TWIN of gui/src/lib/themeDerive.ts — both
// editors turn the 9 user-editable slots into the SAME full palette, so an `st1:` code round-trips to
// an identical look on either platform. The 11 non-editable slots are derived (scheme-aware) or copied
// from the scheme's locked semantic set; the user never edits state colors or the identity (radius/font/
// motion). ponytail: derivations are simple heuristics (alpha tints, a border↔bg mix, black/white
// on-accent) — good enough for a color-only custom theme; the 9 presets keep their hand-tuned exacts.
import type { Palette } from "./themeContrast";
import { luminance } from "./themeContrast";
import type { EditableSlot } from "./themeCode";

function toRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function mix(a: string, b: string, t: number): string {
  const [ar, ag, ab] = toRgb(a);
  const [br, bg, bb] = toRgb(b);
  const ch = (x: number, y: number) => Math.round(x + (y - x) * t).toString(16).padStart(2, "0");
  return `#${ch(ar, br)}${ch(ag, bg)}${ch(ab, bb)}`;
}
function rgba(hex: string, alpha: number): string {
  const [r, g, b] = toRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Scheme-locked slots — semantic state colors + scrim, never user-editable (Void identity lock).
const DARK = { green: "#4ade80", yellow: "#facc15", red: "#ff6467", recording: "#c25b52", scrim: "rgba(0,0,0,0.55)" };
const LIGHT = { green: "#16a34a", yellow: "#92660a", red: "#e7000b", recording: "#b0443c", scrim: "rgba(0,0,0,0.25)" };

export function deriveCustom(e: Record<EditableSlot, string>): Palette {
  const light = luminance(e.bg) > 0.5;
  const sc = light ? LIGHT : DARK;
  return {
    bg: e.bg,
    surface: e.surface,
    surface2: e.surface2,
    border: e.border,
    border2: mix(e.border, e.bg, 0.35), // faint inner divider: border pulled toward bg
    text1: e.text1,
    text2: e.text2,
    text3: e.text3,
    accent: e.accent,
    accentDim: rgba(e.accent, light ? 0.1 : 0.18), // selected-chip tint
    accentGlow: rgba(e.accent, light ? 0.22 : 0.3),
    onAccent: luminance(e.accent) > 0.5 ? "#0a0a0a" : "#fafafa", // legible ON the accent fill
    paletteBg: e.surface,
    recording: sc.recording,
    green: sc.green,
    yellow: sc.yellow,
    red: sc.red,
    glassBg: e.glassBg,
    glassBorder: e.border,
    scrim: sc.scrim,
  };
}
