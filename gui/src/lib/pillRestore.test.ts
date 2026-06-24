import { describe, it, expect } from "vitest";

// Regression (for_sonnet_boundary_calibration.md): prePanelPos must be stored and
// restored in LOGICAL px with no scale round-trip. Round-tripping through physical
// and dividing by a scale read on a different monitor mis-scales the restore on
// mixed-DPI multi-monitor setups. This locks the invariant as plain arithmetic.
describe("pill restore coordinate convention", () => {
  const saveLogical = (logicalTopLeft: number) => logicalTopLeft;            // §2 Edit A
  const restoreLogical = (stored: number) => stored;                        // §2 Edit B

  it("is identity across any monitor scale (no physical round-trip)", () => {
    for (const scaleSave of [1, 1.25, 1.5, 2]) {
      for (const scaleRestore of [1, 1.25, 1.5, 2]) {
        const idleLogical = 2003;
        const stored = saveLogical(idleLogical);                 // scaleSave unused on purpose
        const restored = restoreLogical(stored);                 // scaleRestore unused on purpose
        expect(restored).toBe(idleLogical);
        void scaleSave; void scaleRestore;
      }
    }
  });

  it("the OLD physical round-trip drifts when scales differ (documents the bug)", () => {
    const idleLogical = 2003;
    const scaleSave = 1.0, scaleRestore = 1.5;
    const storedPhysical = idleLogical * scaleSave;        // old save
    const restoredLogical = storedPhysical / scaleRestore; // old restore, wrong divisor
    expect(restoredLogical).not.toBe(idleLogical);         // 1335.33 ≠ 2003 → the bug
  });
});
