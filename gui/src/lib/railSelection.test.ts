import { describe, it, expect } from "vitest";
import { railSliderFromElement } from "./railSelection";

describe("railSliderFromElement", () => {
  it("reads offsetTop and offsetHeight from the active button", () => {
    const btn = { offsetTop: 48, offsetHeight: 36 } as HTMLElement;
    expect(railSliderFromElement(btn)).toEqual({ translateY: 48, height: 36 });
  });
});
