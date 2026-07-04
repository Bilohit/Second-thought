import type { ToastItem } from "../hooks/useToasts";

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
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      aria-live={toast.tone === "error" ? "assertive" : "polite"}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        padding: "9px 10px 9px 12px",
        background: "var(--glass-bg)",
        border: "1px solid var(--border)",
        borderLeft: `3px solid ${TONE_COLOR[toast.tone]}`,
        borderRadius: "var(--radius)",
        boxShadow: "var(--glass-shadow)",
        animation: "fadeIn 0.22s var(--menu-travel-ease) both",
        minWidth: 200,
        maxWidth: 380,
      }}
    >
      <span style={{ fontSize: 11.5, color: "var(--text-2)", lineHeight: 1.4 }}>
        {toast.message}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
        {toast.action && (
          <button
            onClick={() => { toast.action!.run(); onDismiss(toast.id); }}
            style={{
              background: "none",
              border: `1px solid ${TONE_COLOR[toast.tone]}`,
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
              color: "var(--text-1)",
              fontSize: 11,
              lineHeight: 1,
              padding: "4px 8px",
              fontFamily: "inherit",
              whiteSpace: "nowrap",
            }}
          >
            {toast.action.label}
          </button>
        )}
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
          }}
        >
          ✕
        </button>
      </div>
    </div>
  );
}
