/**
 * PillOverlay.tsx
 * ---------------
 * Compact "Capsule" / "Minimal" presentations of the capture pipeline.
 * Pure presentation over useCapture's real state — no parallel state
 * machine. Click (or the global hotkey) expands back to the full overlay.
 *
 * Corner style is a deliberate, narrow exception to the app's sharp-0px-
 * radius lock (see DESIGN.md / index.css): it only ever touches this one
 * component's shape, never any panel/control elsewhere.
 */
import type { CaptureState, CaptureStep } from "../hooks/useCapture";
import { deriveYoutubeSteps } from "../hooks/useCapture";

export type PillMode = "capsule" | "minimal";
export type PillCorner = "sharp" | "rounded";

interface Props {
  mode: PillMode;
  corner: PillCorner;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  onExpand: () => void;
}

function pillLabel(state: CaptureState, stepDefs: CaptureStep[]): string {
  if (state.phase === "error") return "Error";
  if (state.phase === "done") {
    return state.result?.category ? `Filed · ${state.result.category}` : "Done";
  }
  if (state.phase === "background" && state.backgroundJob) {
    const { steps, stepDefs: ytDefs } = deriveYoutubeSteps(state.backgroundJob);
    return ytDefs.find((d) => steps[d.id] === "active")?.label ?? "Working";
  }
  if (state.phase === "capturing") {
    const active = stepDefs.find((d) => state.steps[d.id as keyof CaptureState["steps"]] === "active");
    return active?.label ?? "Working";
  }
  return "Second Thought";
}

export const PILL_DIMS: Record<PillMode, { w: number; h: number }> = {
  capsule: { w: 168, h: 36 },
  minimal: { w: 36, h: 36 },
};

export default function PillOverlay({ mode, corner, captureState, stepDefs, onExpand }: Props) {
  const isActive = captureState.phase === "capturing" || captureState.phase === "background";
  const isError  = captureState.phase === "error";
  const isDone   = captureState.phase === "done";
  const label    = pillLabel(captureState, stepDefs);

  const dotColor = isError ? "var(--red)" : isDone ? "var(--green)" : isActive ? "var(--accent)" : "var(--text-3)";

  if (mode === "minimal") {
    return (
      <button
        type="button"
        className="drag-region"
        onClick={onExpand}
        aria-label={`Second Thought — ${label}. Click to expand.`}
        title={label}
        style={{
          width: PILL_DIMS.minimal.w,
          height: PILL_DIMS.minimal.h,
          padding: 0,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: corner === "rounded" ? "50%" : "0px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          animation: isActive ? "pillPulseGlow 1.1s ease-in-out infinite" : "none",
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: dotColor,
            transition: "background 0.2s ease",
          }}
        />
      </button>
    );
  }

  return (
    <button
      type="button"
      className="drag-region"
      onClick={onExpand}
      aria-label={`Second Thought — ${label}. Click to expand.`}
      style={{
        position: "relative",
        width: PILL_DIMS.capsule.w,
        height: PILL_DIMS.capsule.h,
        padding: "0 14px",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: corner === "rounded" ? `${PILL_DIMS.capsule.h / 2}px` : "0px",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        color: "var(--text-1)",
        fontSize: 11,
        letterSpacing: "0.02em",
        fontFamily: "inherit",
      }}
    >
      {isActive && (
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: -2,
            padding: 2,
            borderRadius: "inherit",
            background:
              "conic-gradient(from var(--pill-angle), transparent 0% 70%, var(--accent) 85%, transparent 100%)",
            WebkitMask: "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
            WebkitMaskComposite: "xor",
            maskComposite: "exclude",
            animation: "pillSpin 1.4s linear infinite",
            pointerEvents: "none",
          }}
        />
      )}
      <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
    </button>
  );
}
