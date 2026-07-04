/**
 * icons.tsx
 * ---------
 * Shared icon set for the pill menus — exact paths reused from
 * CaptureOverlay.tsx's header row so the menu items look identical to the
 * full-window equivalents. `hide` is the chevron-into-tray glyph from the
 * "Collapse" button, repurposed here as the menu's "send to tray" action.
 */
import type { JSX } from "react";

export type MenuTarget = "search" | "vault" | "settings" | "inbox" | "stats" | "hide";

export const MENU_LABELS: Record<MenuTarget, string> = {
  search: "Look",
  vault: "Vault",
  settings: "Settings",
  inbox: "Inbox",
  stats: "History",
  hide: "Hide",
};

export const NAV_TARGETS: Exclude<MenuTarget, "hide">[] = ["search", "vault", "settings", "inbox", "stats"];
export const ALL_TARGETS: MenuTarget[] = [...NAV_TARGETS, "hide"];

export function MenuIcon({ target, size = 16 }: { target: MenuTarget; size?: number }): JSX.Element {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (target) {
    case "search":
      return (
        <svg {...common}>
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      );
    case "vault":
      return (
        <svg {...common}>
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "settings":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v2m0 16v2M4.22 4.22l1.42 1.42m12.72 12.72 1.42 1.42M2 12h2m16 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
      );
    case "inbox":
      return (
        <svg {...common}>
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
        </svg>
      );
    case "stats":
      return (
        <svg {...common}>
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      );
    case "hide":
      return (
        <svg {...common}>
          <path d="M12 4v9" />
          <path d="M8 10l4 4 4-4" />
          <path d="M4 18h16" />
        </svg>
      );
  }
}

/** Mic glyph shared by the capture panel's record button and the minimal
 *  pill's recording state (steady icon — the flashing dot read as an error). */
export function MicIcon({ size }: { size: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}
