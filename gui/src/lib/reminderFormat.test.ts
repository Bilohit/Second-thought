import { describe, it, expect } from "vitest";
import { formatWhen, pickReminderChoices, REMINDER_CHOICE_CAP } from "./reminderFormat";

const NOW = new Date("2026-07-03T12:00:00");

describe("formatWhen", () => {
  it("today", () => expect(formatWhen("2026-07-03T15:00", NOW)).toBe("Today 3:00 PM"));
  it("tomorrow", () => expect(formatWhen("2026-07-04T09:00", NOW)).toBe("Tomorrow 9:00 AM"));
  it("later date", () => expect(formatWhen("2026-07-05T15:00", NOW)).toBe("Sun, Jul 5, 3:00 PM"));
  it("invalid iso passes through", () => expect(formatWhen("garbage", NOW)).toBe("garbage"));
});

describe("pickReminderChoices", () => {
  const ev = (when_iso: string, label = "x") => ({ when_iso, label });

  it("sorts earliest first — body order is not chronological order", () => {
    const out = pickReminderChoices(
      [ev("2026-07-05T15:00", "retro"), ev("2026-07-03T15:00", "standup"), ev("2026-07-04T09:00", "review")],
      NOW,
    );
    expect(out.map((c) => c.whenIso)).toEqual([
      "2026-07-03T15:00", "2026-07-04T09:00", "2026-07-05T15:00",
    ]);
    // The compact shells auto-create out[0]; that must be the EARLIEST, not the first mentioned.
    expect(out[0].eventLabel).toBe("standup");
  });

  it("labels each chip through formatWhen", () => {
    expect(pickReminderChoices([ev("2026-07-04T09:00")], NOW)[0].label).toBe("Tomorrow 9:00 AM");
  });

  it("drops unparseable instants instead of rendering a dead chip", () => {
    const out = pickReminderChoices([ev("garbage"), ev("2026-07-04T09:00")], NOW);
    expect(out).toHaveLength(1);
    expect(out[0].whenIso).toBe("2026-07-04T09:00");
  });

  it("dedupes on the instant, keeping the first-seen event label", () => {
    const out = pickReminderChoices([ev("2026-07-04T09:00", "a"), ev("2026-07-04T09:00", "b")], NOW);
    expect(out).toHaveLength(1);
    expect(out[0].eventLabel).toBe("a");
  });

  it("caps the chip row, and the cap is the earliest N", () => {
    const many = ["2026-07-09", "2026-07-08", "2026-07-07", "2026-07-06", "2026-07-05"]
      .map((d) => ev(`${d}T09:00`));
    const out = pickReminderChoices(many, NOW);
    expect(out).toHaveLength(REMINDER_CHOICE_CAP);
    expect(out.map((c) => c.whenIso)).toEqual([
      "2026-07-05T09:00", "2026-07-06T09:00", "2026-07-07T09:00",
    ]);
  });

  it("returns nothing for no events, and never throws on an empty cap", () => {
    expect(pickReminderChoices([], NOW)).toEqual([]);
    expect(pickReminderChoices([ev("2026-07-04T09:00")], NOW, 0)).toEqual([]);
  });
});
