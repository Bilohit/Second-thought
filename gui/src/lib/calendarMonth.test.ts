import { describe, it, expect } from "vitest";
import { monthWeeks, addMonths, todayYearMonth, isoDate, isSameDay, classifyReminder, groupByDay } from "./calendarMonth";

describe("monthWeeks", () => {
  it("every week has exactly 7 days, and the grid is 4-6 full weeks", () => {
    for (let month = 0; month < 12; month++) {
      const weeks = monthWeeks(2026, month, new Date(2026, month, 1));
      expect(weeks.length).toBeGreaterThanOrEqual(4);
      expect(weeks.length).toBeLessThanOrEqual(6);
      for (const week of weeks) expect(week).toHaveLength(7);
    }
  });

  it("days run consecutively across the whole grid, including week boundaries", () => {
    const weeks = monthWeeks(2026, 1, new Date(2026, 1, 1)); // Feb 2026
    const flat = weeks.flat();
    for (let i = 1; i < flat.length; i++) {
      const prev = flat[i - 1].date;
      const cur = flat[i].date;
      const diffDays = (cur.getTime() - prev.getTime()) / 86400000;
      expect(diffDays).toBe(1);
    }
  });

  it("every day 1..daysInMonth appears exactly once, marked inMonth", () => {
    const weeks = monthWeeks(2026, 1, new Date(2026, 1, 1)); // Feb 2026 (28 days)
    const inMonthDays = weeks.flat().filter((d) => d.inMonth).map((d) => d.date.getDate());
    expect(inMonthDays).toEqual(Array.from({ length: 28 }, (_, i) => i + 1));
  });

  it("leading/trailing padding cells belong to the adjacent month, not the target month", () => {
    const weeks = monthWeeks(2026, 1, new Date(2026, 1, 1));
    const flat = weeks.flat();
    const leading = flat.slice(0, flat.findIndex((d) => d.inMonth));
    for (const cell of leading) expect(cell.date.getMonth()).toBe(0); // January
  });

  it("marks exactly one cell isToday when `now` falls inside the grid", () => {
    const now = new Date(2026, 1, 14);
    const weeks = monthWeeks(2026, 1, now);
    const todays = weeks.flat().filter((d) => d.isToday);
    expect(todays).toHaveLength(1);
    expect(todays[0].iso).toBe("2026-02-14");
  });

  it("marks no cell isToday when `now` is outside the displayed month", () => {
    const weeks = monthWeeks(2026, 1, new Date(2026, 5, 14)); // June, viewing Feb
    expect(weeks.flat().some((d) => d.isToday)).toBe(false);
  });

  it("handles a month whose first day is a Sunday with zero leading padding (Nov 2026)", () => {
    const weeks = monthWeeks(2026, 10, new Date(2026, 10, 1));
    expect(weeks[0][0].inMonth).toBe(true);
    expect(weeks[0][0].date.getDate()).toBe(1);
  });
});

describe("addMonths / todayYearMonth", () => {
  it("wraps forward across a year boundary", () => {
    expect(addMonths(2026, 11, 1)).toEqual({ year: 2027, month: 0 });
  });

  it("wraps backward across a year boundary", () => {
    expect(addMonths(2026, 0, -1)).toEqual({ year: 2025, month: 11 });
  });

  it("stays within the same year for an interior month", () => {
    expect(addMonths(2026, 5, 1)).toEqual({ year: 2026, month: 6 });
  });

  it("todayYearMonth reads the local calendar month off `now`", () => {
    expect(todayYearMonth(new Date(2026, 7, 6))).toEqual({ year: 2026, month: 7 });
  });
});

describe("isoDate / isSameDay", () => {
  it("pads single-digit month/day", () => {
    expect(isoDate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("isSameDay ignores time-of-day", () => {
    expect(isSameDay(new Date(2026, 0, 5, 23, 59), new Date(2026, 0, 5, 0, 1))).toBe(true);
    expect(isSameDay(new Date(2026, 0, 5), new Date(2026, 0, 6))).toBe(false);
  });
});

describe("classifyReminder", () => {
  const now = new Date(2026, 7, 6, 12, 0);

  it("fired wins regardless of fire_at time", () => {
    expect(classifyReminder("fired", "2099-01-01T00:00", now)).toBe("fired");
    expect(classifyReminder("fired", "2000-01-01T00:00", now)).toBe("fired");
  });

  it("pending + past fire_at is overdue", () => {
    expect(classifyReminder("pending", "2026-08-01T09:00", now)).toBe("overdue");
  });

  it("pending + future fire_at is upcoming", () => {
    expect(classifyReminder("pending", "2026-08-10T09:00", now)).toBe("upcoming");
  });

  it("an unparseable fire_at falls back to upcoming rather than throwing", () => {
    expect(classifyReminder("pending", "not-a-date", now)).toBe("upcoming");
  });
});

describe("groupByDay", () => {
  it("groups items sharing a local calendar day", () => {
    const items = [
      { fire_at: "2026-08-10T08:00" },
      { fire_at: "2026-08-10T14:00" },
      { fire_at: "2026-08-11T08:00" },
    ];
    const grouped = groupByDay(items);
    expect(grouped.get("2026-08-10")).toHaveLength(2);
    expect(grouped.get("2026-08-11")).toHaveLength(1);
    expect(grouped.size).toBe(2);
  });

  it("skips unparseable fire_at values instead of throwing", () => {
    const grouped = groupByDay([{ fire_at: "garbage" }, { fire_at: "2026-08-10T08:00" }]);
    expect(grouped.size).toBe(1);
  });

  it("returns an empty map for an empty list", () => {
    expect(groupByDay([]).size).toBe(0);
  });
});
