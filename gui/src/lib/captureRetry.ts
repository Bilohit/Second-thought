/**
 * captureRetry.ts - Pure retry/backoff policy for a capture that fails
 * because the Python server hasn't bound its port yet (P1-1, for_sonnet.md).
 * Only a "connection failure" (refused/unreachable) is retried — any other
 * error (a real pipeline error) surfaces immediately.
 */

/** Bounded backoff schedule; null once attempts are exhausted. */
const RETRY_DELAYS_MS = [500, 1500, 3000];

export function isConnectionFailure(err: unknown): boolean {
  return (
    err instanceof TypeError ||
    /failed to fetch|networkerror|load failed/i.test((err as Error)?.message ?? "")
  );
}

/** `attempt` is the number of retries already made (0 on first failure). */
export function nextRetryDelayMs(attempt: number): number | null {
  return RETRY_DELAYS_MS[attempt] ?? null;
}
