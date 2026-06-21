/**
 * StepIndicator.tsx
 * -----------------
 * Agent-Plan style pipeline indicator (UI-ENHANCEMENT-PLAN.md B4.1).
 *
 *   - Vertical dashed connector aligned to the icon CENTRE, derived from the
 *     icon-box width (ICON_BOX) — no brittle hard-coded left offset, so the
 *     rail stays centred if the icon size ever changes.
 *   - One `statusConfig` map ({ icon, fg, label }) routes every state so the
 *     icon, rail colour, and text can't drift apart.
 *   - State changes animate (scale/rotate icon swap, rail fill) — reduced-motion
 *     collapses these to instant via index.css.
 *   - Optional per-step `detail` renders as a muted sub-line when present.
 */
import type { CaptureStep, StepState } from "../hooks/useCapture";

interface Props {
  steps:      Record<string, StepState>;
  stepDefs:   CaptureStep[];
}

// Geometry — connector derives from these so it scales with the icon box.
const ICON_BOX = 16;                 // icon column width
const RAIL_X   = ICON_BOX / 2;       // centre of the icon → rail x-offset
const ROW_GAP  = 9;

interface StatusMeta {
  label:   string;
  fg:      string;   // text + active-icon colour
  rail:    string;   // connector colour entering this step
  weight:  number;
  opacity: number;
}

const statusConfig: Record<StepState, StatusMeta> = {
  active:  { label: "in progress", fg: "var(--accent)", rail: "var(--accent)", weight: 500, opacity: 1 },
  done:    { label: "complete",    fg: "var(--text-2)", rail: "var(--green)",  weight: 400, opacity: 1 },
  error:   { label: "error",       fg: "var(--red)",    rail: "var(--red)",    weight: 400, opacity: 1 },
  pending: { label: "pending",     fg: "var(--text-3)", rail: "var(--border)", weight: 400, opacity: 0.4 },
};

function StepIcon({ status }: { status: StepState }) {
  if (status === "active") {
    return <span aria-hidden="true" className="spinner-ring" style={{ flexShrink: 0 }} />;
  }

  if (status === "done") {
    return (
      <svg
        viewBox="0 0 14 14" width={14} height={14} fill="none"
        stroke="var(--green)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true"
        style={{ flexShrink: 0, animation: "checkPop 0.22s cubic-bezier(0.16,1,0.3,1) forwards" }}
      >
        <polyline points="2,7 6,11 12,3" />
      </svg>
    );
  }

  if (status === "error") {
    return (
      <svg
        viewBox="0 0 14 14" width={14} height={14} fill="none"
        stroke="var(--red)" strokeWidth={2} strokeLinecap="round"
        aria-hidden="true"
        style={{ flexShrink: 0, animation: "checkPop 0.22s cubic-bezier(0.16,1,0.3,1) forwards" }}
      >
        <line x1="3" y1="3" x2="11" y2="11" />
        <line x1="11" y1="3" x2="3" y2="11" />
      </svg>
    );
  }

  // pending — hollow node. `50%` here is a status-dot/pip shape (status
  // dots, the spinner ring, and the popup's connection dot are all round by
  // convention, same as a traffic light), not a panel/control corner radius —
  // it isn't part of the `--radius*` scale and the sharp-corners lock in
  // index.css/DESIGN.md doesn't apply to it.
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block", width: 7, height: 7, borderRadius: "50%",
        border: "1.5px solid var(--border)", background: "transparent", flexShrink: 0,
      }}
    />
  );
}

export default function StepIndicator({ steps, stepDefs }: Props) {
  return (
    <ol
      role="list"
      aria-label="Capture pipeline steps"
      style={{
        margin: 0, padding: 0, listStyle: "none",
        display: "flex", flexDirection: "column", gap: ROW_GAP,
      }}
    >
      {stepDefs.map((def, i) => {
        const status = steps[def.id];
        const cfg    = statusConfig[status];
        const isLast = i === stepDefs.length - 1;
        // Rail entering the NEXT step takes this step's rail colour once done,
        // so the connector "fills" as the pipeline advances.
        const railColor = status === "done" ? statusConfig.done.rail
                        : status === "error" ? statusConfig.error.rail
                        : "var(--border)";

        return (
          <li
            key={def.id}
            role="listitem"
            aria-label={`${def.label}: ${cfg.label}`}
            aria-current={status === "active" ? "step" : undefined}
            style={{
              position: "relative",
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              opacity: cfg.opacity,
              transition: "opacity 0.2s ease",
            }}
          >
            <div style={{ width: ICON_BOX, display: "flex", justifyContent: "center", flexShrink: 0, paddingTop: 1 }}>
              <StepIcon status={status} />
            </div>

            {/* Dashed connector — centred on the icon column, derived offset. */}
            {!isLast && (
              <span
                aria-hidden="true"
                style={{
                  position: "absolute",
                  left: RAIL_X,
                  top: ICON_BOX,
                  bottom: -ROW_GAP,
                  width: 0,
                  borderLeft: `1px dashed ${railColor}`,
                  transform: "translateX(-0.5px)",
                  transition: "border-color 0.25s ease",
                }}
              />
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: cfg.weight,
                  color: cfg.fg,
                  transition: "color 0.2s ease",
                  letterSpacing: "0.01em",
                }}
              >
                {def.label}
              </span>
              {def.detail && (
                <span style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.4 }}>
                  {def.detail}
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
