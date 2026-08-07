import { describe, it, expect } from "vitest";
import { resolvePendingView } from "./syncPendingView";
import type { SyncPendingResponse } from "./api";

describe("resolvePendingView", () => {
  it("the refusal state never carries a count (s143)", () => {
    const blocked: SyncPendingResponse = {
      status: "blocked",
      reason: "ignore_set_unreadable",
      error: "boom",
      label: "Sync blocked — ignore list unreadable",
    };
    const view = resolvePendingView(blocked);
    expect(view).toEqual({ kind: "blocked", label: blocked.label, error: "boom" });
  });

  it("resting (hub: null) reports changed/unknown as separate numbers, never summed", () => {
    const resting: SyncPendingResponse = {
      status: "ok",
      label: "Changed since last sync",
      changed: 3,
      unknown: 2,
      deletes_pending: 1,
      items: [],
      truncated: false,
      sidecar_present: true,
      sidecar_rows: 10,
      scope: { notes_scanned: 20, captures_counted: false, mirror_captures_enabled: false, attachments_counted: false },
      hub: null,
    };
    const view = resolvePendingView(resting);
    expect(view).toEqual({
      kind: "resting",
      label: "Changed since last sync",
      changed: 3,
      unknown: 2,
      deletesPending: 1,
      truncated: false,
    });
  });

  it("hub status ok maps counts.* to the exact matching bucket, not swapped", () => {
    const withHub: SyncPendingResponse = {
      status: "ok",
      label: "Changed since last sync",
      changed: 0,
      unknown: 0,
      deletes_pending: 0,
      items: [],
      truncated: false,
      sidecar_present: true,
      sidecar_rows: 0,
      scope: { notes_scanned: 0, captures_counted: false, mirror_captures_enabled: false, attachments_counted: false },
      hub: {
        status: "ok",
        will_upload: [{ id: "a" }],
        blocked: [{ id: "b" }, { id: "c" }],
        to_pull: [],
        counts: { will_upload: 1, blocked: 2, to_pull: 0 },
      },
    };
    const view = resolvePendingView(withHub);
    expect(view).toEqual({ kind: "hub", willUpload: 1, blocked: 2, toPull: 0 });
  });

  it("hub offline / not_synced surface as their own kinds, not folded into resting", () => {
    const base = {
      status: "ok" as const,
      label: "Changed since last sync",
      changed: 0,
      unknown: 0,
      deletes_pending: 0,
      items: [],
      truncated: false,
      sidecar_present: true,
      sidecar_rows: 0,
      scope: { notes_scanned: 0, captures_counted: false, mirror_captures_enabled: false, attachments_counted: false },
    };
    expect(resolvePendingView({ ...base, hub: { status: "offline", error: "no creds" } }))
      .toEqual({ kind: "hub-offline", error: "no creds" });
    expect(resolvePendingView({ ...base, hub: { status: "not_synced" } }))
      .toEqual({ kind: "hub-not-synced" });
  });
});
