import { describe, expect, it } from "vitest";
import { nextWindowTopLeft, emaVelocity, zeroVelocityAtClamp, dragStartBaseline } from "./dragMath";

describe("nextWindowTopLeft", () => {
  it("adds the logical cursor delta to the logical start, with no scale division", () => {
    // Regression for the DPI bug: a 100-logical-px cursor move must yield a
    // 100-logical-px window move, at any monitor scale factor.
    const result = nextWindowTopLeft({ x: 200, y: 100 }, { x: 100, y: -20 });
    expect(result).toEqual({ x: 300, y: 80 });
  });

  it("a zero delta returns the start position unchanged", () => {
    const result = nextWindowTopLeft({ x: 300, y: 300 }, { x: 0, y: 0 });
    expect(result).toEqual({ x: 300, y: 300 });
  });
});

describe("emaVelocity", () => {
  it("blends toward the instantaneous sample", () => {
    const v0 = { x: 0, y: 0 };
    const v1 = emaVelocity(v0, { x: 10, y: 0 }, 1, 0.5);
    expect(v1.x).toBeCloseTo(5);
  });

  it("returns the previous velocity unchanged for a non-positive dt", () => {
    const v0 = { x: 7, y: -3 };
    expect(emaVelocity(v0, { x: 100, y: 100 }, 0)).toEqual(v0);
  });
});

describe("zeroVelocityAtClamp", () => {
  it("zeroes the axis that got clamped, keeps the other", () => {
    const result = zeroVelocityAtClamp({ x: 999, y: 50 }, { x: 800, y: 50 }, { x: 120, y: -40 });
    expect(result).toEqual({ x: 0, y: -40 });
  });

  it("keeps both axes when nothing was clamped", () => {
    const result = zeroVelocityAtClamp({ x: 10, y: 20 }, { x: 10, y: 20 }, { x: 5, y: -5 });
    expect(result).toEqual({ x: 5, y: -5 });
  });
});

describe("dragStartBaseline", () => {
  it("returns the settled idle top-left when a close is pending", () => {
    const idle = { x: 300, y: 200 };
    const stale = { x: 280, y: 160 }; // stale open-state window top-left
    expect(dragStartBaseline(idle, stale)).toEqual(idle);
  });

  it("returns the live read when nothing is pending", () => {
    const live = { x: 400, y: 150 };
    expect(dragStartBaseline(null, live)).toEqual(live);
  });

  it("keeps the pill glued to the cursor when idle and stale disagree", () => {
    const idle = { x: 300, y: 200 };
    const stale = { x: 280, y: 160 }; // open-state top-left, differs from idle
    const cursorDelta = { x: 50, y: 10 };
    const next = nextWindowTopLeft(dragStartBaseline(idle, stale), cursorDelta);
    // The window must move by exactly the cursor delta from the authoritative
    // idle baseline, not from the stale open-state read.
    expect(next).toEqual({ x: idle.x + cursorDelta.x, y: idle.y + cursorDelta.y });
  });
});
