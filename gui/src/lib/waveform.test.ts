import { describe, it, expect } from "vitest";
import { rms, updateNoiseFloor, gateGain, resamplePolyline } from "./waveform";

describe("rms", () => {
  it("computes root-mean-square", () => {
    expect(rms(new Float32Array([3, 4, 0, 0]))).toBeCloseTo(2.5); // sqrt((9+16)/4)
  });
  it("empty -> 0", () => {
    expect(rms(new Float32Array(0))).toBe(0);
  });
});

describe("updateNoiseFloor", () => {
  it("rises slowly toward quiet frames, holds against loud ones", () => {
    const quiet = updateNoiseFloor(0.01, 0.02);
    expect(quiet).toBeGreaterThan(0.01);
    expect(quiet).toBeLessThan(0.02);
    // a loud speech frame must barely move the floor
    expect(updateNoiseFloor(0.01, 0.5)).toBeLessThan(0.02);
  });
});

describe("gateGain", () => {
  it("closes at/below the floor margin, opens above it", () => {
    expect(gateGain(0.01, 0.01)).toBe(0);
    expect(gateGain(0.1, 0.01)).toBe(1);
  });
  it("soft knee between closed and open", () => {
    const g = gateGain(0.025, 0.01); // inside the knee (floor*1.5 .. floor*4)
    expect(g).toBeGreaterThan(0);
    expect(g).toBeLessThan(1);
  });
});

describe("resamplePolyline", () => {
  it("keeps sign (raw signal, not envelope)", () => {
    const out = resamplePolyline(new Float32Array([0.5, -0.5]), 2);
    expect(out[0]).toBeCloseTo(0.5);
    expect(out[1]).toBeCloseTo(-0.5);
  });
  it("n<=0 or empty -> empty", () => {
    expect(resamplePolyline(new Float32Array(0), 4)).toEqual([]);
    expect(resamplePolyline(new Float32Array([1]), 0)).toEqual([]);
  });
});
