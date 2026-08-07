/**
 * syncPendingView.ts — pure decision layer over GET /sync/pending's payload
 * (see lib/api.ts's SyncPendingResponse, mirrored from sync_pending.py).
 *
 * This is the one place the SYNC tab's Pending panel decides WHICH of its
 * four render states applies. Centralizing it here (instead of branching
 * inline in the component) is what makes the binding copy rules structurally
 * checkable instead of "reviewer has to eyeball the JSX":
 *
 *   - blocked  -> label + error, NEVER a number (s143: "the refusal state
 *     never shows a count" — there is no changed/unknown field on this
 *     branch of SyncPendingResponse to read one from).
 *   - resting  -> the local diff, label always "Changed since last sync"
 *     (rendered from the server's own `label`, never hardcoded past it).
 *     `changed` and `unknown` stay two separate numbers, never summed.
 *   - hub / hub-offline / hub-not-synced -> only ever reachable when the
 *     caller actually fetched `hub=true`; this module never fetches
 *     anything, it only shapes whatever payload it's handed.
 */
import type { SyncPendingResponse } from "./api";

export type PendingView =
  | { kind: "blocked"; label: string; error: string }
  | {
      kind: "resting";
      label: string;
      changed: number;
      unknown: number;
      deletesPending: number;
      truncated: boolean;
    }
  | { kind: "hub"; willUpload: number; blocked: number; toPull: number }
  | { kind: "hub-offline"; error?: string }
  | { kind: "hub-not-synced" };

export function resolvePendingView(data: SyncPendingResponse): PendingView {
  if (data.status === "blocked") {
    return { kind: "blocked", label: data.label, error: data.error };
  }
  const hub = data.hub;
  if (hub && hub.status === "ok") {
    return {
      kind: "hub",
      willUpload: hub.counts.will_upload,
      blocked: hub.counts.blocked,
      toPull: hub.counts.to_pull,
    };
  }
  if (hub && hub.status === "offline") {
    return { kind: "hub-offline", error: hub.error };
  }
  if (hub && hub.status === "not_synced") {
    return { kind: "hub-not-synced" };
  }
  return {
    kind: "resting",
    label: data.label,
    changed: data.changed,
    unknown: data.unknown,
    deletesPending: data.deletes_pending,
    truncated: data.truncated,
  };
}
