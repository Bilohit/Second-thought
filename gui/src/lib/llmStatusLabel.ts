import type { LlmStatus } from "./api";

export function llmStatusLabel(status: LlmStatus): string {
  if (status === "loading") return "Warming up…";
  if (status === "disconnected") return "Not connected";
  return "Second Thought";
}

export function llmStatusTooltip(status: LlmStatus): string {
  if (status === "loading") return "LLM loading…";
  if (status === "disconnected") return "LLM offline — model not loaded";
  return "Ready";
}
