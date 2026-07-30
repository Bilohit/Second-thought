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
  BTN_GHOST, ROW_CARD, INPUT_STYLE,
  focusRing, blurRing,
} from "./ui/styles";
import {
  MenuIcon, RefreshIcon, BellIcon, CloseIcon,
  ClipboardIcon, LinkIcon, ImageIcon, MicIcon, CheckIcon, TrashIcon,
} from "./PillMenu/icons";

const NEW_FOLDER_SENTINEL = "__new_folder__";
/** s114/d07 — no pre-selected destination. The dropdown opened on `_scratchpad`
 *  (the only value `item.category` can ever hold, since list_scratchpad reports
 *  the parent folder) and Approve then "filed" the note into the folder it was
 *  already in: status stripped, file renamed, item back in the list forever. */
const PICK_SENTINEL = "__pick__";

/** Folders a scratchpad item can be approved INTO. `_`-prefixed folders are the
 *  vault's machine territory (`_scratchpad`, `_trash`, `_attachments`,
 *  `_mobile_inbox`, `_templates`) — `/vault/categories` returns them because the
 *  Library legitimately lists them, but none is a filing destination. The server
 *  rejects the scratchpad itself too (approve_scratchpad_item); this keeps it
 *  off the menu so the rejection is never reachable by an ordinary click. */
export function filingCategories(names: string[]): string[] {
  return names.filter((n) => !n.startsWith("_") && !n.startsWith("."));
}

/** The row's lead line: what this capture is, and where it came from. */
function kindLabel(item: InboxItem): string {
  const base = item.kind === "link" ? (item.source ? `link · ${item.source}` : "link")
    : item.kind === "voice" ? "voice"
    : item.kind === "image" ? "image"
    : "text";
  return item.failure ? `${base} · ${item.failure}` : base;
}

function KindIcon({ kind }: { kind: InboxItem["kind"] }): JSX.Element {
  if (kind === "link") return <LinkIcon size={12} />;
  if (kind === "image") return <ImageIcon size={12} />;
  if (kind === "voice") return <MicIcon size={12} />;
  return <ClipboardIcon size={12} />;
}

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
  // s114/d07: starts UNSET, always. There is no correct default here — the only
  // value the server can report for `item.category` is the scratchpad folder
  // itself, and approving into that was the dead loop this row is fixing.
  const [target, setTarget] = useState("");
  const [creatingNew, setCreatingNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);

  // Drop a selection that disappeared from the vault (folder renamed/deleted
  // while the panel was open) back to unset, rather than filing somewhere else.
  useEffect(() => {
    if (target && !categories.includes(target)) setTarget("");
  }, [categories, target]);

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
        // s114/d07: a hairline-separated row, not a bordered card. These sit INSIDE the Inbox
        // capsule's own bordered surface, so the old ROW_CARD made every item a card-in-a-card
        // (council/hierarchy). Border + fill dropped; the divider does the separating.
        borderBottom: "1px solid var(--border-2)",
        padding: "11px 2px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        // The leaving slide-out owns `transform`/`transition` inline (and
        // therefore wins over the hover class's CSS) only while it's
        // actually playing — at rest those properties are left to
        // .row-hover-lift so the bold hover lift isn't shadowed by an
        // always-on inline transform.
        // No height/margin animation — matches TrashView.tsx's row exit (transform+opacity only,
        // the layout-property animation rule in the phase-6 animation pass §5 rule 5); the row
        // keeps its space until removeItem's setTimeout unmounts it, then surrounding rows reflow
        // instantly rather than via an animated collapse.
        ...(leaving
          ? {
              opacity: 0,
              transform: "translateX(12px)",
              pointerEvents: "none",
              transition: "opacity 0.26s cubic-bezier(0.22,1,0.36,1), transform 0.26s cubic-bezier(0.22,1,0.36,1)",
            }
          : {}),
      }}
    >
      {/* s114/d07: kind + source leads, not the generated filename. The filename stays reachable
          as the row's title/aria text — it identifies the file, it just never explained it. */}
      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}
        title={item.filename}
      >
        <span
          style={{
            display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0,
            fontSize: 10, letterSpacing: "0.03em", whiteSpace: "nowrap",
            // Only a FAILED capture is colour-coded; an ordinary one is quiet.
            color: item.failure ? "var(--yellow)" : "var(--text-3)",
          }}
        >
          <KindIcon kind={item.kind} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{kindLabel(item)}</span>
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
            value={target || PICK_SENTINEL}
            onChange={(e) => {
              if (e.target.value === NEW_FOLDER_SENTINEL) enterNewFolderMode();
              else if (e.target.value === PICK_SENTINEL) setTarget("");
              else setTarget(e.target.value);
            }}
            aria-label={`Target category for ${item.filename}`}
            style={{
              flex: 1,
              minWidth: 0,
              height: 28,
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              padding: "0 8px",
              fontSize: 11,
              color: target ? "var(--text-2)" : "var(--text-3)",
              outline: "none",
              fontFamily: "inherit",
            }}
          >
            <option value={PICK_SENTINEL}>Choose a folder…</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
            <option value={NEW_FOLDER_SENTINEL}>+ New folder…</option>
          </select>
        )}
        {/* s114/d07: Approve is the suggested action — filled, semibold, check icon leading — and
            it is DISABLED until a real destination is picked. The council's hierarchy lens found
            the dropdown carried the least visual weight in this row while Approve carried the
            most, which is exactly how an unset destination went unnoticed. Discard stays live
            throughout: junk is still one click away without choosing where to file it first. */}
        <button
          onClick={() => effectiveTarget && onApprove(item.note_id, effectiveTarget)}
          disabled={!effectiveTarget || pending}
          title={effectiveTarget ? undefined : "Pick a folder first"}
          style={{
            height: 28,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "0 11px",
            fontSize: 11,
            fontWeight: effectiveTarget ? 600 : 400,
            fontFamily: "inherit",
            whiteSpace: "nowrap",
            borderRadius: "var(--radius-sm)",
            border: "1px solid " + (effectiveTarget && !pending ? "var(--text-1)" : "var(--border)"),
            background: effectiveTarget && !pending ? "var(--text-1)" : "var(--surface)",
            color: effectiveTarget && !pending ? "var(--bg)" : "var(--text-3)",
            cursor: !effectiveTarget || pending ? "not-allowed" : "pointer",
            transition: "background 0.18s, color 0.18s, border-color 0.18s",
          }}
        >
          {pending ? "Filing…" : <><CheckIcon size={12} />Approve</>}
        </button>
        <button
          onClick={() => onDiscard(item.note_id)}
          disabled={pending}
          title="Discard"
          aria-label="Discard"
          className="btn-hover hover-danger"
          style={{
            ...BTN_GHOST,
            width: 28,
            height: 28,
            flex: "none",
            padding: 0,
            justifyContent: "center",
            border: "1px solid var(--border)",
            opacity: pending ? 0.5 : 1,
            cursor: pending ? "default" : "pointer",
          }}
        >
          <TrashIcon size={13} />
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
      // s114/d07: machine folders (`_scratchpad`, `_trash`, `_attachments`, …) come back from
      // /vault/categories because the Library lists them; none is a filing destination.
      setCategories(filingCategories(catRes.categories.map((c) => c.name)));
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
    }, 260);
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
          .then((res) => setCategories(filingCategories(res.categories.map((c) => c.name))))
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
