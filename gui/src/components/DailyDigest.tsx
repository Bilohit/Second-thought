import { useEffect, useState, type CSSProperties } from "react";
import type { DigestStats } from "../lib/api";

interface DailyDigestProps {
  open: boolean;
  stats: DigestStats | null;
  dateLabel: string;
  onClose: () => void;
}

const TRAVEL = "cubic-bezier(0.22,1,0.36,1)";
const SETTLE = "cubic-bezier(0.16,1,0.3,1)";
const DUR = 260;

function IconCalendar(props: { size?: number }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <rect x="4" y="5" width="16" height="15" rx="0.5" />
      <path d="M4 9.5h16M8 3.5V6M16 3.5V6" />
    </svg>
  );
}

function IconClose(props: { size?: number }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function IconCaptured(props: { size?: number; color?: string }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={props.color ?? "currentColor"} strokeWidth={1.7}>
      <path d="M12 4v16M4 12h16" />
    </svg>
  );
}

function IconTouched(props: { size?: number; color?: string }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={props.color ?? "currentColor"} strokeWidth={1.7}>
      <path d="M5 20l1-4L16.5 5.5a1.5 1.5 0 0 1 2 2L8 18l-4 1z" />
    </svg>
  );
}

function IconBell(props: { size?: number; color?: string }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={props.color ?? "currentColor"} strokeWidth={1.7}>
      <path d="M12 3a5 5 0 0 0-5 5v3l-2 4h14l-2-4V8a5 5 0 0 0-5-5z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </svg>
  );
}

function IconClock(props: { size?: number; color?: string }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={props.color ?? "currentColor"} strokeWidth={1.7}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

interface CellProps {
  icon: React.ReactNode;
  value: number;
  label: string;
  flagged?: boolean;
}

function Cell({ icon, value, label, flagged }: CellProps) {
  const cellStyle: CSSProperties = {
    background: "var(--surface)",
    padding: "14px 12px",
    display: "flex",
    alignItems: "center",
    gap: 10,
  };
  const numStyle: CSSProperties = {
    fontSize: 19,
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
    color: flagged ? "var(--yellow)" : "var(--text-1)",
    lineHeight: 1,
  };
  const labelStyle: CSSProperties = {
    fontSize: 9.5,
    color: "var(--text-3)",
    letterSpacing: "0.05em",
    marginTop: 3,
  };
  return (
    <div style={cellStyle}>
      {icon}
      <div>
        <div style={numStyle}>{value}</div>
        <div style={labelStyle}>{label}</div>
      </div>
    </div>
  );
}

/** ponytail: full-window-mode only for now — pill modes and the phone peer get
 *  their own digest surface later (F-14 remainder). Show-once keys off
 *  calendar day in localStorage (owned by FullWindow), not the sync
 *  scheduler — this component is purely presentational. */
export default function DailyDigest({ open, stats, dateLabel, onClose }: DailyDigestProps) {
  const [everOpened, setEverOpened] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (open && stats) {
      setEverOpened(true);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    return undefined;
  }, [open, stats]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!everOpened || !stats) return null;

  const reducedMotion = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scrimStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    background: "var(--scrim)",
    opacity: visible ? 1 : 0,
    pointerEvents: visible ? "auto" : "none",
    transition: `opacity ${DUR}ms ${SETTLE}`,
  };

  const baseTransform = "translate(-50%,-50%)";
  const hiddenTransform = reducedMotion
    ? baseTransform
    : `${baseTransform} translateY(10px) scale(0.97)`;
  const shownTransform = reducedMotion
    ? baseTransform
    : `${baseTransform} translateY(0) scale(1)`;

  const panelStyle: CSSProperties = {
    position: "absolute",
    top: "50%",
    left: "50%",
    width: 340,
    background: "var(--surface)",
    border: "1px solid var(--border)",
    opacity: visible ? 1 : 0,
    transform: visible ? shownTransform : hiddenTransform,
    pointerEvents: visible ? "auto" : "none",
    transition: `opacity ${DUR}ms ${TRAVEL}, transform ${DUR}ms ${TRAVEL}`,
  };

  const headStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "10px 14px",
    borderBottom: "1px solid var(--border-2)",
  };

  const titleStyle: CSSProperties = {
    fontSize: 11,
    letterSpacing: "0.08em",
    color: "var(--text-1)",
    fontWeight: 600,
    flex: 1,
    textTransform: "uppercase",
  };

  const closeBtnStyle: CSSProperties = {
    background: "none",
    border: "none",
    color: "var(--text-3)",
    cursor: "pointer",
    padding: 3,
    display: "flex",
  };

  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: 1,
    background: "var(--border-2)",
  };

  const flagged = stats.reminders_due > 0;

  const footStyle: CSSProperties = {
    padding: "9px 14px",
    fontSize: 11,
    color: "var(--text-3)",
    display: "flex",
    alignItems: "center",
    gap: 6,
  };

  const dotStyle: CSSProperties = {
    width: 5,
    height: 5,
    background: "var(--yellow)",
    flex: "none",
  };

  return (
    <>
      <div style={scrimStyle} onClick={onClose} />
      <div style={panelStyle}>
        <div style={headStyle}>
          <span style={{ color: "var(--text-2)", display: "flex" }}><IconCalendar /></span>
          <span style={titleStyle}>TODAY — {dateLabel}</span>
          <button style={closeBtnStyle} onClick={onClose} aria-label="Dismiss digest">
            <IconClose />
          </button>
        </div>
        <div style={gridStyle}>
          <Cell icon={<IconCaptured color="var(--text-3)" />} value={stats.captured} label="CAPTURED" />
          <Cell icon={<IconTouched color="var(--text-3)" />} value={stats.touched} label="TOUCHED" />
          <Cell
            icon={<IconBell color={flagged ? "var(--yellow)" : "var(--text-3)"} />}
            value={stats.reminders_due}
            label="REMINDERS DUE"
            flagged={flagged}
          />
          <Cell icon={<IconClock color="var(--text-3)" />} value={stats.unrevisited} label="UNREVISITED" />
        </div>
        <div style={footStyle}>
          {flagged ? (
            <>
              <span style={dotStyle} />
              <span>{stats.reminders_due} reminder{stats.reminders_due === 1 ? "" : "s"} due · generated today, closing discards it.</span>
            </>
          ) : (
            <span>Generated today · closing discards it.</span>
          )}
        </div>
      </div>
    </>
  );
}
