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
import CapsuleMenu from "./PillMenu/CapsuleMenu";
import RadialMenu, { type PillGeometry } from "./PillMenu/RadialMenu";
import type { MenuTarget } from "./PillMenu/icons";

export type PillMode = "capsule" | "minimal";
export type PillCorner = "sharp" | "rounded";

interface Props {
  mode: PillMode;
  corner: PillCorner;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  menuOpen: boolean;
  /** Minimal mode only: gates the radial fan's render separately from
   *  `menuOpen` so it can never paint before the pill window has actually
   *  grown to fit it (pill-fan-clip fix). Falls back to `menuOpen` when
   *  omitted. Unused in capsule mode. */
  fanOpen?: boolean;
  /** Only "custom" anchor with the menu closed is draggable (for_sonnet.md
   *  Problem 2) — an anchored pill snaps back via Settings' anchor grid and
   *  must never be ungrabbable-dragged away from it. */
  draggable: boolean;
  /** True while a custom JS pointer-drag gesture has this pill grabbed —
   *  drives the press-state scale affordance (§8.5, user-confirmed). */
  dragging: boolean;
  onDragPointerDown: (e: React.PointerEvent) => void;
  /** Which screen edge the capsule bar is pinned to — icons stagger in from
   *  this edge (§4.3.3). Unused in minimal mode. */
  nearEdge: "left" | "right";
  onToggleMenu: () => void;
  inboxCount: number;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
  /** Minimal mode only: the radial fan's screen-space geometry (App.tsx
   *  computes this on open from the pill's own window position), and which
   *  fan style Settings has picked. Unused in capsule mode. */
  pillGeometry?: PillGeometry | null;
  fanStyle?: "spread" | "capped";
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
    if (state.starting) return "Starting up";
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
  mode, corner, captureState, stepDefs, menuOpen, fanOpen, draggable, dragging, onDragPointerDown, nearEdge, onToggleMenu, inboxCount, onSelect, onHide,
  pillGeometry, fanStyle,
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
          className={`${draggable ? "pill-drag-handle" : ""}${dragging ? " pill-grabbed" : ""}`}
          onPointerDown={draggable ? onDragPointerDown : undefined}
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
            cursor: draggable ? "grab" : "pointer",
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
          open={fanOpen ?? menuOpen}
          corner={corner}
          fanStyle={fanStyle}
          pillGeometry={pillGeometry}
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
      draggable={draggable}
      dragging={dragging}
      onDragPointerDown={onDragPointerDown}
      nearEdge={nearEdge}
      onToggle={onToggleMenu}
      onSelect={onSelect}
      onHide={onHide}
    />
  );
}
