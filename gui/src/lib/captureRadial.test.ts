import { describe, it, expect } from "vitest";
import { captureRadialFan, CAPTURE_SATELLITE_IDS } from "./captureRadial";

describe("captureRadialFan", () => {
  it("returns exactly the 4 satellites, in the fixed id order", () => {
    const fan = captureRadialFan(80);
    expect(fan.map((s) => s.id)).toEqual(CAPTURE_SATELLITE_IDS);
    expect(fan).toHaveLength(4);
  });

  it("every satellite sits exactly `radius` px from the center pill", () => {
    const radius = 80;
    const fan = captureRadialFan(radius);
    for (const s of fan) {
      const dist = Math.hypot(s.x, s.y);
      expect(dist).toBeCloseTo(radius, 6);
    }
  });

  it("the fan is symmetric about the vertical axis (upward, not sideways)", () => {
    const fan = captureRadialFan(80);
    // Outer pair (note/shot) and inner pair (voice/clip) mirror across x=0,
    // and every y is negative (above the center pill, matching the mock's
    // upward-opening pillrig).
    expect(fan[0].x).toBeCloseTo(-fan[3].x, 6);
    expect(fan[1].x).toBeCloseTo(-fan[2].x, 6);
    for (const s of fan) expect(s.y).toBeLessThan(0);
  });

  it("scales linearly with radius", () => {
    const small = captureRadialFan(40);
    const big = captureRadialFan(80);
    for (let i = 0; i < 4; i++) {
      expect(big[i].x).toBeCloseTo(small[i].x * 2, 6);
      expect(big[i].y).toBeCloseTo(small[i].y * 2, 6);
    }
  });
});
