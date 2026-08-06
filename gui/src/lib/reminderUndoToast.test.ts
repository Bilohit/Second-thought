import { describe, it, expect } from "vitest";
import { makeReminderUndoState, isReminderUndoExpired, reminderUndoRemainingMs } from "./reminderUndoToast";

describe("makeReminderUndoState", () => {
  it("names the instant it set, so the bar is not just asserting one exists", () => {
    const s = makeReminderUndoState(1, "Tomorrow 9:00 AM", 1000);
    expect(s.message).toBe("Reminder set — Tomorrow 9:00 AM");
    expect(s.id).toBe(1);
    expect(s.expiresAt).toBe(1000 + 5000);
  });

  it("falls back to the bare message when there is no due-time label", () => {
    expect(makeReminderUndoState(1, "", 1000).message).toBe("Reminder set");
  });

  it("honors a custom ttlMs", () => {
    const s = makeReminderUndoState(1, "a", 1000, 2000);
    expect(s.expiresAt).toBe(3000);
  });
});

describe("isReminderUndoExpired", () => {
  it("false before expiry, true at/after expiry", () => {
    const s = makeReminderUndoState(1, "a", 1000, 5000);
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
    const s = makeReminderUndoState(1, "a", 1000, 5000);
    expect(reminderUndoRemainingMs(s, 1000)).toBe(5000);
    expect(reminderUndoRemainingMs(s, 4000)).toBe(2000);
    expect(reminderUndoRemainingMs(s, 9000)).toBe(0);
    expect(reminderUndoRemainingMs(s, 20000)).toBe(0);
  });
});
