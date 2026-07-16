import { describe, expect, it } from "vitest";
import { diffLines } from "./lineDiff";

describe("diffLines", () => {
  it("returns all-same rows for identical text", () => {
    const rows = diffLines("a\nb\nc", "a\nb\nc");
    expect(rows.every((r) => r.kind === "same")).toBe(true);
    expect(rows.map((r) => r.local)).toEqual(["a", "b", "c"]);
  });

  it("marks local-only additions with a blank on the remote side", () => {
    const rows = diffLines("a\nb\nlocal-add\nc", "a\nb\nc");
    const added = rows.find((r) => r.local === "local-add");
    expect(added).toBeDefined();
    expect(added!.kind).toBe("local-only");
    expect(added!.remote).toBeNull();
  });

  it("marks remote-only additions with a blank on the local side", () => {
    const rows = diffLines("a\nb\nc", "a\nb\nremote-add\nc");
    const added = rows.find((r) => r.remote === "remote-add");
    expect(added).toBeDefined();
    expect(added!.kind).toBe("remote-only");
    expect(added!.local).toBeNull();
  });

  it("handles the conflict-resolver mock's divergent-tail case", () => {
    const local = "# title\n\n- shared line\n- local extra\n- run against 500-note vault";
    const remote = "# title\n\n- shared line\n- remote extra\n- run against 500-note vault";
    const rows = diffLines(local, remote);
    const kinds = rows.map((r) => r.kind);
    expect(kinds).toContain("local-only");
    expect(kinds).toContain("remote-only");
    // shared head and tail lines still align as "same"
    expect(rows[0]).toEqual({ kind: "same", local: "# title", remote: "# title" });
    expect(rows[rows.length - 1].kind).toBe("same");
  });

  it("handles empty strings without throwing", () => {
    expect(diffLines("", "")).toEqual([{ kind: "same", local: "", remote: "" }]);
  });
});
