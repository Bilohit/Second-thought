/**
 * reminderUndoToast.ts — pure state/lifecycle math for the pill-mode
 * auto-create-reminder undo toast (P2 reminder-consent parity). Full mode
 * asks explicit consent before creating a reminder (App.tsx toast + "Set
 * reminder" action); pill modes have no room for that toast, so they
 * auto-create instead and offer a brief undo window here. No side effects —
 * App.tsx owns the actual setTimeout/createReminder/deleteReminder calls.
 */

export interface ReminderUndoState {
  /** ID of the reminder just auto-created — Undo deletes it. */
  id: number;
  /** Short label shown in the pill/capsule bar in place of its normal text. */
  message: string;
  /** Epoch ms when the toast should auto-dismiss (undo no longer offered). */
  expiresAt: number;
}

const DEFAULT_TTL_MS = 5000;

/** Builds the toast state right after auto-create succeeds.
 *
 *  Singular by construction since s148's REM-1: a note's `remind_at` frontmatter
 *  holds exactly ONE instant, so the compact shells auto-create exactly one
 *  reminder — the earliest detected date. This used to take `ids`/`labels` arrays
 *  and render a "+N more" suffix, which was false twice over once the scalar
 *  became authoritative: N were attempted, one survived, and it was not the one
 *  the suffix implied. `whenLabel` is the human due-time (formatWhen's output),
 *  so the bar names the instant it actually set rather than just asserting one. */
export function makeReminderUndoState(
  id: number,
  whenLabel: string,
  nowMs: number,
  ttlMs: number = DEFAULT_TTL_MS,
): ReminderUndoState {
  const message = whenLabel ? `Reminder set — ${whenLabel}` : "Reminder set";
  return { id, message, expiresAt: nowMs + ttlMs };
}

/** True once `nowMs` has reached the toast's expiry — App.tsx's dismiss
 *  timer checks this instead of trusting its own setTimeout delay blindly,
 *  so a delayed/throttled timer callback never re-arms a second dismiss. */
export function isReminderUndoExpired(state: ReminderUndoState | null, nowMs: number): boolean {
  return state !== null && nowMs >= state.expiresAt;
}

/** Milliseconds until `state` should auto-dismiss, floored at 0 — the value
 *  App.tsx passes straight to `setTimeout`. */
export function reminderUndoRemainingMs(state: ReminderUndoState, nowMs: number): number {
  return Math.max(0, state.expiresAt - nowMs);
}
