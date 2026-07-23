import { describe, it, expect } from "vitest";
import {
  REVEAL_WINDOW_MS,
  tickRemaining,
  revealFraction,
  formatCountdown,
  barColor,
} from "./pairingReveal";

describe("tickRemaining", () => {
  it("counts down by the frame delta when running", () => {
    expect(tickRemaining(60_000, 16, false)).toBe(59_984);
  });
  it("freezes while paused (hover / hidden tab)", () => {
    expect(tickRemaining(42_000, 500, true)).toBe(42_000);
  });
  it("never goes negative — clamps at zero on the last frame", () => {
    expect(tickRemaining(10, 33, false)).toBe(0);
  });
});

describe("revealFraction", () => {
  it("is 1 at the start and 0 at the end", () => {
    expect(revealFraction(REVEAL_WINDOW_MS, REVEAL_WINDOW_MS)).toBe(1);
    expect(revealFraction(0, REVEAL_WINDOW_MS)).toBe(0);
  });
  it("is the linear share in between", () => {
    expect(revealFraction(30_000, 60_000)).toBeCloseTo(0.5);
  });
  it("stays in 0‥1 even if remaining somehow exceeds total or drops below 0", () => {
    expect(revealFraction(99_000, 60_000)).toBe(1);
    expect(revealFraction(-5, 60_000)).toBe(0);
  });
  it("does not divide by zero", () => {
    expect(revealFraction(10, 0)).toBe(0);
  });
});

describe("formatCountdown", () => {
  it("renders m:ss with a zero-padded seconds field", () => {
    expect(formatCountdown(60_000)).toBe("1:00");
    expect(formatCountdown(47_000)).toBe("0:47");
    expect(formatCountdown(9_000)).toBe("0:09");
  });
  it("ceils, so a partial second still reads as the higher value until truly elapsed", () => {
    expect(formatCountdown(59_400)).toBe("1:00");
    expect(formatCountdown(200)).toBe("0:01");
    expect(formatCountdown(0)).toBe("0:00");
  });
  it("never renders a negative clock", () => {
    expect(formatCountdown(-500)).toBe("0:00");
  });
});

describe("barColor", () => {
  it("is the neutral accent for most of the window", () => {
    expect(barColor(1)).toBe("var(--accent)");
    expect(barColor(0.5)).toBe("var(--accent)");
  });
  it("crosses to yellow, then red, as the window closes (state signal, not decoration)", () => {
    expect(barColor(0.3)).toBe("var(--yellow)");
    expect(barColor(0.1)).toBe("var(--red)");
    expect(barColor(0)).toBe("var(--red)");
  });
});
