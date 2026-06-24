import { describe, expect, it } from "vitest";
import { ANCHOR_ORDER, isPillDraggable } from "./pillAnchor";

describe("isPillDraggable", () => {
  it("is draggable only for custom anchor with the menu closed", () => {
    expect(isPillDraggable("custom", false)).toBe(true);
  });

  it("is not draggable for custom anchor with the menu open", () => {
    expect(isPillDraggable("custom", true)).toBe(false);
  });

  it("is not draggable for a fixed anchor with the menu closed", () => {
    expect(isPillDraggable("tl", false)).toBe(false);
  });

  it("is not draggable for a fixed anchor with the menu open", () => {
    expect(isPillDraggable("tl", true)).toBe(false);
  });

  // Regression guard for for_sonnet.md §2.3 symptom 3: the pill must never be
  // draggable while a menu is open, for ANY anchor — this is what keeps the
  // pill locked during the overlay's exit animation in minimal mode.
  it("is never draggable while the menu is open, for every anchor", () => {
    for (const anchor of ANCHOR_ORDER) {
      expect(isPillDraggable(anchor, true)).toBe(false);
    }
  });
});
