/**
 * reminderUndoToast.ts — pure state/lifecycle math for the pill-mode
 * auto-create-reminder undo toast (P2 reminder-consent parity). Full mode
 * asks explicit consent before creating a reminder (App.tsx toast + "Set
 * reminder" action); pill modes have no room for that toast, so they
 * auto-create instead and offer a brief undo window here. No side effects —
 * App.tsx owns the actual setTimeout/createReminder/deleteReminder calls.
 */

export interface ReminderUndoState {
  /** IDs of the reminders just auto-created — Undo deletes all of them. */
  ids: number[];
  /** Short label shown in the pill/capsule bar in place of its normal text. */
  message: string;
  /** Epoch ms when the toast should auto-dismiss (undo no longer offered). */
  expiresAt: number;
}

const DEFAULT_TTL_MS = 5000;

/** Builds the toast state right after auto-create succeeds. `labels` is the
 *  per-event reminder label list (same order as `ids`); only the first is
 *  shown, with a "+N more" suffix mirroring the full-mode toast's wording. */
export function makeReminderUndoState(
  ids: number[],
  labels: string[],
  nowMs: number,
  ttlMs: number = DEFAULT_TTL_MS,
): ReminderUndoState {
  const more = labels.length > 1 ? ` (+${labels.length - 1} more)` : "";
  const message = labels.length > 0 ? `Reminder set${more}` : "Reminder set";
  return { ids, message, expiresAt: nowMs + ttlMs };
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
