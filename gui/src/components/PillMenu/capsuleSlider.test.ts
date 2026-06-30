import { describe, it, expect } from "vitest";
import { sliderRect } from "./capsuleSlider";
import { CAPSULE_PAD_X } from "./CapsuleMenu";

describe("sliderRect", () => {
  it("bleeds left over the pad for the first item", () => {
    const r = sliderRect(12, 44, 0, 6);
    expect(r.left).toBe(12 - CAPSULE_PAD_X);
    expect(r.width).toBe(44 + CAPSULE_PAD_X);
  });
  it("bleeds right over the pad for the last item", () => {
    const r = sliderRect(232, 44, 5, 6);
    expect(r.left).toBe(232);
    expect(r.width).toBe(44 + CAPSULE_PAD_X);
  });
  it("leaves interior items untouched", () => {
    const r = sliderRect(100, 44, 2, 6);
    expect(r.left).toBe(100);
    expect(r.width).toBe(44);
  });
});
