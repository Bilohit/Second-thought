import { describe, it, expect } from "vitest";
import { mergeProvisional, type ProvisionalRow, type CanonicalNoteRow } from "./provisional";

interface Row extends CanonicalNoteRow {
  note_id?: string;
  filename: string;
}

function prov(overrides: Partial<ProvisionalRow> = {}): ProvisionalRow {
  return {
    op_id: "op-1",
    note_id: "note-a",
    body_hash: "hash-1",
    staged_at: 1700000000,
    device: "phone-1",
    modified: "2026-07-11T10:00:00",
    path: "/vault/.sync/provisional/op-1.md",
    ...overrides,
  };
}

describe("mergeProvisional", () => {
  it("flags provisional rows with provisional: true", () => {
    const rows = mergeProvisional<Row>([], [prov()]);
    expect(rows).toHaveLength(1);
    expect(rows[0].provisional).toBe(true);
  });

  it("flags canonical rows with provisional: false", () => {
    const canonical: Row[] = [{ note_id: "note-b", filename: "b.md" }];
    const rows = mergeProvisional(canonical, []);
    expect(rows).toHaveLength(1);
    expect(rows[0].provisional).toBe(false);
  });

  it("hides a provisional row once its note_id appears in canonical (Drive supersedes LAN)", () => {
    const canonical: Row[] = [{ note_id: "note-a", filename: "a.md" }];
    const rows = mergeProvisional(canonical, [prov({ note_id: "note-a" })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].provisional).toBe(false);
  });

  it("keeps a provisional row whose note_id has no canonical counterpart yet", () => {
    const canonical: Row[] = [{ note_id: "note-b", filename: "b.md" }];
    const rows = mergeProvisional(canonical, [prov({ note_id: "note-a" })]);
    expect(rows).toHaveLength(2);
    const provRow = rows.find((r) => r.provisional);
    expect(provRow).toBeDefined();
    expect((provRow as ProvisionalRow & { provisional: true }).note_id).toBe("note-a");
  });

  it("dedupes multiple provisional rows for the same note_id once canonical arrives", () => {
    const canonical: Row[] = [{ note_id: "note-a", filename: "a.md" }];
    const rows = mergeProvisional(canonical, [
      prov({ op_id: "op-1", note_id: "note-a" }),
      prov({ op_id: "op-2", note_id: "note-a" }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].provisional).toBe(false);
  });

  it("canonical rows without a note_id never dedupe a provisional row", () => {
    const canonical: Row[] = [{ filename: "untracked.md" }];
    const rows = mergeProvisional(canonical, [prov({ note_id: "note-a" })]);
    expect(rows).toHaveLength(2);
  });

  it("returns an empty list for empty inputs", () => {
    expect(mergeProvisional<Row>([], [])).toEqual([]);
  });

  it("preserves canonical row fields on the merged output", () => {
    const canonical: Row[] = [{ note_id: "note-b", filename: "b.md" }];
    const rows = mergeProvisional(canonical, []);
    expect(rows[0]).toMatchObject({ note_id: "note-b", filename: "b.md", provisional: false });
  });

  it("preserves provisional row fields on the merged output", () => {
    const rows = mergeProvisional<Row>([], [prov({ device: "phone-2" })]);
    expect(rows[0]).toMatchObject({ device: "phone-2", provisional: true });
  });
});
