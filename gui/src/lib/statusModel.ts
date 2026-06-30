import type { CaptureState } from "../hooks/useCapture";
import type { LlmStatus } from "./api";
import { llmStatusLabel } from "./llmStatusLabel";

export type Pulse = "pillPulseGlow" | "llmLoadingPulse" | "llmWarnFade" | "none";

export interface StatusVisual {
  dotColor: string;
  label: string;
  pulse: Pulse;
}

export function statusVisual(captureState: CaptureState, llmStatus: LlmStatus): StatusVisual {
  const { phase } = captureState;

  if (phase === "error") {
    return { dotColor: "var(--red)", label: "Error", pulse: "none" };
  }
  if (phase === "done") {
    return { dotColor: "var(--green)", label: captureState.result?.category ?? "Done", pulse: "none" };
  }
  if (phase === "capturing" || phase === "background") {
    return { dotColor: "var(--accent)", label: "Working", pulse: "pillPulseGlow" };
  }
  // idle — driven by llmStatus
  return {
    dotColor: llmStatus === "disconnected" ? "var(--yellow)" : "var(--text-3)",
    label: llmStatusLabel(llmStatus),
    pulse: llmStatus === "loading" ? "llmLoadingPulse" : llmStatus === "disconnected" ? "llmWarnFade" : "none",
  };
}
