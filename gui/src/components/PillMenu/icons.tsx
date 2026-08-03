/**
 * icons.tsx
 * ---------
 * Shared icon set for the pill menus — exact paths reused from
 * CaptureOverlay.tsx's header row so the menu items look identical to the
 * full-window equivalents.
 */
import type { JSX } from "react";

export type MenuTarget = "search" | "vault" | "settings" | "inbox" | "stats" | "newnote";

export const MENU_LABELS: Record<MenuTarget, string> = {
  search: "Look",
  vault: "Vault",
  settings: "Settings",
  inbox: "Inbox",
  stats: "History",
  newnote: "New Note",
};

export const ALL_TARGETS: MenuTarget[] = ["search", "vault", "settings", "inbox", "stats", "newnote"];

export function MenuIcon({ target, size = 16 }: { target: MenuTarget; size?: number }): JSX.Element {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (target) {
    case "search":
      // Eye — the "Look" menu glyph (looking over the vault). Distinct from the
      // magnifier `SearchIcon`, which is reserved for the in-panel Search/Chat
      // toggle button so the two read distinctly.
      return (
        <svg {...common}>
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
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
    case "newnote":
      // Reuse PlusIcon's glyph rather than drawing a new path — see the
      // repo's icon rule (never a one-off SVG when an export exists).
      return <PlusIcon size={size} />;
  }
}

/** Mic glyph shared by the capture panel's record button and the minimal
 *  pill's recording state (steady icon — the flashing dot read as an error). */
export function MicIcon({ size }: { size: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

/** Play triangle — AudioPlayer's play affordance (O-9 voice-attachment player). */
export function PlayIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="6 3 21 12 6 21 6 3" />
    </svg>
  );
}

/** Pause bars — AudioPlayer's pause affordance (O-9 voice-attachment player). */
export function PauseIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </svg>
  );
}

/** Circular "turning arrow" refresh/sync glyph — shared by every vault-index
 *  refresh control (was duplicated inline in LookPanel.tsx). */
export function RefreshIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  );
}

/** Magnifier glyph — Look panel's "Search" mode in the segmented icon toggle
 *  (paired with ChatIcon for "Chat"). Distinct from the Look *menu* icon,
 *  which is binoculars (MenuIcon target="search"). */
export function SearchIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

/** Bell glyph — the Inbox panel's "Reminders" mode in the segmented icon toggle
 *  (paired with MenuIcon target="inbox" for the "Review" tab). */
export function BellIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.268 21a2 2 0 0 0 3.464 0" />
      <path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326" />
    </svg>
  );
}

/** Chat bubble glyph — Look panel's "Chat" mode in the segmented icon toggle
 *  (paired with SearchIcon for "Search"). */
export function ChatIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}

/** Up-arrow send glyph — compact chat composer's icon send button
 *  (LookPanel.tsx, compact branch). */
export function SendIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </svg>
  );
}

/** Floppy-disk glyph — explicit-commit save button (SettingsPanel's Look
 *  chat system prompt field, the one field that doesn't auto-save). */
export function SaveIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" />
      <path d="M17 21v-8H7v8" />
      <path d="M7 3v5h8" />
    </svg>
  );
}

/** Clock glyph — "staged, unconfirmed" state marker (VaultManager's staged
 *  file rows). Was a one-off inline SVG; hoisted here per the shared icon
 *  module convention. */
export function ClockIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15.5 14" />
    </svg>
  );
}

// ── Sync tab (E6) ───────────────────────────────────────────────────────────
// Added here rather than inline per the shared-icon-module convention. Nothing
// in the existing set fits: RefreshIcon is the vault-index/rotate glyph and is
// reused as-is for "Sync now" and "Rotate secret", but the Sync tab also needs
// a disclosure chevron, the two ladder node states, and one glyph per plane.

/** Disclosure chevron — rung heads and history expanders. Rotates 90deg when open. */
export function ChevronRightIcon({ size = 12 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

/** Horizontal mirror of ChevronRightIcon — the Projects pager's "previous
 *  page" stepper (SP3 Task 9, spec §5.5.1/board's Option C). Added here per
 *  this repo's icon rule rather than pasted inline into ProjectsPane.tsx. */
export function ChevronLeftIcon({ size = 12 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 6l-6 6 6 6" />
    </svg>
  );
}

/** Check glyph — a ladder node that is genuinely done (never drawn for an unknown state). */
export function CheckIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="4 12 9 17 20 6" />
    </svg>
  );
}

/* s114/d07 — capture-kind glyphs for the Inbox review row. The row leads with WHAT a capture is
 * ("clipboard", "link · en.wikipedia.org", "voice · 0:38") instead of a generated filename that
 * tells the user nothing. Exported here, never inlined at the call site, per the repo's icon rule.
 * Voice reuses MicIcon and image reuses ImageIcon below; only these two are new. */

/** Clipboard glyph — a plain text capture (the desktop's default capture route). */
export function ClipboardIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="8" y="3" width="8" height="4" />
      <path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" />
    </svg>
  );
}

/** Copy-to-clipboard action glyph (two overlapping sheets) — distinct from
 *  ClipboardIcon above, which is a clipboard-with-clip OBJECT used to label
 *  a capture's clipboard SOURCE TYPE, not an action. */
export function CopyIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="1" />
      <path d="M5 15V5a1 1 0 0 1 1-1h10" />
    </svg>
  );
}

/** Link glyph — a URL capture. */
export function LinkIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
    </svg>
  );
}

/** Image glyph — a photo/screenshot capture. */
export function ImageIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" />
      <circle cx="9" cy="10" r="2" />
      <path d="M21 16l-5-5-6 6" />
    </svg>
  );
}

/** Trash glyph — the Inbox row's Discard action (icon-only square button). */
export function TrashIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4h6v2" />
    </svg>
  );
}

/** Alert glyph — a failed pass, a missing client_secret.json, a stopped scheduler. */
export function AlertIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5" />
      <path d="M12 16.5v.01" />
    </svg>
  );
}

/** Warning-triangle glyph — Task 2.6 name-clash badge (distinct from AlertIcon's
 *  circle, which is already used elsewhere for failed-pass/stopped-scheduler
 *  states). aria-hidden here; callers needing an accessible name (the clash
 *  badge does) pass their own aria-label on the wrapping element. */
export function WarningTriangleIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

/** Cloud glyph — Google Drive, the canonical sync plane. */
export function CloudIcon({ size = 16 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.5 19H7a5 5 0 0 1-.6-9.96A6.5 6.5 0 0 1 18.9 8.4 4.3 4.3 0 0 1 17.5 19Z" />
    </svg>
  );
}

/** X / close glyph — dismiss buttons (toasts, reminder rows, panel headers). */
export function CloseIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 6 6 18" />
      <path d="M6 6l12 12" />
    </svg>
  );
}

/** Grid/panes glyph — FullWindow's Dashboard rail button (sits beside
 *  MenuIcon target="search"/"vault" at 18px). */
export function DashboardIcon({ size = 18 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="8" height="8" rx="1" />
      <rect x="13" y="3" width="8" height="8" rx="1" />
      <rect x="3" y="13" width="8" height="8" rx="1" />
      <rect x="13" y="13" width="8" height="8" rx="1" />
    </svg>
  );
}

/** Padlock glyph — the custom-theme editor's LOCKED rows (state colors,
 *  radius/font/motion identity) that stay non-editable by design. */
export function LockIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="9" rx="1" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

/** Plus glyph — the "Custom" swatch's add affordance in the theme picker. */
export function PlusIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

/** Bold-B format glyph — shared by NoteEditor's format toolbar and the
 *  compact quick pad's two-action format row (Task 11: promoted here after
 *  the two components carried byte-divergent local copies — CompactQuickNote's
 *  had `aria-hidden="true"`, NoteEditor's didn't; this export keeps that
 *  attribute, matching every other glyph in this module). */
export function BoldIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 5v14M8 5h3a3 3 0 010 6H8M8 12h4a3.5 3.5 0 010 7H8" />
    </svg>
  );
}

/** Checklist glyph — shared by NoteEditor's format toolbar and the compact
 *  quick pad's format row (Task 11: promoted here for the same reason as
 *  `BoldIcon` above). */
export function ChecklistIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} aria-hidden="true">
      <rect x="3" y="9" width="6" height="6" rx="1" />
      <path d="M4.5 12l1.3 1.3L8 10.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 10.5h9M12 14.5h9" strokeLinecap="round" />
    </svg>
  );
}

/** Pin glyph — the compact quick pad's always-on-top toggle. Not duplicated
 *  elsewhere today; promoted here anyway per the repo's icon rule (every
 *  user-facing icon is an export of this module, never a component-local
 *  one-off). */
export function PinIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 2v7" />
      <path d="M7 9h10l1.5 5H5.5z" />
      <path d="M12 14v8" />
    </svg>
  );
}

/** Three-line list glyph — sub-project 3's rail toggle "Tags" position
 *  (paired with DashboardIcon's tile glyph for "Projects"). */
export function ListIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
    </svg>
  );
}

/** Pencil glyph — rename affordances (sub-project 3's Inbox-suggestion
 *  Rename button). */
export function PencilIcon({ size = 14 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

// ── Sub-project 3 Task 5: the projects pane's note rows + sort instrument.
// Board (mock 2026-08-01-projects-fullwindow-v3.html) draws these inline;
// hoisted here per the repo's icon rule (never a one-off inline SVG when an
// export exists). Paths transcribed 1:1 from the board's `I` icon map.

/** File-with-folded-corner glyph — a note row's leading icon. */
export function FileIcon({ size = 12 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
      <polyline points="14 3 14 7 18 7" />
    </svg>
  );
}

/** Descending stack with a down-arrow — the "newest first" sort arrangement.
 *  One of three DISTINCT silhouettes (spec §4.5): not one glyph rotated. */
export function SortNewestIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 4v15" />
      <path d="M3 16l3 3 3-3" />
      <line x1="12" y1="6" x2="21" y2="6" />
      <line x1="12" y1="12" x2="18" y2="12" />
      <line x1="12" y1="18" x2="15" y2="18" />
    </svg>
  );
}

/** Hourglass-with-bars silhouette — the "oldest first" sort arrangement. */
export function SortOldestIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 3h12" />
      <path d="M6 21h12" />
      <path d="M7 3v3.2a3 3 0 0 0 1.1 2.3L12 12l-3.9 3.5A3 3 0 0 0 7 17.8V21" />
      <path d="M17 3v3.2a3 3 0 0 1-1.1 2.3L12 12l3.9 3.5a3 3 0 0 1 1.1 2.3V21" />
    </svg>
  );
}

/** Pencil-on-a-line silhouette — the "recently edited" sort arrangement. */
export function SortEditedIcon({ size = 13 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 20h18" />
      <path d="M5 16.4V13l8.2-8.2a1.8 1.8 0 0 1 2.6 0l1.4 1.4a1.8 1.8 0 0 1 0 2.6L9 17H5.6a.6.6 0 0 1-.6-.6z" />
    </svg>
  );
}

/** Two-headed cycle-arrow glyph — the sort button's "click to change"
 *  acknowledgement mark. Distinct from `RefreshIcon` (single-headed,
 *  reserved for vault-index refresh actions). */
export function CycleIcon({ size = 11 }: { size?: number }): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 10a8 8 0 0 1 13.3-3.3L20 9" />
      <polyline points="20 4 20 9 15 9" />
      <path d="M20 14a8 8 0 0 1-13.3 3.3L4 15" />
      <polyline points="4 20 4 15 9 15" />
    </svg>
  );
}
