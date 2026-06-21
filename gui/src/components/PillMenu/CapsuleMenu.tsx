/**
 * CapsuleMenu.tsx
 * ---------------
 * Capsule-mode (168×36 bar) on-click pill menu (for_sonnet.md "Problem 5").
 * Closed: status dot + label, the whole bar is one drag+click region — no
 * sub-section click targets. Open: morphs to an icons-only bar showing all
 * 6 actions (~36px each, no text), all visible at once.
 *
 * Edge-awareness lives one level up: the OS window is what actually grows
 * (see App.tsx's openingMenu branch — decision #5c pins whichever edge is
 * nearer the screen edge and grows the other way), already repositioned so
 * the correct edge of the *window* stays anchored where the pill visually
 * was. This component only renders the morph at its natural width inside
 * that window — it never measures or anchors itself.
 */
import type { PillCorner } from "../PillOverlay";
import { useDragCloseOnMove } from "../../lib/useDragCloseOnMove";
import { ALL_TARGETS, MENU_LABELS, MenuIcon, type MenuTarget } from "./icons";

export const CAPSULE_CLOSED_W = 168;
export const CAPSULE_ICON_W = 36;
export const CAPSULE_OPEN_W = ALL_TARGETS.length * CAPSULE_ICON_W + 16;
export const CAPSULE_H = 36;

interface Props {
  open: boolean;
  corner: PillCorner;
  label: string;
  dotColor: string;
  isActive: boolean;
  inboxCount: number;
  onToggle: () => void;
  /** Dragging the bar closes the menu instead of being locked while it's
   *  open (for_sonnet.md "Problem 4" decision #4b). */
  onDragClose: () => void;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
}

export default function CapsuleMenu({ open, corner, label, dotColor, isActive, inboxCount, onToggle, onDragClose, onSelect, onHide }: Props) {
  const dragHandlers = useDragCloseOnMove(open, onDragClose);

  return (
    <button
      type="button"
      className={`capsule-menu drag-region${open ? " open" : ""}`}
      data-corner={corner}
      aria-haspopup="menu"
      aria-label={`Second Thought — ${label}. Click to ${open ? "close" : "open"} the menu.`}
      aria-expanded={open}
      style={{ width: open ? CAPSULE_OPEN_W : CAPSULE_CLOSED_W, height: CAPSULE_H }}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      onPointerDown={dragHandlers.onPointerDown}
      onPointerMove={dragHandlers.onPointerMove}
      onPointerUp={dragHandlers.onPointerUp}
    >
      {isActive && <span className="capsule-ring" aria-hidden="true" />}
      <span className="capsule-dot no-drag" aria-hidden="true" style={{ background: dotColor }} />
      <span className="capsule-label">{label}</span>
      {ALL_TARGETS.map((id) => {
        const isHide = id === "hide";
        const showBadge = id === "inbox" && inboxCount > 0;
        return (
          <div
            key={id}
            role="menuitem"
            tabIndex={open ? 0 : -1}
            className={`capsule-item no-drag${isHide ? " capsule-item-hide" : ""}`}
            aria-label={showBadge ? `${MENU_LABELS[id]}, ${inboxCount} item${inboxCount === 1 ? "" : "s"} need review` : MENU_LABELS[id]}
            title={MENU_LABELS[id]}
            onClick={(e) => { e.stopPropagation(); isHide ? onHide() : onSelect(id); }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isHide ? onHide() : onSelect(id); }
            }}
          >
            <MenuIcon target={id} size={16} />
            {showBadge && <span className="spoke-badge" aria-hidden="true" />}
          </div>
        );
      })}
    </button>
  );
}
