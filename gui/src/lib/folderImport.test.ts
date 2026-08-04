import { describe, expect, it } from "vitest";
import { rename, rowsFrom, selection, selectedNoteCount, toggle } from "./folderImport";
import type { FolderImportCandidate } from "./api";

const CANDS: FolderImportCandidate[] = [
  { folder: "Work", suggested: "Work", valid: true, existing: false, count: 12, phone_count: 3 },
  { folder: "My Notes", suggested: "My-Notes", valid: false, existing: false, count: 4, phone_count: 0 },
];

describe("folderImport rows", () => {
  it("checks usable folders by default and leaves ineligible ones unchecked", () => {
    const rows = rowsFrom(CANDS);
    expect(rows.map((r) => r.checked)).toEqual([true, false]);
    // the sanitised name is a PREFILL the user can see and edit, never an applied rename
    expect(rows[1].name).toBe("My-Notes");
    expect(rows[1].valid).toBe(true);
  });

  it("carries the phone-authored count through for disclosure without filtering", () => {
    const rows = rowsFrom(CANDS);
    expect(rows[0].phoneCount).toBe(3);
    // all 12 notes are still selected -- phone_count discloses, it never subtracts
    expect(selectedNoteCount(rows)).toBe(12);
  });

  it("an ineligible folder becomes selectable only once its name validates", () => {
    let rows = rowsFrom(CANDS);
    rows = rename(rows, "My Notes", "two words");
    expect(rows[1].valid).toBe(false);
    rows = toggle(rows, "My Notes");
    expect(rows[1].checked).toBe(false); // cannot consent to a name that cannot be written
    rows = rename(rows, "My Notes", "My-Notes");
    rows = toggle(rows, "My Notes");
    expect(rows[1].checked).toBe(true);
  });

  it("unticks a ticked row whose name is edited into an invalid one", () => {
    let rows = rowsFrom(CANDS);
    expect(rows[0].checked).toBe(true);
    rows = rename(rows, "Work", "Work Stuff");
    expect(rows[0].checked).toBe(false);
    expect(selection(rows)).toEqual([]);
  });

  it("selection omits unchecked rows and counts only what will be written", () => {
    const rows = rowsFrom(CANDS);
    expect(selection(rows)).toEqual([{ folder: "Work", name: "Work" }]);
    expect(selectedNoteCount(rows)).toBe(12);
  });

  it("an empty suggestion leaves the field blank rather than guessing", () => {
    const rows = rowsFrom([
      { folder: "!!!", suggested: "", valid: false, existing: false, count: 2, phone_count: 0 },
    ]);
    expect(rows[0].name).toBe("");
    expect(rows[0].valid).toBe(false);
    expect(rows[0].checked).toBe(false);
  });
});
