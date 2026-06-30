import { useEffect, useRef, useState } from "react";
import { checkHealth, type LlmStatus } from "../lib/api";

// ponytail: polls every 3s at launch until ready, then stops. No mid-session polling (Option A).
const POLL_INTERVAL_MS = 3000;

export function useLlmStatus(): LlmStatus {
  const [status, setStatus] = useState<LlmStatus>("loading");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const { serverOk, llmStatus } = await checkHealth();
      if (cancelled) return;
      // Server still booting (uvicorn/warmup) — not LLM offline.
      const display = !serverOk ? "loading" as const : llmStatus;
      setStatus(display);
      if (!serverOk || llmStatus === "loading") {
        timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  return status;
}
