import { describe, it, expect } from "vitest";
import { captureRadialFan, CAPTURE_SATELLITE_IDS } from "./captureRadial";

describe("captureRadialFan", () => {
  it("returns exactly the 5 satellites, in the fixed id order", () => {
    const fan = captureRadialFan(80);
    expect(fan.map((s) => s.id)).toEqual(CAPTURE_SATELLITE_IDS);
    expect(fan).toHaveLength(5);
  });

  it("every satellite sits exactly `radius` px from the center pill", () => {
    const radius = 80;
    const fan = captureRadialFan(radius);
    for (const s of fan) {
      const dist = Math.hypot(s.x, s.y);
      expect(dist).toBeCloseTo(radius, 6);
    }
  });

  it("the fan is symmetric about the vertical axis (upward, not sideways), center satellite on-axis", () => {
    const fan = captureRadialFan(80);
    // Outer pair (note/calendar) and inner pair (voice/shot) mirror across x=0; the middle
    // satellite (clip) sits dead-center on the vertical axis. Every y is negative (above the
    // center pill, matching the mock's upward-opening pillrig).
    expect(fan[0].x).toBeCloseTo(-fan[4].x, 6);
    expect(fan[1].x).toBeCloseTo(-fan[3].x, 6);
    expect(fan[2].x).toBeCloseTo(0, 6);
    for (const s of fan) expect(s.y).toBeLessThan(0);
  });

  it("adjacent satellites keep the original 4-item fan's 40° spacing", () => {
    const radius = 80;
    const fan = captureRadialFan(radius);
    for (let i = 1; i < fan.length; i++) {
      const a = Math.atan2(fan[i - 1].y, fan[i - 1].x);
      const b = Math.atan2(fan[i].y, fan[i].x);
      const stepDeg = ((b - a) * 180) / Math.PI;
      expect(stepDeg).toBeCloseTo(40, 6);
    }
  });

  it("scales linearly with radius", () => {
    const small = captureRadialFan(40);
    const big = captureRadialFan(80);
    for (let i = 0; i < CAPTURE_SATELLITE_IDS.length; i++) {
      expect(big[i].x).toBeCloseTo(small[i].x * 2, 6);
      expect(big[i].y).toBeCloseTo(small[i].y * 2, 6);
    }
  });
});
