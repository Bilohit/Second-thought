// FR-23 Option C: the folder-structure import's pure selection state.
//
// The import is the one surface in this product that writes into a note body outside the
// editor, so every rule about what CAN be submitted lives here, in pure functions with a
// sibling test -- not inside the component. `VaultManager` renders these rows and posts
// `selection(rows)`; it never decides eligibility itself.
//
// The naming rule is the server's, mirrored: a project name is simultaneously a tag token,
// a TOML key and a directory name (`projects.py:32`). `isValidProjectName` is the existing
// mirror of that regex and is reused rather than re-expressed here.
import { isValidProjectName } from "./projectsView";
import type { FolderImportCandidate } from "./api";

export interface ImportRow {
  folder: string;
  /** The name that will be written as `#project@<name>`. Starts as the server's suggestion:
   *  the folder's own name when it is already usable, the sanitised form when it is not,
   *  and "" when nothing usable survives -- a blank field the user fills, never a guess. */
  name: string;
  checked: boolean;
  valid: boolean;
  existing: boolean;
  count: number;
  /** Disclosure only -- the row reads "includes N notes written on your phone". Never
   *  filters, skips or gates anything (DECISIONS §5 s140). */
  phoneCount: number;
}

/** A folder whose name is already usable starts ticked; an ineligible one starts unticked
 *  with its suggestion prefilled, so nothing is ever applied that the user has not seen. */
export function rowsFrom(candidates: FolderImportCandidate[]): ImportRow[] {
  return candidates.map((c) => ({
    folder: c.folder,
    name: c.suggested,
    checked: c.valid,
    valid: isValidProjectName(c.suggested),
    existing: c.existing,
    count: c.count,
    phoneCount: c.phone_count,
  }));
}

/** Re-validates on every keystroke and unticks a row whose name stops being usable --
 *  otherwise a user could tick a valid name, edit it to something invalid, and submit a
 *  selection the server would reject with the folder silently doing nothing. */
export function rename(rows: ImportRow[], folder: string, name: string): ImportRow[] {
  return rows.map((r) => {
    if (r.folder !== folder) return r;
    const valid = isValidProjectName(name);
    return { ...r, name, valid, checked: r.checked && valid };
  });
}

/** Ticking is refused outright while the name is unusable. The checkbox is the consent,
 *  so it must never be possible to give consent for something that cannot be written. */
export function toggle(rows: ImportRow[], folder: string): ImportRow[] {
  return rows.map((r) =>
    r.folder === folder && (r.checked || r.valid) ? { ...r, checked: !r.checked } : r,
  );
}

export function selection(rows: ImportRow[]): { folder: string; name: string }[] {
  return rows.filter((r) => r.checked && r.valid).map((r) => ({ folder: r.folder, name: r.name }));
}

/** The number the confirm button states ("Add tags to N notes"). Counts only what will
 *  actually be written, so the button can never overstate the blast radius. */
export function selectedNoteCount(rows: ImportRow[]): number {
  return rows.reduce((n, r) => (r.checked && r.valid ? n + r.count : n), 0);
}
