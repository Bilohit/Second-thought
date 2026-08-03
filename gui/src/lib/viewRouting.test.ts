import { describe, it, expect } from "vitest";
import { VIEW_TO_RAIL, railDestinationFor, type LegacyView } from "./viewRouting";

describe("viewRouting — FR-07 regression: History must not alias Vault", () => {
  it("stats routes to its own history destination", () => {
    expect(VIEW_TO_RAIL.stats).toBe("history");
  });

  it("stats and vault no longer collide on the same destination", () => {
    expect(VIEW_TO_RAIL.stats).not.toBe(VIEW_TO_RAIL.vault);
  });

  it("every legacy view still resolves to a destination", () => {
    (Object.keys(VIEW_TO_RAIL) as LegacyView[]).forEach((view) => {
      expect(VIEW_TO_RAIL[view]).toBeTruthy();
    });
  });

  it("railDestinationFor is a pure lookup that matches the table", () => {
    (Object.keys(VIEW_TO_RAIL) as LegacyView[]).forEach((view) => {
      expect(railDestinationFor(view)).toBe(VIEW_TO_RAIL[view]);
    });
  });
});
