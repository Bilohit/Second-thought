// WCAG contrast + snap-to-pass for the custom-theme editor (Wave 3 T6). VENDORED PARITY TWIN:
// the phone's `phone/src/lib/themeContrast.ts` carries byte-identical logic (only the Palette source
// differs — the phone imports it from tokens, this side defines it locally since gui keeps palettes in
// index.css, not a TS record). Keep the two in lockstep.
//
// Guardrails (OF-27 applied — text-3 is AA-for-text 4.5:1, not the older 3:1):
//   text1/bg ≥ 7 · text2/bg ≥ 4.5 · text3/bg ≥ 4.5 · accent/bg ≥ 3 · border/bg ≥ 1.5 (soft, warn-only)

// The full palette shape (mirrors the phone's Palette). The editor edits 9 of these and derives the
// rest; the contrast checks read bg + text1/text2/text3/accent/border.
export type Palette = {
  bg: string; surface: string; surface2: string; border: string; border2: string;
  text1: string; text2: string; text3: string;
  accent: string; accentDim: string; accentGlow: string; onAccent: string; paletteBg: string;
  recording: string; green: string; yellow: string; red: string;
  glassBg: string; glassBorder: string; scrim: string;
};

export type Check = { key: string; ratio: number; min: number; pass: boolean; soft: boolean };

function toRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
// sRGB channel → linear (WCAG 2.x relative-luminance definition).
function lin(v: number): number {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
export function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(a: string, b: string): number {
  const la = luminance(a),
    lb = luminance(b);
  const hi = Math.max(la, lb),
    lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

// The five guardrail rows, in editor display order. `border` is soft (warn-only, never blocks Save).
const GUARDRAILS: Array<{ key: keyof Palette; min: number; soft?: boolean }> = [
  { key: "text1", min: 7 },
  { key: "text2", min: 4.5 },
  { key: "text3", min: 4.5 }, // OF-27: AA-for-text, not the older 3:1
  { key: "accent", min: 3 },
  { key: "border", min: 1.5, soft: true },
];

export function checkPalette(p: Palette): Check[] {
  return GUARDRAILS.map((g) => {
    const ratio = contrast(p[g.key], p.bg);
    return { key: g.key as string, ratio, min: g.min, pass: ratio >= g.min, soft: !!g.soft };
  });
}

// Only the checks that would BLOCK Save — non-soft and failing. Empty ⇒ the palette is publishable.
export function hardFails(p: Palette): Check[] {
  return checkPalette(p).filter((c) => !c.soft && !c.pass);
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l]; // achromatic
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h / 6, s, l];
}
function hue2rgb(p: number, q: number, t: number): number {
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}
function hslToHex(h: number, s: number, l: number): string {
  let r: number, g: number, b: number;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  const hx = (v: number) => Math.round(v * 255).toString(16).padStart(2, "0");
  return `#${hx(r)}${hx(g)}${hx(b)}`;
}

// Nudge the foreground toward the shade the bg demands (darker on a light bg, lighter on a dark one),
// stepping HSL lightness until contrast ≥ min — hue/saturation preserved so "snap to pass" stays the
// user's color, just a legible shade of it. ponytail: linear L-walk in 1% steps (≤100, always
// terminates); OKLCH would be perceptually smoother but adds a dep. Falls back to pure black/white.
export function snapToPass(fgHex: string, bgHex: string, min: number): string {
  if (contrast(fgHex, bgHex) >= min) return fgHex;
  const bgLight = luminance(bgHex) > 0.5;
  const [h, s, l0] = rgbToHsl(...toRgb(fgHex));
  let l = l0;
  const step = bgLight ? -0.01 : 0.01;
  for (let i = 0; i < 100; i++) {
    l = Math.min(1, Math.max(0, l + step));
    const cand = hslToHex(h, s, l);
    if (contrast(cand, bgHex) >= min) return cand;
    if (l === 0 || l === 1) break;
  }
  return bgLight ? "#000000" : "#ffffff";
}
