/**
 * templateNote.ts
 * ----------------
 * "Set as template" (P3-B editor 3-dot menu). There is no vault-side or
 * server-side template concept anywhere in this codebase today — no
 * `omni_capture/` endpoint, no frontmatter field, nothing (verified at
 * source: no hit for the word "template" outside comments/unrelated
 * substrings in either `gui/src` or `omni_capture/`). This agent's brief is
 * scoped to `gui/` only, so a real vault-side template feature is out of
 * reach here.
 *
 * ponytail: gui-local only (localStorage), one template slot, no consumer.
 * Marking a note "as template" here only remembers its path client-side —
 * nothing in this phase's scope creates a new note FROM it (the mock's own
 * "from template" affordance is the phone's swipe-up gesture, P4-B, not
 * this task). Real ceiling: this is a placeholder for a genuine vault-side
 * template (e.g. a frontmatter flag + a "new from template" capture path)
 * that a future phase with `omni_capture/` in scope should build for real;
 * upgrade path is deleting this module once that lands.
 */

const KEY = "second-thought:template-note-path";

export function getTemplateNotePath(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setTemplateNotePath(path: string): void {
  try {
    localStorage.setItem(KEY, path);
  } catch {
    // localStorage unavailable (e.g. private/blocked) -- silently a no-op,
    // matching every other best-effort localStorage write in this repo.
  }
}

export function isTemplateNote(path: string): boolean {
  return getTemplateNotePath() === path;
}
