import type { CaptureState } from "../hooks/useCapture";
import type { LlmStatus } from "../lib/api";
import { statusVisual } from "../lib/statusModel";

const PULSE_ANIMATION: Record<string, string> = {
  pillPulseGlow:   "pillPulseGlow 1.1s ease-in-out infinite",
  llmLoadingPulse: "llmLoadingPulse 2.4s cubic-bezier(0.45,0,0.55,1) infinite",
  llmWarnFade:     "llmWarnFade 2.8s cubic-bezier(0.45,0,0.55,1) infinite",
  none:            "none",
};

interface Props {
  captureState: CaptureState;
  llmStatus: LlmStatus;
  showLabel?: boolean;
  size?: number;
}

export default function StatusIndicator({ captureState, llmStatus, showLabel = false, size = 7 }: Props) {
  const { dotColor, label, pulse } = statusVisual(captureState, llmStatus);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: size,
          height: size,
          borderRadius: "50%",
          background: dotColor,
          transition: "background 0.2s ease",
          animation: PULSE_ANIMATION[pulse],
        }}
      />
      {showLabel && (
        <span style={{ fontSize: 12, color: "var(--text-2)" }}>{label}</span>
      )}
    </span>
  );
}
