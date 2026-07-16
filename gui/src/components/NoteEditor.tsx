import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  getNoteContent,
  saveNoteContent,
  searchCaptures,
  createReminder,
  getNoteHistory,
  getNoteHistoryRevision,
  getNoteConflict,
  resolveNoteConflict,
  addNoteAttachment,
  attachmentUrl,
  NoteConflictError,
  type NoteContent,
  type SearchResult,
  type NoteRevision,
  type NoteHistoryStatus,
  type NoteConflict,
  type ConflictResolveAction,
} from "../lib/api";
import { applyMarkdownFormat, parseOutline, parseWikilinks, type FormatKind } from "../lib/noteFormat";
import { parseAttachments } from "../lib/attachments";
import { diffLines } from "../lib/lineDiff";
import { BellIcon, ClockIcon } from "./PillMenu/icons";
import { RADIAL_STAGGER_MS } from "./PillMenu/RadialMenu";

const TRAVEL = "cubic-bezier(0.22,1,0.36,1)";
const SETTLE = "cubic-bezier(0.16,1,0.3,1)";
const DUR = 260;
const SAVE_DEBOUNCE_MS = 900;

interface NoteEditorProps {
  open: boolean;
  path: string | null;
  onClose: () => void;
  onOpenExternal: (path: string) => void;
}

// -- local icons (feature-specific glyphs; Bell/Clock reused from PillMenu/icons.tsx) --

function IconBack(props: { size?: number }) {
  const size = props.size ?? 15;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M15 5l-7 7 7 7" />
    </svg>
  );
}
function IconPlus(props: { size?: number }) {
  const size = props.size ?? 19;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
function IconMeta(props: { size?: number }) {
  const size = props.size ?? 17;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M11.5 3H4v7.5L13 20l7-7z" /><circle cx="8.5" cy="7.5" r="1.3" />
    </svg>
  );
}
function IconConnections(props: { size?: number }) {
  const size = props.size ?? 17;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <circle cx="6" cy="6" r="2.1" /><circle cx="18" cy="6" r="2.1" /><circle cx="12" cy="18" r="2.1" />
      <path d="M8 7l7-0.7M13.5 16.3l3-8.7M10.5 16.3l-3-8.7" />
    </svg>
  );
}
function IconExternal(props: { size?: number }) {
  const size = props.size ?? 17;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M7 17L17 7M9 7h8v8" /><path d="M6 4H4v16h16v-2" />
    </svg>
  );
}
function IconAttach(props: { size?: number }) {
  const size = props.size ?? 17;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M17 7.5l-7.5 7.5a2.5 2.5 0 0 0 3.5 3.5L21 10.5a5 5 0 0 0-7-7L6 11.5a7.5 7.5 0 0 0 10.5 10.5" />
    </svg>
  );
}
function IconCheck(props: { size?: number }) {
  const size = props.size ?? 17;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
function IconLock(props: { size?: number }) {
  const size = props.size ?? 11;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <rect x="5" y="10.5" width="14" height="9" rx="0.5" /><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" />
    </svg>
  );
}
function IconChevron(props: { size?: number; open?: boolean }) {
  const size = props.size ?? 12;
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}
      style={{ transform: props.open ? "rotate(180deg)" : "none", transition: `transform ${DUR}ms ${SETTLE}` }}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}
function IconOffline(props: { size?: number }) {
  const size = props.size ?? 18;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M8.6 13.4a6 6 0 0 1 4.6-1.7M5.2 10.3a10 10 0 0 1 3-2M12 6.5a10 10 0 0 1 6.9 3.7M15.4 13.4c.3.2.6.4.8.7" />
      <circle cx="12" cy="17.5" r="0.9" fill="currentColor" stroke="none" /><path d="M3.5 3.5l17 17" />
    </svg>
  );
}
function IconNotSynced(props: { size?: number }) {
  const size = props.size ?? 18;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M6.5 17.5a4.5 4.5 0 0 1 0-9 6 6 0 0 1 11.6 1.3A4 4 0 0 1 17.5 17.5z" />
    </svg>
  );
}
const FMT_ICON_PATHS: Record<FormatKind, JSX.Element> = {
  bold: <path d="M7 4.5h6a3.5 3.5 0 0 1 0 7H7zM7 11.5h7a3.5 3.5 0 0 1 0 8H7z" />,
  italic: <path d="M14 4h-4M14 4l-4 16M10 20H6" />,
  heading: <path d="M6 5v14M18 5v14M6 12h12" />,
  list: <><path d="M9 6.5h11M9 12h11M9 17.5h11" /><circle cx="4.5" cy="6.5" r="1.1" /><circle cx="4.5" cy="12" r="1.1" /><circle cx="4.5" cy="17.5" r="1.1" /></>,
  link: <><path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 0 0-5.7-5.7l-1.3 1.3" /><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 0 0 5.7 5.7l1.3-1.3" /></>,
  code: <path d="M9 8l-4 4 4 4M15 8l4 4-4 4" />,
};
function FmtIcon({ kind, size = 16 }: { kind: FormatKind; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      {FMT_ICON_PATHS[kind]}
    </svg>
  );
}

const FMT_ORDER: { kind: FormatKind; label: string }[] = [
  { kind: "bold", label: "Bold" },
  { kind: "italic", label: "Italic" },
  { kind: "heading", label: "Heading" },
  { kind: "list", label: "List" },
  { kind: "link", label: "Link" },
  { kind: "code", label: "Code block" },
];
// quarter-arc fan up-and-left, matching the approved mock (05-desktop-viewer-refined-v2.html)
const FAN_OFFSETS: [number, number][] = [
  [0, -96], [-30, -91], [-56, -78], [-78, -56], [-91, -30], [-96, 0],
];
const FAN_OFFSETS_REDUCED: [number, number][] = [
  [0, -48], [0, -92], [0, -136], [0, -180], [0, -224], [0, -268],
];

type DrawerKey = "meta" | "conn" | "remind" | "history";

export default function NoteEditor({ open, path, onClose, onOpenExternal }: NoteEditorProps) {
  const [everOpened, setEverOpened] = useState(false);
  const [visible, setVisible] = useState(false);
  const [note, setNote] = useState<NoteContent | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [baseMtime, setBaseMtime] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "conflict" | "error">("idle");
  const [conflictBody, setConflictBody] = useState<string | null>(null);
  const [pinnedDrawer, setPinnedDrawer] = useState<DrawerKey | null>(null);
  const [hoverDrawer, setHoverDrawer] = useState<DrawerKey | null>(null);
  const [radialOpen, setRadialOpen] = useState(false);
  const [firedSpoke, setFiredSpoke] = useState<FormatKind | null>(null);
  const [mentions, setMentions] = useState<SearchResult[] | null>(null);
  const [reminderWhen, setReminderWhen] = useState("");
  const [reminderLabel, setReminderLabel] = useState("");
  const [reminderBusy, setReminderBusy] = useState(false);
  const [reminderDone, setReminderDone] = useState(false);

  // -- F-3: version history --
  const [historyStatus, setHistoryStatus] = useState<NoteHistoryStatus | null>(null);
  const [historyRevisions, setHistoryRevisions] = useState<NoteRevision[] | null>(null);
  const [historyExpanded, setHistoryExpanded] = useState<string | null>(null);
  const [historyPreviews, setHistoryPreviews] = useState<Record<string, string>>({});
  const [historyConfirming, setHistoryConfirming] = useState<string | null>(null);
  const [historyRestoring, setHistoryRestoring] = useState(false);
  const [historyToast, setHistoryToast] = useState<string | null>(null);

  // -- F-1: conflict resolver (desktop half) --
  const [conflict, setConflict] = useState<NoteConflict | null>(null);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [conflictBusy, setConflictBusy] = useState(false);

  // -- F-13 (desktop half): attachments --
  const [attachBusy, setAttachBusy] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastSavedBodyRef = useRef("");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reducedMotion = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // -- mount / open animation (mirrors DailyDigest.tsx exactly) --
  useEffect(() => {
    if (open && path) {
      setEverOpened(true);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    return undefined;
  }, [open, path]);

  // -- load note on open --
  useEffect(() => {
    if (!open || !path) return;
    let cancelled = false;
    setNote(null);
    setLoadError(null);
    setSaveState("idle");
    setConflictBody(null);
    setPinnedDrawer(null);
    setHoverDrawer(null);
    setRadialOpen(false);
    setMentions(null);
    setReminderDone(false);
    setHistoryStatus(null);
    setHistoryRevisions(null);
    setHistoryExpanded(null);
    setHistoryPreviews({});
    setHistoryConfirming(null);
    setConflict(null);
    setConflictOpen(false);
    setAttachError(null);
    getNoteContent(path)
      .then((n) => {
        if (cancelled) return;
        setNote(n);
        setBody(n.body);
        lastSavedBodyRef.current = n.body;
        setBaseMtime(n.mtime);
      })
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "Failed to load note"); });
    // F-1: conflict check is best-effort and never blocks note load.
    getNoteConflict(path)
      .then((c) => { if (!cancelled) setConflict(c); })
      .catch(() => { if (!cancelled) setConflict(null); });
    // F-3: prefetch history status (not the revision list -- that's still
    // lazy on drawer pin) so the instrument rail can hide the slot entirely
    // when Drive auth is absent, rather than surfacing that only after the
    // user clicks in.
    getNoteHistory(path)
      .then((r) => { if (!cancelled) { setHistoryStatus(r.status); setHistoryRevisions(r.revisions); } })
      .catch(() => { if (!cancelled) setHistoryStatus("offline"); });
    return () => { cancelled = true; };
  }, [open, path]);

  // -- debounced autosave; stops once a conflict is surfaced until the user reloads --
  useEffect(() => {
    if (!open || !path || baseMtime === null) return;
    if (saveState === "conflict") return;
    if (body === lastSavedBodyRef.current) return;
    setSaveState("saving");
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveNoteContent(path, body, baseMtime)
        .then((r) => {
          lastSavedBodyRef.current = body;
          setBaseMtime(r.mtime);
          setSaveState("saved");
        })
        .catch((err) => {
          if (err instanceof NoteConflictError) {
            setConflictBody(err.currentBody);
            setSaveState("conflict");
          } else {
            setSaveState("error");
          }
        });
    }, SAVE_DEBOUNCE_MS);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, open, path, baseMtime, saveState]);

  useEffect(() => () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); }, []);

  const reloadFromDisk = useCallback(() => {
    if (!path) return;
    getNoteContent(path).then((n) => {
      setNote(n);
      setBody(n.body);
      lastSavedBodyRef.current = n.body;
      setBaseMtime(n.mtime);
      setSaveState("idle");
      setConflictBody(null);
    }).catch(() => {});
  }, [path]);

  // -- Escape: close a drawer/radial first, else close the editor --
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (radialOpen) { setRadialOpen(false); return; }
      if (pinnedDrawer) { setPinnedDrawer(null); return; }
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, radialOpen, pinnedDrawer, onClose]);

  const applyFmt = useCallback((kind: FormatKind) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const r = applyMarkdownFormat(body, ta.selectionStart, ta.selectionEnd, kind);
    setBody(r.value);
    setFiredSpoke(kind);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(r.selStart, r.selEnd);
    });
    setTimeout(() => { setFiredSpoke(null); setRadialOpen(false); }, reducedMotion ? 0 : 420);
  }, [body, reducedMotion]);

  const scrollToLine = useCallback((line: number) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const lines = body.split("\n");
    const offset = lines.slice(0, line).reduce((n, l) => n + l.length + 1, 0);
    const lineHeight = parseFloat(getComputedStyle(ta).lineHeight || "22") || 22;
    ta.focus();
    ta.setSelectionRange(offset, offset + (lines[line]?.length ?? 0));
    ta.scrollTop = Math.max(0, line * lineHeight - ta.clientHeight / 3);
  }, [body]);

  const loadMentions = useCallback(() => {
    if (!note || mentions !== null) return;
    searchCaptures(note.title, { limit: 6 })
      .then((r) => setMentions(r.results.filter((x) => x.path !== note.path).slice(0, 5)))
      .catch(() => setMentions([]));
  }, [note, mentions]);

  const loadHistory = useCallback(() => {
    if (!note || historyStatus !== null) return;
    getNoteHistory(note.path)
      .then((r) => { setHistoryStatus(r.status); setHistoryRevisions(r.revisions); })
      .catch(() => { setHistoryStatus("offline"); setHistoryRevisions([]); });
  }, [note, historyStatus]);

  const toggleRevision = useCallback((rev: NoteRevision) => {
    setHistoryExpanded((cur) => {
      const next = cur === rev.id ? null : rev.id;
      if (next && !(rev.id in historyPreviews) && note) {
        getNoteHistoryRevision(note.path, rev.id)
          .then((r) => setHistoryPreviews((p) => ({ ...p, [rev.id]: r.body })))
          .catch(() => setHistoryPreviews((p) => ({ ...p, [rev.id]: "" })));
      }
      return next;
    });
    setHistoryConfirming(null);
  }, [historyPreviews, note]);

  const confirmRestore = useCallback((rev: NoteRevision) => {
    if (!note || baseMtime === null) return;
    const revBody = historyPreviews[rev.id];
    if (revBody === undefined) return;
    setHistoryRestoring(true);
    saveNoteContent(note.path, revBody, baseMtime)
      .then((r) => {
        setBody(revBody);
        lastSavedBodyRef.current = revBody;
        setBaseMtime(r.mtime);
        setSaveState("saved");
        setHistoryConfirming(null);
        setHistoryExpanded(null);
        setHistoryRestoring(false);
        setHistoryToast(`Restored rev ${rev.id.slice(0, 4)} — synced as a normal edit`);
        setTimeout(() => setHistoryToast(null), 2400);
      })
      .catch((err) => {
        setHistoryRestoring(false);
        if (err instanceof NoteConflictError) {
          setConflictBody(err.currentBody);
          setSaveState("conflict");
        }
      });
  }, [note, baseMtime, historyPreviews]);

  const showDrawer = useCallback((key: DrawerKey) => { if (!pinnedDrawer) setHoverDrawer(key); }, [pinnedDrawer]);
  const clearHoverDrawer = useCallback(() => { if (!pinnedDrawer) setHoverDrawer(null); }, [pinnedDrawer]);
  const togglePin = useCallback((key: DrawerKey) => {
    setPinnedDrawer((cur) => (cur === key ? null : key));
    setHoverDrawer(null);
    if (key === "conn") loadMentions();
    if (key === "history") loadHistory();
  }, [loadMentions, loadHistory]);

  const resolveConflict = useCallback((action: ConflictResolveAction) => {
    if (!note || !conflict) return;
    setConflictBusy(true);
    // "theirs" overwrites the note body, so pass the mtime we read when the
    // diff opened -- the server 409s (NoteConflictError) if the note was
    // edited on disk since, rather than clobbering that edit.
    resolveNoteConflict(note.path, conflict.conflict_path, action, conflict.local_mtime)
      .then(() => {
        setConflictBusy(false);
        setConflictOpen(false);
        setConflict(null);
        if (action === "theirs") reloadFromDisk();
      })
      .catch((err) => {
        setConflictBusy(false);
        if (err instanceof NoteConflictError) {
          // Stale diff: the note changed under us. Re-fetch fresh bodies +
          // mtime so the user resolves against what's actually on disk.
          getNoteConflict(note.path).then(setConflict).catch(() => {});
        }
      });
  }, [note, conflict, reloadFromDisk]);

  // F-13: attachment blocks parsed from the current body -- always reflects
  // what's actually on disk/in the textarea, no separate source of truth.
  const attachments = useMemo(() => parseAttachments(body), [body]);

  const handleAttachFile = useCallback((file: File | null) => {
    if (!file || !note || baseMtime === null) return;
    setAttachBusy(true);
    setAttachError(null);
    addNoteAttachment(note.path, file, baseMtime)
      .then((r) => {
        setAttachBusy(false);
        // Re-read from disk: the backend appended the link line + updated
        // `attachments` frontmatter directly (body-sacred normal file-write),
        // so the editor's in-memory body/mtime need to catch up.
        void r;
        reloadFromDisk();
      })
      .catch((err) => {
        setAttachBusy(false);
        if (err instanceof NoteConflictError) {
          setConflictBody(err.currentBody);
          setSaveState("conflict");
        } else {
          setAttachError(err instanceof Error ? err.message : "Failed to attach file");
        }
      });
  }, [note, baseMtime, reloadFromDisk]);

  if (!everOpened || !path) return null;

  const activeDrawer = pinnedDrawer ?? hoverDrawer;
  const drawerOpen = activeDrawer !== null;

  // -- styles --
  const wrapStyle: CSSProperties = {
    position: "absolute", inset: 0, zIndex: 20,
    background: "var(--bg)",
    display: "flex", flexDirection: "column",
    opacity: visible ? 1 : 0,
    transform: visible ? "translateY(0)" : (reducedMotion ? "none" : "translateY(8px)"),
    pointerEvents: visible ? "auto" : "none",
    transition: `opacity ${reducedMotion ? 1 : DUR}ms ${TRAVEL}, transform ${reducedMotion ? 1 : DUR}ms ${TRAVEL}`,
  };
  const topbarStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, padding: "0 14px",
    height: 46, borderBottom: "1px solid var(--border-2)", flex: "none",
  };
  const iconBtnStyle: CSSProperties = {
    width: 28, height: 28, display: "inline-flex", alignItems: "center", justifyContent: "center",
    background: "none", border: "1px solid transparent", color: "var(--text-2)", cursor: "pointer",
    transition: `color ${DUR}ms ${SETTLE}, border-color ${DUR}ms ${SETTLE}`,
  };
  const titleStyle: CSSProperties = {
    fontSize: 14, fontWeight: 600, letterSpacing: "-0.02em", color: "var(--text-1)",
    flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  };
  const dotColor = saveState === "conflict" ? "var(--red)" : saveState === "saving" ? "var(--yellow)" : "var(--green)";
  const syncLabel = saveState === "conflict" ? "conflict" : saveState === "saving" ? "saving" : saveState === "error" ? "save failed" : "synced";
  const syncStyle: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-3)" };
  const dotStyle: CSSProperties = { width: 6, height: 6, borderRadius: "50%", background: dotColor, transition: `background ${DUR}ms ${SETTLE}` };

  const bodyRowStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", position: "relative" };
  const contentStyle: CSSProperties = { flex: 1, minWidth: 0, overflowY: "auto", position: "relative" };
  const measureStyle: CSSProperties = { maxWidth: "62ch", margin: "0 auto", width: "100%", padding: "24px 24px 96px" };
  const h1Style: CSSProperties = { fontSize: 21, fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 16px", color: "var(--text-1)" };
  const paperStyle: CSSProperties = {
    width: "100%", minHeight: 380, background: "transparent", border: "none", color: "var(--text-1)",
    font: "inherit", fontSize: 13.5, lineHeight: 1.75, resize: "none", padding: 0, outline: "none",
  };

  const railStyle: CSSProperties = {
    width: 48, flex: "0 0 48px", borderLeft: "1px solid var(--border-2)",
    display: "flex", flexDirection: "column", alignItems: "center", padding: "12px 0", gap: 8,
  };
  function instBtnStyle(pinned: boolean, disabled?: boolean): CSSProperties {
    return {
      width: 34, height: 34, display: "flex", alignItems: "center", justifyContent: "center",
      background: pinned ? "var(--accent-d)" : "none",
      border: pinned ? "1px solid var(--border)" : "1px solid transparent",
      color: disabled ? "var(--border)" : pinned ? "var(--text-1)" : "var(--text-3)",
      cursor: disabled ? "default" : "pointer",
      transition: `color ${DUR}ms ${SETTLE}, border-color ${DUR}ms ${SETTLE}, background ${DUR}ms ${SETTLE}`,
    };
  }
  const drawerStyle: CSSProperties = {
    position: "absolute", top: 0, right: 48, bottom: 0,
    width: drawerOpen ? 236 : 0, overflow: "hidden",
    background: "var(--surface)", borderLeft: drawerOpen ? "1px solid var(--border)" : "1px solid transparent",
    transition: `width ${DUR}ms ${TRAVEL}`, zIndex: 6,
  };
  const drawerInnerStyle: CSSProperties = { width: 236, height: "100%", overflowY: "auto", paddingBottom: 14 };
  const drawerHeadStyle: CSSProperties = {
    fontSize: 11, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase",
    padding: "12px 14px 8px", borderBottom: "1px solid var(--border-2)", marginBottom: 4,
  };

  const fmtZoneStyle: CSSProperties = { position: "absolute", bottom: 16, right: 16, zIndex: 12, width: 44, height: 44 };
  const fmtDialStyle: CSSProperties = {
    position: "absolute", bottom: 0, right: 0, width: 44, height: 44, borderRadius: "50%",
    background: "var(--surface)", border: `1px solid ${radialOpen ? "var(--accent)" : "var(--border)"}`,
    color: "var(--text-1)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
    boxShadow: radialOpen ? "0 0 0 5px var(--accent-glow)" : "none",
    transition: `border-color ${DUR}ms ${SETTLE}, box-shadow ${DUR}ms ${SETTLE}`,
    zIndex: 2,
  };

  return (
    <div style={wrapStyle} role="dialog" aria-label="Note editor">
      <div style={topbarStyle} className="no-drag">
        <button style={iconBtnStyle} onClick={onClose} aria-label="Back" title="Back">
          <IconBack />
        </button>
        <span style={titleStyle}>{note?.title ?? "…"}</span>
        {note && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: "none" }}
              onChange={(e) => { handleAttachFile(e.target.files?.[0] ?? null); e.target.value = ""; }}
            />
            <button
              style={iconBtnStyle}
              onClick={() => fileInputRef.current?.click()}
              disabled={attachBusy}
              aria-label="Attach a file"
              title="Attach a file"
            >
              <IconAttach size={15} />
            </button>
          </>
        )}
        <span style={syncStyle}><span style={dotStyle} /> {syncLabel}</span>
      </div>
      {attachError && (
        <div style={{ padding: "4px 14px", fontSize: 11, color: "var(--red)" }}>{attachError}</div>
      )}

      {loadError && (
        <div style={{ padding: 14, color: "var(--red)", fontSize: 12 }}>{loadError}</div>
      )}

      {conflict && !conflictOpen && (
        <button
          onClick={() => setConflictOpen(true)}
          style={{
            display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
            background: "none", border: "none", borderBottom: "1px solid color-mix(in srgb, var(--red) 35%, transparent)",
            padding: "6px 14px", fontSize: 11, color: "var(--red)", cursor: "pointer", font: "inherit",
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)", flex: "none" }} />
          Conflicted copy exists
          <span style={{ marginLeft: "auto", color: "var(--text-2)", textDecoration: "underline", textUnderlineOffset: 3 }}>Resolve</span>
        </button>
      )}

      {saveState === "conflict" && conflictBody !== null && (
        <div style={{
          display: "flex", alignItems: "center", gap: 10, padding: "8px 14px",
          background: "var(--accent-d)", borderBottom: "1px solid var(--border-2)",
          fontSize: 11.5, color: "var(--text-2)",
        }}>
          <span style={{ width: 6, height: 6, background: "var(--red)", flex: "none" }} />
          <span style={{ flex: 1 }}>
            This note changed on disk since it was opened. Your edits here are kept, but not saved yet.
          </span>
          <button
            style={{ font: "inherit", fontSize: 10.5, color: "var(--text-1)", background: "var(--surface)", border: "1px solid var(--border)", padding: "3px 9px", cursor: "pointer" }}
            onClick={reloadFromDisk}
          >
            RELOAD (discards local edits)
          </button>
        </div>
      )}

      {note && (
        <div style={bodyRowStyle}>
          <div style={contentStyle}>
            <div style={measureStyle}>
              <h1 style={h1Style}>{note.title}</h1>
              <textarea
                ref={textareaRef}
                style={paperStyle}
                aria-label="Note body (editable)"
                spellCheck={false}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />

              {/* F-13: attachment blocks -- image thumbnail / inline audio
                  player / generic file link, one per `[attachment: ...]`
                  link found in the body above. Display-only here; authoring
                  happens via the topbar attach button. */}
              {attachments.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 20 }}>
                  {attachments.map((a) => (
                    <div key={a.filename} style={{ border: "1px solid var(--border)" }}>
                      <div style={{
                        display: "flex", alignItems: "center", gap: 6, fontSize: 10,
                        letterSpacing: "0.08em", color: "var(--text-3)", padding: "6px 10px",
                        borderBottom: "1px solid var(--border-2)", textTransform: "uppercase",
                      }}>
                        {a.kind === "audio" ? "VOICE MEMO" : a.kind === "image" ? "IMAGE" : "FILE"} · {a.filename}
                      </div>
                      {a.kind === "image" && (
                        <img
                          src={attachmentUrl(note.path, a.filename)}
                          alt={a.filename}
                          style={{ display: "block", width: "100%", maxHeight: 320, objectFit: "contain", background: "var(--surface)" }}
                        />
                      )}
                      {a.kind === "audio" && (
                        // ponytail: native <audio controls> instead of the mock's
                        // custom waveform scrubber -- zero-dependency playback that
                        // covers the same job (play/pause/seek/time); revisit with a
                        // custom waveform only if the native control visibly falls short.
                        <audio controls style={{ width: "100%", display: "block" }} src={attachmentUrl(note.path, a.filename)} />
                      )}
                      {a.kind === "file" && (
                        <a
                          href={attachmentUrl(note.path, a.filename)}
                          target="_blank"
                          rel="noreferrer"
                          style={{ display: "block", padding: "10px 12px", fontSize: 12, color: "var(--text-2)" }}
                        >
                          Open {a.filename}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Radial formatting instrument — reuses Minimal capture-radial mechanics:
                plus->X toggle, RADIAL_STAGGER_MS fan-out, reduced-motion static column. */}
            <div style={fmtZoneStyle}>
              {radialOpen && (
                <span style={{
                  position: "absolute", bottom: 52, right: 52, fontSize: 10.5, color: "var(--text-3)",
                  background: "var(--glass-bg)", border: "1px solid var(--border-2)", padding: "3px 8px",
                  whiteSpace: "nowrap", zIndex: 11,
                }}>
                  Select text, then pick an action
                </span>
              )}
              {FMT_ORDER.map((f, i) => {
                const [ox, oy] = (reducedMotion ? FAN_OFFSETS_REDUCED : FAN_OFFSETS)[i];
                const fired = firedSpoke === f.kind;
                const spokeStyle: CSSProperties = {
                  position: "absolute", bottom: 4, right: 4, width: 36, height: 36, borderRadius: "50%",
                  background: "var(--glass-bg)", border: `1px solid ${fired ? "var(--green)" : "var(--border)"}`,
                  color: fired ? "var(--green)" : "var(--text-3)",
                  display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
                  opacity: radialOpen ? 1 : 0,
                  pointerEvents: radialOpen ? "auto" : "none",
                  transform: radialOpen ? `translate(${ox}px, ${oy}px) scale(1)` : "translate(0,0) scale(0.5)",
                  transitionProperty: "transform, opacity, color, border-color",
                  transitionDuration: `${reducedMotion ? 1 : 260}ms, ${reducedMotion ? 1 : 160}ms, 160ms, 160ms`,
                  transitionTimingFunction: `${TRAVEL}, ${SETTLE}, ${SETTLE}, ${SETTLE}`,
                  transitionDelay: radialOpen ? `${i * RADIAL_STAGGER_MS}ms` : "0ms",
                };
                return (
                  <button key={f.kind} style={spokeStyle} aria-label={f.label} title={f.label} onClick={() => applyFmt(f.kind)}>
                    <FmtIcon kind={f.kind} />
                  </button>
                );
              })}
              <button
                style={fmtDialStyle}
                aria-label="Formatting actions"
                aria-expanded={radialOpen}
                title="Formatting (radial)"
                onClick={() => setRadialOpen((v) => !v)}
              >
                <span style={{ display: "flex", transform: radialOpen ? "rotate(45deg)" : "none", transition: `transform ${reducedMotion ? 1 : DUR}ms ${TRAVEL}` }}>
                  <IconPlus />
                </span>
              </button>
            </div>
          </div>

          {/* Instrument rail (right edge) — hover previews, click pins */}
          <nav style={railStyle} aria-label="Instrument dock">
            <button
              style={instBtnStyle(pinnedDrawer === "meta")}
              aria-label="Metadata" title="Metadata"
              onMouseEnter={() => showDrawer("meta")} onMouseLeave={clearHoverDrawer}
              onClick={() => togglePin("meta")}
            ><IconMeta /></button>
            <button
              style={instBtnStyle(pinnedDrawer === "conn")}
              aria-label="Connections and outline" title="Connections & outline"
              onMouseEnter={() => showDrawer("conn")} onMouseLeave={clearHoverDrawer}
              onClick={() => togglePin("conn")}
            ><IconConnections /></button>
            <button
              style={instBtnStyle(pinnedDrawer === "remind")}
              aria-label="Remind me" title="Remind me"
              onMouseEnter={() => showDrawer("remind")} onMouseLeave={clearHoverDrawer}
              onClick={() => togglePin("remind")}
            ><BellIcon size={16} /></button>
            {historyStatus !== "offline" && (
              <button
                style={instBtnStyle(pinnedDrawer === "history")}
                aria-label="Version history" title="Version history"
                onMouseEnter={() => showDrawer("history")} onMouseLeave={clearHoverDrawer}
                onClick={() => togglePin("history")}
              ><ClockIcon size={16} /></button>
            )}
            <button
              style={instBtnStyle(false)}
              aria-label="Open in external editor" title="Open in your set markdown editor"
              onClick={() => onOpenExternal(note.path)}
            ><IconExternal /></button>
          </nav>

          {/* Drawers */}
          <div style={drawerStyle}>
            {drawerOpen && activeDrawer === "meta" && (
              <div style={drawerInnerStyle}>
                <div style={drawerHeadStyle}>METADATA</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "8px 14px", fontSize: 11.5, color: "var(--text-3)" }}>
                  <span>category: <b style={{ color: "var(--text-2)" }}>{note.category}</b></span>
                  <span>status: <b style={{ color: "var(--text-2)" }}>{note.status ?? "—"}</b></span>
                  {note.tags.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {note.tags.map((t) => (
                        <span key={t} style={{ border: "1px solid var(--border)", padding: "2px 6px", fontSize: 10.5 }}>{t}</span>
                      ))}
                    </div>
                  )}
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    <IconLock /> machine-owned · read-only here
                  </span>
                </div>
              </div>
            )}
            {drawerOpen && activeDrawer === "conn" && (
              <ConnectionsDrawer body={body} mentions={mentions} onJump={scrollToLine} />
            )}
            {drawerOpen && activeDrawer === "history" && (
              <HistoryDrawer
                status={historyStatus}
                revisions={historyRevisions}
                expanded={historyExpanded}
                previews={historyPreviews}
                confirming={historyConfirming}
                restoring={historyRestoring}
                onToggle={toggleRevision}
                onAskRestore={setHistoryConfirming}
                onCancelRestore={() => setHistoryConfirming(null)}
                onConfirmRestore={confirmRestore}
                onRetry={() => { setHistoryStatus(null); loadHistory(); }}
              />
            )}
            {drawerOpen && activeDrawer === "remind" && (
              <div style={drawerInnerStyle}>
                <div style={drawerHeadStyle}>REMIND ME</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "10px 14px" }}>
                  <label style={{ fontSize: 10.5, color: "var(--text-3)" }} htmlFor="ne-remind-when">When</label>
                  {/* ponytail: mock shows a free-text "Tomorrow, 9:00 AM" field, which
                      implies NLP date parsing. Using a native datetime-local input
                      instead avoids a new parsing dependency and gives an
                      unambiguous ISO value for free. */}
                  <input id="ne-remind-when" type="datetime-local" value={reminderWhen} onChange={(e) => setReminderWhen(e.target.value)} />
                  <label style={{ fontSize: 10.5, color: "var(--text-3)" }} htmlFor="ne-remind-label">Label</label>
                  <input id="ne-remind-label" type="text" value={reminderLabel} onChange={(e) => setReminderLabel(e.target.value)} placeholder={note.title} />
                  <button
                    style={{ alignSelf: "flex-start", font: "inherit", fontSize: 11, color: "var(--text-1)", background: "var(--surface-2)", border: "1px solid var(--border)", padding: "5px 12px", cursor: "pointer" }}
                    disabled={!reminderWhen || reminderBusy}
                    onClick={() => {
                      setReminderBusy(true);
                      createReminder(note.path, reminderLabel || note.title, reminderWhen)
                        .then(() => { setReminderDone(true); setReminderBusy(false); })
                        .catch(() => setReminderBusy(false));
                    }}
                  >
                    {reminderBusy ? "SETTING…" : "SET REMINDER"}
                  </button>
                  {reminderDone && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--green)" }}>
                      <IconCheck size={13} /> Reminder set
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {conflictOpen && conflict && (
        <ConflictResolverOverlay
          conflict={conflict}
          busy={conflictBusy}
          onResolve={resolveConflict}
          onClose={() => setConflictOpen(false)}
        />
      )}

      {historyToast && (
        <div style={{
          position: "absolute", left: "50%", bottom: 18, transform: "translateX(-50%)",
          background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-1)",
          fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 8, zIndex: 30,
        }}>
          <IconCheck size={13} /> {historyToast}
        </div>
      )}
    </div>
  );
}

function HistoryDrawer({
  status, revisions, expanded, previews, confirming, restoring,
  onToggle, onAskRestore, onCancelRestore, onConfirmRestore, onRetry,
}: {
  status: NoteHistoryStatus | null;
  revisions: NoteRevision[] | null;
  expanded: string | null;
  previews: Record<string, string>;
  confirming: string | null;
  restoring: boolean;
  onToggle: (rev: NoteRevision) => void;
  onAskRestore: (id: string) => void;
  onCancelRestore: () => void;
  onConfirmRestore: (rev: NoteRevision) => void;
  onRetry: () => void;
}) {
  const rowStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", fontSize: 11.5,
    color: "var(--text-2)", cursor: "pointer", border: "none", background: "none", font: "inherit",
    width: "100%", textAlign: "left", borderBottom: "1px solid var(--border-2)",
  };
  const statePanelStyle: CSSProperties = {
    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
    gap: 10, padding: 24, textAlign: "center", color: "var(--text-3)",
  };

  return (
    <div style={{ width: 236, height: "100%", overflowY: "auto", paddingBottom: 14 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase", padding: "12px 14px 8px", borderBottom: "1px solid var(--border-2)", marginBottom: 4 }}>
        VERSION HISTORY
      </div>
      {status === null && (
        <div style={{ padding: "6px 14px", fontSize: 11.5, color: "var(--text-3)" }}>Loading…</div>
      )}
      {status === "offline" && (
        <div style={statePanelStyle}>
          <IconOffline size={22} />
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>Can&apos;t reach Drive</span>
          <span style={{ fontSize: 10.5 }}>Revision history lives on the hub.</span>
          <button
            style={{ font: "inherit", fontSize: 10.5, color: "var(--text-1)", background: "var(--surface)", border: "1px solid var(--border)", padding: "3px 9px", cursor: "pointer" }}
            onClick={onRetry}
          >
            RETRY
          </button>
        </div>
      )}
      {status === "not_synced" && (
        <div style={statePanelStyle}>
          <IconNotSynced size={22} />
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>Hasn&apos;t synced yet</span>
          <span style={{ fontSize: 10.5 }}>Versions appear after the first Drive sync.</span>
        </div>
      )}
      {status === "ok" && revisions && revisions.length === 0 && (
        <div style={{ padding: "6px 14px", fontSize: 11.5, color: "var(--text-3)" }}>No revisions yet.</div>
      )}
      {status === "ok" && revisions?.map((rev) => {
        const open = expanded === rev.id;
        const preview = previews[rev.id];
        return (
          <div key={rev.id}>
            <button
              style={{ ...rowStyle, cursor: rev.current ? "default" : "pointer" }}
              onClick={() => !rev.current && onToggle(rev)}
              aria-expanded={open}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: rev.current ? "var(--green)" : "var(--text-3)", flex: "none" }} />
              <span style={{ color: "var(--text-1)" }}>rev {rev.id.slice(0, 4)}</span>
              <span style={{ marginLeft: "auto", color: "var(--text-3)", fontSize: 10 }}>
                {rev.modified_time ? new Date(rev.modified_time).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—"}
              </span>
              {rev.current
                ? <span style={{ fontSize: 9.5, color: "var(--green)", letterSpacing: "0.06em" }}>CURRENT</span>
                : <IconChevron open={open} />}
            </button>
            {open && !rev.current && (
              <div style={{ padding: "0 14px 12px" }}>
                <div style={{
                  background: "var(--glass-bg)", border: "1px solid var(--glass-border)",
                  fontSize: 11, lineHeight: 1.6, color: "var(--text-2)", padding: 8,
                  maxHeight: 128, overflowY: "auto", whiteSpace: "pre-wrap", marginBottom: 8,
                }}>
                  {preview === undefined ? "…" : (preview || "(empty)")}
                </div>
                {confirming !== rev.id ? (
                  <button
                    style={{ font: "inherit", fontSize: 10.5, color: "var(--text-1)", background: "var(--surface-2)", border: "1px solid var(--border)", padding: "4px 10px", cursor: "pointer" }}
                    disabled={preview === undefined}
                    onClick={() => onAskRestore(rev.id)}
                  >
                    Restore this version
                  </button>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, border: "1px solid var(--yellow)", padding: 8, fontSize: 10.5, color: "var(--text-2)" }}>
                    <span>Restores body onto current frontmatter — becomes a normal edit that syncs.</span>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        style={{ font: "inherit", fontSize: 10.5, color: "var(--on-accent)", background: "var(--accent)", border: "none", padding: "4px 10px", cursor: "pointer" }}
                        disabled={restoring}
                        onClick={() => onConfirmRestore(rev)}
                      >
                        {restoring ? "RESTORING…" : "CONFIRM"}
                      </button>
                      <button
                        style={{ font: "inherit", fontSize: 10.5, color: "var(--text-2)", background: "none", border: "1px solid var(--border)", padding: "4px 10px", cursor: "pointer" }}
                        onClick={onCancelRestore}
                      >
                        CANCEL
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// -- F-1: conflict resolver overlay (desktop) --------------------------------
// Mirrors mock 06-conflict-resolver.html's desktop pane: two-column line diff,
// green=local/yours, red=remote/theirs, three explicit actions (keep-both is
// the safe default — it destroys nothing).
function ConflictResolverOverlay({
  conflict, busy, onResolve, onClose,
}: {
  conflict: NoteConflict;
  busy: boolean;
  onResolve: (action: ConflictResolveAction) => void;
  onClose: () => void;
}) {
  const rows = diffLines(conflict.local_body, conflict.remote_body);
  const colStyle: CSSProperties = { flex: 1, minWidth: 0, overflowY: "auto", borderRight: "1px solid var(--border-2)" };
  const headStyle: CSSProperties = {
    fontSize: 10, letterSpacing: "0.08em", color: "var(--text-2)", padding: "8px 10px",
    borderBottom: "1px solid var(--border-2)", display: "flex", alignItems: "center", gap: 6, position: "sticky", top: 0, background: "var(--surface)",
  };
  const lineStyle = (kind: "same" | "local-only" | "remote-only", side: "local" | "remote"): CSSProperties => {
    const highlight = (kind === "local-only" && side === "local") || (kind === "remote-only" && side === "remote");
    return {
      fontSize: 11, lineHeight: 1.7, padding: "1px 10px", whiteSpace: "pre-wrap", overflowWrap: "break-word",
      color: highlight ? "var(--text-1)" : "var(--text-2)",
      background: highlight ? (side === "local" ? "rgba(74,222,128,0.08)" : "rgba(255,100,103,0.08)") : "transparent",
      boxShadow: highlight ? `inset 2px 0 0 ${side === "local" ? "var(--green)" : "var(--red)"}` : "none",
      minHeight: "1.7em",
    };
  };
  const actionBtn = (kind: "primary" | "ghost"): CSSProperties => ({
    font: "inherit", fontSize: 11.5, padding: "6px 14px", cursor: busy ? "default" : "pointer",
    border: kind === "primary" ? "none" : "1px solid var(--border)",
    background: kind === "primary" ? "var(--accent)" : "none",
    color: kind === "primary" ? "var(--on-accent)" : "var(--text-2)",
    opacity: busy ? 0.6 : 1,
  });

  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 25, background: "var(--bg)", display: "flex", flexDirection: "column" }} role="dialog" aria-label="Resolve conflict">
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 14px", height: 46, borderBottom: "1px solid var(--border-2)", flex: "none" }}>
        <button style={{ width: 28, height: 28, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "none", border: "1px solid var(--border)", color: "var(--text-2)", cursor: "pointer" }} onClick={onClose} aria-label="Back" title="Back">
          <IconBack />
        </button>
        <span style={{ fontSize: 12, letterSpacing: "0.06em", color: "var(--text-1)", fontWeight: 600 }}>RESOLVE CONFLICT</span>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <div style={colStyle}>
          <div style={headStyle}><span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)" }} />YOURS · THIS DEVICE</div>
          {rows.map((r, i) => <div key={i} style={lineStyle(r.kind, "local")}>{r.local ?? ""}</div>)}
        </div>
        <div style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
          <div style={headStyle}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)" }} />
            {(conflict.remote_device ?? "REMOTE").toUpperCase()}{conflict.remote_modified ? ` · ${new Date(conflict.remote_modified).toLocaleString()}` : ""}
          </div>
          {rows.map((r, i) => <div key={i} style={lineStyle(r.kind, "remote")}>{r.remote ?? ""}</div>)}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, padding: "10px 14px", borderTop: "1px solid var(--border-2)", flexWrap: "wrap", flex: "none" }}>
        <button style={actionBtn("primary")} disabled={busy} onClick={() => onResolve("both")}>Keep both</button>
        <button style={actionBtn("ghost")} disabled={busy} onClick={() => onResolve("mine")}>Keep mine</button>
        <button style={actionBtn("ghost")} disabled={busy} onClick={() => onResolve("theirs")}>Keep theirs</button>
      </div>
    </div>
  );
}

function ConnectionsDrawer({ body, mentions, onJump }: { body: string; mentions: SearchResult[] | null; onJump: (line: number) => void }) {
  const links = parseWikilinks(body);
  const outline = parseOutline(body);
  const rowStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "7px 14px", fontSize: 12,
    color: "var(--text-2)", cursor: "pointer", border: "none", background: "none", font: "inherit",
    width: "100%", textAlign: "left",
  };
  const groupStyle: CSSProperties = { fontSize: 10.5, letterSpacing: "0.08em", color: "var(--text-3)", padding: "10px 14px 4px", textTransform: "uppercase" };
  return (
    <div style={{ width: 236, height: "100%", overflowY: "auto", paddingBottom: 14 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase", padding: "12px 14px 8px", borderBottom: "1px solid var(--border-2)", marginBottom: 4 }}>
        CONNECTIONS
      </div>
      {links.length === 0 && <div style={{ padding: "6px 14px", fontSize: 11.5, color: "var(--text-3)" }}>No linked notes yet.</div>}
      {links.map((l) => <div key={l} style={rowStyle}>{l}</div>)}

      {/* ponytail: unlinked-mention "LINK" one-click action (in the approved
          mock) would need a backend endpoint that mutates the *mentioning*
          note's body to insert a wikilink — real scope, deferred. This shows
          mentions read-only via the existing /search endpoint (no new
          backend surface) rather than half-building that mutation. */}
      {mentions === null && <div style={{ padding: "6px 14px", fontSize: 11, color: "var(--text-3)" }}>…</div>}
      {mentions !== null && mentions.length > 0 && (
        <>
          <div style={groupStyle}>MENTIONS</div>
          {mentions.map((m) => (
            <div key={m.path} style={rowStyle} title={m.path}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.filename ?? m.path}</span>
            </div>
          ))}
        </>
      )}

      <div style={groupStyle}>OUTLINE</div>
      {outline.length === 0 && <div style={{ padding: "6px 14px", fontSize: 11.5, color: "var(--text-3)" }}>No headings.</div>}
      {outline.map((o) => (
        <button key={o.line} style={{ ...rowStyle, paddingLeft: 14 + (o.level - 1) * 10, color: "var(--text-3)" }} onClick={() => onJump(o.line)}>
          {o.text}
        </button>
      ))}
    </div>
  );
}
