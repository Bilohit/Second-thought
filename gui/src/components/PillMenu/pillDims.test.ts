import { describe, it, expect } from "vitest";
import { PILL_DIMS } from "../PillOverlay";

// All DisplayMode values — "full" has no PILL_DIMS entry, must fall back.
const allModes = ["full", "capsule", "minimal"] as const;

describe("pillDims fallback", () => {
  it("PILL_DIMS[mode] ?? PILL_DIMS.minimal is defined for every DisplayMode", () => {
    for (const mode of allModes) {
      const dims = (PILL_DIMS as any)[mode] ?? PILL_DIMS.minimal;
      expect(dims).toBeDefined();
      expect(typeof dims.w).toBe("number");
      expect(typeof dims.h).toBe("number");
    }
  });
});
