import { useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import StepIndicator from "../StepIndicator";
import {
  getStats, getInbox, approveInboxItem, discardInboxItem,
  type LlmStatus, type Stats, type InboxItem,
} from "../../lib/api";
import { fileKind } from "../../lib/fileIngest";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";

interface DashboardViewProps {
  visible: boolean;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  llmStatus: LlmStatus;
  onOpenFile: (path: string) => void;
  onCaptureFile: (path: string) => void;
}

export default function DashboardView({ visible, captureState, stepDefs, llmStatus, onOpenFile, onCaptureFile }: DashboardViewProps) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [rejected, setRejected] = useState(false);
  const rejectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!visible) return;
    getStats().then(setStats).catch(() => {});
    getInbox().then((r) => setInbox(r.inbox)).catch(() => {});
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    let unlisten: (() => void) | undefined;
    getCurrentWebview().onDragDropEvent((event) => {
      const { type } = event.payload;
      if (type === "over") setDragOver(true);
      else if (type === "leave") setDragOver(false);
      else if (type === "drop") {
        setDragOver(false);
        const path = event.payload.paths[0];
        if (!path) return;
        const kind = fileKind(path);
        if (!kind) {
          setRejected(true);
          if (rejectTimer.current) clearTimeout(rejectTimer.current);
          rejectTimer.current = setTimeout(() => setRejected(false), 2000);
          return;
        }
        void onCaptureFile(path);
      }
    }).then((fn) => { unlisten = fn; });
    return () => {
      unlisten?.();
      if (rejectTimer.current) clearTimeout(rejectTimer.current);
    };
  }, [visible, onCaptureFile]);

  if (!visible) return null;

  const handleApprove = (noteId: string) =>
    approveInboxItem(noteId).then(() => setInbox((rows) => rows.filter((r) => r.note_id !== noteId))).catch(() => {});
  const handleDiscard = (noteId: string) =>
    discardInboxItem(noteId).then(() => setInbox((rows) => rows.filter((r) => r.note_id !== noteId))).catch(() => {});

  return (
    <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, padding: 14, overflow: "hidden" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        {renderCaptureCard(captureState, stepDefs, dragOver, rejected)}
        {renderRecentCard(stats, onOpenFile)}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        {renderHealthCard(llmStatus, stats)}
        {renderInboxCard(inbox, handleApprove, handleDiscard)}
      </div>
    </div>
  );
}

function renderCaptureCard(
  captureState: CaptureState,
  stepDefs: CaptureStep[],
  dragOver: boolean,
  rejected: boolean,
) {
  const last = captureState.result;
  const isIdle = captureState.phase === "idle";
  return (
    <div style={cardStyle(isIdle)}>
      <div style={CLABEL}>Capture<span style={{ flex: 1 }} /><span style={chipStyle(captureState.phase === "capturing")}>
        {captureState.phase === "capturing" ? "live" : captureState.phase === "done" ? "done" : "idle"}
      </span></div>
      {isIdle && (
        <div style={dropBoxStyle(dragOver, rejected)}>
          {rejected
            ? "Unsupported file type"
            : "Drop a file, paste, or auto-capture clipboard / URL / audio"}
        </div>
      )}
      {!isIdle && <StepIndicator steps={captureState.steps} stepDefs={stepDefs} />}
      {last?.path && (
        <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 10, background: "var(--glass-bg)" }}>
          <div style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{last.path}</div>
          {last.category && <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 4 }}>Routed to <b>{last.category}</b></div>}
        </div>
      )}
    </div>
  );
}

function dropBoxStyle(dragOver: boolean, rejected: boolean): React.CSSProperties {
  return {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 120,
    border: `1px dashed ${rejected ? "var(--red)" : dragOver ? "var(--accent)" : "var(--border)"}`,
    borderRadius: "var(--radius-sm)",
    padding: 20,
    color: rejected ? "var(--red)" : "var(--text-3)",
    fontSize: 12,
    textAlign: "center",
    boxShadow: dragOver && !rejected ? "0 0 0 1px var(--accent-glow)" : undefined,
    transition: "border-color 0.2s ease, box-shadow 0.2s ease, color 0.2s ease",
  };
}

function renderRecentCard(stats: Stats | null, onOpenFile: (path: string) => void) {
  const rows = stats?.recent ?? [];
  return (
    <div style={cardStyle(true)}>
      <div style={CLABEL}>
        Recent activity
        <span style={{ flex: 1 }} />
        {rows.length > 0 && <span style={chipStyle(false)}>{rows.length}</span>}
      </div>
      <div style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minWidth: 0 }}>
        {rows.map((row) => (
          <button
            key={row.id}
            type="button"
            className="btn-hover"
            onClick={() => { if (row.path) onOpenFile(row.path); }}
            style={{
              display: "flex", alignItems: "flex-start", gap: 8, width: "100%",
              padding: "7px 8px", cursor: "pointer", border: "none", borderBottom: "1px solid var(--border-2)",
              background: "transparent", textAlign: "left", fontFamily: "inherit",
            }}
          >
            <span style={{
              fontSize: 12, color: "var(--text-1)", flex: 1, minWidth: 0,
              lineHeight: 1.45, wordBreak: "break-word",
            }}>
              {row.filename ?? row.path}
            </span>
            <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 }}>
              <span style={{ fontSize: 10, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0 5px", color: "var(--text-3)", whiteSpace: "nowrap" }}>{row.category}</span>
              <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{row.timestamp}</span>
            </span>
          </button>
        ))}
        {rows.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--text-3)", padding: "12px 0", textAlign: "center" }}>No recent captures</div>
        )}
      </div>
    </div>
  );
}

function renderHealthCard(llmStatus: LlmStatus, stats: Stats | null) {
  const dot = (ok: boolean) => (
    <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: ok ? "var(--green)" : "var(--yellow)", flexShrink: 0 }} />
  );
  const rows: { label: string; value: string; ok: boolean }[] = [
    { label: "LLM", value: llmStatus === "ready" ? "ready" : llmStatus === "loading" ? "warming up" : "offline", ok: llmStatus === "ready" },
    { label: "Vault", value: stats ? `${stats.total} notes` : "…", ok: true },
    { label: "Index", value: "synced", ok: true },
    { label: "Queue", value: "0 pending", ok: true },
  ];
  return (
    <div style={cardStyle(false)}>
      <div style={CLABEL}>Health</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {rows.map((r) => (
          <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-2)" }}>
            {dot(r.ok)}
            {r.label}
            <span style={{ marginLeft: "auto", color: "var(--text-3)" }}>{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function renderInboxCard(inbox: InboxItem[], onApprove: (id: string) => void, onDiscard: (id: string) => void) {
  return (
    <div style={cardStyle(true)}>
      <div style={CLABEL}>Inbox<span style={{ flex: 1 }} />{inbox.length > 0 && <span style={chipStyle(false)}>{inbox.length} need review</span>}</div>
      <div style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minWidth: 0 }}>
        {inbox.map((item) => (
          <div key={item.note_id} style={{ border: "1px solid var(--border-2)", borderRadius: "var(--radius-sm)", background: "var(--glass-bg)", padding: "8px 10px", marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.filename}</div>
            <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}>{item.category}</div>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button onClick={() => onApprove(item.note_id)} style={miniBtnStyle(true)}>File</button>
              <button onClick={() => onDiscard(item.note_id)} style={miniBtnStyle(false)}>Dismiss</button>
            </div>
          </div>
        ))}
        {inbox.length === 0 && <div style={{ fontSize: 11, color: "var(--text-3)", padding: "12px 0", textAlign: "center" }}>No items need review</div>}
      </div>
    </div>
  );
}


function cardStyle(fill: boolean): React.CSSProperties {
  return { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 14, display: "flex", flexDirection: "column", minHeight: 0, ...(fill ? { flex: 1, overflow: "hidden" } : {}) };
}
const CLABEL: React.CSSProperties = { fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 };
function chipStyle(accent: boolean): React.CSSProperties {
  return { fontSize: 10, border: `1px solid ${accent ? "var(--accent)" : "var(--border)"}`, borderRadius: "var(--radius-sm)", padding: "1px 7px", color: accent ? "var(--text-1)" : "var(--text-2)", background: "var(--glass-bg)" };
}
function miniBtnStyle(go: boolean): React.CSSProperties {
  return { fontSize: 10, border: `1px solid ${go ? "var(--accent)" : "var(--border)"}`, borderRadius: "var(--radius-sm)", background: "transparent", color: go ? "var(--text-1)" : "var(--text-2)", padding: "2px 8px", cursor: "pointer", fontFamily: "inherit" };
}
