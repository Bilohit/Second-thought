/**
 * useCapture.ts - Core state-management hook for a single capture session.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { readText, readImage } from "@tauri-apps/plugin-clipboard-manager";
import { streamCapture, getJobStatus, HttpError, type StepName, type StepStatus, type ContentType } from "../lib/api";
import { logger, setRunId } from "../lib/logger";

/** Short, log-friendly correlation ID — not a security token, just unique enough
 *  to join frontend/backend lines for one capture run in the merged log file. */
function newRunId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export type StepState = "pending" | "active" | "done" | "error";

export interface CaptureStep {
  id: string;
  label: string;
  detail?: string;
}

export interface ContentPreview {
  type: "text" | "url" | "image";
  snippet: string;
  domain?: string;
  imageSrc?: string;
}

export interface ThinkingState {
  rationale: string;
  key_signals: string[];
  confidence: number;
  category: string;
}

export interface BackgroundJobState {
  id: string;
  kind: string;
  status: string;
  // Last non-terminal status seen for this job. Preserved across the final
  // "error" transition so the step list can still show *which* stage failed
  // (the backend's terminal "error" status itself carries no stage info).
  lastActiveStatus?: string;
  chunkIndex?: number | null;
  chunkTotal?: number | null;
  detail?: string | null;
}

export interface CaptureState {
  phase: "idle" | "capturing" | "background" | "done" | "error";
  steps: Record<StepName, StepState>;
  preview: ContentPreview | null;
  result: { path: string | null; category: string | null } | null;
  errorMsg: string | null;
  thinking: ThinkingState | null;
  backgroundJob: BackgroundJobState | null;
}

const STEP_DEFS: CaptureStep[] = [
  { id: "intercept", label: "Intercepting clipboard" },
  { id: "enrich",    label: "Enriching content"      },
  { id: "decide",    label: "Deciding category"       },
  { id: "write",     label: "Writing to vault"        },
];

const INITIAL_STEPS: Record<StepName, StepState> = {
  intercept: "pending",
  enrich:    "pending",
  decide:    "pending",
  write:     "pending",
};

// Tied to the footer's `fadeIn 0.22s` animation (CaptureOverlay.tsx Footer) plus
// a brief moment to actually read "Saved to …" — not an arbitrary long wait.
const AUTO_DISMISS_DONE_MS = 1100;
// Errors stay visible longer so the user has time to read what went wrong.
const AUTO_DISMISS_ERROR_MS = 2200;

// ── YouTube background-job step list ────────────────────────────────────────
// Ordered, real backend stages (no illustrative/fake stages) -- see
// _run_youtube_job in server.py for the statuses this mirrors.
const YT_STAGE_DEFS: CaptureStep[] = [
  { id: "detect",             label: "Detecting YouTube link" },
  { id: "fetching",           label: "Fetching transcript & title" },
  { id: "writing_transcript", label: "Saving transcript" },
  { id: "summarizing",        label: "Summarizing" },
  { id: "combining",          label: "Combining sections" },
  { id: "finalizing",         label: "Finalizing note" },
];

// Position of each backend status in the pipeline, *excluding* the synthetic
// "detect" stage (which is always done once a job exists at all). "queued"
// sits before "fetching" -- no stage is active yet.
const YT_STATUS_ORDER = ["queued", "fetching", "writing_transcript", "summarizing", "combining", "finalizing"];

// Status names from a job already in flight when the server restarted into a
// newer app version (rare: only matters for the few seconds-to-minutes a job
// outlives a restart). Mapped onto the nearest current stage so the step list
// still advances instead of sitting on "pending" until the job finishes.
const LEGACY_STATUS_MAP: Record<string, string> = {
  enriching: "fetching",
  deciding: "combining",
  writing: "finalizing",
};

function normalizeYtStatus(status: string): string {
  return LEGACY_STATUS_MAP[status] ?? status;
}

export function deriveYoutubeSteps(job: BackgroundJobState): { steps: Record<string, StepState>; stepDefs: CaptureStep[] } {
  const steps: Record<string, StepState> = { detect: "done" };
  for (const def of YT_STAGE_DEFS) {
    if (def.id !== "detect") steps[def.id] = "pending";
  }

  if (job.status === "done") {
    for (const def of YT_STAGE_DEFS) steps[def.id] = "done";
  } else {
    // On "error" the backend's terminal status carries no stage info, so use
    // the last non-terminal status this job reported to know which stage failed.
    const effectiveStatus = normalizeYtStatus(job.status === "error" ? job.lastActiveStatus ?? "queued" : job.status);
    const activeIdx = YT_STATUS_ORDER.indexOf(effectiveStatus); // -1 (unknown) treated as "queued"
    YT_STAGE_DEFS.forEach((def, i) => {
      if (def.id === "detect") return;
      const stageIdx = i; // YT_STAGE_DEFS[1..] lines up 1:1 with YT_STATUS_ORDER[1..]
      if (stageIdx < activeIdx) steps[def.id] = "done";
      else if (stageIdx === activeIdx) steps[def.id] = job.status === "error" ? "error" : "active";
      // else stays "pending"
    });
  }

  const stepDefs = YT_STAGE_DEFS.map((def) =>
    def.id === "summarizing" && job.detail ? { ...def, detail: job.detail } : def,
  );
  return { steps, stepDefs };
}

async function readClipboard(): Promise<{
  contentType: ContentType;
  content: string;
  preview: ContentPreview;
}> {
  await new Promise((r) => setTimeout(r, 120));

  let imageError: unknown = null;
  try {
    const img = await readImage();
    if (img) {
      const [rgba, { width, height }] = await Promise.all([img.rgba(), img.size()]);
      const canvas = new OffscreenCanvas(width, height);
      const ctx = canvas.getContext("2d")!;
      ctx.putImageData(new ImageData(new Uint8ClampedArray(rgba), width, height), 0, 0);
      const blob = await canvas.convertToBlob({ type: "image/png" });
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(reader.error ?? new Error("FileReader failed"));
        reader.readAsDataURL(blob);
      });
      const b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
      return { contentType: "image_b64", content: b64, preview: { type: "image", snippet: "Clipboard image", imageSrc: dataUrl } };
    }
  } catch (err) {
    imageError = err;
  }

  const text = (await readText()) ?? "";
  const trimmed = text.trim();

  if (!trimmed && imageError) {
    const msg = imageError instanceof Error ? imageError.message : String(imageError);
    throw new Error(`Could not read clipboard image: ${msg}`);
  }

  if (/^https?:\/\//i.test(trimmed)) {
    let domain = trimmed;
    try { domain = new URL(trimmed).hostname; } catch { /* ignore */ }
    return { contentType: "url", content: trimmed, preview: { type: "url", snippet: trimmed, domain } };
  }

  return {
    contentType: "text",
    content: trimmed,
    preview: { type: "text", snippet: trimmed.length > 120 ? trimmed.slice(0, 117) + "..." : trimmed },
  };
}

const BLANK_STATE: CaptureState = {
  phase: "idle",
  steps: { ...INITIAL_STEPS },
  preview: null,
  result: null,
  errorMsg: null,
  thinking: null,
  backgroundJob: null,
};

const JOB_POLL_MS = 1500;

/**
 * holdOpenRef: when `.current` is true, the window is never auto-hidden at
 * the end of a run (pinned pill mode) — state just resets to idle instead,
 * so the pill stays on screen as a calm persistent indicator. Read via a
 * ref (not a parameter re-passed on every call) so the dismiss timer's
 * closure always sees the latest value without re-subscribing.
 */
export function useCapture(holdOpenRef?: { current: boolean }) {
  const [state, setState] = useState<CaptureState>(BLANK_STATE);
  const abortRef = useRef<AbortController | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobPollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  // Set synchronously (before any await) so two trigger-capture events that
  // fire milliseconds apart can't both pass the check -- a useState flag
  // would still be stale for the second callback at that point.
  const inFlightRef = useRef(false);

  const setStep = useCallback((step: StepName, status: StepStatus) => {
    setState((prev) => ({
      ...prev,
      steps: {
        ...prev.steps,
        [step]: status === "active" ? "active" : status === "done" ? "done" : "error",
      },
    }));
  }, []);

  const scheduleDismiss = useCallback((delayMs: number) => {
    if (dismissTimer.current) clearTimeout(dismissTimer.current);
    dismissTimer.current = setTimeout(async () => {
      if (holdOpenRef?.current) {
        // Pinned pill: stay visible, just settle back to idle.
        setState(BLANK_STATE);
        return;
      }
      await getCurrentWindow().hide();
      setTimeout(() => setState(BLANK_STATE), 300);
    }, delayMs);
  }, [holdOpenRef]);

  const stopJobPolling = useCallback(() => {
    if (jobPollTimer.current) {
      clearInterval(jobPollTimer.current);
      jobPollTimer.current = null;
    }
  }, []);

  // Keeps the HUD open and live for the whole background job: the step list
  // advances as real progress comes in, and the window only closes once the
  // job reaches a terminal state (done/error) or its registry entry expires.
  const pollJob = useCallback((jobId: string) => {
    stopJobPolling();
    jobPollTimer.current = setInterval(async () => {
      try {
        const job = await getJobStatus(jobId);
        setState((prev) => {
          if (prev.backgroundJob?.id !== jobId) return prev;
          const prevJob = prev.backgroundJob;
          const phase: CaptureState["phase"] =
            job.status === "done" ? "done" : job.status === "error" ? "error" : "background";
          return {
            ...prev,
            phase,
            result: job.status === "done" ? { path: job.path, category: job.category } : prev.result,
            errorMsg: job.status === "error" ? job.error ?? "Background job failed" : prev.errorMsg,
            backgroundJob: {
              ...prevJob,
              status: job.status,
              lastActiveStatus: job.status === "error" ? prevJob.lastActiveStatus : job.status,
              chunkIndex: job.chunk_index,
              chunkTotal: job.chunk_total,
              detail: job.detail,
            },
          };
        });
        if (job.status === "done") {
          stopJobPolling();
          scheduleDismiss(AUTO_DISMISS_DONE_MS);
        } else if (job.status === "error") {
          stopJobPolling();
          scheduleDismiss(AUTO_DISMISS_ERROR_MS);
        }
      } catch (err) {
        if (err instanceof HttpError && err.status === 404) {
          // Job registry entry expired (job_ttl_seconds) before we finished
          // polling. The desktop notification already fired on completion --
          // treat this as done rather than surfacing a stale-looking error.
          logger.debug("capture", "job poll 404 -- assuming completed", { jobId });
          stopJobPolling();
          setState((prev) => (prev.backgroundJob?.id === jobId ? { ...prev, phase: "done" } : prev));
          scheduleDismiss(AUTO_DISMISS_DONE_MS);
          return;
        }
        logger.debug("capture", "job poll failed", err);
      }
    }, JOB_POLL_MS);
  }, [stopJobPolling, scheduleDismiss]);

  const runCapture = useCallback(async () => {
    if (inFlightRef.current) {
      logger.debug("capture", "runCapture ignored -- a run is already in flight");
      return;
    }
    inFlightRef.current = true;
    // A second capture starting while a previous background job's poll is
    // still live would otherwise leave that interval running forever, since
    // its closure captures the stale job id from the prior run.
    stopJobPolling();
    // A pending dismiss from the *previous* run (e.g. its AUTO_DISMISS_DONE_MS
    // timer) would otherwise fire mid-way through this new run and hide the
    // window / reset state out from under it.
    if (dismissTimer.current) { clearTimeout(dismissTimer.current); dismissTimer.current = null; }

    const runId = newRunId();
    setRunId(runId);
    logger.info("capture", "runCapture invoked", { runId });
    const stopRun = logger.time("capture", "full capture session");
    // Local, not the shared abortRef: with inFlightRef guaranteeing only one
    // run at a time, this controller belongs solely to this run. abortRef is
    // kept only so unmount cleanup can still cancel an in-progress request.
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ ...BLANK_STATE, phase: "capturing" });

    try {
      const { contentType, content, preview } = await readClipboard();

      if (contentType !== "image_b64" && !content.trim()) {
        throw new Error("Clipboard is empty -- copy something first.");
      }

      setState((prev) => ({ ...prev, preview }));

      logger.debug("capture", "clipboard read", { contentType, preview: preview.type });

      for await (const event of streamCapture(contentType, content, controller.signal, runId)) {
        logger.trace("capture", "stream event", { kind: event.kind });
        if (event.kind === "step") {
          setStep(event.step, event.status);
        } else if (event.kind === "thinking") {
          setState((prev) => ({
            ...prev,
            thinking: {
              rationale: event.rationale,
              key_signals: event.key_signals,
              confidence: event.confidence,
              category: event.category,
            },
          }));
        } else if (event.kind === "done") {
          logger.info("capture", "capture done", { category: event.category, path: event.path });
          stopRun();
          setState((prev) => ({
            ...prev,
            phase: "done",
            result: { path: event.path, category: event.category },
          }));
          scheduleDismiss(AUTO_DISMISS_DONE_MS);
          return;
        } else if (event.kind === "error") {
          throw new Error(event.message);
        } else if (event.kind === "duplicate") {
          // Repeat-fired hotkey (AHK/Hammerspoon double-fire): absorb silently,
          // snap back to idle rather than getting stuck in "capturing".
          logger.debug("capture", "duplicate event absorbed");
          stopRun();
          if (!holdOpenRef?.current) await getCurrentWindow().hide();
          setState(BLANK_STATE);
          return;
        } else if (event.kind === "job") {
          logger.info("capture", "background job handed off", { jobId: event.job_id, status: event.status });
          stopRun();
          setState((prev) => ({
            ...prev,
            phase: "background",
            backgroundJob: { id: event.job_id, kind: event.jobKind, status: event.status, lastActiveStatus: event.status },
          }));
          pollJob(event.job_id);
          return;
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") { logger.debug("capture", "capture aborted"); return; }
      // A bare fetch connection failure (server down / not yet up) surfaces as a
      // TypeError "Failed to fetch". Translate it to the actionable message that
      // the removed /health preflight used to produce.
      const isConnFailure =
        err instanceof TypeError ||
        /failed to fetch|networkerror|load failed/i.test((err as Error)?.message ?? "");
      if (isConnFailure) {
        err = new Error("Python server is not running.\nRestart the Second Thought app (the server is launched and authenticated automatically; a manually-started uvicorn process won't have the GUI's secret).");
      }
      const msg = err instanceof Error ? err.message : String(err);
      logger.error("capture", "capture failed", err);
      stopRun({ failed: true });
      setState((prev) => ({
        ...prev,
        phase: "error",
        errorMsg: msg,
        steps: {
          ...prev.steps,
          ...Object.fromEntries(
            Object.entries(prev.steps)
              .filter(([, v]) => v === "active")
              .map(([k]) => [k, "error"])
          ),
        },
      }));
      scheduleDismiss(AUTO_DISMISS_ERROR_MS);
    } finally {
      setRunId(null);
      inFlightRef.current = false;
    }
  }, [setStep, scheduleDismiss, pollJob, stopJobPolling]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listen<void>("trigger-capture", () => { runCapture(); }).then((fn) => { unlisten = fn; });
    return () => {
      unlisten?.();
      abortRef.current?.abort();
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
      stopJobPolling();
    };
  }, [runCapture, stopJobPolling]);

  return { state, stepDefs: STEP_DEFS };
}
