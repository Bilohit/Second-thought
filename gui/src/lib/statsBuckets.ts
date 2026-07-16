/**
 * statsBuckets.ts — F-16d: pure day-bucket math for the desktop Stats card
 * (streak + contribution heatmap), ported from the phone's
 * `phone/src/lib/stats.ts` bucket logic. The desktop already has per-day
 * data via `/stats`'s `by_day` (captures.db), so this module only does the
 * bucketing/streak arithmetic — no note list, no word counts (desktop's
 * `/stats` doesn't expose those).
 *
 * Pure and deterministic: every function takes `nowMs` explicitly (never
 * reads Date.now() internally) so it's trivially testable — mirrors the
 * phone module's contract exactly.
 *
 * ponytail: `/stats`'s `by_day` only covers the last 30 days (index_writer.py
 * `stats()`), vs. the phone's 140-day field — the heatmap/streak window here
 * is capped at FIELD_DAYS=30 to match what the backend actually returns.
 * Widen FIELD_DAYS only if `/stats` is ever extended to a longer window.
 */

export interface DayBucket {
  date: string; // ISO yyyy-mm-dd (UTC)
  count: number;
}

const DAY_MS = 86_400_000;
export const FIELD_DAYS = 30;

function dayKey(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Consecutive days ending today (working backwards) with >= 1 capture. */
export function currentStreak(byDay: DayBucket[], nowMs: number, maxLookback = 365): number {
  const map = new Map(byDay.map((d) => [d.date, d.count]));
  let streak = 0;
  for (let i = 0; i < maxLookback; i++) {
    const key = dayKey(nowMs - i * DAY_MS);
    if ((map.get(key) ?? 0) > 0) streak++;
    else break;
  }
  return streak;
}

export function totalCaptures(byDay: DayBucket[]): number {
  return byDay.reduce((sum, d) => sum + d.count, 0);
}
