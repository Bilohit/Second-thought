/**
 * CapsuleMenu.tsx
 * ---------------
 * Capsule-mode (136×36 bar) on-click pill menu (for_sonnet.md "Problem 5").
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
import { useEffect, useMemo, useRef } from "react";
import type { PillCorner } from "../PillOverlay";
import { ALL_TARGETS, MENU_LABELS, MenuIcon, type MenuTarget } from "./icons";
import { staggerDelays } from "../../lib/menuTiming";

// 231px — measured (mockups/capsule-width-deadzone.html §3.1) against every
// string that can appear in the closed label (useCapture.ts + PillOverlay's
// pillLabel), Geist Mono 12px. Longest is "Detecting YouTube link"; the rare
// long-category "Filed · <category>" case is excluded by design and ellipsizes
// instead of driving the whole bar's width — confirmed/signed off.
export const CAPSULE_CLOSED_W = 231;
export const CAPSULE_ICON_W = 44; // 36px hitbox + 8px spacing folded inside as padding (no gap deadzone)
export const CAPSULE_PAD_X = 12; // must equal --space-3 in index.css
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
  nearEdge: "left" | "right";
  onToggle: () => void;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
}

export default function CapsuleMenu({ open, corner, label, dotColor, isActive, inboxCount, draggable, dragging, onDragPointerDown, nearEdge, onToggle, onSelect, onHide }: Props) {
  const sliderRef = useRef<HTMLSpanElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const showSliderAt = (el: HTMLButtonElement | null) => {
    const slider = sliderRef.current;
    if (!el || !slider) return;
    slider.style.transform = `translateX(${el.offsetLeft}px)`;
    slider.style.width = `${el.offsetWidth}px`;
    slider.style.opacity = "1";
  };
  const hideSlider = () => {
    if (sliderRef.current) sliderRef.current.style.opacity = "0";
  };

  // Closing the menu shrinks every item back to width 0 — drop the slider
  // immediately so it doesn't visibly collapse with them.
  useEffect(() => { if (!open) hideSlider(); }, [open]);

  // Icons reveal from the screen-near (pinned) edge inward (§4.3.3): when
  // the bar hugs the right edge, the rightmost icon enters first. DOM order
  // stays fixed (ALL_TARGETS) — only the delay assignment flips.
  const delays = useMemo(() => {
    const base = staggerDelays(ALL_TARGETS.length, CAPSULE_ANIM_MS, CAPSULE_ITEM_PLAY_MS);
    return nearEdge === "right" ? [...base].reverse() : base;
  }, [nearEdge]);

  return (
    // A plain div, not a <button>: it hosts real <button role="menuitem">
    // children when open, and a <button> can't validly contain other
    // focusable descendants (screen readers may not expose them correctly).
    // Closing-by-clicking-the-background still works because the toggle
    // button's native click bubbles up to this onClick, and each menuitem
    // stops propagation so selecting one doesn't also re-toggle.
    <div
      className={`capsule-menu${open ? " open" : ""}${draggable ? " pill-drag-handle" : ""}${dragging ? " pill-grabbed" : ""}`}
      data-corner={corner}
      style={{ width: open ? CAPSULE_OPEN_W : CAPSULE_CLOSED_W, height: CAPSULE_H }}
      onPointerDown={draggable ? onDragPointerDown : undefined}
      onClick={onToggle}
      onMouseLeave={hideSlider}
    >
      {isActive && <span className="capsule-ring" aria-hidden="true" />}
      <button
        type="button"
        className="capsule-toggle no-drag"
        aria-haspopup="menu"
        aria-label={`Second Thought — ${label}. Click to ${open ? "close" : "open"} the menu.`}
        aria-expanded={open}
        tabIndex={open ? -1 : 0}
      >
        <span className="capsule-dot" aria-hidden="true" style={{ background: dotColor }} />
        <span className="capsule-label">{label}</span>
      </button>
      <span ref={sliderRef} className="capsule-slider" aria-hidden="true" />
      <div role="menu" aria-label="Second Thought actions" className="capsule-items">
        {ALL_TARGETS.map((id, i) => {
          const isHide = id === "hide";
          const showBadge = id === "inbox" && inboxCount > 0;
          return (
            <button
              key={id}
              type="button"
              ref={(el) => { itemRefs.current[i] = el; }}
              role="menuitem"
              tabIndex={open ? 0 : -1}
              className={`capsule-item no-drag${isHide ? " capsule-item-hide" : ""}`}
              style={{ transitionDelay: `${delays[i]}ms` }}
              aria-label={showBadge ? `${MENU_LABELS[id]}, ${inboxCount} item${inboxCount === 1 ? "" : "s"} need review` : MENU_LABELS[id]}
              title={MENU_LABELS[id]}
              onClick={(e) => { e.stopPropagation(); isHide ? onHide() : onSelect(id); }}
              onMouseEnter={() => showSliderAt(itemRefs.current[i])}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isHide ? onHide() : onSelect(id); }
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
