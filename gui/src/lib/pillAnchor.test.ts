import { describe, expect, it } from "vitest";
import { ANCHOR_LABELS, ANCHOR_ORDER, anchoredMenuPosition, isPillDraggable } from "./pillAnchor";

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

// ISS-039: the placement grid's raw two-letter codes ("tl", "tc", ...) must
// never reach assistive tech as the accessible name.
describe("ANCHOR_LABELS", () => {
  it("has a human-readable label for every anchor in ANCHOR_ORDER", () => {
    for (const a of ANCHOR_ORDER) {
      expect(ANCHOR_LABELS[a]).toBeTruthy();
      expect(ANCHOR_LABELS[a]).not.toBe(a);
    }
  });

  it("labels read as plain English", () => {
    expect(ANCHOR_LABELS.tl).toBe("Top left");
    expect(ANCHOR_LABELS.tc).toBe("Top center");
    expect(ANCHOR_LABELS.tr).toBe("Top right");
    expect(ANCHOR_LABELS.lc).toBe("Left center");
    expect(ANCHOR_LABELS.custom).toBe("Custom (last position)");
    expect(ANCHOR_LABELS.rc).toBe("Right center");
    expect(ANCHOR_LABELS.bl).toBe("Bottom left");
    expect(ANCHOR_LABELS.bc).toBe("Bottom center");
    expect(ANCHOR_LABELS.br).toBe("Bottom right");
  });
});
