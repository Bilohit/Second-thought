import { useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import StepIndicator from "../StepIndicator";
import FluidVisualizer from "../PillMenu/FluidVisualizer";
import { MicIcon, CloseIcon, ChevronRightIcon } from "../PillMenu/icons";
import { formatElapsed } from "../../lib/voiceLimits";
import {
  getStats, getInbox, approveInboxItem, discardInboxItem,
  listReminders, deleteReminder,
  type Stats, type InboxItem, type Reminder,
} from "../../lib/api";
import { fileKind } from "../../lib/fileIngest";
import { formatWhen } from "../../lib/reminderFormat";
import type { CaptureState, CaptureStep } from "../../hooks/useCapture";
import type { VoicePhase } from "../../hooks/useVoiceRecording";
import type { LlmStatus } from "../../lib/api";

interface DashboardViewProps {
  visible: boolean;
  captureState: CaptureState;
  stepDefs: CaptureStep[];
  onOpenFile: (path: string) => void;
  onCaptureFile: (path: string) => void;
  /** Header clicks jump to the full view for that card. */
  onNavigate: (target: "library" | "inbox" | "reminders") => void;
  llmStatus: LlmStatus;
  voicePhase: VoicePhase;
  voiceElapsedMs: number;
  readWaveform: (out: Float32Array) => void;
  readSpectrum: (out: Uint8Array) => void;
  sampleRate: number;
  onVoiceToggle: () => void;
  onVoiceCancel: () => void;
}

export default function DashboardView({
  visible, captureState, stepDefs, onOpenFile, onCaptureFile, onNavigate,
  llmStatus, voicePhase, voiceElapsedMs, readWaveform, readSpectrum, sampleRate, onVoiceToggle, onVoiceCancel,
}: DashboardViewProps) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [rejected, setRejected] = useState(false);
  const rejectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Refetch when the view opens AND whenever a capture settles (done/error),
  // so Recent activity / Inbox / Reminders reflect the note just written.
  // Skipped mid-flight: "capturing"/"background" would refetch too early.
  useEffect(() => {
    if (!visible) return;
    if (captureState.phase === "capturing" || captureState.phase === "background") return;
    getStats().then(setStats).catch(() => {});
    getInbox().then((r) => setInbox(r.inbox)).catch(() => {});
    listReminders().then(setReminders).catch(() => {});
  }, [visible, captureState.phase, llmStatus]);

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
  const handleDeleteReminder = (id: number) =>
    deleteReminder(id).then(() => setReminders((rows) => rows.filter((r) => r.id !== id))).catch(() => {});

  return (
    <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, padding: 14, overflow: "hidden" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        {renderCaptureCard(captureState, stepDefs, dragOver, rejected, voicePhase, voiceElapsedMs, readWaveform, readSpectrum, sampleRate, onVoiceToggle, onVoiceCancel)}
        {renderRecentCard(stats, onOpenFile, () => onNavigate("library"))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        {renderRemindersCard(reminders, handleDeleteReminder, () => onNavigate("reminders"))}
        {renderInboxCard(inbox, handleApprove, handleDiscard, () => onNavigate("inbox"))}
      </div>
    </div>
  );
}

function micButtonStyle(disabled: boolean): React.CSSProperties {
  return {
    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
    width: 64, height: 22, padding: 0, cursor: disabled ? "default" : "pointer",
    border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
    background: "transparent", color: "var(--text-2)",
    fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "inherit",
    opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? "none" : "auto",
    flexShrink: 0,
  };
}

function renderCaptureCard(
  captureState: CaptureState,
  stepDefs: CaptureStep[],
  dragOver: boolean,
  rejected: boolean,
  voicePhase: VoicePhase,
  voiceElapsedMs: number,
  readWaveform: (out: Float32Array) => void,
  readSpectrum: (out: Uint8Array) => void,
  sampleRate: number,
  onVoiceToggle: () => void,
  onVoiceCancel: () => void,
) {
  const last = captureState.result;
  const isIdle = captureState.phase === "idle";
  const voiceIdle = voicePhase === "idle";
  const chipLabel = voicePhase === "sending" ? "sending"
    : captureState.phase === "capturing" ? "live"
    : captureState.phase === "done" ? "done" : "idle";
  const chipColor = (voicePhase !== "idle" || captureState.phase === "capturing") ? "var(--accent)"
    : undefined;
  return (
    // Fixed height: the card must not resize when recording/capture starts.
    <div style={{ ...cardStyle(false), flex: "none" }}>
      <div style={CLABEL}>
        Capture
        <span style={{ flex: 1 }} />
        {voicePhase !== "recording" && <span style={chipStyle(!!chipColor, chipColor)}>{chipLabel}</span>}
        {voiceIdle ? (
          <button
            type="button"
            className="btn-hover"
            onClick={onVoiceToggle}
            disabled={!isIdle}
            title={isIdle ? "Record voice note" : "Finish current capture first"}
            aria-label="Record voice note"
            style={micButtonStyle(!isIdle)}
          >
            <MicIcon size={12} />
            Rec
          </button>
        ) : voicePhase === "recording" ? (
          <>
            <button
              type="button"
              onClick={onVoiceCancel}
              style={{ ...miniBtnStyle(false), height: 22, display: "flex", alignItems: "center" }}
            >
              Cancel
            </button>
            {/* Stop occupies the Rec button's exact spot and size (user-locked Q3). */}
            <button
              type="button"
              onClick={onVoiceToggle}
              style={{ ...micButtonStyle(false), color: "var(--text-1)" }}
            >
              Stop
            </button>
          </>
        ) : null}
      </div>
      {voicePhase === "recording" && (
        <div style={{ height: 120, display: "flex", flexDirection: "column", justifyContent: "center", gap: 14 }}>
          <FluidVisualizer readWaveform={readWaveform} readSpectrum={readSpectrum} sampleRate={sampleRate} height={72} active />
          <div style={{ display: "flex", justifyContent: "center" }}>
            <span style={{ fontSize: 22, color: "var(--text-1)", fontVariantNumeric: "tabular-nums" }}>{formatElapsed(voiceElapsedMs)}</span>
          </div>
        </div>
      )}
      {voicePhase === "sending" && (
        <div style={dropBoxStyle(false, false)}>Sending voice note…</div>
      )}
      {voiceIdle && isIdle && (
        <div style={dropBoxStyle(dragOver, rejected)}>
          {rejected
            ? "Unsupported file type"
            : "Drop a file, paste, or auto-capture clipboard / URL / audio"}
        </div>
      )}
      {voiceIdle && !isIdle && <StepIndicator steps={captureState.steps} stepDefs={stepDefs} />}
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
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: 120,
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

function renderRecentCard(stats: Stats | null, onOpenFile: (path: string) => void, onHeader: () => void) {
  const rows = stats?.recent ?? [];
  return (
    <div style={cardStyle(true)}>
      <div style={CLABEL}>
        {headerLink("Recent activity", onHeader)}
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
              fontSize: 12, color: "var(--text-1)", flex: 1, minWidth: 120,
              lineHeight: 1.45, wordBreak: "break-word",
            }}>
              {row.filename ?? row.path}
            </span>
            {/* Shrinkable (minWidth 0) so the filename's 120px floor wins on
                narrow windows — the category chip ellipsizes first. */}
            <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 1, minWidth: 0 }}>
              <span style={{ fontSize: 10, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0 5px", color: "var(--text-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{row.category}</span>
              <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{row.timestamp}</span>
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

function renderRemindersCard(reminders: Reminder[], onDelete: (id: number) => void, onHeader: () => void) {
  const pending = reminders.filter((r) => r.status === "pending");
  const fired = reminders.filter((r) => r.status !== "pending");
  return (
    <div style={cardStyle(false)}>
      <div style={CLABEL}>{headerLink("Reminders", onHeader)}<span style={{ flex: 1 }} />{pending.length > 0 && <span style={chipStyle(false)}>{pending.length}</span>}</div>
      <div style={{ overflowY: "auto", overflowX: "hidden", maxHeight: 180, display: "flex", flexDirection: "column", gap: 6 }}>
        {pending.map((r) => (
          <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--border-2)", borderRadius: "var(--radius-sm)", background: "var(--glass-bg)", padding: "6px 8px" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</div>
              <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}>{formatWhen(r.fire_at, new Date())}</div>
            </div>
            <button
              onClick={() => onDelete(r.id)}
              aria-label="Delete reminder"
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-3)", fontSize: 12, padding: "2px 4px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
            >
              <CloseIcon />
            </button>
          </div>
        ))}
        {fired.length > 0 && (
          <>
            <div style={{ borderTop: "1px solid var(--border-2)", margin: "4px 0" }} />
            {fired.map((r) => (
              <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", opacity: 0.5 }}>
                <div style={{ flex: 1, minWidth: 0, fontSize: 11, color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</div>
              </div>
            ))}
          </>
        )}
        {reminders.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--text-3)", padding: "8px 0", textAlign: "center" }}>No reminders</div>
        )}
      </div>
    </div>
  );
}

function renderInboxCard(inbox: InboxItem[], onApprove: (id: string) => void, onDiscard: (id: string) => void, onHeader: () => void) {
  return (
    <div style={cardStyle(true)}>
      <div style={CLABEL}>{headerLink("Review", onHeader)}<span style={{ flex: 1 }} />{inbox.length > 0 && <span style={chipStyle(false)}>{inbox.length} need review</span>}</div>
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
function chipStyle(accent: boolean, color?: string): React.CSSProperties {
  const c = accent ? (color ?? "var(--accent)") : undefined;
  return { fontSize: 10, border: `1px solid ${c ?? "var(--border)"}`, borderRadius: "var(--radius-sm)", padding: "1px 7px", color: c ? "var(--text-1)" : "var(--text-2)", background: "var(--glass-bg)" };
}
function miniBtnStyle(go: boolean): React.CSSProperties {
  return { fontSize: 10, border: `1px solid ${go ? "var(--accent)" : "var(--border)"}`, borderRadius: "var(--radius-sm)", background: "transparent", color: go ? "var(--text-1)" : "var(--text-2)", padding: "2px 8px", cursor: "pointer", fontFamily: "inherit" };
}
function headerLink(label: string, onClick: () => void) {
  return (
    <button
      type="button"
      className="hdr-link"
      onClick={onClick}
      title={`Open ${label}`}
      style={{
        background: "none", border: "none", padding: 0, cursor: "pointer",
        font: "inherit", color: "inherit", letterSpacing: "inherit",
        textTransform: "inherit", fontFamily: "inherit",
        display: "inline-flex", alignItems: "center",
      }}
    >
      {label}
      <span className="hdr-chev" aria-hidden="true"><ChevronRightIcon size={10} /></span>
    </button>
  );
}
