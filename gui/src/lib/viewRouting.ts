/**
 * viewRouting.ts
 * --------------
 * Pure alias table mapping the pill-menu's legacy `View` names (App.tsx) to
 * FullWindow's rail destinations. Extracted out of App.tsx so this specific
 * table -- the exact site of FR-07 -- has a runnable regression check
 * independent of the full App.tsx render tree.
 *
 * FR-07: `stats` used to alias onto `library`, the same destination as
 * `vault`. That was harmless while LibraryView still held the "By project" /
 * "Daily rhythm" stats panels, but s130 removed them from LibraryView (they
 * now live only in HistoryView / CompactHistory), so firing the menu's
 * "History" item landed on a screen with no history content at all. `stats`
 * now maps to its own `history` destination.
 */

export type LegacyView = "capture" | "settings" | "vault" | "inbox" | "stats" | "look" | "today" | "note";

export type RailDestination = "dashboard" | "today" | "look" | "library" | "history" | "settings" | "inbox";

export const VIEW_TO_RAIL: Record<LegacyView, RailDestination> = {
  capture: "dashboard",
  look: "look",
  vault: "library",
  settings: "settings",
  inbox: "inbox",
  stats: "history",
  today: "today",
  // ponytail: placeholder destination — FullWindow has no "note" RailView yet
  // (Task 8 adds it). handleMenuSelect's "newnote" branch sets view="note"
  // regardless; until Task 8 lands, full window falls back to Dashboard.
  note: "dashboard",
};

export function railDestinationFor(view: LegacyView): RailDestination {
  return VIEW_TO_RAIL[view];
}
