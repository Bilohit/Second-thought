/**
 * styles.ts
 * ---------
 * Shared style primitives for the five panel surfaces (Capture, Settings,
 * Vault, Inbox, Stats). Hoisted here so control sizing, padding, and radius
 * can't drift between tabs (UI-ENHANCEMENT-PLAN.md Part B3). Every value
 * routes through the CSS-variable tokens defined in index.css — never a
 * literal hex/rgba — per DESIGN.md's Token-Only Rule.
 */
import type { CSSProperties } from "react";

// ── Layout tokens (Part B3.4 / B3.5) ────────────────────────────────────────

/** One header padding shared by every panel header row. */
export const HEADER_PAD = "14px 16px 12px";

/** One body horizontal inset shared by every panel body. */
export const BODY_PAD_X = "16px";

// ── Full-window secondary-panel frame (Settings/Vault/Inbox/Stats) ─────────
// Intentionally opaque, no blur — index.css's --glass-bg is now a fully
// opaque card colour (no translucency/backdrop-filter), so these panels and
// the HUD's .glass-card already share one flat, opaque surface language.

export const PANEL_FRAME: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  width: 440,
  height: "100%",
  background: "var(--glass-bg)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-xl)",
  transition: "opacity 0.2s cubic-bezier(0.16,1,0.3,1), transform 0.2s cubic-bezier(0.16,1,0.3,1)",
};

export function panelTransform(visible: boolean): CSSProperties {
  return {
    pointerEvents: visible ? "all" : "none",
    opacity: visible ? 1 : 0,
    transform: visible ? "translateX(0)" : "translateX(28px)",
  };
}

export const PANEL_HEADER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: HEADER_PAD,
  borderBottom: "1px solid var(--border-2)",
  flexShrink: 0,
};

export const PANEL_BODY_PAD = `0 ${BODY_PAD_X}` as const;

// ── Controls ─────────────────────────────────────────────────────────────
// All radius tokens (--radius, --radius-sm, --radius-lg, --radius-xl) resolve
// to 0px in index.css — the design is sharp, one scale, no mixing. Controls
// still reference the named tokens (not a literal 0) so a future radius
// change only has to touch index.css.

export const INPUT_STYLE: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "7px 10px",
  fontSize: 12,
  color: "var(--text-2)",
  outline: "none",
  width: "100%",
  fontFamily: "inherit",
  transition: "border-color 0.15s, box-shadow 0.15s",
};

export const BTN_PRIMARY: CSSProperties = {
  padding: "8px 22px",
  fontSize: 12,
  fontWeight: 600,
  borderRadius: "var(--radius)",
  border: "none",
  background: "var(--accent)",
  color: "var(--on-accent)",
  cursor: "pointer",
  transition: "background 0.2s, opacity 0.15s",
  letterSpacing: "0.02em",
};

export const BTN_SECONDARY: CSSProperties = {
  padding: "6px 12px",
  fontSize: 12,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--text-2)",
  cursor: "pointer",
  transition: "background 0.15s, color 0.15s",
  whiteSpace: "nowrap",
};

export const BTN_GHOST: CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  padding: "4px 6px",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-3)",
  display: "flex",
  alignItems: "center",
  transition: "color 0.15s, background 0.15s",
};

export function focusRing(e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) {
  e.target.style.borderColor = "color-mix(in srgb, var(--accent) 50%, transparent)";
  e.target.style.boxShadow = "0 0 0 2px color-mix(in srgb, var(--accent) 15%, transparent)";
}
export function blurRing(e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) {
  e.target.style.borderColor = "var(--border)";
  e.target.style.boxShadow = "none";
}

// ── Rows (Part B3.6) ─────────────────────────────────────────────────────
// One row language per surface kind: filled cards for actionable rows
// (Vault categories, Inbox items — click/approve/delete), bare dividers for
// read-only rows (Stats recent activity, Vault file listings).

export const ROW_CARD: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "11px 12px",
};

export const ROW_DIVIDER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 0",
  borderBottom: "1px solid var(--border-2)",
};
