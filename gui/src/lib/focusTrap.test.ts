import { describe, expect, it } from "vitest";
import { cyclicIndex } from "./focusTrap";

describe("cyclicIndex", () => {
  it("steps forward within bounds", () => {
    expect(cyclicIndex(0, 4, 1)).toBe(1);
  });

  it("wraps forward from the last index to the first", () => {
    expect(cyclicIndex(3, 4, 1)).toBe(0);
  });

  it("steps backward within bounds", () => {
    expect(cyclicIndex(2, 4, -1)).toBe(1);
  });

  it("wraps backward from the first index to the last", () => {
    expect(cyclicIndex(0, 4, -1)).toBe(3);
  });

  it("handles a single-item ring by returning the same index both directions", () => {
    expect(cyclicIndex(0, 1, 1)).toBe(0);
    expect(cyclicIndex(0, 1, -1)).toBe(0);
  });

  it("returns -1 for an empty ring", () => {
    expect(cyclicIndex(0, 0, 1)).toBe(-1);
  });
});
