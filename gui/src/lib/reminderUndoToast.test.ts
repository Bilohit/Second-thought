import { describe, it, expect } from "vitest";
import { makeReminderUndoState, isReminderUndoExpired, reminderUndoRemainingMs } from "./reminderUndoToast";

describe("makeReminderUndoState", () => {
  it("single reminder message has no suffix", () => {
    const s = makeReminderUndoState([1], ["Call Bob"], 1000);
    expect(s.message).toBe("Reminder set");
    expect(s.ids).toEqual([1]);
    expect(s.expiresAt).toBe(1000 + 5000);
  });

  it("multiple reminders get a (+N more) suffix", () => {
    const s = makeReminderUndoState([1, 2, 3], ["a", "b", "c"], 1000);
    expect(s.message).toBe("Reminder set (+2 more)");
  });

  it("honors a custom ttlMs", () => {
    const s = makeReminderUndoState([1], ["a"], 1000, 2000);
    expect(s.expiresAt).toBe(3000);
  });
});

describe("isReminderUndoExpired", () => {
  it("false before expiry, true at/after expiry", () => {
    const s = makeReminderUndoState([1], ["a"], 1000, 5000);
    expect(isReminderUndoExpired(s, 5999)).toBe(false);
    expect(isReminderUndoExpired(s, 6000)).toBe(true);
    expect(isReminderUndoExpired(s, 6001)).toBe(true);
  });

  it("null state is never expired", () => {
    expect(isReminderUndoExpired(null, 999999)).toBe(false);
  });
});

describe("reminderUndoRemainingMs", () => {
  it("counts down to zero, never negative", () => {
    const s = makeReminderUndoState([1], ["a"], 1000, 5000);
    expect(reminderUndoRemainingMs(s, 1000)).toBe(5000);
    expect(reminderUndoRemainingMs(s, 4000)).toBe(2000);
    expect(reminderUndoRemainingMs(s, 9000)).toBe(0);
    expect(reminderUndoRemainingMs(s, 20000)).toBe(0);
  });
});
