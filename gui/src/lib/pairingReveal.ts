/**
 * pairingReveal.ts — pure timing/format math for the pairing-QR reveal gate (GUI-19).
 *
 * The pairing QR encodes a live LAN credential (`lan_secret` + the NaCl `key`), so the panel
 * never renders it unbidden: the QR is only ENCODED once the user reveals it, and it reseals
 * itself after a bounded window. This module owns the window math only — the fraction the bar
 * fills, the countdown text, and the accent→warn colour ramp — so it can be tested without a DOM.
 * The component (PairingPanel) owns the effect that actually gates the encode and drives the clock.
 *
 * Reseal is what defends against the real threat (a glance, a screenshot, a screen-share catching
 * the code): the window closes on its own, on `Hide now`, and — in the component — on window blur.
 */

/** How long a revealed QR stays on screen before it reseals itself. */
export const REVEAL_WINDOW_MS = 60_000;

/** Advance the remaining time by one frame. Paused (hover / hidden tab) freezes it; never negative. */
export function tickRemaining(remaining: number, dtMs: number, paused: boolean): number {
  if (paused) return remaining;
  return Math.max(0, remaining - dtMs);
}

/** 0‥1 share of the window still left — the bar's horizontal scale. */
export function revealFraction(remaining: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(1, Math.max(0, remaining / total));
}

/** `m:ss` of the whole seconds still left (ceil, so "0:00" appears only at the very end). */
export function formatCountdown(remainingMs: number): string {
  const s = Math.max(0, Math.ceil(remainingMs / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Bar colour as the window closes: neutral accent, then yellow, then red near the end.
 * red/yellow are the app's SEMANTIC-STATE colours (index.css lock) — used here as a genuine
 * signal that the credential's exposure window is running out, not as decoration.
 *
 * To make the bar stay a single neutral colour instead (strict reading of the lock), return
 * `"var(--accent)"` unconditionally here — it is the only line that decides this.
 */
export function barColor(fraction: number): string {
  if (fraction > 0.34) return "var(--accent)";
  if (fraction > 0.16) return "var(--yellow)";
  return "var(--red)";
}
