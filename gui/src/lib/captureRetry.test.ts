import { describe, expect, it } from "vitest";
import { isConnectionFailure, nextRetryDelayMs } from "./captureRetry";

describe("isConnectionFailure", () => {
  it("treats a bare TypeError (fetch's connection-refused shape) as a connection failure", () => {
    expect(isConnectionFailure(new TypeError("Failed to fetch"))).toBe(true);
  });

  it("treats a real pipeline error as not a connection failure", () => {
    expect(isConnectionFailure(new Error("Ollama returned malformed JSON"))).toBe(false);
  });
});

describe("nextRetryDelayMs", () => {
  it("returns a bounded backoff schedule for the first few attempts", () => {
    expect(nextRetryDelayMs(0)).toBe(500);
    expect(nextRetryDelayMs(1)).toBe(1500);
    expect(nextRetryDelayMs(2)).toBe(3000);
  });

  it("returns null once attempts are exhausted", () => {
    expect(nextRetryDelayMs(3)).toBeNull();
  });
});
