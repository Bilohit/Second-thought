import { describe, expect, it } from "vitest";
import { summarizeLastPass } from "./SyncDashboard";
import type { SyncPassRow } from "../../lib/api";

// ISS-013: the Sync tab never rendered "last synced at" / item counts even though
// the server has always returned them (sync_scheduler.py status()'s last_pass).
// These pin the pure formatter so the rendered line stays a function of real
// SyncPassRow fields, never invented ones.

function row(overrides: Partial<SyncPassRow>): SyncPassRow {
  return {
    started: "2026-07-22T14:30:00",
    finished: "2026-07-22T14:32:00",
    duration_s: 120,
    ok: true,
    ...overrides,
  };
}

describe("summarizeLastPass", () => {
  it("returns null when no pass has ever run", () => {
    expect(summarizeLastPass(null)).toBeNull();
  });

  it("renders the finished time and the sum of the real item counts", () => {
    const line = summarizeLastPass(row({ uploaded: 2, pulled: 3, reconciled: 1, inbox_ingested: 0 }));
    expect(line).toContain("6 items");
    expect(line).toMatch(/^Last sync: \d{1,2}:\d{2}/);
  });

  it("singularizes a count of exactly one item", () => {
    const line = summarizeLastPass(row({ uploaded: 1 }));
    expect(line).toContain("1 item");
    expect(line).not.toContain("1 items");
  });

  it("shows 0 items rather than inventing a count for a failed pass with no summary merged in", () => {
    const line = summarizeLastPass(row({ ok: false, error: "quota exceeded" }));
    expect(line).toContain("0 items");
  });

  it("surfaces conflicts and errors only when present, never as a bare 0", () => {
    const clean = summarizeLastPass(row({ uploaded: 1, conflicts: 0, errors: 0 }));
    expect(clean).not.toMatch(/conflict|error/);

    const dirty = summarizeLastPass(row({ uploaded: 1, conflicts: 2, errors: 1 }));
    expect(dirty).toContain("2 conflicts");
    expect(dirty).toContain("1 error");
  });

  it("falls back to a label without a clock reading when `finished` does not parse", () => {
    const line = summarizeLastPass(row({ finished: "not-a-date" }));
    expect(line).toMatch(/^Last sync ·/);
  });
});
