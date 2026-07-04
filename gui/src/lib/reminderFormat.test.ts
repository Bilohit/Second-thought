import { describe, it, expect } from "vitest";
import { formatWhen } from "./reminderFormat";

const NOW = new Date("2026-07-03T12:00:00");

describe("formatWhen", () => {
  it("today", () => expect(formatWhen("2026-07-03T15:00", NOW)).toBe("Today 3:00 PM"));
  it("tomorrow", () => expect(formatWhen("2026-07-04T09:00", NOW)).toBe("Tomorrow 9:00 AM"));
  it("later date", () => expect(formatWhen("2026-07-05T15:00", NOW)).toBe("Sun, Jul 5, 3:00 PM"));
  it("invalid iso passes through", () => expect(formatWhen("garbage", NOW)).toBe("garbage"));
});
