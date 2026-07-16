import { describe, it, expect } from "vitest";
import { currentStreak, totalCaptures } from "./statsBuckets";

const DAY_MS = 86_400_000;
const NOW = Date.parse("2026-07-14T12:00:00Z");

describe("currentStreak", () => {
  it("counts consecutive days ending today", () => {
    const byDay = [
      { date: "2026-07-14", count: 2 },
      { date: "2026-07-13", count: 1 },
      { date: "2026-07-12", count: 4 },
      { date: "2026-07-10", count: 1 }, // gap on the 11th breaks the streak
    ];
    expect(currentStreak(byDay, NOW)).toBe(3);
  });

  it("zero when today has no captures", () => {
    expect(currentStreak([{ date: "2026-07-13", count: 5 }], NOW)).toBe(0);
  });

  it("empty input -> 0", () => {
    expect(currentStreak([], NOW)).toBe(0);
  });

  it("streak spanning a month boundary", () => {
    const byDay = [
      { date: "2026-07-14", count: 1 },
      { date: "2026-07-13", count: 1 },
      { date: "2026-06-30", count: 1 }, // not contiguous -- ignored
    ];
    expect(currentStreak(byDay, NOW)).toBe(2);
    // Sanity: the gap day used above really is one day before 2026-07-01.
    expect(new Date(Date.parse("2026-07-01T00:00:00Z") - DAY_MS).toISOString().slice(0, 10)).toBe("2026-06-30");
  });
});

describe("totalCaptures", () => {
  it("sums counts", () => {
    expect(totalCaptures([{ date: "a", count: 2 }, { date: "b", count: 5 }])).toBe(7);
  });
  it("empty -> 0", () => {
    expect(totalCaptures([])).toBe(0);
  });
});
