import { describe, it, expect } from "vitest";
import { llmStatusLabel, llmStatusTooltip } from "./llmStatusLabel";

describe("llmStatusLabel", () => {
  it("returns idle label when ready", () => {
    expect(llmStatusLabel("ready")).toBe("Second Thought");
  });
  it("returns loading label ≤14 chars", () => {
    const label = llmStatusLabel("loading");
    expect(label).toBe("Warming up…");
    expect([...label].length).toBeLessThanOrEqual(14);
  });
  it("returns disconnected label ≤14 chars", () => {
    const label = llmStatusLabel("disconnected");
    expect(label).toBe("Not connected");
    expect([...label].length).toBeLessThanOrEqual(14);
  });
});

describe("llmStatusTooltip", () => {
  it("returns descriptive tooltip for disconnected", () => {
    expect(llmStatusTooltip("disconnected")).toContain("offline");
  });
  it("returns loading tooltip", () => {
    expect(llmStatusTooltip("loading")).toContain("loading");
  });
});
