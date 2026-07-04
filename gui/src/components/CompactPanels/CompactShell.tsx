/**
 * CompactShell.tsx
 * -----------------
 * Presentational shell for compact-mode panels (Compact Mode Menu
 * Decoupling, Task 2.1): a fixed-width 288px surface with an always-visible
 * header (icon + target title + close button) and a scrollable body that
 * renders whatever content the caller passes as `children`.
 *
 * This component owns no geometry/window logic — it only renders the panel
 * chrome and reveal animation via `[data-zone]`/`.open` clip-path classes
 * (see `.compact-panel` in index.css). The vertical zone (top/middle/bottom)
 * and window sizing come from `lib/compactPanel.ts` and are wired in by the
 * caller (Task 2.2), not computed here.
 *
 * GATE-1/3 resolved (see scratchpad brief): gap is fixed at 0 (fused
 * border), the header is always shown regardless of target, and there is no
 * `onOpenFull` escape hatch — full controls live inside `children`.
 */
import { MenuIcon, MENU_LABELS, NAV_TARGETS, type MenuTarget } from "../PillMenu/icons";
import type { PillCorner } from "../PillOverlay";
import type { VerticalZone } from "../../lib/compactPanel";

interface CompactShellProps {
  target: Exclude<MenuTarget, "hide">;
  corner: PillCorner;
  zone: VerticalZone;
  /** = panelReady — drives the clip-path reveal via the `.open` class. */
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Task 2.2 (middle zone only): the bar floats over the panel's vertical
   *  midpoint (z-index below bar) rather than at the panel's top edge, so
   *  the header/body need extra top padding to clear it — computed by the
   *  caller from the same offsets that positioned the bar. Omitted (top/
   *  bottom zones) leaves the panel's normal padding untouched. */
  bodyTopPad?: number;
  /** Minimal-mode island morph (Task 3.1): when present, the header renders
   *  an icon tab strip (one per NAV_TARGETS) instead of the static
   *  icon+title, and switching tabs swaps `children` in place via the
   *  caller — no morph replay, no window resize. Omitted in capsule mode,
   *  which keeps the static title header. */
  tabs?: { active: Exclude<MenuTarget, "hide">; onSelect: (t: Exclude<MenuTarget, "hide">) => void };
}

export default function CompactShell({ target, corner, zone, open, onClose, children, bodyTopPad, tabs }: CompactShellProps) {
  return (
    <div
      className={`compact-panel${open ? " open" : ""}`}
      data-zone={zone}
      data-corner={corner}
    >
      <div className="compact-panel-header">
        {tabs ? (
          <div className="compact-panel-tabs" role="tablist">
            {NAV_TARGETS.map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tabs.active === t}
                aria-label={MENU_LABELS[t]}
                title={MENU_LABELS[t]}
                className={`compact-panel-tab${tabs.active === t ? " active" : ""}`}
                onClick={() => tabs.onSelect(t)}
              >
                <MenuIcon target={t} size={16} />
              </button>
            ))}
          </div>
        ) : (
          <span className="compact-panel-title">
            <MenuIcon target={target} size={16} />
            <span>{MENU_LABELS[target]}</span>
          </span>
        )}
        <button
          type="button"
          className="compact-panel-close"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="compact-panel-body" style={bodyTopPad ? { paddingTop: bodyTopPad } : undefined}>{children}</div>
    </div>
  );
}
