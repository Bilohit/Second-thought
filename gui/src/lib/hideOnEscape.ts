/**
 * hideOnEscape.ts
 * ----------------
 * Pure decision for App.tsx's global Escape handler: whether THIS Escape
 * press should hide the pill window, as opposed to unwinding some other
 * open layer first.
 *
 * Escape unwinds one layer at a time — an open compact panel closes first,
 * an open menu closes next, and only once both are already closed (the
 * "bare pill" state) does Escape hide the window. Full window never hides
 * on Escape; it has its own per-surface Escape handling (NoteEditor,
 * LookPanel, InboxPanel, SettingsPanel, ProjectsRail/Pane) and FR-09 is an
 * open finding there — this predicate deliberately does not touch it.
 */

export type EscapeContext = {
  displayMode: "minimal" | "capsule" | "full";
  menuOpen: boolean;
  compactPanel: string | null;
};

export function shouldHideOnEscape(ctx: EscapeContext): boolean {
  return ctx.displayMode !== "full" && !ctx.menuOpen && ctx.compactPanel === null;
}
