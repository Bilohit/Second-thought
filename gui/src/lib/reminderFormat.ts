/**
 * reminderFormat.ts — pure formatting for reminder due-times shown in the
 * offer toast and the Dashboard reminders card. No side effects.
 */

function isSameCalendarDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + n);
  return copy;
}

/** Formats an ISO datetime relative to `now`: "Today 3:00 PM", "Tomorrow 9:00 AM",
 *  or "Sun, Jul 5, 3:00 PM" for anything further out. Invalid input passes through
 *  unchanged rather than throwing or showing "Invalid Date". */
export function formatWhen(iso: string, now: Date): string {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;

  const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  if (isSameCalendarDay(date, now)) return `Today ${time}`;
  if (isSameCalendarDay(date, addDays(now, 1))) return `Tomorrow ${time}`;

  const day = date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day}, ${time}`;
}
