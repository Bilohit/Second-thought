import type { ToastItem } from "../hooks/useToasts";
import { CloseIcon } from "./PillMenu/icons";

const TONE_COLOR: Record<ToastItem["tone"], string> = {
  success: "var(--green)",
  error:   "var(--red)",
  info:    "var(--accent)",
};

interface Props {
  toast: ToastItem;
  onDismiss: (id: string) => void;
}

export default function Toast({ toast, onDismiss }: Props) {
  // A choice toast stacks — message row, then a chip row of mutually-exclusive
  // options. Every other toast keeps the original single row untouched.
  const choices = toast.choices?.length ? toast.choices : null;

  const chipStyle = (accented: boolean) => ({
    background: "none",
    border: `1px solid ${accented ? TONE_COLOR[toast.tone] : "var(--border)"}`,
    borderRadius: "var(--radius-sm)",
    cursor: "pointer",
    color: "var(--text-1)",
    fontSize: 11,
    lineHeight: 1,
    padding: "4px 8px",
    fontFamily: "inherit",
    whiteSpace: "nowrap" as const,
  });

  const dismissButton = (
    <button
      onClick={() => onDismiss(toast.id)}
      aria-label="Dismiss notification"
      style={{
        background: "none",
        border: "none",
        cursor: "pointer",
        color: "var(--text-3)",
        fontSize: 13,
        lineHeight: 1,
        padding: "2px 4px",
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <CloseIcon />
    </button>
  );

  const messageRow = (
    <>
      <span style={{ fontSize: 11.5, color: "var(--text-2)", lineHeight: 1.4 }}>
        {toast.message}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
        {!choices && toast.action && (
          <button
            onClick={() => { toast.action!.run(); onDismiss(toast.id); }}
            style={chipStyle(true)}
          >
            {toast.action.label}
          </button>
        )}
        {dismissButton}
      </div>
    </>
  );

  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      aria-live={toast.tone === "error" ? "assertive" : "polite"}
      style={{
        display: "flex",
        flexDirection: choices ? "column" : "row",
        alignItems: choices ? "stretch" : "center",
        gap: choices ? 8 : 10,
        padding: "9px 10px 9px 12px",
        background: "var(--glass-bg)",
        border: "1px solid var(--border)",
        borderLeft: `3px solid ${TONE_COLOR[toast.tone]}`,
        borderRadius: "var(--radius)",
        boxShadow: "var(--glass-shadow)",
        // Wave 6 (O-8c): toast rise, 260ms (locked standard duration) — was a
        // 220ms fadeIn+3px drift, now the shared toast-rise recipe (index.css).
        animation: "toastRiseIn 260ms var(--menu-travel-ease) both",
        minWidth: 200,
        maxWidth: 380,
      }}
    >
      {choices ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          {messageRow}
        </div>
      ) : (
        messageRow
      )}
      {choices && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {choices.map((c, i) => (
            <button
              key={c.label}
              onClick={() => { c.run(); onDismiss(toast.id); }}
              // The first chip is the earliest instant — the one the compact
              // shells auto-create — so it carries the tone border and the rest
              // stay quiet. The default is visible; nobody loses the ability to pick.
              style={chipStyle(i === 0)}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
