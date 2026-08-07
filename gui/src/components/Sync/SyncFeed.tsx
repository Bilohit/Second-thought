/**
 * Sync/SyncFeed.tsx
 * -----------------
 * P3-E: SYNC's real interior below the hub strip (SyncPanel, mounted unmodified
 * by the caller) — Pending · Conflicts · Activity, each fed by its own real
 * endpoint. Full-window only; no compact variant exists because SyncPanel's own
 * `compact` mode (Settings, the pill) never had this interior to begin with.
 *
 * Three independent best-effort reads, not one combined fetch: a failure in one
 * (e.g. captures.db missing) must never blank the other two sections.
 *
 * BINDING COPY RULES (see the P3-E brief; each is load-bearing, not style):
 *   1. Pending is the LOCAL DIFF at rest, labelled from the server's own
 *      `label` field ("Changed since last sync") — never hardcoded past it.
 *   2. "Queue" never appears in any string this file renders.
 *   3. The hub-resolved exact directions (will_upload/blocked/to_pull) only
 *      ever render after `checkAgainstDrive` — one explicit click. `loadPending`
 *      always calls `getSyncPending(false)`; nothing here calls `hub=true` on
 *      mount, on a poll, or automatically after the first load.
 *   4. The blocked branch (`resolvePendingView`'s `kind: "blocked"`) renders the
 *      server's label + error in red and NOTHING numeric — there is no count
 *      field on that branch to accidentally render.
 *   5. `scope.captures_counted` / `scope.attachments_counted` are read live off
 *      the payload and surfaced as a note when false, never silently dropped.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getSyncActivity, getSyncPending, getVaultConflicts,
  type HubPendingItem, type SyncActivityEvent, type SyncPendingResponse, type VaultConflictEntry,
} from "../../lib/api";
import { resolvePendingView } from "../../lib/syncPendingView";
import { formatWhen } from "../../lib/reminderFormat";
import { Group, Note, StatusDot } from "./parts";
import { AlertIcon, RefreshIcon } from "../PillMenu/icons";
import { BTN_SECONDARY } from "../ui/styles";
import { micro, label as fsLabel, body as fsBody, read as fsRead } from "../../lib/type";

// Server-side caps (sync_pending.py MAX_ITEMS=200, sync_activity.py MAX_LIMIT)
// bound what the API can return; this is a SEPARATE, smaller render cap so one
// large diff doesn't turn the panel into an unscrollable wall of rows.
const ITEM_DISPLAY_CAP = 8;
const ACTIVITY_LIMIT = 25;

const REASON_LABEL: Record<string, string> = {
  content_changed: "changed",
  no_sync_record: "no sync record",
  reconcile_owns_no_base_rev: "already on Drive",
  hub_head_advanced: "Drive has a newer version",
  hub_only: "only on Drive",
};

function reasonLabel(reason: string | undefined): string {
  if (!reason) return "";
  return REASON_LABEL[reason] ?? reason;
}

function HubBucket({ title, items, tone }: { title: string; items: HubPendingItem[]; tone: "ok" | "wait" | "fail" }) {
  if (items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: fsLabel, color: "var(--text-2)" }}>
        <StatusDot tone={tone} />
        {title} ({items.length})
      </div>
      {items.slice(0, ITEM_DISPLAY_CAP).map((it) => (
        <div
          key={it.id}
          style={{
            display: "flex", justifyContent: "space-between", gap: 8,
            fontSize: micro, color: "var(--text-3)", padding: "2px 0 2px 12px",
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.path ?? it.id}</span>
          {it.reason && <span style={{ flexShrink: 0 }}>{reasonLabel(it.reason)}</span>}
        </div>
      ))}
      {items.length > ITEM_DISPLAY_CAP && <Note style={{ paddingLeft: 12 }}>+{items.length - ITEM_DISPLAY_CAP} more</Note>}
    </div>
  );
}

function PendingSection() {
  const [data, setData] = useState<SyncPendingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hubLoading, setHubLoading] = useState(false);

  const loadResting = useCallback(async () => {
    setError(null);
    try {
      setData(await getSyncPending(false));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load pending changes");
    }
  }, []);

  useEffect(() => { void loadResting(); }, [loadResting]);

  // The ONE place `hub=true` is ever requested — a direct response to a click,
  // never wired to mount or to any interval/poll.
  const checkAgainstDrive = async () => {
    setHubLoading(true);
    setError(null);
    try {
      setData(await getSyncPending(true));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to check against Drive");
    } finally {
      setHubLoading(false);
    }
  };

  const view = data ? resolvePendingView(data) : null;

  return (
    <Group label="Pending" delay={0}>
      {!data && !error && <Note>Loading…</Note>}
      {error && <Note tone="fail">{error}</Note>}

      {view?.kind === "blocked" && (
        <div style={{
          display: "flex", gap: 8, alignItems: "flex-start",
          border: "1px solid var(--red)", borderRadius: "var(--radius)", padding: 12,
        }}>
          <span aria-hidden="true" style={{ color: "var(--red)", display: "flex", flexShrink: 0, marginTop: 2 }}>
            <AlertIcon size={14} />
          </span>
          <div>
            <div style={{ fontSize: fsRead, fontWeight: 600, color: "var(--red)" }}>{view.label}</div>
            <div style={{ fontSize: fsLabel, color: "var(--text-3)", marginTop: 4 }}>{view.error}</div>
          </div>
        </div>
      )}

      {view?.kind === "resting" && data?.status === "ok" && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: fsRead, color: "var(--text-1)" }}>
            <StatusDot tone={view.changed > 0 || view.unknown > 0 ? "wait" : "ok"} />
            {view.label}
          </div>
          <div style={{ fontSize: fsLabel, color: "var(--text-3)", marginTop: 4 }}>
            {view.changed} changed &middot; {view.unknown} no sync record
            {view.deletesPending > 0 ? ` · ${view.deletesPending} pending delete${view.deletesPending === 1 ? "" : "s"}` : ""}
          </div>
          {view.truncated && <Note style={{ marginTop: 6 }}>More items exist than are listed below.</Note>}

          {data.items.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 8 }}>
              {data.items.slice(0, ITEM_DISPLAY_CAP).map((it) => (
                <div key={it.id} style={{
                  display: "flex", justifyContent: "space-between", gap: 8,
                  fontSize: micro, color: "var(--text-2)", padding: "3px 0",
                  borderBottom: "1px solid var(--border-2)",
                }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.path}</span>
                  <span style={{ color: "var(--text-3)", flexShrink: 0 }}>{reasonLabel(it.reason)}</span>
                </div>
              ))}
              {data.items.length > ITEM_DISPLAY_CAP && <Note>+{data.items.length - ITEM_DISPLAY_CAP} more</Note>}
            </div>
          )}

          {(!data.scope.captures_counted || !data.scope.attachments_counted) && (
            <Note style={{ marginTop: 8 }}>
              {!data.scope.captures_counted && !data.scope.attachments_counted
                ? "Captures and attachments are not counted here."
                : !data.scope.captures_counted ? "Captures are not counted here." : "Attachments are not counted here."}
            </Note>
          )}
        </>
      )}

      {view && view.kind !== "blocked" && (
        <button
          type="button"
          className="btn-hover"
          onClick={() => void checkAgainstDrive()}
          disabled={hubLoading}
          style={{
            ...BTN_SECONDARY, marginTop: 10, alignSelf: "flex-start",
            display: "inline-flex", alignItems: "center", gap: 6,
            cursor: hubLoading ? "not-allowed" : "pointer", opacity: hubLoading ? 0.6 : 1,
          }}
        >
          <span aria-hidden="true" style={{ display: "flex", animation: hubLoading ? "spin 900ms linear infinite" : undefined }}>
            <RefreshIcon size={12} />
          </span>
          {hubLoading ? "Checking…" : view.kind === "resting" ? "Check against Drive" : "Refresh"}
        </button>
      )}

      {view?.kind === "hub" && data?.status === "ok" && data.hub?.status === "ok" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
          <div style={{ fontSize: fsLabel, color: "var(--text-2)" }}>
            {view.willUpload} will upload &middot; {view.blocked} blocked &middot; {view.toPull} to pull
          </div>
          <HubBucket title="Will upload" items={data.hub.will_upload} tone="ok" />
          <HubBucket title="Blocked" items={data.hub.blocked} tone="fail" />
          <HubBucket title="To pull" items={data.hub.to_pull} tone="wait" />
        </div>
      )}
      {view?.kind === "hub-offline" && (
        <Note tone="wait" style={{ marginTop: 8 }}>
          Drive isn&rsquo;t reachable right now{view.error ? `: ${view.error}` : "."}
        </Note>
      )}
      {view?.kind === "hub-not-synced" && (
        <Note style={{ marginTop: 8 }}>The hub folder doesn&rsquo;t exist on Drive yet.</Note>
      )}
    </Group>
  );
}

function ConflictsSection({ onOpenNote }: { onOpenNote: (path: string) => void }) {
  const [conflicts, setConflicts] = useState<VaultConflictEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      setConflicts(await getVaultConflicts());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load conflicts");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <Group label="Conflicts" delay={45}>
      {!loaded && !error && <Note>Loading…</Note>}
      {error && <Note tone="fail">{error}</Note>}
      {loaded && !error && conflicts.length === 0 && <Note>No conflicts.</Note>}
      {conflicts.map((c) => (
        <div
          key={c.conflict_path}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            border: "1px solid var(--red)", borderRadius: "var(--radius-sm)",
            padding: "8px 10px",
          }}
        >
          <StatusDot tone="fail" />
          <span style={{
            flex: 1, minWidth: 0, fontSize: fsBody, color: "var(--text-1)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {c.title}
          </span>
          <button
            type="button"
            className="btn-hover"
            onClick={() => onOpenNote(c.path)}
            style={{ ...BTN_SECONDARY, padding: "4px 10px", fontSize: fsLabel, cursor: "pointer" }}
          >
            Resolve
          </button>
        </div>
      ))}
    </Group>
  );
}

// -- Activity ------------------------------------------------------------------

function activitySubtext(e: SyncActivityEvent): string {
  const parts: string[] = [e.kind];
  if (e.input_type) parts.push(e.input_type);
  if (e.project) parts.push(e.project);
  return parts.join(" · ");
}

function ActivitySection() {
  const [events, setEvents] = useState<SyncActivityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const now = new Date();

  const load = useCallback(async () => {
    try {
      const r = await getSyncActivity(ACTIVITY_LIMIT);
      setEvents(r.events);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load activity");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <Group label="Activity" delay={90}>
      {!loaded && !error && <Note>Loading…</Note>}
      {error && <Note tone="fail">{error}</Note>}
      {loaded && !error && events.length === 0 && <Note>No recent activity.</Note>}
      {events.map((e, i) => (
        <div
          key={`${e.path ?? e.filename ?? "row"}-${e.at ?? i}`}
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--border-2)" }}
        >
          <StatusDot tone={e.status === "failed" ? "fail" : "ok"} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: fsBody, color: "var(--text-1)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {e.filename ?? e.path ?? "(untitled)"}
            </div>
            <div style={{ fontSize: micro, color: "var(--text-3)", marginTop: 1 }}>{activitySubtext(e)}</div>
          </div>
          <div style={{ fontSize: micro, color: "var(--text-3)", flexShrink: 0 }}>
            {e.at ? formatWhen(e.at, now) : ""}
          </div>
        </div>
      ))}
    </Group>
  );
}

// -- Assembly --------------------------------------------------------------------

export default function SyncFeed({ onOpenNote }: { onOpenNote: (path: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PendingSection />
      <ConflictsSection onOpenNote={onOpenNote} />
      <ActivitySection />
    </div>
  );
}
