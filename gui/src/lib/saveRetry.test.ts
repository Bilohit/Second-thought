import { describe, it, expect } from "vitest";
import { isSaveRetry, saveRetryDelayMs, SAVE_BASE_DELAY_MS, SAVE_MAX_DELAY_MS } from "./saveRetry";

describe("isSaveRetry", () => {
  it("is false before anything has been attempted", () => {
    expect(isSaveRetry("hello", null)).toBe(false);
  });

  it("is true when the same body is about to be sent again", () => {
    expect(isSaveRetry("hello", "hello")).toBe(true);
  });

  it("is false once the user edits — a new body is not a retry", () => {
    expect(isSaveRetry("hello!", "hello")).toBe(false);
  });

  it("does not consider save state, so the effect's own state churn cannot reset the backoff", () => {
    // Regression guard for the first cut of this fix: keying on
    // saveState === "error" zeroed the failure count every time the effect
    // set state to "saving" and re-ran.
    expect(isSaveRetry("same", "same")).toBe(true);
  });
});

describe("saveRetryDelayMs", () => {
  it("uses the plain debounce for a fresh edit", () => {
    expect(saveRetryDelayMs(0)).toBe(SAVE_BASE_DELAY_MS);
    expect(saveRetryDelayMs(-1)).toBe(SAVE_BASE_DELAY_MS);
  });

  it("doubles per consecutive failure", () => {
    expect(saveRetryDelayMs(1)).toBe(SAVE_BASE_DELAY_MS * 2);
    expect(saveRetryDelayMs(2)).toBe(SAVE_BASE_DELAY_MS * 4);
    expect(saveRetryDelayMs(3)).toBe(SAVE_BASE_DELAY_MS * 8);
  });

  it("is monotonic and capped, so retries never run away or stall forever", () => {
    let prev = 0;
    for (let n = 0; n <= 40; n++) {
      const d = saveRetryDelayMs(n);
      expect(d).toBeGreaterThanOrEqual(prev);
      expect(d).toBeLessThanOrEqual(SAVE_MAX_DELAY_MS);
      prev = d;
    }
    expect(saveRetryDelayMs(40)).toBe(SAVE_MAX_DELAY_MS);
  });
});
