/**
 * saveRetry.ts — backoff schedule for NoteEditor's debounced autosave.
 *
 * A failed save never advances `lastSavedBodyRef`, so the autosave effect's
 * dep array sees the same body again and re-fires immediately: an unbounded,
 * un-delayed retry loop against an endpoint that is already failing. These two
 * pure helpers decide *whether* the next scheduled attempt is a retry and
 * *how long* to wait for it.
 */

/** Debounce for a normal (non-retry) save. */
export const SAVE_BASE_DELAY_MS = 900;

/** Ceiling on the backoff — a persistently failing save retries about once a
 *  minute, not once a second. */
export const SAVE_MAX_DELAY_MS = 60_000;

/**
 * True when the pending save re-attempts a body that was already sent, rather
 * than a fresh edit. Any change to the body resets this: new content deserves
 * a prompt attempt even if the previous one failed.
 *
 * Deliberately keyed on the body alone, NOT on the save state — the effect
 * that calls this sets state to "saving" and re-runs, so a state-based
 * predicate would read "not a retry" on its own transition and zero the
 * failure count every time, defeating the backoff.
 */
export function isSaveRetry(body: string, lastAttemptedBody: string | null): boolean {
  return lastAttemptedBody !== null && body === lastAttemptedBody;
}

/**
 * Delay before the next attempt. `failureCount` is the number of consecutive
 * failures for the *current* body; 0 (a fresh edit) gives the plain debounce.
 */
export function saveRetryDelayMs(failureCount: number): number {
  if (failureCount <= 0) return SAVE_BASE_DELAY_MS;
  return Math.min(SAVE_BASE_DELAY_MS * 2 ** failureCount, SAVE_MAX_DELAY_MS);
}
