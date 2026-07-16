/**
 * Sync/parts.tsx
 * --------------
 * Idioms shared by the Sync tab's two views (SyncWizard, SyncDashboard). Kept
 * here so the wizard and the dashboard cannot drift into two dialects of the
 * same control — there is ONE status dot, ONE row.
 *
 * Every colour routes through a token; every semantic colour routes through a
 * `StatusTone` resolved in lib/syncSetup.ts from real server state. Nothing in
 * this file may pick green on its own.
 *
 * The boolean-toggle idiom formerly here moved to `ui/Toggle.tsx` (Wave 4) —
 * it wasn't sync-specific and is now the shared toggle used across panels.
 */
import type { CSSProperties, ReactNode } from "react";
import type { StatusTone } from "../../lib/syncSetup";
import type { SyncPassRow } from "../../lib/api";

// ── Tone -> token ───────────────────────────────────────────────────────────
// `none` is the unknown/neutral tone and is --text-3, NEVER green. This map is
// the single place a tone becomes a colour.

export const TONE_COLOR: Record<StatusTone, string> = {
  ok: "var(--green)",
  wait: "var(--yellow)",
  fail: "var(--red)",
  none: "var(--text-3)",
};

/** Text for screen readers + the colour-blind: colour is never the only signal. */
export const TONE_LABEL: Record<StatusTone, string> = {
  ok: "ok",
  wait: "in progress",
  fail: "failed",
  none: "unknown",
};

/**
 * Round status pip. Round is sanctioned here as a status/instrument affordance
 * (design-system §1), not decoration — and it is only ever drawn beside text
 * that says the same thing, so the colour is reinforcement, not the message.
 */
export function StatusDot({ tone, size = 6 }: { tone: StatusTone; size?: number }) {
  return (
    <span
      role="img"
      aria-label={TONE_LABEL[tone]}
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: "50%",
        display: "inline-block",
        // `none` reads as an empty socket rather than a lit indicator.
        background: tone === "none" ? "transparent" : TONE_COLOR[tone],
        border: tone === "none" ? "1px dashed var(--text-3)" : "none",
        transition: "background 160ms var(--hover-ease-out)",
      }}
    />
  );
}

// ── Rows and type ───────────────────────────────────────────────────────────

/**
 * One settings row: title + optional sub-label on the left, control on the right.
 *
 * `stack` drops the control onto its own line below the title. Layout-only, and
 * needed for real: a wide control (the interval segmented group) plus a title does
 * not fit the 288px capsule panel on one row. Same additive-layout-branch idiom as
 * SettingsPanel's `optionRowStyle` — no control is removed and nothing branches on
 * it but flex-direction.
 */
export function SettingRow({
  title, sub, children, disabled = false, last = false, stack = false,
}: {
  title: string;
  sub?: string;
  children: ReactNode;
  disabled?: boolean;
  last?: boolean;
  stack?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: stack ? "column" : "row",
        alignItems: stack ? "stretch" : "center",
        gap: stack ? 8 : 12,
        padding: "8px 0",
        borderBottom: last ? "none" : "1px solid var(--border-2)",
        opacity: disabled ? 0.4 : 1,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "var(--text-1)" }}>{title}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1 }}>{sub}</div>}
      </div>
      {children}
    </div>
  );
}

/** Explanatory copy. `tone` tints it only when the copy is genuinely about a state. */
export function Note({
  children, tone, style,
}: {
  children: ReactNode;
  tone?: StatusTone;
  style?: CSSProperties;
}) {
  return (
    <p
      style={{
        margin: 0,
        fontSize: 11,
        lineHeight: 1.5,
        color: tone && tone !== "none" ? TONE_COLOR[tone] : "var(--text-3)",
        ...style,
      }}
    >
      {children}
    </p>
  );
}

/** A state line: dot + the same state in words. */
export function StatusLine({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--text-2)" }}>
      <StatusDot tone={tone} />
      {children}
    </span>
  );
}

// ── Pass formatting ─────────────────────────────────────────────────────────

/** `hh:mm` from an ISO timestamp; falls back to the raw string rather than lying. */
export function passTime(iso: string): string {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return iso;
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * One-line summary of a pass. `ok:false` is a first-class outcome here, not an
 * afterthought — a failed pass reads as its error, never as a count of zero.
 */
export function passSummary(row: SyncPassRow): string {
  const secs = `${row.duration_s.toFixed(1)}s`;
  if (!row.ok) return `failed after ${secs}${row.error ? ` · ${row.error}` : ""}`;
  // run_pass() merges arbitrary display-only counts in; show the ones that are
  // present and numeric rather than asserting a fixed shape.
  const counts = ["pulled", "pushed", "conflicts"]
    .map((k) => (typeof row[k] === "number" ? `${k} ${row[k] as number}` : null))
    .filter((s): s is string => s !== null);
  return [...counts, secs].join(" · ");
}

export function passTone(row: SyncPassRow): StatusTone {
  return row.ok ? "ok" : "fail";
}
