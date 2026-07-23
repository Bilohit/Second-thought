import { describe, it, expect } from "vitest";
import { applyAiOfflineOverride } from "./useCapture";
import type { CaptureStep } from "./useCapture";

// ISS-018: applyAiOfflineOverride is the pure piece of the fast-Ollama-
// reachability stall guard -- it swaps the "decide" step's copy so the
// existing generic renderers (StepIndicator, PillOverlay's pillLabel) show
// "AI offline -- saved for retry" instead of "Deciding category" without any
// component needing to know about Ollama reachability at all.

const DEFS: CaptureStep[] = [
  { id: "intercept", label: "Intercepting" },
  { id: "enrich", label: "Enriching content", pillLabel: "Enriching" },
  { id: "decide", label: "Deciding category", pillLabel: "Deciding" },
  { id: "write", label: "Writing to vault", pillLabel: "Writing" },
];

describe("applyAiOfflineOverride", () => {
  it("returns the same array reference when aiOffline is false (common case, no per-render churn)", () => {
    expect(applyAiOfflineOverride(DEFS, false)).toBe(DEFS);
  });

  it("overrides only the decide step's label/pillLabel/detail when aiOffline is true", () => {
    const result = applyAiOfflineOverride(DEFS, true);
    const decide = result.find((d) => d.id === "decide")!;
    expect(decide.label).toBe("AI offline — saved for retry");
    expect(decide.pillLabel).toBe("AI offline");
    expect(decide.detail).toBeTruthy();
  });

  it("leaves every other step untouched when aiOffline is true", () => {
    const result = applyAiOfflineOverride(DEFS, true);
    expect(result.find((d) => d.id === "intercept")).toEqual(DEFS[0]);
    expect(result.find((d) => d.id === "enrich")).toEqual(DEFS[1]);
    expect(result.find((d) => d.id === "write")).toEqual(DEFS[3]);
  });

  it("preserves step order and count", () => {
    const result = applyAiOfflineOverride(DEFS, true);
    expect(result.map((d) => d.id)).toEqual(["intercept", "enrich", "decide", "write"]);
  });
});
