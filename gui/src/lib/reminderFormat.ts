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

/** Max date chips the offer toast will render. Beyond this the count stays
 *  truthful and the extras are simply not offered — the note's `remind_at` has
 *  room for exactly one instant either way, so a longer list buys nothing. */
export const REMINDER_CHOICE_CAP = 3;

export interface ReminderChoice {
  /** Chip label, e.g. "Tomorrow 9:00 AM". */
  label: string;
  /** The instant this chip would set, passed straight to createReminder. */
  whenIso: string;
  /** The detected event's own label — still sent to POST /reminders for its
   *  optional notification text, even though the row derives its label from
   *  the note title (server.py's REM-1 docstring). */
  eventLabel: string;
}

/**
 * Turn the detected date mentions into the offer's explicit single choice
 * (DECISIONS §5 s148.6). Earliest first, invalid instants dropped, deduped on
 * the instant itself, capped at REMINDER_CHOICE_CAP.
 *
 * Sorting is defensive: the server emits events in body order, which is not
 * chronological order, and "the earliest one" is what the compact shells
 * auto-create — so the ordering has to be established here, once, rather than
 * assumed at each call site.
 */
export function pickReminderChoices(
  events: readonly { when_iso: string; label: string }[],
  now: Date,
  cap: number = REMINDER_CHOICE_CAP,
): ReminderChoice[] {
  const seen = new Set<number>();
  return events
    .map((e) => ({ e, t: new Date(e.when_iso).getTime() }))
    .filter(({ t }) => !isNaN(t))
    .sort((a, b) => a.t - b.t)
    .filter(({ t }) => (seen.has(t) ? false : (seen.add(t), true)))
    .slice(0, Math.max(0, cap))
    .map(({ e }) => ({ label: formatWhen(e.when_iso, now), whenIso: e.when_iso, eventLabel: e.label }));
}
