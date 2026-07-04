import { describe, it, expect } from "vitest";
import { statusVisual } from "./statusModel";
import type { CaptureState } from "../hooks/useCapture";

const BLANK_STEPS = { intercept: "pending", enrich: "pending", decide: "pending", write: "pending" } as CaptureState["steps"];

function state(phase: CaptureState["phase"], extra: Partial<CaptureState> = {}): CaptureState {
  return { phase, steps: BLANK_STEPS, preview: null, result: null, errorMsg: null, thinking: null, backgroundJob: null, starting: false, reminderOffer: null, ...extra };
}

// Characterization table: every phase × llmStatus combo
describe("statusVisual", () => {
  describe("idle phase", () => {
    it("idle/loading → text-3 dot, warming label, llmLoadingPulse", () => {
      expect(statusVisual(state("idle"), "loading")).toEqual({
        dotColor: "var(--text-3)",
        label: "Warming up…",
        pulse: "llmLoadingPulse",
      });
    });
    it("idle/ready → text-3 dot, default label, no pulse", () => {
      expect(statusVisual(state("idle"), "ready")).toEqual({
        dotColor: "var(--text-3)",
        label: "Second Thought",
        pulse: "none",
      });
    });
    it("idle/disconnected → yellow dot, disconnected label, llmWarnFade", () => {
      expect(statusVisual(state("idle"), "disconnected")).toEqual({
        dotColor: "var(--yellow)",
        label: "Not connected",
        pulse: "llmWarnFade",
      });
    });
  });

  describe("capturing phase", () => {
    it("capturing/loading → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("capturing"), "loading")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
    it("capturing/ready → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("capturing"), "ready")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
    it("capturing/disconnected → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("capturing"), "disconnected")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
  });

  describe("background phase", () => {
    it("background/loading → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("background"), "loading")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
    it("background/ready → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("background"), "ready")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
    it("background/disconnected → accent dot, Working label, pillPulseGlow", () => {
      expect(statusVisual(state("background"), "disconnected")).toEqual({
        dotColor: "var(--accent)",
        label: "Working",
        pulse: "pillPulseGlow",
      });
    });
  });

  describe("done phase", () => {
    it("done/ready, no category → green dot, Done label, no pulse", () => {
      expect(statusVisual(state("done"), "ready")).toEqual({
        dotColor: "var(--green)",
        label: "Done",
        pulse: "none",
      });
    });
    it("done with category → green dot, category as label", () => {
      expect(statusVisual(state("done", { result: { path: "/vault/t.md", category: "Tools" } }), "ready")).toEqual({
        dotColor: "var(--green)",
        label: "Tools",
        pulse: "none",
      });
    });
    it("done/loading → green dot overrides llm state", () => {
      expect(statusVisual(state("done"), "loading")).toEqual({
        dotColor: "var(--green)",
        label: "Done",
        pulse: "none",
      });
    });
    it("done/disconnected → green dot overrides llm state", () => {
      expect(statusVisual(state("done"), "disconnected")).toEqual({
        dotColor: "var(--green)",
        label: "Done",
        pulse: "none",
      });
    });
  });

  describe("error phase", () => {
    it("error/ready → red dot, Error label, no pulse", () => {
      expect(statusVisual(state("error"), "ready")).toEqual({
        dotColor: "var(--red)",
        label: "Error",
        pulse: "none",
      });
    });
    it("error/loading → red dot overrides llm state", () => {
      expect(statusVisual(state("error"), "loading")).toEqual({
        dotColor: "var(--red)",
        label: "Error",
        pulse: "none",
      });
    });
    it("error/disconnected → red dot overrides llm state", () => {
      expect(statusVisual(state("error"), "disconnected")).toEqual({
        dotColor: "var(--red)",
        label: "Error",
        pulse: "none",
      });
    });
  });
});
