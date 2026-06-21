/**
 * RadialMenu.tsx
 * --------------
 * Minimal-mode (36×36 dot) on-click pill menu — icon-only spokes fanned
 * around the pill. Geometry is delegated entirely to ../../lib/fanLayout's
 * unifiedFan() (the single, signed-off law for every pill position — see
 * for_sonnet.md "Problem 2 + 3"); this component only renders the result and
 * owns the per-spoke interaction (click, keyboard arrow navigation,
 * tooltips). Chip size is dynamic (returned by unifiedFan), not a constant.
 *
 * Rendered as siblings of the pill button inside the same `position:
 * relative` wrapper (see PillOverlay.tsx) — each `.spoke` self-centers via
 * `top:50%; left:50%` + a negative chip-size margin, exactly like the
 * mockups, so spokes radiate from the pill's true visual center regardless
 * of where that wrapper sits on screen.
 */
import { useMemo, useRef } from "react";
import type { PillCorner } from "../PillOverlay";
import { unifiedFan, type FanResult } from "../../lib/fanLayout";
import { useRadialTuning } from "../../lib/devTuning";
import { ALL_TARGETS, MENU_LABELS, MenuIcon, type MenuTarget } from "./icons";

// Production defaults (for_sonnet.md "Constants table") — overridable live
// by the dev tuner once it lands.
export const RADIAL_RADIUS = 100;
export const RADIAL_CHIP_MAX = 36;
export const RADIAL_CHIP_MIN = 33;
export const RADIAL_PAD = 0;
export const RADIAL_MIN_SPACING_DEG = 34;
export const RADIAL_ICON_SIZE = 16;
export const RADIAL_STAGGER_MS = 22;
export const RADIAL_ANIM_MS = 220;
export const RADIAL_SCALE_CLOSED = 0.6;
export const RADIAL_SCALE_HOVER = 1.06;
export const RADIAL_SCALE_PRESS = 0.95;

export interface PillGeometry {
  cx: number;
  cy: number;
  sw: number;
  sh: number;
}

interface Props {
  open: boolean;
  corner: PillCorner;
  /** The pill's current screen-space center and the screen dimensions, in
   *  the same logical-px units as RADIAL_RADIUS — required for every anchor
   *  (a pinned anchor is just a known center fed into the same geometry). */
  pillGeometry?: PillGeometry | null;
  fanStyle?: "spread" | "capped";
  inboxCount: number;
  onSelect: (target: Exclude<MenuTarget, "hide">) => void;
  onHide: () => void;
}

const ITEM_IDS = ALL_TARGETS;

export default function RadialMenu({ open, corner, pillGeometry, fanStyle, inboxCount, onSelect, onHide }: Props) {
  // Dev tuner overrides (off by default — see for_sonnet.md "Dev-only
  // troubleshooting tuner") take precedence over the `fanStyle` prop too, so
  // its fan-style toggle can A/B against the Settings choice live.
  const tuning = useRadialTuning();
  const effectiveFanStyle = tuning.fanStyleOverride ?? fanStyle ?? "spread";
  const fan = useMemo<FanResult>(() => {
    if (!pillGeometry) return { items: [], chip: tuning.chipMax, span: 0, fullFits: false };
    return unifiedFan({
      cx: pillGeometry.cx,
      cy: pillGeometry.cy,
      sw: pillGeometry.sw,
      sh: pillGeometry.sh,
      radius: tuning.radius,
      chipMax: tuning.chipMax,
      chipMin: tuning.chipMin,
      pad: tuning.pad,
      ids: ITEM_IDS,
      minSpacingDeg: tuning.minSpacingDeg,
      fanStyle: effectiveFanStyle,
      spreadMaxArc: tuning.spreadMaxArc,
    });
  }, [pillGeometry?.cx, pillGeometry?.cy, pillGeometry?.sw, pillGeometry?.sh, effectiveFanStyle, tuning]);
  const positions = fan.items;
  const chip = fan.chip;

  const itemRefs = useRef<Partial<Record<MenuTarget, HTMLButtonElement | null>>>({});

  const focusByOffset = (fromId: MenuTarget, offset: number) => {
    const order = positions.map((p) => p.id as MenuTarget);
    const idx = order.indexOf(fromId);
    if (idx === -1) return;
    const next = order[(idx + offset + order.length) % order.length];
    itemRefs.current[next]?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent, id: MenuTarget) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); focusByOffset(id, 1); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); focusByOffset(id, -1); }
  };

  return (
    <>
      {positions.map((pos, i) => {
        const id = pos.id as MenuTarget;
        const label = MENU_LABELS[id];
        const isHide = id === "hide";
        const showBadge = id === "inbox" && inboxCount > 0;
        return (
          <button
            key={id}
            ref={(el) => { itemRefs.current[id] = el; }}
            type="button"
            role="menuitem"
            data-corner={corner}
            className={`spoke${isHide ? " spoke-hide" : ""}${open ? " open" : ""}`}
            style={
              {
                "--tx": `${Math.round(pos.x)}px`,
                "--ty": `${Math.round(pos.y)}px`,
                "--spoke-size": `${Math.round(chip)}px`,
                "--spoke-icon-size": `${RADIAL_ICON_SIZE}px`,
                "--spoke-anim-ms": `${RADIAL_ANIM_MS}ms`,
                "--spoke-scale-closed": RADIAL_SCALE_CLOSED,
                "--spoke-scale-hover": RADIAL_SCALE_HOVER,
                "--spoke-scale-press": RADIAL_SCALE_PRESS,
                transitionDelay: open ? `${i * RADIAL_STAGGER_MS}ms` : "0ms",
              } as React.CSSProperties
            }
            tabIndex={open ? 0 : -1}
            title={label}
            aria-label={showBadge ? `${label}, ${inboxCount} item${inboxCount === 1 ? "" : "s"} need review` : label}
            onClick={(e) => { e.stopPropagation(); isHide ? onHide() : onSelect(id); }}
            onKeyDown={(e) => handleKeyDown(e, id)}
          >
            <MenuIcon target={id} size={RADIAL_ICON_SIZE} />
            {showBadge && <span className="spoke-badge" aria-hidden="true" />}
          </button>
        );
      })}
    </>
  );
}
