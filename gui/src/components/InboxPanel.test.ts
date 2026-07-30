import { describe, expect, it } from "vitest";
import { filingCategories } from "./InboxPanel";

// s114 / flow-review d07 (P0). The Inbox's folder dropdown defaulted to `_scratchpad` on every
// item — `list_scratchpad` reports each item's category as its PARENT FOLDER, which is always the
// scratchpad, and `/vault/categories` deliberately returns `_scratchpad` because the Library lists
// it. Approving then "moved" the note into the folder it already sat in: status stripped, file
// renamed, item back in the list on the next refresh, forever, behind a success transition.
//
// The server rejects the scratchpad as a destination (approve_scratchpad_item), which is the root
// fix. This is the other half: the bad destination never appears in the menu, so the rejection is
// unreachable by an ordinary click rather than merely survivable.

describe("filingCategories", () => {
  it("drops the scratchpad — the destination that caused the dead loop", () => {
    expect(filingCategories(["_scratchpad", "personal", "work"])).toEqual(["personal", "work"]);
  });

  it("drops every machine folder, not just the scratchpad", () => {
    // These all come back from /vault/categories for the Library's benefit; none is a place a
    // reviewed capture belongs.
    expect(
      filingCategories(["_trash", "_attachments", "_mobile_inbox", "_templates", "recipes"]),
    ).toEqual(["recipes"]);
  });

  it("drops dot-folders", () => {
    expect(filingCategories([".omni_capture", ".sync", "work"])).toEqual(["work"]);
  });

  it("keeps ordinary folders untouched and in order", () => {
    const real = ["personal", "recipes", "work"];
    expect(filingCategories(real)).toEqual(real);
  });

  it("returns empty rather than inventing a destination for a vault with no real folders", () => {
    // The row's Approve stays disabled in this state — the correct outcome. Previously
    // `categories[0]` would have picked `_scratchpad` here and produced the loop.
    expect(filingCategories(["_scratchpad", "_trash"])).toEqual([]);
  });

  it("does not treat an internal underscore as a machine folder", () => {
    expect(filingCategories(["my_notes", "read_later"])).toEqual(["my_notes", "read_later"]);
  });
});
