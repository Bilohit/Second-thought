import { describe, expect, it } from "vitest";
import { smoothLevel, envelope, fluidCurve, fluidRing, LAYERS, perceptualLevel, bandLevels } from "./fluidviz";

describe("fluidviz", () => {
  it("envelope is 0 at the ends and 1 in the middle", () => {
    expect(envelope(0)).toBeCloseTo(0, 6);
    expect(envelope(1)).toBeCloseTo(0, 6);
    expect(envelope(0.5)).toBeCloseTo(1, 6);
  });

  it("smoothLevel rises faster than it falls", () => {
    const up = smoothLevel(0, 1) - 0;
    const down = 1 - smoothLevel(1, 0);
    expect(up).toBeGreaterThan(down);
  });

  it("fluidCurve is silent at level 0 and bounded by level * gain", () => {
    const out = new Array<number>(32);
    fluidCurve(32, 1.23, 0, LAYERS[0], out);
    expect(out.every((v) => v === 0)).toBe(true);
    fluidCurve(32, 1.23, 0.5, LAYERS[0], out);
    expect(out.every((v) => Math.abs(v) <= 0.5 * LAYERS[0].gain + 1e-9)).toBe(true);
  });

  it("fluidRing stays at 1.0 when silent and within ±0.2 at full level", () => {
    const out = new Array<number>(48);
    fluidRing(48, 0.7, 0, out);
    expect(out.every((v) => Math.abs(v - 1) < 1e-9)).toBe(true);
    fluidRing(48, 0.7, 1, out);
    expect(out.every((v) => Math.abs(v - 1) <= 0.2 + 1e-9)).toBe(true);
  });

  it("perceptualLevel is 0 at/below the gate cutoff, ~1 at 0.06, and monotonic", () => {
    const floor = 0.005;
    expect(perceptualLevel(floor * 1.5, floor)).toBe(0);
    expect(perceptualLevel(floor * 1.4, floor)).toBe(0);
    expect(perceptualLevel(0.06, floor)).toBeCloseTo(1, 6);
    const a = perceptualLevel(0.02, floor);
    const b = perceptualLevel(0.04, floor);
    const c = perceptualLevel(0.06, floor);
    expect(a).toBeLessThan(b);
    expect(b).toBeLessThan(c);
  });

  it("bandLevels handles all-zero and all-255 spectra, and isolates a spike", () => {
    const sampleRate = 48000;
    const fftSize = 2048;
    const n = fftSize / 2;

    const zero = new Uint8Array(n);
    expect(bandLevels(zero, sampleRate, fftSize)).toEqual([0, 0, 0]);

    const full = new Uint8Array(n).fill(255);
    const [lo, mid, hi] = bandLevels(full, sampleRate, fftSize);
    expect(lo).toBeCloseTo(1, 6);
    expect(mid).toBeCloseTo(1, 6);
    expect(hi).toBeCloseTo(1, 6);

    // Spike only in the low band's bin range (0-300Hz -> bins 0..~12).
    const spikeLow = new Uint8Array(n);
    spikeLow[5] = 255;
    const [loSpike, midSpike, hiSpike] = bandLevels(spikeLow, sampleRate, fftSize);
    expect(loSpike).toBeGreaterThan(0);
    expect(midSpike).toBe(0);
    expect(hiSpike).toBe(0);
  });
});
