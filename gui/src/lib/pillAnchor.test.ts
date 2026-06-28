import { describe, expect, it } from "vitest";
import { ANCHOR_ORDER, anchoredMenuPosition, isPillDraggable } from "./pillAnchor";

const area = { x: 0, y: 0, w: 1920, h: 1080, scale: 1 };

it("br anchor pins grown box to bottom-right minus margin, deterministically", () => {
  const small = anchoredMenuPosition("br", 60, 60, area)!;
  const grown = anchoredMenuPosition("br", 320, 320, area)!;
  // both flush to the same right/bottom edge regardless of box size
  expect(small.x + 60).toBe(grown.x + 320);
  expect(small.y + 60).toBe(grown.y + 320);
});

it("custom returns null (live-read path owns it)", () => {
  expect(anchoredMenuPosition("custom", 60, 60, area)).toBeNull();
});

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
