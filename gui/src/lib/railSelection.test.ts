import { describe, it, expect } from "vitest";
import { railSliderRect } from "./railSelection";

describe("railSliderRect", () => {
  it("returns null when nothing is selected", () => {
    expect(railSliderRect(-1, 3, 300, 8)).toBeNull();
  });

  it("splits the container into N equal buttons with gaps and returns slot 0", () => {
    // 3 buttons, 2 gaps of 8px each: each button height = (300 - 16) / 3
    const r = railSliderRect(0, 3, 300, 8);
    expect(r).toEqual({ translateY: 0, height: (300 - 16) / 3 });
  });

  it("offsets translateY by (buttonHeight + gap) per index", () => {
    const btnH = (300 - 16) / 3;
    const r = railSliderRect(1, 3, 300, 8);
    expect(r).toEqual({ translateY: btnH + 8, height: btnH });
  });

  it("handles the last index", () => {
    const btnH = (300 - 16) / 3;
    const r = railSliderRect(2, 3, 300, 8);
    expect(r).toEqual({ translateY: (btnH + 8) * 2, height: btnH });
  });
});
