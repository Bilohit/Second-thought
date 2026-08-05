// Morph-motion durations → inline CSS custom properties on documentElement.
//
// WHY THIS EXISTS: the capsule/panel/island morph durations were hand-tuned by
// the user by feel, and they live in TWO places — TypeScript constants that
// drive the JS-side sequencing (window moves, panelReady gating, exit lag) and
// literal `ms` values in index.css that drive the CSS transitions. Nothing
// enforced that the two agreed. Worse, CapsuleMenu.tsx's own comment claimed
// the CSS read `--capsule-bar-ms`/`--capsule-item-ms` custom properties — those
// properties did not exist, so the documented guard was a reference to nothing.
// A redesign editing one side would silently change the motion with a fully
// green test suite (the pill's tests mount no DOM and exercise no CSS class).
//
// The fix is not a stricter test — it is removing the second copy. The TS
// constants are now the single source; the CSS consumes them as custom
// properties. Drift is no longer representable, only mis-mapping is, and
// motionVars.test.ts pins the mapping.
//
// Applied as inline properties on documentElement, NOT via a <style> tag: the
// production CSP is `style-src 'self'` with no `unsafe-inline`, so an injected
// stylesheet is silently dropped in release builds. This mirrors exactly what
// lib/customThemeVars.ts already does for the palette — same mechanism, same
// reason. Every CSS site keeps a literal fallback equal to today's value, so a
// failure to apply degrades to the current motion rather than to no motion.
//
// The import below reaches into a component module because that is where these
// constants have always lived (the bar owns its own timing). compactPanel.test.ts
// already imports from the same place for the PANEL_W equality lock, so this
// direction is established, not new. CapsuleMenu does not import this module —
// there is no cycle.
import { CAPSULE_ANIM_MS, CAPSULE_ITEM_PLAY_MS } from "../components/PillMenu/CapsuleMenu";
import { PANEL_ANIM_MS, PANEL_EXIT_MS, PANEL_CONTENT_LIFT_MS } from "./compactPanel";

// The close choreography: the panel wipe runs first and the bar shrink lags
// behind it, so the two finish together. index.css encoded the lag as a bare
// `100ms` with a comment warning "never raise that constant instead of this
// delay" — the relationship is now computed, so the warning is enforced by
// arithmetic rather than by hoping someone reads it.
export const PANEL_CLOSE_LAG_MS = PANEL_EXIT_MS - CAPSULE_ANIM_MS;

// Every custom property this module writes. Values are strings with the `ms`
// unit already attached, because CSS `transition-duration` will not accept a
// bare number.
export const MOTION_VARS: Record<string, string> = {
  "--capsule-bar-ms": `${CAPSULE_ANIM_MS}ms`,
  "--capsule-item-ms": `${CAPSULE_ITEM_PLAY_MS}ms`,
  "--panel-anim-ms": `${PANEL_ANIM_MS}ms`,
  "--panel-lift-delay-ms": `${PANEL_CONTENT_LIFT_MS}ms`,
  "--island-content-delay-ms": `${PANEL_ANIM_MS}ms`,
  "--panel-close-lag-ms": `${PANEL_CLOSE_LAG_MS}ms`,
};

// Idempotent and side-effect-free beyond the target's inline style. Safe to
// call on every mount; there is no matching remove() because these values are
// constant for the life of the process — unlike the theme palette, nothing
// ever switches them back off.
export function applyMotionVars(target: HTMLElement = document.documentElement) {
  const s = target.style;
  for (const [name, value] of Object.entries(MOTION_VARS)) s.setProperty(name, value);
}
