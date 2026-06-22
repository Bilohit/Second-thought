/**
 * PillOverlay.tsx
 * ---------------
 * Compact "Capsule" / "Minimal" presentations of the capture pipeline.
 * Pure presentation over useCapture's real state — no parallel state
 * machine. Clicking the pill toggles an on-click menu (radial fan for
 * minimal, capsule-morph for capsule) instead of expanding to the full
 * window; selecting a menu item is what actually expands+routes (see
 * App.tsx's onSelect/onHide wiring). Re-clicking the pill while the menu is
 * open dismisses it without hiding the app (D1, for_sonnet.md §5.1/§10).
 *
 * Closed pill is draggable; open pill is not (for_sonnet.md Problem 2) — the
 * `drag-region` class is only applied while the menu is closed, so the OS
 * can't move the window while it's open. Closing itself is click-off
 * (App.tsx's outer wrapper onClick), not drag (for_sonnet.md Problem 3).
 *
 * Corner style is a deliberate, narrow exception to the app's sharp-0px-
 * radius lock (see DESIGN.md / index.css): it only ever touches this one
 * component's shape (and the menu chips, which inherit it — D2), never any
 * panel/control elsewhere.
 */
import type { CaptureState, CaptureStep } from "../hooks/useCapture";
import { deriveYoutubeSteps } from "../hooks/useCapture";
import RadialMenu, { type PillGeometry } from "./PillMenu/RadialMenu";
import CapsuleMenu from "./PillMenu/CapsuleMenu";
import type { MenuTarget } from "./PillMenu/icons";

export type PillMode = "capsule" | "minimal";
export type PillCorner = "sharp" | "rounded";

interface Props {
  mode: PillMode;
  corner: PillCorner;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  menuOpen: boolean;
  onToggleMenu: () => void;
  pillGeometry?: PillGeometry | null;
  fanStyle?: "spread" | "capped";
  inboxCount: number;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
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

export default function PillOverlay({
  mode, corner, captureState, stepDefs, menuOpen, onToggleMenu, pillGeometry, fanStyle, inboxCount, onSelect, onHide,
}: Props) {
  const isActive = captureState.phase === "capturing" || captureState.phase === "background";
  const isError  = captureState.phase === "error";
  const isDone   = captureState.phase === "done";
  const label    = pillLabel(captureState, stepDefs);

  const dotColor = isError ? "var(--red)" : isDone ? "var(--green)" : isActive ? "var(--accent)" : "var(--text-3)";

  if (mode === "minimal") {
    return (
      <div style={{ position: "relative", width: PILL_DIMS.minimal.w, height: PILL_DIMS.minimal.h }}>
        <button
          type="button"
          className={menuOpen ? undefined : "drag-region"}
          onClick={(e) => { e.stopPropagation(); onToggleMenu(); }}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`Second Thought — ${label}. Click to ${menuOpen ? "close" : "open"} the menu.`}
          title={label}
          style={{
            width: PILL_DIMS.minimal.w,
            height: PILL_DIMS.minimal.h,
            padding: 0,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: corner === "rounded" ? "50%" : "0px",
            cursor: menuOpen ? "pointer" : "grab",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
            zIndex: 21,
            boxShadow: menuOpen ? "0 0 0 1px var(--accent-glow)" : "none",
            transition: "transform 0.18s cubic-bezier(0.16,1,0.3,1), box-shadow 0.15s ease",
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
        <RadialMenu
          open={menuOpen}
          corner={corner}
          pillGeometry={pillGeometry}
          fanStyle={fanStyle}
          inboxCount={inboxCount}
          onSelect={onSelect}
          onHide={onHide}
        />
      </div>
    );
  }

  return (
    <CapsuleMenu
      open={menuOpen}
      corner={corner}
      label={label}
      dotColor={dotColor}
      isActive={isActive}
      inboxCount={inboxCount}
      onToggle={onToggleMenu}
      onSelect={onSelect}
      onHide={onHide}
    />
  );
}
