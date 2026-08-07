/**
 * SkyPanel.tsx — the STARS sky's collapsible control panel (s156, D2/D-B user-ruled). Holds the
 * density tick rail, the Smart-connections toggle (moved here verbatim from BrowseStarsView.tsx —
 * it now lives with the other sky controls instead of floating alone top-right), and zoom controls.
 *
 * Open on first visit, then remembers the user's last state (D2) via `lib/skyPrefs.ts`'s
 * `useSkyPrefs`, the same persisted-pref shape `lib/smartConnectionsPref.ts` already uses in this
 * file's neighbourhood.
 *
 * The density control is a hand-rolled tick rail (`role="slider"`), not a native
 * `<input type="range">` — the user's own choice (D-B, board referenced in the plan) over a
 * segmented control or stepper. A hand-rolled slider owns its own keyboard contract; that contract
 * is exactly what `SkyPanel.test.tsx` pins.
 */
import { useCallback, useRef } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { ChevronRightIcon } from "../PillMenu/icons";
import { Toggle } from "../ui/Toggle";
import { BTN_SECONDARY } from "../ui/styles";
import { micro, label as fsLabel } from "../../lib/type";
import { DENSITY_STEPS, densityStep } from "../../lib/starsSim";
import { ZOOM_MIN, ZOOM_MAX, zoomPercent } from "../../lib/skyViewport";

// s152 (moved from BrowseStarsView.tsx, s156): the Smart-connections tooltip copy. Lives with the
// row that renders it now that the row itself has moved into this panel.
const SMART_CONNECTIONS_EXPLANATION =
  "Groups notes by meaning using embeddings that already exist on this device. Nothing leaves your device.";

const LAST_INDEX = DENSITY_STEPS.length - 1;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  densityIndex: number;
  onDensityChange: (index: number) => void;
  smartConnections: boolean;
  onSmartConnectionsChange: (enabled: boolean) => void;
  scale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
  edgeCount: number;
}

export default function SkyPanel({
  open,
  onOpenChange,
  densityIndex,
  onDensityChange,
  smartConnections,
  onSmartConnectionsChange,
  scale,
  onZoomIn,
  onZoomOut,
  onZoomReset,
  edgeCount,
}: Props) {
  if (!open) {
    return (
      <button
        type="button"
        // "sky-panel" (not a styled class — a marker) lets BrowseStarsView's background-pan
        // handler on the host div tell "the user grabbed a control" from "the user grabbed the
        // sky", the same way it already does for `.bs-star`.
        className="btn-hover sky-panel"
        style={collapsedBtnStyle}
        aria-expanded={false}
        aria-label="Open sky controls"
        onClick={() => onOpenChange(true)}
      >
        SKY
      </button>
    );
  }

  const step = densityStep(densityIndex);

  return (
    <div className="sky-panel" style={panelStyle}>
      <div style={headerRowStyle}>
        <span style={headerTitleStyle}>SKY</span>
        <button
          type="button"
          className="icon-btn"
          aria-expanded={true}
          aria-label="Collapse sky controls"
          onClick={() => onOpenChange(false)}
          style={chevronBtnStyle}
        >
          <span style={chevronRotateStyle}>
            <ChevronRightIcon size={12} />
          </span>
        </button>
      </div>

      <div style={groupStyle}>
        <span style={groupLabelStyle}>Density</span>
        <DensityRail densityIndex={densityIndex} onDensityChange={onDensityChange} />
        <span style={hintStyle}>{step.name} · {edgeCount} connections</span>
      </div>

      <div style={smartRowStyle} title={SMART_CONNECTIONS_EXPLANATION}>
        <Toggle checked={smartConnections} onChange={onSmartConnectionsChange} label="Smart connections" />
        <span style={smartLabelStyle}>Smart connections</span>
      </div>

      <div style={groupStyle}>
        <span style={groupLabelStyle}>Zoom</span>
        <div style={zoomRowStyle}>
          <button
            type="button"
            className="btn-hover"
            style={zoomBtnStyle}
            aria-label="Zoom out"
            disabled={scale <= ZOOM_MIN}
            onClick={onZoomOut}
          >
            −
          </button>
          <span style={zoomPctStyle}>{zoomPercent(scale)}%</span>
          <button
            type="button"
            className="btn-hover"
            style={zoomBtnStyle}
            aria-label="Zoom in"
            disabled={scale >= ZOOM_MAX}
            onClick={onZoomIn}
          >
            +
          </button>
          <button type="button" className="btn-hover" style={resetBtnStyle} onClick={onZoomReset}>
            RESET
          </button>
        </div>
      </div>
    </div>
  );
}

/** The tick rail (D-B): a hand-rolled `role="slider"`. Keyboard: ArrowRight/Up +1,
 *  ArrowLeft/Down -1, Home -> first, End -> last, clamped at both ends — see the file header. */
function DensityRail({
  densityIndex,
  onDensityChange,
}: {
  densityIndex: number;
  onDensityChange: (index: number) => void;
}) {
  const railRef = useRef<HTMLDivElement | null>(null);
  const step = densityStep(densityIndex);
  const clamp = (i: number): number => Math.min(Math.max(i, 0), LAST_INDEX);
  const fillPct = LAST_INDEX === 0 ? 0 : (clamp(densityIndex) / LAST_INDEX) * 100;

  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      let next: number;
      switch (e.key) {
        case "ArrowRight":
        case "ArrowUp":
          next = clamp(densityIndex + 1);
          break;
        case "ArrowLeft":
        case "ArrowDown":
          next = clamp(densityIndex - 1);
          break;
        case "Home":
          next = 0;
          break;
        case "End":
          next = LAST_INDEX;
          break;
        default:
          return;
      }
      e.preventDefault();
      onDensityChange(next);
    },
    [densityIndex, onDensityChange]
  );

  // Shared by pointer down + move — maps a client x to the nearest step index using the RAIL's own
  // measured width (never a hardcoded 186; the panel's width is a layout detail, not a math constant).
  const indexFromPointer = useCallback((e: ReactPointerEvent<HTMLDivElement>): number => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = rect.width === 0 ? 0 : x / rect.width;
    return clamp(Math.round(ratio * LAST_INDEX));
  }, []);

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      const next = indexFromPointer(e);
      if (next !== densityIndex) onDensityChange(next);
    },
    [densityIndex, indexFromPointer, onDensityChange]
  );

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
      const next = indexFromPointer(e);
      if (next !== densityIndex) onDensityChange(next);
    },
    [densityIndex, indexFromPointer, onDensityChange]
  );

  return (
    <div
      ref={railRef}
      role="slider"
      tabIndex={0}
      className="sky-density-rail"
      aria-label="Connection density"
      aria-valuemin={1}
      aria-valuemax={DENSITY_STEPS.length}
      aria-valuenow={densityIndex + 1}
      aria-valuetext={step.name}
      style={railStyle}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
    >
      <div style={trackStyle} aria-hidden="true" />
      <div style={{ ...fillStyle, width: `${fillPct}%` }} aria-hidden="true" />
      <div style={ticksWrapStyle} aria-hidden="true">
        {DENSITY_STEPS.map((_, i) => (
          <span key={i} style={tickStyle} />
        ))}
      </div>
      <div style={{ ...thumbStyle, left: `${fillPct}%` }} aria-hidden="true" />
    </div>
  );
}

// ── styles ───────────────────────────────────────────────────────────────────────────────────────
const PANEL_W = 186;

const collapsedBtnStyle: CSSProperties = {
  position: "absolute", top: 12, right: 14, zIndex: 6,
  padding: "6px 12px", fontSize: fsLabel, letterSpacing: "0.04em", color: "var(--text-2)",
  background: "var(--glass-bg)", border: "1px solid var(--border)", cursor: "pointer",
};
const panelStyle: CSSProperties = {
  position: "absolute", top: 12, right: 14, zIndex: 6, width: PANEL_W,
  background: "var(--glass-bg)", border: "1px solid var(--border)",
  display: "flex", flexDirection: "column", gap: 12, padding: "10px 12px",
};
const headerRowStyle: CSSProperties = { display: "flex", alignItems: "center", justifyContent: "space-between" };
const headerTitleStyle: CSSProperties = { fontSize: fsLabel, letterSpacing: "0.04em", color: "var(--text-2)" };
const chevronBtnStyle: CSSProperties = { width: 20, height: 20 };
// The chevron rotates 90deg while the panel is open (its own doc comment's contract) — pointing
// "down" reads as "this section is expanded, click to collapse it".
const chevronRotateStyle: CSSProperties = { display: "flex", transform: "rotate(90deg)" };
const groupStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 6 };
const groupLabelStyle: CSSProperties = {
  fontSize: micro, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-3)",
};
const hintStyle: CSSProperties = { fontSize: micro, color: "var(--text-3)" };
const smartRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const smartLabelStyle: CSSProperties = { fontSize: fsLabel, color: "var(--text-3)" };
const zoomRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 6 };
const zoomBtnStyle: CSSProperties = { ...BTN_SECONDARY, padding: "4px 8px", minWidth: 24, textAlign: "center" };
const zoomPctStyle: CSSProperties = {
  fontSize: fsLabel, color: "var(--text-2)", minWidth: 34, textAlign: "center",
  fontVariantNumeric: "tabular-nums",
};
const resetBtnStyle: CSSProperties = { ...BTN_SECONDARY, padding: "4px 8px", marginLeft: "auto" };

// The rail itself IS the measured track (pointer math reads its own rect) — 18px tall to give the
// keyboard focus ring and the pointer hit target room without the 1px visual track looking padded.
// :focus-visible ring lives in index.css (`.sky-density-rail`) — inline styles can't express a
// pseudo-class, and component-local <style> tags are dead in production (CSP).
const railStyle: CSSProperties = {
  position: "relative", height: 18, cursor: "pointer", touchAction: "none",
};
const trackStyle: CSSProperties = {
  position: "absolute", left: 0, right: 0, top: "50%", height: 1,
  transform: "translateY(-50%)", background: "var(--border)",
};
const fillStyle: CSSProperties = {
  position: "absolute", left: 0, top: "50%", height: 1,
  transform: "translateY(-50%)", background: "var(--text-3)",
};
const ticksWrapStyle: CSSProperties = {
  position: "absolute", left: 0, right: 0, top: "50%", transform: "translateY(-50%)",
  display: "flex", justifyContent: "space-between",
};
const tickStyle: CSSProperties = { width: 1, height: 5, background: "var(--border)" };
// Square thumb (D-B, exact contract) — no border radius, unlike a star's round core.
const thumbStyle: CSSProperties = {
  position: "absolute", top: "50%", width: 7, height: 11,
  transform: "translate(-50%, -50%)", background: "var(--text-1)",
};
