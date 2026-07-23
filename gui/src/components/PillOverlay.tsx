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
import { useState, type ReactNode } from "react";
import type { CaptureState, CaptureStep } from "../hooks/useCapture";
import { deriveYoutubeSteps } from "../hooks/useCapture";
import CapsuleMenu, { CAPSULE_CLOSED_W, CAPSULE_H, CAPSULE_OPEN_W } from "./PillMenu/CapsuleMenu";
import RadialMenu, { type PillGeometry } from "./PillMenu/RadialMenu";
import { MENU_LABELS, type MenuTarget } from "./PillMenu/icons";
import type { LlmStatus } from "../lib/api";
import { llmStatusLabel, llmStatusTooltip } from "../lib/llmStatusLabel";
import type { VoicePhase } from "../hooks/useVoiceRecording";
import { formatElapsed } from "../lib/voiceLimits";
import { MicIcon, RefreshIcon } from "./PillMenu/icons";
import FluidVisualizer from "./PillMenu/FluidVisualizer";
import CompactShell from "./CompactPanels/CompactShell";
import CompactLook from "./CompactPanels/CompactLook";
import CompactInbox from "./CompactPanels/CompactInbox";
import CompactSettings from "./CompactPanels/CompactSettings";
import CompactVault from "./CompactPanels/CompactVault";
import CompactHistory from "./CompactPanels/CompactHistory";
import type { PanelExtrudeZone } from "../lib/compactPanel";
import type { useLookChat } from "../hooks/useLookChat";
import type { LookChatPersist } from "../App";
import type { SettingsForward } from "./FullWindow/FullWindow";
export type { PillMode, PillCorner } from "../lib/pillTypes";
import type { PillMode, PillCorner } from "../lib/pillTypes";

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
  /** Task 2.2: middle-float variant deleted — App.tsx maps
   *  `resolveVerticalZone`'s "middle" result to "top" before it ever reaches
   *  here, so only the two extrude directions remain. */
  panelZone?: PanelExtrudeZone;
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
  /** Capsule mode only (RC-3): the capsule twin of `islandTarget` above —
   *  lingers past `compactPanel` flipping to null (App.tsx's
   *  lastCapsulePanelTargetRef) so CompactShell and the bar/panel absolute
   *  offsets stay mounted with their last content through the whole
   *  PANEL_EXIT_MS close, instead of snapping to the flex-centered layout
   *  while the OS window is still panel-sized. */
  capsulePanelTarget?: Exclude<MenuTarget, "hide"> | null;
  onClosePanel?: () => void;
  /** C2: forwarded straight through to both CompactShell mounts below —
   *  fires when a render throw inside a compact panel auto-collapses it, so
   *  App can tint the pill briefly. See CompactShell's `onPanelError` doc. */
  onPanelError?: (error: unknown) => void;
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
  /** P2 reminder-consent parity: a just-auto-created reminder's brief undo
   *  window (App.tsx's reminderUndo state). While set and the pill is idle,
   *  it takes over the pill/capsule bar's label + click target (tap to
   *  undo) instead of its normal status text / menu-open behavior — the
   *  bar's own content-swap is reused rather than adding a second floating
   *  toast element, since the pill/capsule OS window is sized tightly
   *  around the bar with no spare room for one. */
  reminderToast?: { message: string; onUndo: () => void } | null;
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
  compactPanel, panelReady, panelZone, panelGeom, islandGeom, islandTarget, capsulePanelTarget, onClosePanel, onPanelError,
  lookMode, onSelectLookMode, lookChat, lookChatPersist,
  settingsProps, onOpenFile, reminderToast,
}: Props) {
  const isActive = captureState.phase === "capturing" || captureState.phase === "background";
  const isError  = captureState.phase === "error";
  const isDone   = captureState.phase === "done";
  const isIdle   = !isActive && !isError && !isDone;
  const isRecording = voicePhase === "recording";
  // Only takes over the bar when nothing more urgent (recording/capturing/
  // error/done) is already showing there — a reminder undo toast should
  // never mask a live capture's own status.
  const showReminderToast = !!reminderToast && isIdle && !isRecording;
  const label    = showReminderToast ? reminderToast!.message
    : isRecording ? formatElapsed(voiceElapsedMs) : pillLabel(captureState, stepDefs, llmStatus);

  // priority: recording > error > done > capturing > reminder-undo > llm-status > idle
  const dotColor =
    isRecording                          ? "var(--recording)"
    : isError                            ? "var(--red)"
    : isDone                             ? "var(--green)"
    : isActive                           ? "var(--accent)"
    : showReminderToast                  ? "var(--green)"
    : isIdle && llmStatus === "disconnected" ? "var(--yellow)"
    : "var(--text-3)";

  // B3/B5: Vault and Inbox each forward their own top-level action controls
  // (open folder/refresh/new-folder; Inbox/Reminders toggle+refresh) up
  // through this single slot so CompactShell's header can render them —
  // only one target's content is ever mounted at a time (keyed remount in
  // renderPanelBody below), so one shared slot is enough; the owning
  // component clears it to null on unmount/target switch.
  const [panelHeaderActions, setPanelHeaderActions] = useState<ReactNode | null>(null);

  // Shared panel body switch — capsule's extruded-sheet render and minimal's
  // island morph both need the exact same target->content mapping, so it's
  // factored out once rather than duplicated per mode (Task 3.1).
  // Task 2.4/M1: keyed remount per target so the content-swap CSS animation
  // (`.compact-swap` / `compactSwapIn` in index.css) restarts on every icon
  // click, exactly like FullWindow's `key={view}` pattern. Keyed INSIDE
  // `.compact-panel-body` (CompactShell renders this as `children`) so the
  // scroll container itself never remounts — only this inner wrapper does.
  const renderPanelBody = (target: Exclude<MenuTarget, "hide">) => (
    <div key={target} className="compact-swap">
      {target === "search" && lookMode && onSelectLookMode && lookChat && lookChatPersist ? (
        <CompactLook
          lookMode={lookMode}
          onSelectLookMode={onSelectLookMode}
          lookChat={lookChat}
          lookChatPersist={lookChatPersist}
          onClose={() => onClosePanel?.()}
          onHeaderActionsChange={setPanelHeaderActions}
        />
      ) : target === "inbox" ? (
        <CompactInbox onHeaderActionsChange={setPanelHeaderActions} />
      ) : target === "settings" && settingsProps ? (
        <CompactSettings onClose={() => onClosePanel?.()} {...settingsProps} />
      ) : target === "vault" ? (
        <CompactVault onHeaderActionsChange={setPanelHeaderActions} />
      ) : target === "stats" ? (
        <CompactHistory onOpenFile={onOpenFile} />
      ) : (
        /* Placeholder fallback — reached only if a target's required props
           (e.g. settingsProps) weren't supplied by the caller. */
        <div style={{ padding: "var(--space-3)", fontSize: 12, color: "var(--text-2)" }}>
          {MENU_LABELS[target]} panel — content coming soon.
        </div>
      )}
    </div>
  );

  if (mode === "minimal") {
    const panelActive = !!(islandTarget && islandGeom);
    // Island geometry not ready yet (panel just requested, morph rects not
    // computed/committed) — render the plain pill+fan, identical to no-panel
    // state. The very next render (islandGeom populated by App's reconcile
    // effect) picks up the island.
    const island = islandTarget && islandGeom ? (
      <div
        className="island-panel"
        data-panel-open={panelReady ? "true" : "false"}
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
            open={panelReady ?? false}
            onClose={() => onClosePanel?.()}
            showClose
            headerActions={panelHeaderActions}
            onPanelError={onPanelError}
          >
            {renderPanelBody(islandTarget)}
          </CompactShell>
        </div>
      </div>
    ) : null;

    const pillLeft = panelActive ? islandGeom!.startRect.left : undefined;
    const pillTop = panelActive ? islandGeom!.startRect.top : undefined;

    return (
      <div style={{ position: "relative", width: panelActive ? "100%" : PILL_DIMS.minimal.w, height: panelActive ? "100%" : PILL_DIMS.minimal.h }}>
        {island}
        {!panelActive && isRecording && (
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
            if (showReminderToast) { reminderToast!.onUndo(); return; }
            if (isRecording) { onVoiceToggle(); return; }
            onToggleMenu();
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            if (!menuOpen && !showReminderToast) onVoiceToggle();
          }}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={showReminderToast
            ? `${label}. Click to undo.`
            : isRecording
            ? `Second Thought — recording, ${label}. Click to stop and send.`
            : `Second Thought — ${label}. Click to ${menuOpen ? "close" : "open"} the menu.`}
          title={showReminderToast ? `${label} — click to undo` : isRecording ? `Recording — ${label}` : isIdle ? llmStatusTooltip(llmStatus) : label}
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
            position: panelActive ? "absolute" : "relative",
            left: pillLeft,
            top: pillTop,
            zIndex: 21,
            boxShadow: menuOpen ? "0 0 0 1px var(--accent-glow)" : "none",
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
          ) : showReminderToast ? (
            <span aria-hidden="true" style={{ display: "flex", color: "var(--green)" }}>
              <RefreshIcon size={14} />
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
        {!compactPanel && (
          <RadialMenu
            open={fanOpen ?? menuOpen}
            corner={corner}
            fanStyle={fanStyle}
            pillGeometry={pillGeometry}
            inboxCount={inboxCount}
            onSelect={onSelect}
            onHide={onHide}
          />
        )}
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
      panelZone={compactPanel ? (panelZone ?? "top") : undefined}
      activeTarget={compactPanel ?? null}
      onToggle={() => { if (showReminderToast) { reminderToast!.onUndo(); return; } if (isRecording) { onVoiceToggle(); return; } onToggleMenu(); }}
      onContextMenu={(e) => { e.preventDefault(); if (!menuOpen && !showReminderToast) onVoiceToggle(); }}
      onSelect={onSelect}
      onHide={() => {
        // ISS-028: Hide while a compact panel is open used to leave the bar
        // stuck as `capsule-menu open exiting` (both classes fighting each
        // other in index.css) because the panel's own open state lingered
        // through the hide. Closing the panel first collapses back to the
        // plain bar-only close, the one path CSS already handles cleanly.
        if (compactPanel && onClosePanel) onClosePanel();
        onHide();
      }}
      voicePhase={voicePhase}
      voiceElapsedMs={voiceElapsedMs}
      readWaveform={readWaveform}
      readSpectrum={readSpectrum}
      sampleRate={sampleRate}
    />
  );

  // No panel open (or geometry not yet available) — unchanged render path,
  // CapsuleMenu alone, centered by App's flex wrapper exactly as before.
  // RC-3: capsulePanelTarget lingers past compactPanel flipping to null so
  // this branch (and CompactShell's exit-clip morph) keeps rendering through
  // the whole close instead of bailing to the plain centered CapsuleMenu
  // while the OS window is still panel-sized.
  const capsuleTarget = capsulePanelTarget ?? compactPanel;
  if (!capsuleTarget || !panelGeom) return capsuleMenu;

  // GATE-1 option A (extruded sheet): CompactShell renders as a sibling of
  // CapsuleMenu, both absolutely positioned via the same offsets App.tsx
  // computed for the grown OS window (computeCapsulePanelGeometry) — this
  // wrapper replaces the flex-centered layout for exactly the panel-open
  // lifetime, matching how the window itself stopped being pill-sized.
  const zone = panelZone ?? "top";

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div style={{ position: "absolute", left: panelGeom.panelOffsetX, top: panelGeom.panelOffsetY, zIndex: 2 }}>
        <CompactShell
          target={capsuleTarget}
          corner={corner}
          zone={zone}
          open={panelReady ?? false}
          onClose={() => onClosePanel?.()}
          showClose={false}
          headerActions={panelHeaderActions}
          onPanelError={onPanelError}
        >
          {renderPanelBody(capsuleTarget)}
        </CompactShell>
      </div>
      <div style={{ position: "absolute", left: panelGeom.barOffsetX, top: panelGeom.barOffsetY, zIndex: 2, width: CAPSULE_OPEN_W, height: CAPSULE_H }}>
        {capsuleMenu}
      </div>
    </div>
  );
}
