/**
 * TrashView.tsx — F-2 Library "Trash" section (mock 05-desktop-trash.html).
 * Lists notes sitting in `_trash/` (title, original category, deleted-when,
 * 30-day purge countdown) with a per-row Restore action that moves the file
 * back to its original category folder (GET /trash, POST /trash/restore).
 */
import { useCallback, useEffect, useState } from "react";
import { getTrash, restoreFromTrash, type TrashItem } from "../../lib/api";

interface Props {
  visible: boolean;
}

function relativeDeleted(deletedAt: number): string {
  const days = Math.floor((Date.now() / 1000 - deletedAt) / 86400);
  if (days <= 0) return "deleted today";
  if (days === 1) return "deleted 1d ago";
  return `deleted ${days}d ago`;
}

function purgeCountdown(purgeAt: number): string {
  const days = Math.max(0, Math.ceil((purgeAt - Date.now() / 1000) / 86400));
  return days <= 0 ? "purges soon" : `purges in ${days}d`;
}

export default function TrashView({ visible }: Props) {
  const [items, setItems] = useState<TrashItem[] | null>(null);
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    getTrash().then(setItems).catch(() => setItems([]));
  }, []);

  useEffect(() => {
    if (visible) load();
  }, [visible, load]);

  const restore = useCallback((item: TrashItem) => {
    setLeaving((s) => new Set(s).add(item.filename));
    restoreFromTrash(item.filename)
      .then((r) => {
        setToast(`Restored to ${r.category}`);
        setTimeout(() => {
          setItems((cur) => (cur ?? []).filter((i) => i.filename !== item.filename));
          setLeaving((s) => { const n = new Set(s); n.delete(item.filename); return n; });
          setTimeout(() => setToast(null), 1800);
        }, 260);
      })
      .catch(() => {
        setLeaving((s) => { const n = new Set(s); n.delete(item.filename); return n; });
      });
  }, []);

  if (!visible) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
      <div style={{
        display: "flex", alignItems: "baseline", gap: 10, padding: "10px 14px",
        borderBottom: "1px solid var(--border-2)", flex: "none",
      }}>
        <span style={{ fontSize: 12, letterSpacing: "0.08em", color: "var(--text-1)", fontWeight: 600 }}>TRASH</span>
        <span style={{ fontSize: 11, color: "var(--text-3)", marginLeft: "auto" }}>Purge policy: 30 days</span>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {items === null && (
          <div style={{ padding: 20, textAlign: "center", fontSize: 12, color: "var(--text-3)" }}>Loading…</div>
        )}
        {items !== null && items.length === 0 && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, padding: "32px 14px", textAlign: "center" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.7">
              <path d="M4 7h16M9 7V4h6v3M6.5 7l1 13h9l1-13" /><path d="M10 11v5M14 11v5" />
            </svg>
            <span style={{ fontSize: 13, color: "var(--text-1)" }}>Nothing in trash</span>
            <span style={{ fontSize: 11, color: "var(--text-3)", maxWidth: "34ch" }}>
              Deleted notes wait here for 30 days before purge.
            </span>
          </div>
        )}
        {items?.map((item) => {
          const isLeaving = leaving.has(item.filename);
          return (
            <div
              key={item.filename}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 14px", borderBottom: "1px solid var(--border-2)",
                opacity: isLeaving ? 0 : 1,
                transform: isLeaving ? "translateX(28px)" : "translateX(0)",
                pointerEvents: isLeaving ? "none" : "auto",
                transition: "transform 0.26s cubic-bezier(0.22,1,0.36,1), opacity 0.26s cubic-bezier(0.22,1,0.36,1)",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-1)" }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</span>
                  <span style={{
                    fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", color: "var(--text-3)",
                    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                    padding: "1px 6px", flexShrink: 0,
                  }}>
                    {item.category}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
                  {relativeDeleted(item.deleted_at)} · {purgeCountdown(item.purge_at)}
                </div>
              </div>
              <button
                className="btn-hover"
                onClick={() => restore(item)}
                style={{
                  fontSize: 11, color: "var(--text-1)", background: "var(--surface-2)",
                  border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
                  padding: "5px 12px", cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
                }}
              >
                Restore
              </button>
            </div>
          );
        })}
      </div>

      {toast && (
        <div style={{
          position: "absolute", left: "50%", bottom: 18, transform: "translateX(-50%)",
          background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-1)",
          fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 8, zIndex: 6,
        }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
            <path d="M5 12.5l4.5 4.5L19 7" />
          </svg>
          {toast}
        </div>
      )}
    </div>
  );
}
