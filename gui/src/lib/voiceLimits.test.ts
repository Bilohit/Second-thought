import { describe, it, expect } from "vitest";
import { MAX_RECORDING_MS, shouldAutoStop, formatElapsed } from "./voiceLimits";

describe("voiceLimits", () => {
  it("auto-stops at the cap, not before", () => {
    expect(shouldAutoStop(MAX_RECORDING_MS - 1)).toBe(false);
    expect(shouldAutoStop(MAX_RECORDING_MS)).toBe(true);
  });
  it("formats m:ss with zero-padded seconds", () => {
    expect(formatElapsed(7_000)).toBe("0:07");
    expect(formatElapsed(754_000)).toBe("12:34");
  });
});
