import { describe, expect, it } from "vitest";
import { indicatorWidth, indicatorTransform, slideDirection } from "./segmentedToggle";

describe("indicatorWidth", () => {
  it("splits the padding box into N equal segments", () => {
    expect(indicatorWidth(2)).toBe("calc((100% - 4px) / 2)");
    expect(indicatorWidth(3)).toBe("calc((100% - 4px) / 3)");
  });
  it("never divides by zero / negative (clamps count to >= 1)", () => {
    expect(indicatorWidth(0)).toBe("calc((100% - 4px) / 1)");
    expect(indicatorWidth(-2)).toBe("calc((100% - 4px) / 1)");
  });
});

describe("indicatorTransform", () => {
  it("steps by whole segments (% of own width)", () => {
    expect(indicatorTransform(0)).toBe("translateX(0%)");
    expect(indicatorTransform(1)).toBe("translateX(100%)");
    expect(indicatorTransform(2)).toBe("translateX(200%)");
  });
  it("clamps an invalid active index (-1) to the first segment", () => {
    expect(indicatorTransform(-1)).toBe("translateX(0%)");
  });
});

describe("slideDirection", () => {
  it("forward when the new index is greater", () => {
    expect(slideDirection(0, 1)).toBe(1);
  });
  it("backward when the new index is smaller", () => {
    expect(slideDirection(1, 0)).toBe(-1);
  });
  it("zero (fade only) when unchanged or first mount", () => {
    expect(slideDirection(0, 0)).toBe(0);
    expect(slideDirection(1, 1)).toBe(0);
  });
});
