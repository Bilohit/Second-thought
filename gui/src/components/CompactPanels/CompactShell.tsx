/**
 * CompactShell.tsx
 * -----------------
 * Presentational shell for compact-mode panels (Compact Mode Menu
 * Decoupling, Task 2.1): a fixed-width 288px surface with an always-visible
 * header (icon + target title, optionally a close button) and a scrollable
 * body that renders whatever content the caller passes as `children`.
 *
 * This component owns no geometry/window logic — it only renders the panel
 * chrome and reveal animation via `[data-zone]`/`.open` clip-path classes
 * (see `.compact-panel` in index.css). The vertical zone (top/bottom) and
 * window sizing come from `lib/compactPanel.ts` and are wired in by the
 * caller (Task 2.2), not computed here.
 *
 * GATE-1/3 resolved (see scratchpad brief): gap is fixed at 0 (fused
 * border), the header is always shown regardless of target, and there is no
 * `onOpenFull` escape hatch — full controls live inside `children`.
 *
 * Task 2.2 (GATE-B=A, bar-as-header): the tab-strip paradigm (one icon per
 * NAV_TARGETS in the panel header, swapping `children` in place) is
 * retired — the bar itself (CapsuleMenu / minimal fan) is the only target
 * switcher now. In minimal mode that means switching targets goes through
 * close island -> reopen fan -> pick; this is the accepted cost of GATE-B=A,
 * do not re-add tabs here.
 */
import { MENU_LABELS, CloseIcon, type MenuTarget } from "../PillMenu/icons";
import type { PillCorner } from "../PillOverlay";
import type { PanelExtrudeZone } from "../../lib/compactPanel";
import ErrorBoundary from "../ErrorBoundary";

interface CompactShellProps {
  target: Exclude<MenuTarget, "hide">;
  corner: PillCorner;
  zone: PanelExtrudeZone;
  /** = panelReady — drives the clip-path reveal via the `.open` class. */
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Capsule mode has no ✕ — clicking the bar/off-panel closes it (same as
   *  before). Minimal mode's island has no bar to click off of, so it keeps
   *  the ✕. */
  showClose: boolean;
  /** Task 2.4 (B3/B5): per-target icon-only controls (Vault's open-folder/
   *  refresh/new-folder, Inbox's Inbox/Reminders toggle + refresh) rendered
   *  right-aligned in the header, immediately before the close button —
   *  lets those panels drop their own duplicate header row entirely. */
  headerActions?: React.ReactNode;
  /** C2: forwarded to the body's ErrorBoundary so a render throw inside a
   *  panel can tint the pill (App owns the transient `.pill-error` flag) in
   *  addition to this shell auto-collapsing via `onClose`. */
  onPanelError?: (error: unknown) => void;
}

export default function CompactShell({ target, corner, zone, open, onClose, children, showClose, headerActions, onPanelError }: CompactShellProps) {
  return (
    <div
      className={`compact-panel${open ? " open" : ""}`}
      data-zone={zone}
      data-corner={corner}
      // RC-1: the pill window's outer wrapper closes the panel on any click
      // (dead-space click-to-close). Panel-interior clicks must never reach
      // it — one choke point here covers header, headerActions, and body.
      onClick={(e) => e.stopPropagation()}
    >
      <div className="compact-panel-header">
        <span className="compact-panel-title">{MENU_LABELS[target]}</span>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-1)", flex: "0 0 auto" }}>
          {headerActions}
          {showClose && (
            <button
              type="button"
              className="compact-panel-close"
              onClick={onClose}
              aria-label="Close"
            >
              <CloseIcon />
            </button>
          )}
        </div>
      </div>
      <div className="compact-panel-body">
        {/* C2: any render throw inside a compact panel auto-collapses back
            to the pill (user decision) instead of permanently blanking the
            grown window. Keyed by target so switching panels always mounts
            a fresh boundary. */}
        <ErrorBoundary key={target} onError={(e) => { onPanelError?.(e); onClose(); }}>
          {children}
        </ErrorBoundary>
      </div>
    </div>
  );
}
