/**
 * CapsuleMenu.tsx
 * ---------------
 * Capsule-mode (154×36 closed bar, see CAPSULE_CLOSED_W) on-click pill menu
 * (for_sonnet.md "Problem 5").
 * Closed: status dot + label, the whole bar is one drag+click region — no
 * sub-section click targets. Open: morphs to an icons-only bar showing all
 * 6 actions (~36px each, no text), all visible at once.
 *
 * Edge-awareness lives one level up: the OS window is what actually grows
 * (see App.tsx's openingMenu branch, `computeCapsuleMenuGeometry` —
 * for_sonnet.md Problem 3 pins whichever edge is nearer the screen edge and
 * grows the other way), already repositioned so the correct edge of the
 * *window* stays anchored where the pill visually was. This component only
 * renders the morph at its natural width inside that window — it never
 * measures or anchors itself.
 *
 * Closed is draggable, open is not (for_sonnet.md Problem 2) — the
 * `drag-region` class is only applied while closed.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { PillCorner } from "../PillOverlay";
import { ALL_TARGETS, MENU_LABELS, MenuIcon, type MenuTarget } from "./icons";
import { sliderRect } from "./capsuleSlider";
import { staggerDelays } from "../../lib/menuTiming";
import type { LlmStatus } from "../../lib/api";
import type { VoicePhase } from "../../hooks/useVoiceRecording";
import { formatElapsed } from "../../lib/voiceLimits";
import FluidVisualizer from "./FluidVisualizer";

// 154px — "Second Thought" (Geist Mono 12px, 98px text) with symmetric side
// insets: 28px left (12px pad + 8px dot + 8px gap) = 28px right (12px pad +
// 16px label slack). pillLabel strings in useCapture.ts stay within the text
// budget; long vault category names on done ellipsize instead of widening.
export const CAPSULE_PAD_X = 12; // must equal --space-3 in index.css
export const CAPSULE_DOT_W = 8;
export const CAPSULE_DOT_GAP = 8; // must equal --space-2 on .capsule-label
export const CAPSULE_TEXT_W = 98; // measured width of "Second Thought"
export const CAPSULE_SIDE_INSET = CAPSULE_PAD_X + CAPSULE_DOT_W + CAPSULE_DOT_GAP;
export const CAPSULE_LABEL_CHROME = CAPSULE_SIDE_INSET * 2;
export const CAPSULE_CLOSED_W = CAPSULE_TEXT_W + CAPSULE_LABEL_CHROME;
export const CAPSULE_ICON_W = 44; // 36px hitbox + 8px spacing folded inside as padding (no gap deadzone)
// No flex `gap` between open-state icons — each .capsule-item carries its own
// spacing as inner padding so hitboxes touch edge-to-edge with zero dead
// pixels between them (for_sonnet.md §3.2).
export const CAPSULE_OPEN_W =
  ALL_TARGETS.length * CAPSULE_ICON_W
  + CAPSULE_PAD_X * 2;
export const CAPSULE_H = 36;

// One coordinated timeline (for_sonnet.md §4): the bar width transition and
// the icon stagger now share CAPSULE_ANIM_MS, so the last icon finishes
// at/just before the bar settles instead of ~300ms after it (must match the
// `--capsule-bar-ms`/`--capsule-item-ms` transition durations in index.css).
export const CAPSULE_ANIM_MS = 260;
export const CAPSULE_ITEM_PLAY_MS = 180;
const CAPSULE_EXIT_BUFFER_MS = 60;
// Window must stay full-width this long after close starts before App.tsx
// shrinks it, so the morph never gets clipped mid-exit (§4.3.2/§8.2). The
// last item's delay is CAPSULE_ANIM_MS - CAPSULE_ITEM_PLAY_MS (see
// staggerDelays), so it finishes playing right at CAPSULE_ANIM_MS.
export const CAPSULE_EXIT_MS = CAPSULE_ANIM_MS + CAPSULE_EXIT_BUFFER_MS;

interface Props {
  open: boolean;
  corner: PillCorner;
  label: string;
  dotColor: string;
  isActive: boolean;
  llmStatus: LlmStatus;
  inboxCount: number;
  /** for_sonnet.md Problem 2: only "custom" anchor with the menu closed is
   *  draggable; everything else gets the default pointer cursor instead of
   *  the drag-region class. */
  draggable: boolean;
  /** True while a custom JS pointer-drag gesture has this pill grabbed —
   *  drives the press-state scale affordance (§8.5, user-confirmed). */
  dragging: boolean;
  onDragPointerDown: (e: React.PointerEvent) => void;
  /** Which screen edge the bar's near edge is pinned to — icons stagger in
   *  from this edge inward (§4.3.3), confirmed against the mock. */
  nearEdge: "left" | "right" | "center";
  /** True while the bar is playing its close morph but menuOpen is already
   *  false — keeps label/dot hidden and layout pinned until the window shrinks. */
  exiting?: boolean;
  /** False hides the bar for one origin-shift resize frame (WebView2
   *  stale-frame mask, see CAPSULE_OPEN_FLICKER_PLAN.md). Default true. */
  shown?: boolean;
  /** Which vertical third the fused compact panel grows from — drives square
   *  seam corners on the bar when a panel is open (GATE-1 option A). */
  panelZone?: "top" | "middle" | "bottom";
  /** The compact panel target currently open (Task 2.1 step 6), or null when
   *  no panel is out. The matching icon gets the `active` class (color
   *  flip only — the indicator element itself is Task 2.4/M2). */
  activeTarget?: MenuTarget | null;
  onToggle: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
  /** Voice recording (A6): while recording and the bar is closed, the
   *  oscilloscope trace replaces the label text; unused otherwise. */
  voicePhase?: VoicePhase;
  voiceElapsedMs?: number;
  readWaveform?: (out: Float32Array) => void;
  readSpectrum?: (out: Uint8Array) => void;
  sampleRate?: number;
}

export default function CapsuleMenu({ open, corner, label, dotColor, isActive, llmStatus, inboxCount, draggable, dragging, onDragPointerDown, nearEdge, exiting = false, shown = true, panelZone, activeTarget = null, onToggle, onContextMenu, onSelect, onHide, voicePhase, voiceElapsedMs, readWaveform, readSpectrum, sampleRate }: Props) {
  const isRecording = voicePhase === "recording";
  const sliderRef = useRef<HTMLSpanElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const showSliderAt = (el: HTMLButtonElement | null) => {
    const slider = sliderRef.current;
    if (!el || !slider) return;
    const idx = itemRefs.current.indexOf(el);
    const { left, width } = sliderRect(el.offsetLeft, el.offsetWidth, idx, itemRefs.current.length);
    slider.style.transform = `translateX(${left}px)`;
    slider.style.width = `${width}px`;
    slider.style.opacity = "1";
  };
  const hideSlider = () => {
    if (sliderRef.current) sliderRef.current.style.opacity = "0";
  };

  // Closing the menu shrinks every item back to width 0 — drop the slider
  // immediately so it doesn't visibly collapse with them.
  useEffect(() => { if (!open) hideSlider(); }, [open]);

  // ISS-028 fallback: `exiting` is driven by App.tsx's close-morph timer, but
  // if a panel-close interrupts that timeline the prop can get stuck true
  // indefinitely — the bar then renders `capsule-menu open exiting`
  // simultaneously, a combination index.css never expects to resolve on its
  // own. This local timeout is a hard backstop: however `exiting` got stuck,
  // it self-clears once the morph should long since have finished, so the
  // bar always settles instead of wedging half-closed.
  const [forceExitClear, setForceExitClear] = useState(false);
  useEffect(() => {
    if (!exiting) { setForceExitClear(false); return; }
    const t = setTimeout(() => setForceExitClear(true), CAPSULE_EXIT_MS + 200);
    return () => clearTimeout(t);
  }, [exiting]);
  const effectiveExiting = exiting && !forceExitClear;

  // Task 2.4/M2 (pick c — sliding background pill): index of the icon whose
  // compact panel is currently open, or -1 while none is. Icon slots are
  // fixed 44px flex items (index.css:1035) so `activeIndex * 44` is exact —
  // no measuring needed, same discipline as the rail-slider pattern.
  const activeIndex = activeTarget ? ALL_TARGETS.indexOf(activeTarget) : -1;

  // Icons reveal from the screen-near (pinned) edge inward (§4.3.3): when
  // the bar hugs the right edge, the rightmost icon enters first. DOM order
  // stays fixed (ALL_TARGETS) — only the delay assignment flips.
  const delays = useMemo(() => {
    const base = staggerDelays(ALL_TARGETS.length, CAPSULE_ANIM_MS, CAPSULE_ITEM_PLAY_MS);
    if (nearEdge === "right") return [...base].reverse();
    if (nearEdge === "center") {
      const n = ALL_TARGETS.length;
      const maxDelay = CAPSULE_ANIM_MS - CAPSULE_ITEM_PLAY_MS;
      // center-out: middle index(es) get delay 0, outermost get maxDelay
      const step = maxDelay / ((n - 1) / 2);
      return ALL_TARGETS.map((_, i) => Math.round(step * Math.abs(i - (n - 1) / 2)));
    }
    return base;
  }, [nearEdge]);

  return (
    // A plain div, not a <button>: it hosts real <button role="menuitem">
    // children when open, and a <button> can't validly contain other
    // focusable descendants (screen readers may not expose them correctly).
    // Closing-by-clicking-the-background still works because the toggle
    // button's native click bubbles up to this onClick, and each menuitem
    // stops propagation so selecting one doesn't also re-toggle.
    <div
      className={`capsule-menu${open ? " open" : ""}${effectiveExiting ? " exiting" : ""}${draggable ? " pill-drag-handle" : ""}${dragging ? " pill-grabbed" : ""}`}
      data-corner={corner}
      data-near={nearEdge}
      data-panel-zone={panelZone}
      style={{ width: open ? CAPSULE_OPEN_W : CAPSULE_CLOSED_W, height: CAPSULE_H, visibility: shown ? "visible" : "hidden" }}
      onPointerDown={draggable ? onDragPointerDown : undefined}
      onClick={onToggle}
      onContextMenu={onContextMenu}
      onMouseLeave={hideSlider}
    >
      {isActive && <span className="capsule-ring" aria-hidden="true" />}
      <button
        type="button"
        className="capsule-toggle no-drag"
        aria-haspopup="menu"
        aria-label={isRecording
          ? `Second Thought — recording, ${label}. Click to stop and send.`
          : `Second Thought — ${label}. Click to ${open ? "close" : "open"} the menu.`}
        aria-expanded={open}
        tabIndex={open ? -1 : 0}
      >
        <span
          className={`capsule-dot${isRecording ? " rec-dot" : ""}`}
          aria-hidden="true"
          style={{
            background: dotColor,
            animation: isRecording ? undefined : !isActive && llmStatus === "loading"
              ? "llmLoadingPulse 2.4s cubic-bezier(0.45,0,0.55,1) infinite"
              : !isActive && llmStatus === "disconnected"
              ? "llmWarnFade 2.8s cubic-bezier(0.45,0,0.55,1) infinite"
              : "none",
          }}
        />
        {isRecording && readWaveform ? (
          <span className="capsule-label capsule-voice-row" aria-hidden="true">
            <FluidVisualizer readWaveform={readWaveform} readSpectrum={readSpectrum} sampleRate={sampleRate} width={CAPSULE_TEXT_W - 34} height={20} active />
            <span className="capsule-voice-timer">{formatElapsed(voiceElapsedMs ?? 0)}</span>
          </span>
        ) : (
          <span className="capsule-label">{label}</span>
        )}
      </button>
      <span ref={sliderRef} className="capsule-slider" aria-hidden="true" />
      {activeIndex >= 0 && (
        // Persistent "which panel is open" indicator — distinct from
        // .capsule-slider above (that one is imperative, hover-driven, and
        // gets wiped on close). Mounts fresh on null->target (fades in via
        // the compactSwapIn-style keyframe below, no slide since there's no
        // prior transform to animate from); subsequent target->target
        // switches just update the transform prop in place, so only the
        // already-mounted element's `transition: transform` plays (slide,
        // no re-fade).
        <span
          className="capsule-active-ind"
          aria-hidden="true"
          style={{ transform: `translateX(${activeIndex * CAPSULE_ICON_W}px)` }}
        />
      )}
      <div role="menu" aria-label="Second Thought actions" className="capsule-items">
        {ALL_TARGETS.map((id, i) => {
          const isHide = id === "hide";
          const showBadge = id === "inbox" && inboxCount > 0;
          const activate = () => { isHide ? onHide() : onSelect(id); };
          return (
            <button
              key={id}
              type="button"
              ref={(el) => { itemRefs.current[i] = el; }}
              role="menuitem"
              tabIndex={open ? 0 : -1}
              className={`capsule-item no-drag${isHide ? " capsule-item-hide" : ""}${activeTarget === id ? " active" : ""}`}
              style={{ transitionDelay: `${delays[i]}ms` }}
              aria-label={showBadge ? `${MENU_LABELS[id]}, ${inboxCount} item${inboxCount === 1 ? "" : "s"} need review` : MENU_LABELS[id]}
              title={MENU_LABELS[id]}
              onClick={(e) => { e.stopPropagation(); activate(); }}
              onMouseEnter={() => showSliderAt(itemRefs.current[i])}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
              }}
            >
              <MenuIcon target={id} size={16} />
              {showBadge && (
                <span className="spoke-badge" aria-hidden="true">
                  {inboxCount > 9 ? "9+" : inboxCount}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
