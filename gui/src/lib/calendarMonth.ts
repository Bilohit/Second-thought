/**
 * calendarMonth.ts
 * ----------------
 * CAL-D: pure month arithmetic for the NOTES capture-pane calendar surface
 * (`NotesView.tsx`'s calendar satellite/morph). No date library — none is
 * installed on either platform (see `reminderFormat.ts` for the same native
 * `Date` convention this file follows) and none is to be added; every
 * function here is plain `Date` field math.
 *
 * `fire_at` values come from the `reminders` SQLite table (`GET /reminders`,
 * `gui/src/lib/api.ts`'s `Reminder.fire_at`) — a naive-local ISO string,
 * exactly as `omni_capture/today_view.py:_parse_local` treats it: an
 * offset-aware value converts to local time, a naive one is assumed already
 * local. `new Date(iso)` + the local getters (`getFullYear`/`getMonth`/
 * `getDate`) give the identical reading without any TZ library.
 */

export interface MonthDay {
  date: Date;
  /** YYYY-MM-DD, local calendar day. */
  iso: string;
  /** False for the leading/trailing days of the adjacent months that pad the grid to full weeks. */
  inMonth: boolean;
  isToday: boolean;
}

/** Local YYYY-MM-DD for `d` — the same key both `monthWeeks` cells and `groupByDay` use to match. */
export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/**
 * Full-week grid (Sunday-first, 4-6 rows of 7) for `month` (0-indexed) of `year`, padded with the
 * adjacent months' days so every row is complete — the standard month-grid shape. `now` marks the
 * single `isToday` cell when today falls inside this grid (it may not, for a month far from now).
 */
export function monthWeeks(year: number, month: number, now: Date): MonthDay[][] {
  const first = new Date(year, month, 1);
  const startOffset = first.getDay(); // 0=Sun .. 6=Sat, days to back up to the grid's Sunday
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const totalCells = Math.ceil((startOffset + daysInMonth) / 7) * 7;
  const gridStart = new Date(year, month, 1 - startOffset);

  const weeks: MonthDay[][] = [];
  for (let w = 0; w < totalCells / 7; w++) {
    const week: MonthDay[] = [];
    for (let d = 0; d < 7; d++) {
      const cell = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + w * 7 + d);
      week.push({ date: cell, iso: isoDate(cell), inMonth: cell.getMonth() === month, isToday: isSameDay(cell, now) });
    }
    weeks.push(week);
  }
  return weeks;
}

/** Navigate `delta` whole months from `year`/`month` (0-indexed), wrapping the year correctly. */
export function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  const d = new Date(year, month + delta, 1);
  return { year: d.getFullYear(), month: d.getMonth() };
}

export function todayYearMonth(now: Date): { year: number; month: number } {
  return { year: now.getFullYear(), month: now.getMonth() };
}

/** Semantic tier for one reminder, per the calendar's colour rule (spec: red=overdue,
 *  dim=already fired, plain=upcoming). `fired` wins regardless of clock time -- it is the
 *  table's own delivered-state, not a derived one. */
export type ReminderTier = "overdue" | "fired" | "upcoming";

export function classifyReminder(status: string, fireAtIso: string, now: Date): ReminderTier {
  if (status === "fired") return "fired";
  const fireAt = new Date(fireAtIso);
  if (!isNaN(fireAt.getTime()) && fireAt.getTime() < now.getTime()) return "overdue";
  return "upcoming";
}

/** Groups any `fire_at`-bearing list (i.e. `Reminder[]`) by local calendar day, keyed the same way
 *  `monthWeeks`' cells are (`isoDate`) so a day cell's density dots are a plain Map lookup.
 *  Unparseable `fire_at` values are skipped, not thrown -- one bad reminder must never blank the
 *  whole month. Kept generic (no import of `api.ts`'s `Reminder` type) so this stays a
 *  zero-dependency pure module. */
export function groupByDay<T extends { fire_at: string }>(items: T[]): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const d = new Date(item.fire_at);
    if (isNaN(d.getTime())) continue;
    const key = isoDate(d);
    const list = map.get(key);
    if (list) list.push(item);
    else map.set(key, [item]);
  }
  return map;
}
