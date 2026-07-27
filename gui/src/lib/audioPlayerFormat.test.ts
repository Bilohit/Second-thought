import { describe, it, expect } from "vitest";
import { formatClock } from "./audioPlayerFormat";

describe("formatClock", () => {
  it("formats zero as 0:00", () => {
    expect(formatClock(0)).toBe("0:00");
  });
  it("formats sub-minute seconds with zero-padding", () => {
    expect(formatClock(7)).toBe("0:07");
  });
  it("formats minutes and seconds", () => {
    expect(formatClock(75)).toBe("1:15");
  });
  it("floors fractional seconds", () => {
    expect(formatClock(75.9)).toBe("1:15");
  });
  it("clamps negative input to zero", () => {
    expect(formatClock(-3)).toBe("0:00");
  });
});
