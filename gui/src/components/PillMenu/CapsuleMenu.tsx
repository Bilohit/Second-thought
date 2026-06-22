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
import { useEffect, useRef } from "react";
import type { PillCorner } from "../PillOverlay";
import { ALL_TARGETS, MENU_LABELS, MenuIcon, type MenuTarget } from "./icons";

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

interface Props {
  open: boolean;
  corner: PillCorner;
  label: string;
  dotColor: string;
  isActive: boolean;
  inboxCount: number;
  onToggle: () => void;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
}

export default function CapsuleMenu({ open, corner, label, dotColor, isActive, inboxCount, onToggle, onSelect, onHide }: Props) {
  const sliderRef = useRef<HTMLSpanElement>(null);
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

  const showSliderAt = (el: HTMLDivElement | null) => {
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

  return (
    <button
      type="button"
      className={`capsule-menu${open ? " open" : " drag-region"}`}
      data-corner={corner}
      aria-haspopup="menu"
      aria-label={`Second Thought — ${label}. Click to ${open ? "close" : "open"} the menu.`}
      aria-expanded={open}
      style={{ width: open ? CAPSULE_OPEN_W : CAPSULE_CLOSED_W, height: CAPSULE_H }}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      onMouseLeave={hideSlider}
    >
      {isActive && <span className="capsule-ring" aria-hidden="true" />}
      <span className="capsule-dot no-drag" aria-hidden="true" style={{ background: dotColor }} />
      <span className="capsule-label">{label}</span>
      <span ref={sliderRef} className="capsule-slider" aria-hidden="true" />
      {ALL_TARGETS.map((id, i) => {
        const isHide = id === "hide";
        const showBadge = id === "inbox" && inboxCount > 0;
        return (
          <div
            key={id}
            ref={(el) => { itemRefs.current[i] = el; }}
            role="menuitem"
            tabIndex={open ? 0 : -1}
            className={`capsule-item no-drag${isHide ? " capsule-item-hide" : ""}`}
            style={{ transitionDelay: `${i * 45}ms` }}
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
          </div>
        );
      })}
    </button>
  );
}
