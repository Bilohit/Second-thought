import { describe, expect, it } from "vitest";
import { initialPadState, reduce } from "./quickPad";

describe("quickPad", () => {
  it("starts empty with no note and writes nothing", () => {
    const s = initialPadState(null);
    expect(s.noteId).toBeNull();
    expect(s.dirty).toBe(false);
  });

  it("does not create a note when the pad merely opens", () => {
    const created: string[] = [];
    reduce(initialPadState(null), { type: "open" }, { create: (t) => { created.push(t); return "x"; } });
    expect(created).toEqual([]);
  });

  it("creates exactly one note on the first keystroke, not on the second", () => {
    const created: string[] = [];
    const deps = { create: (t: string) => { created.push(t); return "note-1"; } };
    let s = reduce(initialPadState(null), { type: "type", text: "r" }, deps);
    s = reduce(s, { type: "type", text: "ri" }, deps);
    s = reduce(s, { type: "type", text: "rin" }, deps);
    expect(created).toHaveLength(1);
    expect(s.noteId).toBe("note-1");
  });

  it("reopens to the last note made", () => {
    const s = initialPadState("note-7");
    expect(s.noteId).toBe("note-7");
  });

  it("plus clears the pad and arms a fresh create", () => {
    let s = { ...initialPadState("note-7"), text: "old", dirty: true };
    s = reduce(s, { type: "new" }, { create: () => "unused" });
    expect(s.text).toBe("");
    expect(s.noteId).toBeNull();
  });

  it("discarding an untouched pad deletes nothing", () => {
    const deleted: string[] = [];
    reduce(initialPadState(null), { type: "discard" }, { del: (id: string) => { deleted.push(id); } });
    expect(deleted).toEqual([]);
  });

  it("discarding a written pad deletes exactly that note", () => {
    const deleted: string[] = [];
    const s = { ...initialPadState("note-3"), text: "x", dirty: true };
    reduce(s, { type: "discard" }, { del: (id: string) => { deleted.push(id); } });
    expect(deleted).toEqual(["note-3"]);
  });
});
