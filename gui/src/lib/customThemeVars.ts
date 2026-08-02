// Custom-theme CSS variable application (FR-03 fix). Writes the derived
// palette as inline custom properties on a target element (documentElement
// in production) rather than an injected <style> tag: the production CSP is
// `style-src 'self'` with no `unsafe-inline`/nonce, so an injected
// stylesheet is silently dropped by the webview in release builds — only
// `npm run dev`'s devCsp (which does allow 'unsafe-inline') ever exercised
// it. Inline properties on the root element apply unconditionally (not
// scoped to `[data-theme="custom"]`) and outrank the linked stylesheet,
// which is why removeCustomThemeVars must remove every property this sets,
// exactly — otherwise switching from "custom" to a built-in preset leaves
// stale custom values overriding the preset.
import type { Palette } from "./themeContrast";

// The exact set of CSS custom properties applyCustomThemeVars writes.
// removeCustomThemeVars clears precisely this set — keep the two in sync.
export const CUSTOM_THEME_VAR_NAMES = [
  "--bg", "--surface", "--surface-2", "--border", "--border-2",
  "--text-1", "--text-2", "--text-3",
  "--accent", "--accent-d", "--accent-glow", "--on-accent", "--palette-bg",
  "--recording", "--green", "--yellow", "--red",
  "--glass-bg", "--glass-border", "--scrim",
] as const;

export function applyCustomThemeVars(p: Palette, target: HTMLElement = document.documentElement) {
  const s = target.style;
  s.setProperty("--bg", p.bg);
  s.setProperty("--surface", p.surface);
  s.setProperty("--surface-2", p.surface2);
  s.setProperty("--border", p.border);
  s.setProperty("--border-2", p.border2);
  s.setProperty("--text-1", p.text1);
  s.setProperty("--text-2", p.text2);
  s.setProperty("--text-3", p.text3);
  s.setProperty("--accent", p.accent);
  s.setProperty("--accent-d", p.accentDim);
  s.setProperty("--accent-glow", p.accentGlow);
  s.setProperty("--on-accent", p.onAccent);
  s.setProperty("--palette-bg", p.paletteBg);
  s.setProperty("--recording", p.recording);
  s.setProperty("--green", p.green);
  s.setProperty("--yellow", p.yellow);
  s.setProperty("--red", p.red);
  s.setProperty("--glass-bg", p.glassBg);
  s.setProperty("--glass-border", p.glassBorder);
  s.setProperty("--scrim", p.scrim);
}

export function removeCustomThemeVars(target: HTMLElement = document.documentElement) {
  const s = target.style;
  for (const name of CUSTOM_THEME_VAR_NAMES) s.removeProperty(name);
}
