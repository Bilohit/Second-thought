/**
 * InboxPanel.tsx
 * --------------
 * Review queue for scratchpad captures the pipeline routed as "needs review."
 * Each item can be approved (optionally into a different category) or
 * discarded outright. Mirrors SettingsPanel's slide-in frame.
 */

import { useCallback, useEffect, useState } from "react";
import {
  getInbox,
  approveInboxItem,
  discardInboxItem,
  getVaultCategories,
  suggestCategories,
  type InboxItem,
} from "../lib/api";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  BTN_GHOST, BTN_PRIMARY, ROW_CARD, INPUT_STYLE,
  focusRing, blurRing,
} from "./ui/styles";
import { MenuIcon } from "./PillMenu/icons";

const NEW_FOLDER_SENTINEL = "__new_folder__";

interface Props {
  visible: boolean;
  onClose: () => void;
  onCountChange?: (count: number) => void;
  measureRef?: (el: HTMLDivElement | null) => void;
}

function InboxRow({
  item,
  categories,
  onApprove,
  onDiscard,
  leaving,
}: {
  item: InboxItem;
  categories: string[];
  onApprove: (noteId: string, target?: string) => void;
  onDiscard: (noteId: string) => void;
  leaving: boolean;
}) {
  const fallbackTarget = categories.includes(item.category) ? item.category : (categories[0] ?? "");
  const [target, setTarget] = useState(fallbackTarget);
  const [creatingNew, setCreatingNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);

  // Re-clamp if the category list arrives/changes after this row's initial
  // render (the seeded item.category may be "unknown" or otherwise absent
  // from the real category list).
  useEffect(() => {
    if (target && !categories.includes(target)) {
      setTarget(fallbackTarget);
    }
  }, [categories, target, fallbackTarget]);

  const date = new Date(item.modified * 1000).toLocaleDateString(undefined, {
    month: "short", day: "numeric",
  });

  const enterNewFolderMode = () => {
    setCreatingNew(true);
    setNewName("");
    if (suggestions === null && !suggestLoading) {
      setSuggestLoading(true);
      suggestCategories(item.note_id)
        .then((res) => setSuggestions(res.suggestions))
        .catch(() => setSuggestions([]))
        .finally(() => setSuggestLoading(false));
    }
  };

  const effectiveTarget = creatingNew ? newName.trim() : target;

  return (
    <div
      className="row-hover-lift"
      style={{
        ...ROW_CARD,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        maxHeight: leaving ? 0 : 260,
        overflow: "hidden",
        // The leaving slide-out owns `transform`/`transition` inline (and
        // therefore wins over the hover class's CSS) only while it's
        // actually playing — at rest those properties are left to
        // .row-hover-lift so the bold hover lift isn't shadowed by an
        // always-on inline transform.
        ...(leaving
          ? {
              opacity: 0,
              transform: "translateX(12px)",
              marginBottom: 0,
              transition: "opacity 0.18s ease, transform 0.18s ease, max-height 0.22s ease, margin-bottom 0.22s ease",
            }
          : {}),
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {item.filename}
        </span>
        <span style={{ fontSize: 10, color: "var(--text-3)", whiteSpace: "nowrap" }}>{date}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {creatingNew ? (
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New folder name"
            aria-label={`New folder name for ${item.filename}`}
            style={{ ...INPUT_STYLE, flex: 1, padding: "5px 8px", fontSize: 11 }}
            onFocus={focusRing}
            onBlur={blurRing}
            onKeyDown={(e) => { if (e.key === "Escape") setCreatingNew(false); }}
          />
        ) : (
          <select
            value={target}
            onChange={(e) => {
              if (e.target.value === NEW_FOLDER_SENTINEL) enterNewFolderMode();
              else setTarget(e.target.value);
            }}
            aria-label={`Target category for ${item.filename}`}
            style={{
              flex: 1,
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              padding: "5px 8px",
              fontSize: 11,
              color: "var(--text-2)",
              outline: "none",
              fontFamily: "inherit",
            }}
          >
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
            <option value={NEW_FOLDER_SENTINEL}>+ New folder…</option>
          </select>
        )}
        <button
          onClick={() => effectiveTarget && onApprove(item.note_id, effectiveTarget)}
          disabled={!effectiveTarget}
          style={{
            ...BTN_PRIMARY,
            padding: "5px 12px",
            fontSize: 11,
            whiteSpace: "nowrap",
            opacity: effectiveTarget ? 1 : 0.5,
            cursor: effectiveTarget ? "pointer" : "not-allowed",
          }}
        >
          Approve
        </button>
        <button
          onClick={() => onDiscard(item.note_id)}
          title="Discard"
          className="btn-hover hover-danger"
          style={BTN_GHOST}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14H6L5 6" />
            <path d="M10 11v6M14 11v6" />
            <path d="M9 6V4h6v2" />
          </svg>
        </button>
      </div>

      {creatingNew && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {!suggestLoading && suggestions?.map((s) => (
            <button
              key={s}
              onClick={() => setNewName(s)}
              className="btn-hover"
              style={{
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                padding: "3px 8px",
                fontSize: 10,
                color: "var(--text-3)",
                cursor: "pointer",
              }}
            >
              {s}
            </button>
          ))}
          <button
            onClick={() => setCreatingNew(false)}
            style={{ fontSize: 10, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: "3px 4px" }}
          >
            Use existing folder
          </button>
        </div>
      )}
    </div>
  );
}

export default function InboxPanel({ visible, onClose, onCountChange, measureRef }: Props) {
  const [mounted, setMounted] = useState(visible);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leavingIds, setLeavingIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [inboxRes, catRes] = await Promise.all([getInbox(), getVaultCategories()]);
      setItems(inboxRes.inbox);
      onCountChange?.(inboxRes.count);
      setCategories(catRes.categories.map((c) => c.name));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load inbox");
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    if (visible) { setMounted(true); load(); }
  }, [visible, load]);

  const handleTransitionEnd = () => {
    if (!visible) setMounted(false);
  };

  const removeItem = (noteId: string) => {
    setLeavingIds((s) => new Set(s).add(noteId));
    setTimeout(() => {
      setItems((list) => {
        const next = list.filter((i) => i.note_id !== noteId);
        onCountChange?.(next.length);
        return next;
      });
      setLeavingIds((s) => { const n = new Set(s); n.delete(noteId); return n; });
    }, 230);
  };

  const handleApprove = async (noteId: string, target?: string) => {
    setError(null);
    try {
      await approveInboxItem(noteId, target);
      removeItem(noteId);
      // Target may be a brand-new folder name (the backend auto-creates it
      // on approve) -- refresh the category list so it shows up elsewhere.
      if (target && !categories.includes(target)) {
        getVaultCategories()
          .then((res) => setCategories(res.categories.map((c) => c.name)))
          .catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to approve item");
    }
  };

  const handleDiscard = async (noteId: string) => {
    setError(null);
    try {
      await discardInboxItem(noteId);
      removeItem(noteId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to discard item");
    }
  };

  if (!mounted) return null;

  return (
    <div
      ref={measureRef}
      style={{
        ...PANEL_FRAME,
        ...panelTransform(visible),
        overflowY: "auto",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      <div className="drag-region" style={PANEL_HEADER}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--text-2)", display: "flex" }} aria-hidden="true">
            <MenuIcon target="inbox" size={14} />
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
            Inbox {items.length > 0 && <span style={{ color: "var(--text-3)", fontWeight: 400 }}>({items.length})</span>}
          </span>
        </div>
        <div className="no-drag" style={{ display: "flex", gap: 4 }}>
          <button
            className="btn-hover"
            style={BTN_GHOST}
            title="Refresh"
            onClick={load}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
          <button
            className="no-drag icon-close-btn"
            onClick={onClose}
            title="Close"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="2" y1="2" x2="12" y2="12" />
              <line x1="12" y1="2" x2="2" y2="12" />
            </svg>
          </button>
        </div>
      </div>

      <div
        className="no-drag"
        style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 8 }}
      >
        {loading && (
          <div style={{ display: "flex", justifyContent: "center", padding: 20 }}>
            <span style={{ fontSize: 12, color: "var(--text-3)" }}>Loading…</span>
          </div>
        )}
        {error && (
          <span style={{ fontSize: 11, color: "var(--red)" }}>{error} — is the Python server running?</span>
        )}
        {!loading && !error && items.length === 0 && (
          <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center", paddingTop: 20 }}>
            Nothing needs review.
          </span>
        )}
        {items.map((item) => (
          <InboxRow
            key={item.note_id}
            item={item}
            categories={categories}
            onApprove={handleApprove}
            onDiscard={handleDiscard}
            leaving={leavingIds.has(item.note_id)}
          />
        ))}
      </div>
    </div>
  );
}
