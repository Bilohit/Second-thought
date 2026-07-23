/**
 * InboxPanel.tsx
 * --------------
 * Review queue for scratchpad captures the pipeline routed as "needs review."
 * Each item can be approved (optionally into a different category) or
 * discarded outright. Mirrors SettingsPanel's slide-in frame.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { slideDirection } from "../lib/segmentedToggle";
import {
  getInbox,
  approveInboxItem,
  discardInboxItem,
  getVaultCategories,
  suggestCategories,
  listReminders,
  deleteReminder,
  type InboxItem,
  type Reminder,
} from "../lib/api";
import { formatWhen } from "../lib/reminderFormat";
import SegmentedToggle from "./ui/SegmentedToggle";
import {
  PANEL_FRAME, PANEL_HEADER, panelTransform,
  BTN_GHOST, BTN_PRIMARY, ROW_CARD, INPUT_STYLE,
  focusRing, blurRing,
} from "./ui/styles";
import { MenuIcon, RefreshIcon, BellIcon, CloseIcon } from "./PillMenu/icons";

const NEW_FOLDER_SENTINEL = "__new_folder__";

export type InboxTab = "inbox" | "reminders";

interface Props {
  visible: boolean;
  onClose: () => void;
  onCountChange?: (count: number) => void;
  measureRef?: (el: HTMLDivElement | null) => void;
  /** Full-window shell hosts this panel inline (no slide frame, no close). */
  embedded?: boolean;
  /** Which tab to show on mount — full-window "Reminders" header jumps here. */
  initialTab?: InboxTab;
  /** Compact Mode Menu Decoupling (B5): distinct from `embedded` — Full's
   *  FullWindow also passes `embedded`, so this is the flag that actually
   *  means "hosted inside a CompactShell panel." Suppresses this component's
   *  entire header row; the Inbox/Reminders toggle + refresh move into
   *  CompactShell's header via `onHeaderActionsChange`. Full-window usage
   *  never sets this, so its render is unaffected. */
  compactHeader?: boolean;
  /** Only consulted while `compactHeader` is true — receives the current
   *  tab-toggle + refresh cluster (or `null` on unmount) so the caller can
   *  forward it into `CompactShell`'s `headerActions` slot. */
  onHeaderActionsChange?: (actions: React.ReactNode | null) => void;
  /** Hoists tab selection so an external header (CompactShell's
   *  headerActions) can control it; uncontrolled local state is the
   *  fallback, so Full-window (which never passes these) is unchanged. */
  tab?: InboxTab;
  onTabChange?: (tab: InboxTab) => void;
}

function InboxRow({
  item,
  categories,
  onApprove,
  onDiscard,
  leaving,
  pending,
}: {
  item: InboxItem;
  categories: string[];
  onApprove: (noteId: string, target?: string) => void;
  onDiscard: (noteId: string) => void;
  leaving: boolean;
  /** ISS-035: true from the click that started Approve/Discard until the
   *  server confirms (or fails) — disables both buttons immediately instead
   *  of leaving the row inert-looking for the ~1s round trip. */
  pending: boolean;
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
            style={{ ...INPUT_STYLE, flex: 1, minWidth: 0, padding: "5px 8px", fontSize: 11 }}
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
              minWidth: 0,
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
          disabled={!effectiveTarget || pending}
          style={{
            ...BTN_PRIMARY,
            padding: "5px 12px",
            fontSize: 11,
            whiteSpace: "nowrap",
            opacity: pending ? 0.5 : effectiveTarget ? 1 : 0.5,
            cursor: pending ? "default" : effectiveTarget ? "pointer" : "not-allowed",
          }}
        >
          {pending ? "Filing…" : "Approve"}
        </button>
        <button
          onClick={() => onDiscard(item.note_id)}
          disabled={pending}
          title="Discard"
          aria-label="Discard"
          className="btn-hover hover-danger"
          style={{ ...BTN_GHOST, opacity: pending ? 0.5 : 1, cursor: pending ? "default" : "pointer" }}
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

export default function InboxPanel({
  visible, onClose, onCountChange, measureRef, embedded = false, initialTab = "inbox",
  compactHeader = false, onHeaderActionsChange, tab: tabProp, onTabChange,
}: Props) {
  const [mounted, setMounted] = useState(visible);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leavingIds, setLeavingIds] = useState<Set<string>>(new Set());
  // ISS-035: marked synchronously at click time (before the network await),
  // so Approve/Discard give immediate feedback instead of sitting inert for
  // the ~1s round trip. Cleared on error so a failed row is retryable;
  // success clears it implicitly via removeItem dropping the item entirely.
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [internalTab, setInternalTab] = useState<InboxTab>(initialTab);
  const tab = tabProp ?? internalTab;
  const setTab = onTabChange ?? setInternalTab;
  const [reminders, setReminders] = useState<Reminder[]>([]);

  // Directional content-swap: Inbox=0, Reminders=1. Slides by the toggle's
  // index delta; the keyed swap panel replays its slide-in on tab change.
  const tabIndex = tab === "reminders" ? 1 : 0;
  const prevTabIndexRef = useRef(tabIndex);
  const swapDir = slideDirection(prevTabIndexRef.current, tabIndex);
  useEffect(() => { prevTabIndexRef.current = tabIndex; }, [tabIndex]);

  const loadReminders = useCallback(() => {
    listReminders().then(setReminders).catch(() => {});
  }, []);
  const handleDeleteReminder = (id: number) =>
    deleteReminder(id).then(() => setReminders((rows) => rows.filter((r) => r.id !== id))).catch(() => {});

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
    if (visible) { setMounted(true); setTab(initialTab); load(); loadReminders(); }
  }, [visible, load, loadReminders, initialTab]);

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
    setPendingIds((s) => new Set(s).add(noteId));
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
      setPendingIds((s) => { const n = new Set(s); n.delete(noteId); return n; });
    }
  };

  const handleDiscard = async (noteId: string) => {
    setError(null);
    setPendingIds((s) => new Set(s).add(noteId));
    try {
      await discardInboxItem(noteId);
      removeItem(noteId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to discard item");
      setPendingIds((s) => { const n = new Set(s); n.delete(noteId); return n; });
    }
  };

  // Inbox/Reminders toggle + refresh — rendered inline in this component's
  // own header in Full mode (unchanged below); compactHeader mode instead
  // forwards them up so CompactShell's header can render them, in place of
  // this component's own (now-suppressed) duplicate row. No count badge
  // here (user decision) — that text lives only in the Full-mode header.
  const headerActionButtons = (
    <>
      <SegmentedToggle
        ariaLabel="Inbox view"
        options={[
          // Icons only in the compact/capsule header (mirrors the Look
          // Search/Chat toggle); the full-window header keeps text labels.
          { key: "inbox" as const, label: "Review", icon: compactHeader ? <MenuIcon target="inbox" size={14} /> : undefined },
          { key: "reminders" as const, label: "Reminders", icon: compactHeader ? <BellIcon size={14} /> : undefined },
        ]}
        value={tab}
        onChange={setTab}
      />
      <button
        className="btn-hover"
        style={BTN_GHOST}
        title="Refresh"
        aria-label="Refresh"
        onClick={() => { load(); loadReminders(); }}
      >
        <RefreshIcon size={13} />
      </button>
    </>
  );

  useEffect(() => {
    if (!compactHeader) return;
    onHeaderActionsChange?.(headerActionButtons);
    return () => onHeaderActionsChange?.(null);
    // headerActionButtons is rebuilt every render from these same values —
    // listing it would just be noise, and its closures (load/loadReminders
    // etc.) are always current at call time regardless of this array.
  }, [compactHeader, tab, onHeaderActionsChange]);

  if (!mounted) return null;

  const pending = reminders.filter((r) => r.status === "pending");
  const fired = reminders.filter((r) => r.status !== "pending");

  return (
    <div
      ref={measureRef}
      style={{
        ...(embedded
          ? { position: "relative", width: "100%", height: "100%", border: "none", borderRadius: 0, background: "transparent" }
          : { ...PANEL_FRAME, ...panelTransform(visible) }),
        overflowY: "auto",
        // Clip the content-swap's horizontal slide so it never spawns a
        // bottom scrollbar (this is the panel's own scroll container).
        overflowX: "hidden",
      }}
      onTransitionEnd={handleTransitionEnd}
    >
      {!compactHeader && (
        <div className={embedded ? undefined : "drag-region"} style={PANEL_HEADER}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "var(--text-2)", display: "flex" }} aria-hidden="true">
              <MenuIcon target="inbox" size={14} />
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
              Inbox {tab === "inbox" && items.length > 0 && <span style={{ color: "var(--text-3)", fontWeight: 400 }}>({items.length})</span>}
            </span>
          </div>
          <div className="no-drag" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {headerActionButtons}
            {!embedded && (
              <button
                className="no-drag icon-close-btn"
                onClick={onClose}
                title="Close"
                aria-label="Close"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="2" y1="2" x2="12" y2="12" />
                  <line x1="12" y1="2" x2="2" y2="12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      <div key={tab} className="seg-swap-panel" style={{ "--swap-dir": swapDir } as CSSProperties}>
      {tab === "inbox" && (
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
              pending={pendingIds.has(item.note_id)}
            />
          ))}
        </div>
      )}

      {tab === "reminders" && (
        <div
          className="no-drag"
          style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6 }}
        >
          {pending.map((r) => (
            <div key={r.id} style={{ ...ROW_CARD, padding: "8px 10px", display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</div>
                <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}>{formatWhen(r.fire_at, new Date())}</div>
              </div>
              <button
                onClick={() => handleDeleteReminder(r.id)}
                aria-label="Delete reminder"
                className="btn-hover hover-danger"
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-3)", fontSize: 12, padding: "2px 4px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
              >
                <CloseIcon />
              </button>
            </div>
          ))}
          {fired.length > 0 && (
            <>
              <div style={{ borderTop: "1px solid var(--border-2, var(--border))", margin: "4px 0" }} />
              {fired.map((r) => (
                <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", opacity: 0.5 }}>
                  <div style={{ flex: 1, minWidth: 0, fontSize: 11, color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</div>
                </div>
              ))}
            </>
          )}
          {reminders.length === 0 && (
            <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center", paddingTop: 20 }}>
              No reminders.
            </span>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
