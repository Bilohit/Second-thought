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
import CapsuleMenu, { CAPSULE_CLOSED_W, CAPSULE_H, CAPSULE_PAD_X, CAPSULE_ICON_W } from "./PillMenu/CapsuleMenu";
import RadialMenu, { type PillGeometry } from "./PillMenu/RadialMenu";
import { ALL_TARGETS, MENU_LABELS, type MenuTarget } from "./PillMenu/icons";
import { sliderRect } from "./PillMenu/capsuleSlider";
import type { LlmStatus } from "../lib/api";
import { llmStatusLabel, llmStatusTooltip } from "../lib/llmStatusLabel";
import type { VoicePhase } from "../hooks/useVoiceRecording";
import { formatElapsed } from "../lib/voiceLimits";
import { MicIcon } from "./PillMenu/icons";
import FluidVisualizer from "./PillMenu/FluidVisualizer";
import CompactShell from "./CompactPanels/CompactShell";
import CompactLook from "./CompactPanels/CompactLook";
import CompactInbox from "./CompactPanels/CompactInbox";
import CompactSettings from "./CompactPanels/CompactSettings";
import CompactVault from "./CompactPanels/CompactVault";
import CompactHistory from "./CompactPanels/CompactHistory";
import type { VerticalZone } from "../lib/compactPanel";
import type { useLookChat } from "../hooks/useLookChat";
import type { LookChatPersist } from "../App";
import type { SettingsForward } from "./FullWindow/FullWindow";

export type PillMode = "capsule" | "minimal";
export type PillCorner = "sharp" | "rounded";

interface Props {
  mode: PillMode;
  corner: PillCorner;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  llmStatus: LlmStatus;
  menuOpen: boolean;
  /** Capsule mode: gates the width morph until the OS window has grown
   *  (mirrors fanOpen). Falls back to `menuOpen` when omitted. */
  capsuleMorphOpen?: boolean;
  /** Capsule mode: true during the close morph after menuOpen flips false. */
  capsuleExiting?: boolean;
  /** Capsule mode: false hides the bar for one origin-shift resize frame
   *  (WebView2 stale-frame mask). Defaults to true. */
  capsuleShown?: boolean;
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
  nearEdge: "left" | "right" | "center";
  onToggleMenu: () => void;
  inboxCount: number;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
  /** Minimal mode only: the radial fan's screen-space geometry (App.tsx
   *  computes this on open from the pill's own window position), and which
   *  fan style Settings has picked. Unused in capsule mode. */
  pillGeometry?: PillGeometry | null;
  fanStyle?: "spread" | "capped";
  /** Voice recording (A6): right-click starts, left-click stops & sends,
   *  Esc cancels (wired in App.tsx). Ignored while the menu is open. */
  voicePhase: VoicePhase;
  voiceElapsedMs: number;
  readWaveform: (out: Float32Array) => void;
  readSpectrum: (out: Uint8Array) => void;
  sampleRate: number;
  onVoiceToggle: () => void;
  onVoiceCancel: () => void;
  /** Capsule mode only (Compact Mode Menu Decoupling, Task 2.2): the
   *  in-pill panel that opens instead of routing into FullWindow. `null`
   *  means no panel — CapsuleMenu renders alone exactly as before. Mirrors
   *  how `pillGeometry`/`fanStyle` flow for minimal mode's fan. */
  compactPanel?: Exclude<MenuTarget, "hide"> | null;
  /** = App's panelReady — gates CompactShell's reveal until the OS window
   *  has actually grown to fit it (same contract as capsuleMorphOpen). */
  panelReady?: boolean;
  panelZone?: VerticalZone;
  /** Bar/panel placement within the grown window, from
   *  `computeCapsulePanelGeometry` (App.tsx, memoized in
   *  capsulePanelGeomRef at open time). Undefined/null while no panel is
   *  open — the plain centered CapsuleMenu render path is used instead. */
  panelGeom?: { barOffsetX: number; barOffsetY: number; panelOffsetX: number; panelOffsetY: number } | null;
  /** Minimal mode only (Task 3.1): the island-morph rects in in-window
   *  coordinates, from `computeIslandMorphRects` (App.tsx, memoized in
   *  islandMorphGeomRef at open time) — `startRect` is always the pill's own
   *  on-screen rect (pillOffset, zero-drift origin), `endRect` the settled
   *  panel rect. Undefined/null while no panel is open. */
  islandGeom?: { startRect: { left: number; top: number; width: number; height: number }; endRect: { left: number; top: number; width: number; height: number } } | null;
  /** Minimal mode only: which target the island is showing. Lingers past
   *  `compactPanel` flipping to null (App.tsx's lastMinimalPanelTargetRef)
   *  so the island stays mounted with its last content through the whole
   *  close morph, while `compactPanel` itself (used for the pill's own
   *  fade-back-in) flips immediately. */
  islandTarget?: Exclude<MenuTarget, "hide"> | null;
  /** Gates the island's CompactShell reveal — distinct from `panelReady`
   *  (window-grown gate): content additionally waits for the rect-morph to
   *  settle plus the mock's 120ms `content-hid` delay (App.tsx). */
  islandContentReady?: boolean;
  onClosePanel?: () => void;
  /** Task 2.3: Look panel content/state, mirrored from FullWindow's wiring
   *  so CompactLook has full parity (search/chat, ignore-history, clear,
   *  reload indexing) — only present/used while compactPanel === "search". */
  lookMode?: "search" | "chat";
  onSelectLookMode?: (m: "search" | "chat") => void;
  lookChat?: ReturnType<typeof useLookChat>;
  lookChatPersist?: LookChatPersist;
  /** Task 2.4: Settings content/state, mirrored from FullWindow's wiring so
   *  CompactSettings has full parity (theme, display mode, corner, pinned,
   *  anchor, fan style, snap, monitor picker, look-chat persist) — only
   *  present/used while compactPanel === "settings". */
  settingsProps?: SettingsForward;
  /** Task 2.4: open-note handler for CompactVault/CompactHistory, mirrored
   *  from FullWindow's onOpenFile wiring. */
  onOpenFile?: (path: string) => void;
}

function stepPillLabel(def: CaptureStep): string {
  return def.pillLabel ?? def.label;
}

function pillLabel(state: CaptureState, stepDefs: CaptureStep[], llmStatus: LlmStatus): string {
  if (state.phase === "error") return "Error";
  if (state.phase === "done") {
    return state.result?.category ?? "Done";
  }
  if (state.phase === "background" && state.backgroundJob) {
    const { steps, stepDefs: ytDefs } = deriveYoutubeSteps(state.backgroundJob);
    const active = ytDefs.find((d) => steps[d.id] === "active");
    return active ? stepPillLabel(active) : "Working";
  }
  if (state.phase === "capturing") {
    if (state.starting) return "Starting";
    const active = stepDefs.find((d) => state.steps[d.id as keyof CaptureState["steps"]] === "active");
    return active ? stepPillLabel(active) : "Working";
  }
  // idle: swap label to reflect LLM state
  return llmStatusLabel(llmStatus);
}

export const PILL_DIMS: Record<PillMode, { w: number; h: number }> = {
  capsule: { w: CAPSULE_CLOSED_W, h: CAPSULE_H },
  minimal: { w: 36, h: 36 },
};

export default function PillOverlay({
  mode, corner, captureState, stepDefs, llmStatus, menuOpen, capsuleMorphOpen, capsuleExiting, capsuleShown, fanOpen, draggable, dragging, onDragPointerDown, nearEdge, onToggleMenu, inboxCount, onSelect, onHide,
  pillGeometry, fanStyle, voicePhase, voiceElapsedMs, readWaveform, readSpectrum, sampleRate, onVoiceToggle,
  compactPanel, panelReady, panelZone, panelGeom, islandGeom, islandTarget, islandContentReady, onClosePanel,
  lookMode, onSelectLookMode, lookChat, lookChatPersist,
  settingsProps, onOpenFile,
}: Props) {
  const isActive = captureState.phase === "capturing" || captureState.phase === "background";
  const isError  = captureState.phase === "error";
  const isDone   = captureState.phase === "done";
  const isIdle   = !isActive && !isError && !isDone;
  const isRecording = voicePhase === "recording";
  const label    = isRecording ? formatElapsed(voiceElapsedMs) : pillLabel(captureState, stepDefs, llmStatus);

  // priority: recording > error > done > capturing > llm-status > idle
  const dotColor =
    isRecording                          ? "var(--recording)"
    : isError                            ? "var(--red)"
    : isDone                             ? "var(--green)"
    : isActive                           ? "var(--accent)"
    : isIdle && llmStatus === "disconnected" ? "var(--yellow)"
    : "var(--text-3)";

  // Shared panel body switch — capsule's extruded-sheet render and minimal's
  // island morph both need the exact same target->content mapping, so it's
  // factored out once rather than duplicated per mode (Task 3.1).
  const renderPanelBody = (target: Exclude<MenuTarget, "hide">) =>
    target === "search" && lookMode && onSelectLookMode && lookChat && lookChatPersist ? (
      <CompactLook
        lookMode={lookMode}
        onSelectLookMode={onSelectLookMode}
        lookChat={lookChat}
        lookChatPersist={lookChatPersist}
        onClose={() => onClosePanel?.()}
      />
    ) : target === "inbox" ? (
      <CompactInbox />
    ) : target === "settings" && settingsProps ? (
      <CompactSettings onClose={() => onClosePanel?.()} {...settingsProps} />
    ) : target === "vault" ? (
      <CompactVault />
    ) : target === "stats" ? (
      <CompactHistory onOpenFile={onOpenFile} />
    ) : (
      /* Placeholder fallback — reached only if a target's required props
         (e.g. settingsProps) weren't supplied by the caller. */
      <div style={{ padding: "var(--space-3)", fontSize: 12, color: "var(--text-2)" }}>
        {MENU_LABELS[target]} panel — content coming soon.
      </div>
    );

  if (mode === "minimal") {
    // Island geometry not ready yet (panel just requested, morph rects not
    // computed/committed) — render the plain pill+fan, identical to no-panel
    // state. The very next render (islandGeom populated by App's reconcile
    // effect) picks up the island.
    const island = islandTarget && islandGeom ? (
      <div
        className="island-panel"
        data-panel-open={islandContentReady ? "true" : "false"}
        style={{
          position: "absolute",
          left: (panelReady ? islandGeom.endRect.left : islandGeom.startRect.left),
          top: (panelReady ? islandGeom.endRect.top : islandGeom.startRect.top),
          width: (panelReady ? islandGeom.endRect.width : islandGeom.startRect.width),
          height: (panelReady ? islandGeom.endRect.height : islandGeom.startRect.height),
          overflow: "hidden",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: corner === "rounded" ? 12 : 0,
          zIndex: 30,
        }}
      >
        <div style={{ width: islandGeom.endRect.width, height: islandGeom.endRect.height }}>
          <CompactShell
            target={islandTarget}
            corner={corner}
            zone={panelZone ?? "top"}
            open={islandContentReady ?? false}
            onClose={() => onClosePanel?.()}
            tabs={{ active: islandTarget, onSelect }}
          >
            {renderPanelBody(islandTarget)}
          </CompactShell>
        </div>
      </div>
    ) : null;

    return (
      <div style={{ position: "relative", width: PILL_DIMS.minimal.w, height: PILL_DIMS.minimal.h }}>
        {isRecording && (
          <div aria-hidden="true" style={{ position: "absolute", left: -6, top: -6, width: 48, height: 48, zIndex: 20, pointerEvents: "none" }}>
            <FluidVisualizer readWaveform={readWaveform} width={48} height={48} active variant="ring" />
          </div>
        )}
        <button
          type="button"
          className={`${draggable ? "pill-drag-handle" : ""}${dragging ? " pill-grabbed" : ""}`}
          onPointerDown={draggable ? onDragPointerDown : undefined}
          onClick={(e) => {
            e.stopPropagation();
            if (isRecording) { onVoiceToggle(); return; }
            onToggleMenu();
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            if (!menuOpen) onVoiceToggle();
          }}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={isRecording
            ? `Second Thought — recording, ${label}. Click to stop and send.`
            : `Second Thought — ${label}. Click to ${menuOpen ? "close" : "open"} the menu.`}
          title={isRecording ? `Recording — ${label}` : isIdle ? llmStatusTooltip(llmStatus) : label}
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
            // Island morph (Task 3.1): pill fades out over 160ms the instant
            // a panel is requested, and is not interactive/focusable while
            // the island sits on top of it. Fades back in as soon as the
            // panel closes (compactPanel -> null), independent of the
            // island's own rect-reverse-morph duration.
            opacity: compactPanel ? 0 : 1,
            pointerEvents: compactPanel ? "none" : "auto",
            transition: "transform 0.18s cubic-bezier(0.16,1,0.3,1), box-shadow 0.15s ease, opacity 160ms cubic-bezier(0.16,1,0.3,1)",
            animation: isActive ? "pillPulseGlow 1.1s ease-in-out infinite" : "none",
          }}
        >
          {isRecording ? (
            <span aria-hidden="true" style={{ display: "flex", color: "var(--text-1)" }}>
              <MicIcon size={14} />
            </span>
          ) : (
            <span
              aria-hidden="true"
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: dotColor,
                transition: "background 0.2s ease",
                animation: isIdle && llmStatus === "loading"
                  ? "llmLoadingPulse 2.4s cubic-bezier(0.45,0,0.55,1) infinite"
                  : isIdle && llmStatus === "disconnected"
                  ? "llmWarnFade 2.8s cubic-bezier(0.45,0,0.55,1) infinite"
                  : "none",
              }}
            />
          )}
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
        {island}
      </div>
    );
  }

  const capsuleMenu = (
    <CapsuleMenu
      open={capsuleMorphOpen ?? menuOpen}
      corner={corner}
      label={label}
      dotColor={dotColor}
      isActive={isActive}
      llmStatus={llmStatus}
      inboxCount={inboxCount}
      draggable={draggable}
      dragging={dragging}
      onDragPointerDown={onDragPointerDown}
      nearEdge={nearEdge}
      exiting={capsuleExiting}
      shown={capsuleShown}
      onToggle={() => { if (isRecording) { onVoiceToggle(); return; } onToggleMenu(); }}
      onContextMenu={(e) => { e.preventDefault(); if (!menuOpen) onVoiceToggle(); }}
      onSelect={onSelect}
      onHide={onHide}
      voicePhase={voicePhase}
      voiceElapsedMs={voiceElapsedMs}
      readWaveform={readWaveform}
      readSpectrum={readSpectrum}
      sampleRate={sampleRate}
    />
  );

  // No panel open (or geometry not yet available) — unchanged render path,
  // CapsuleMenu alone, centered by App's flex wrapper exactly as before.
  if (!compactPanel || !panelGeom) return capsuleMenu;

  // GATE-1 option A (extruded sheet): CompactShell renders as a sibling of
  // CapsuleMenu, both absolutely positioned via the same offsets App.tsx
  // computed for the grown OS window (computeCapsulePanelGeometry) — this
  // wrapper replaces the flex-centered layout for exactly the panel-open
  // lifetime, matching how the window itself stopped being pill-sized.
  const zone = panelZone ?? "top";
  // Middle zone: bar floats over the panel's vertical midpoint rather than
  // its top edge, so panel content needs top padding to clear the bar.
  const bodyTopPad = zone === "middle"
    ? Math.max(0, panelGeom.barOffsetY + CAPSULE_H - panelGeom.panelOffsetY)
    : undefined;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div style={{ position: "absolute", left: panelGeom.panelOffsetX, top: panelGeom.panelOffsetY, zIndex: zone === "middle" ? 1 : 2 }}>
        <CompactShell
          target={compactPanel}
          corner={corner}
          zone={zone}
          open={panelReady ?? false}
          onClose={() => onClosePanel?.()}
          bodyTopPad={bodyTopPad}
        >
          {renderPanelBody(compactPanel)}
        </CompactShell>
      </div>
      <div style={{ position: "absolute", left: panelGeom.barOffsetX, top: panelGeom.barOffsetY, zIndex: 2 }}>
        {capsuleMenu}
      </div>
      {(() => {
        // GATE-1 option A: keep the capsule-slider pinned under the selected
        // icon while its panel is open. CapsuleMenu's own slider is
        // imperative DOM-ref state driven by hover — it gets wiped by its
        // `useEffect(() => { if (!open) hideSlider(); }, [open])` the moment
        // menuOpen flips false for the panel-open transition. Rather than
        // touch CapsuleMenu, render a second `.capsule-slider`-styled
        // element here, on top of it, pinned to the selected icon's rect
        // (same math CapsuleMenu uses for hover).
        const idx = ALL_TARGETS.indexOf(compactPanel);
        if (idx < 0) return null;
        const { left, width } = sliderRect(CAPSULE_PAD_X + idx * CAPSULE_ICON_W, CAPSULE_ICON_W, idx, ALL_TARGETS.length);
        return (
          <div style={{ position: "absolute", left: panelGeom.barOffsetX, top: panelGeom.barOffsetY, zIndex: 3, pointerEvents: "none" }}>
            <span
              aria-hidden="true"
              className="capsule-slider"
              style={{ transform: `translateX(${left}px)`, width, opacity: 1 }}
            />
          </div>
        );
      })()}
    </div>
  );
}
