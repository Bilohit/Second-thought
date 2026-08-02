import { useEffect, useState } from "react";
import { getToday, deleteReminder, createDailyNote, type TodayViewData, type TodayReminder } from "../../lib/api";
import { formatWhen } from "../../lib/reminderFormat";
import { logger } from "../../lib/logger";

interface TodayViewProps {
  visible: boolean;
  onOpenNote: (path: string) => void;
}

export default function TodayView({ visible, onOpenNote }: TodayViewProps) {
  const [data, setData] = useState<TodayViewData | null>(null);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    getToday()
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => logger.warn("today", "getToday failed", err));
    return () => { cancelled = true; };
  }, [visible]);

  if (!visible) return null;

  const handleStartDaily = () => {
    createDailyNote(data?.date)
      .then((note) => {
        getToday().then(setData).catch((err) => logger.warn("today", "refetch failed", err));
        onOpenNote(note.path);
      })
      .catch((err) => logger.warn("today", "create daily note failed", err));
  };

  const handleComplete = (id: number) => {
    setData((d) => d && {
      ...d,
      overdue: d.overdue.filter((r) => r.id !== id),
      due_today: d.due_today.filter((r) => r.id !== id),
    });
    deleteReminder(id)
      .then(() => getToday().then(setData).catch((err) => logger.warn("today", "refetch failed", err)))
      .catch((err) => logger.warn("today", "delete reminder failed", { id, err }));
  };

  const dateline = formatDateline(data?.date);
  const overdue = data?.overdue ?? [];
  const dueToday = data?.due_today ?? [];
  const nothingDue = overdue.length === 0 && dueToday.length === 0;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 280px", gap: 14, padding: 14, overflow: "hidden" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        {dateline && <div style={{ fontSize: 12, color: "var(--text-2)", letterSpacing: "0.04em" }}>{dateline}</div>}

        <div style={cardStyle(false)}>
          <div style={CLABEL}>
            Reminders
            <span style={{ flex: 1 }} />
            {overdue.length > 0 && <span style={overdueBadgeStyle}>{overdue.length} OVERDUE</span>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {overdue.map((r) => (
              <ReminderRow key={r.id} row={r} overdue onComplete={handleComplete} onOpenNote={onOpenNote} />
            ))}
            {dueToday.map((r) => (
              <ReminderRow key={r.id} row={r} overdue={false} onComplete={handleComplete} onOpenNote={onOpenNote} />
            ))}
            {nothingDue && (
              <div style={{ fontSize: 11, color: "var(--text-3)", padding: "8px 0", textAlign: "center" }}>Nothing due.</div>
            )}
          </div>
        </div>

        <div style={cardStyle(false)}>
          <div style={CLABEL}>Scratchpad</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-3)" }}>
            <SheafIcon />
            {data && data.scratchpad_count > 0
              ? `${data.scratchpad_count} in scratchpad`
              : "Inbox clear"}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0, overflow: "hidden" }}>
        <div style={cardStyle(true)}>
          <div style={CLABEL}>Daily note</div>
          {data?.daily_note ? (
            <button
              type="button"
              className="btn-hover"
              onClick={() => onOpenNote(data.daily_note!.path)}
              style={{
                display: "flex", flexDirection: "column", gap: 4, width: "100%", textAlign: "left",
                border: "1px solid var(--border-2)", borderRadius: "var(--radius-sm)", background: "var(--glass-bg)",
                padding: "10px 12px", cursor: "pointer", fontFamily: "inherit",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {data.daily_note.title}
              </span>
              <span style={{ fontSize: 10, color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {basename(data.daily_note.path)}
              </span>
            </button>
          ) : (
            <button
              type="button"
              className="btn-hover"
              aria-label="Start today's note"
              onClick={handleStartDaily}
              style={{
                display: "flex", flexDirection: "column", gap: 4, width: "100%", textAlign: "left",
                border: "1px solid var(--border-2)", borderRadius: "var(--radius-sm)", background: "var(--glass-bg)",
                padding: "10px 12px", cursor: "pointer", fontFamily: "inherit",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--text-1)" }}>Start today's note</span>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>No daily note yet — create one.</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ReminderRow({
  row, overdue, onComplete, onOpenNote,
}: {
  row: TodayReminder;
  overdue: boolean;
  onComplete: (id: number) => void;
  onOpenNote: (path: string) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--border-2)", borderRadius: "var(--radius-sm)", background: "var(--glass-bg)", padding: "6px 8px" }}>
      <button
        type="button"
        onClick={() => onComplete(row.id)}
        aria-label="Complete reminder"
        title="Complete reminder"
        style={{
          width: 16, height: 16, flexShrink: 0, padding: 0, cursor: "pointer",
          border: `1px solid ${overdue ? "var(--red)" : "var(--text-3)"}`,
          borderRadius: "var(--radius-sm)", background: "transparent",
        }}
      />
      <button
        type="button"
        className="btn-hover"
        onClick={() => onOpenNote(row.note_path)}
        style={{
          flex: 1, minWidth: 0, textAlign: "left", border: "none", background: "transparent",
          padding: 0, cursor: "pointer", fontFamily: "inherit", fontSize: 12, color: "var(--text-1)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}
      >
        {row.title}
      </button>
      <span style={{ fontSize: 10, color: overdue ? "var(--red)" : "var(--text-3)", flexShrink: 0, whiteSpace: "nowrap" }}>
        {formatWhen(row.fire_at, new Date())}
      </span>
    </div>
  );
}

function SheafIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

/** FR-08: `daily_note.path` is the server's absolute OS path (e.g.
 *  "C:\Users\<name>\...\Daily\2026-08-02.md") -- doctrine bans ever
 *  presenting a path as the source of truth, and the title right above this
 *  line already identifies the note. This keeps the line (still useful: the
 *  exact filename, distinct from the human title) while dropping everything
 *  that leaks the user's OS directory tree. Handles both \ and / separators
 *  since the path comes from a Windows server. No reveal-in-folder affordance
 *  exists in this view to hand the real path to instead (tauri.ts's
 *  revealItemInDir is used only for the log file, in Settings) -- worth
 *  wiring here later, not built now. */
function basename(path: string): string {
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx === -1 ? path : path.slice(idx + 1);
}

/** "date" comes back as an ISO calendar day (YYYY-MM-DD); format like the
 *  phone's dateline (weekday + month/day), parsed as local time so an
 *  off-UTC machine doesn't roll to the adjacent day. */
function formatDateline(isoDay: string | undefined): string | null {
  if (!isoDay) return null;
  const parts = isoDay.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return isoDay;
  const [y, m, d] = parts;
  const date = new Date(y, m - 1, d);
  if (isNaN(date.getTime())) return isoDay;
  return date.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}

function cardStyle(fill: boolean): React.CSSProperties {
  return { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 14, display: "flex", flexDirection: "column", minHeight: 0, ...(fill ? { flex: 1, overflow: "hidden" } : {}) };
}
const CLABEL: React.CSSProperties = { fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 };
const overdueBadgeStyle: React.CSSProperties = { fontSize: 10, border: "1px solid var(--red)", borderRadius: "var(--radius-sm)", padding: "1px 7px", color: "var(--red)", background: "var(--glass-bg)" };
