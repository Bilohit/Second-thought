import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { flushSync } from "react-dom";
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
  fetchAttachmentBlob,
  createNote,
  moveToTrash,
  NoteConflictError,
  type NoteContent,
  type SearchResult,
  type NoteRevision,
  type NoteHistoryStatus,
  type NoteConflict,
  type ConflictResolveAction,
} from "../lib/api";
import { applyMarkdownFormat, parseOutline, parseWikilinks, type FormatKind } from "../lib/noteFormat";
import { displayProject } from "../lib/projectsView";
import { parseAttachments, attachErrorMessage, NO_ATTACH_HINT } from "../lib/attachments";
import { isSaveRetry, saveRetryDelayMs } from "../lib/saveRetry";
import { logger } from "../lib/logger";
import { diffLines } from "../lib/lineDiff";
import { BellIcon, ClockIcon, BoldIcon, ChecklistIcon } from "./PillMenu/icons";
import { Markdown } from "./Markdown";
import { TagChip } from "./TagChip";
import { parseBlocks } from "../lib/markdown";

const TRAVEL = "cubic-bezier(0.22,1,0.36,1)";
const SETTLE = "cubic-bezier(0.16,1,0.3,1)";
const DUR = 260;
// Task 10 (E): the format toolbar's clipping edge box width AND the distance
// the toolbar translates to hide itself off that edge -- these two used to be
// the same "46" written twice with nothing forcing them to agree (that
// mismatch was the peek-edge bug). One constant, used in both fmtEdgeStyle
// and toolbarColStyle below.
const TOOLBAR_EDGE_W = 52;
// Autosave debounce + failure backoff live in lib/saveRetry.ts (GUI-18).

interface NoteEditorProps {
  open: boolean;
  path: string | null;
  onClose: () => void;
  onOpenExternal: (path: string) => void;
  /** Task 9 (C1): NoteEditor no longer owns its own top bar -- FullWindow's
   *  shared topbar hosts it instead, the same seam InboxPanel/CompactQuickNote
   *  already use to lift controls into CompactShell's `headerActions` slot.
   *  Receives the back control, note title, sync state, and (once a note is
   *  loaded) the mode toggle / open-external / more-menu trio, or `null` on
   *  unmount. */
  onHeaderActionsChange?: (actions: React.ReactNode | null) => void;
}

// -- local icons (feature-specific glyphs; Bell/Clock/Bold/Checklist reused from PillMenu/icons.tsx) --

function IconBack(props: { size?: number }) {
  const size = props.size ?? 15;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M15 5l-7 7 7 7" />
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
function LinkFmtIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <rect x="4" y="7" width="10" height="5" rx="2.5" transform="rotate(45 9 9.5)" />
      <rect x="10" y="13" width="10" height="5" rx="2.5" transform="rotate(45 15 15.5)" />
    </svg>
  );
}
function TagIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M11 3H4a1 1 0 00-1 1v7a1 1 0 00.29.71l9 9a1 1 0 001.42 0l7-7a1 1 0 000-1.42l-9-9A1 1 0 0011 3z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="7.5" cy="7.5" r="1" fill="currentColor" />
    </svg>
  );
}
function MicIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v2a7 7 0 0 0 14 0v-2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 19v3M8 22h8" strokeLinecap="round" />
    </svg>
  );
}
function CameraIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round">
      <path d="M4 7h3l1.5-2h7L17 7h3v12H4V7z" />
      <circle cx="12" cy="13" r="3.3" />
    </svg>
  );
}
function MoreIcon(props: { size?: number }) {
  const size = props.size ?? 16;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <circle cx="12" cy="5.5" r="1.3" fill="currentColor" />
      <circle cx="12" cy="12" r="1.3" fill="currentColor" />
      <circle cx="12" cy="18.5" r="1.3" fill="currentColor" />
    </svg>
  );
}
function OutlineIcon(props: { size?: number }) {
  const size = props.size ?? 14;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6h16M8 12h12M8 18h12" />
      <circle cx="4" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="4" cy="18" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
function IconEye(props: { size?: number }) {
  const size = props.size ?? 15;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function IconPencil(props: { size?: number }) {
  const size = props.size ?? 15;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
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
const FMT_ORDER: { kind: FormatKind; label: string; Icon: (p: { size?: number }) => JSX.Element }[] = [
  { kind: "bold", label: "Bold", Icon: BoldIcon },
  { kind: "checklist", label: "Checklist", Icon: ChecklistIcon },
  { kind: "link", label: "Link", Icon: LinkFmtIcon },
  { kind: "tag", label: "Tag", Icon: TagIcon },
];

type DrawerKey = "meta" | "conn" | "remind" | "history";

export default function NoteEditor({ open, path, onClose, onOpenExternal, onHeaderActionsChange }: NoteEditorProps) {
  const [visible, setVisible] = useState(false);
  const [note, setNote] = useState<NoteContent | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [mode, setMode] = useState<"view" | "edit">("edit");
  const [baseMtime, setBaseMtime] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "conflict" | "error">("idle");
  const [conflictBody, setConflictBody] = useState<string | null>(null);
  const [pinnedDrawer, setPinnedDrawer] = useState<DrawerKey | null>(null);
  const [toolbarPeeking, setToolbarPeeking] = useState(false);
  const [toolbarLocked, setToolbarLocked] = useState(false);
  const [firedFmt, setFiredFmt] = useState<FormatKind | null>(null);
  const toolbarOut = toolbarPeeking || toolbarLocked;
  const [mentions, setMentions] = useState<SearchResult[] | null>(null);
  const [reminderWhen, setReminderWhen] = useState("");
  const [reminderLabel, setReminderLabel] = useState("");
  const [reminderBusy, setReminderBusy] = useState(false);
  const [reminderDone, setReminderDone] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

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
  // Wave 6 (O-8c): resolution collapses the overlay (panel-collapse, DUR/SETTLE)
  // instead of an instant unmount, then a toast confirms the outcome.
  const [conflictClosing, setConflictClosing] = useState(false);

  // -- F-13 (desktop half): attachments --
  const [attachBusy, setAttachBusy] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [attachFilter, setAttachFilter] = useState<string>("*/*");

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastSavedBodyRef = useRef("");
  // GUI-18: last body actually *sent* (as opposed to successfully saved) plus
  // its consecutive-failure count — together these drive the autosave backoff.
  const lastAttemptedBodyRef = useRef<string | null>(null);
  const saveFailuresRef = useRef(0);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Task 8: New Note support (null `path`) — the note is created on the
  // FIRST KEYSTROKE, never on open/click, mirroring
  // CompactPanels/CompactQuickNote.tsx's identical create-on-type +
  // getNoteContent()-for-a-real-mtime sequence. `creatingRef` guards
  // re-entrant creates while that round trip is in flight; `mountedRef`
  // detects the editor having been navigated away from (unmounted) before it
  // resolves, so an abandoned, never-shown, never-autosaved-into note file
  // doesn't silently persist (same orphan concern CompactQuickNote guards).
  const creatingRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const reducedMotion = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // -- mount / open animation (mirrors DailyDigest.tsx exactly). Keyed on
  // `open` alone, not `[open, path]` -- a New Note (null `path` until the
  // first keystroke creates one) must still fade in. --
  useEffect(() => {
    if (open) {
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = () => setMenuOpen(false);
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [menuOpen]);

  // -- load note on open --
  useEffect(() => {
    if (!open || !path) return;
    let cancelled = false;
    setNote(null);
    setLoadError(null);
    setSaveState("idle");
    setMode("edit");
    setConflictBody(null);
    setPinnedDrawer(null);
    setMenuOpen(false);
    setToolbarPeeking(false);
    setToolbarLocked(false);
    lockPriorModeRef.current = null;
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

  // -- debounced autosave; stops once a conflict is surfaced until the user reloads.
  // Keyed on `note` (not the raw `path` prop): a New Note is created
  // internally on first keystroke without ever changing the `path` prop (see
  // handleNewNoteChange below), so `note`/`baseMtime` are the source of truth
  // for "is there something real to save to" in both the opened-existing-note
  // and just-self-created-note cases. --
  useEffect(() => {
    if (!open || !note || baseMtime === null) return;
    if (saveState === "conflict") return;
    if (body === lastSavedBodyRef.current) return;
    // GUI-18: a failed save leaves lastSavedBodyRef untouched, so this effect
    // re-fires on the identical body. Track the last *attempted* body too and
    // back the retry off, instead of hammering a failing endpoint at the plain
    // debounce interval forever.
    const retrying = isSaveRetry(body, lastAttemptedBodyRef.current);
    if (!retrying) saveFailuresRef.current = 0;
    const delay = saveRetryDelayMs(saveFailuresRef.current);
    const savePath = note.path;

    setSaveState("saving");
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      lastAttemptedBodyRef.current = body;
      saveNoteContent(savePath, body, baseMtime)
        .then((r) => {
          saveFailuresRef.current = 0;
          lastSavedBodyRef.current = body;
          setBaseMtime(r.mtime);
          setSaveState("saved");
        })
        .catch((err) => {
          if (err instanceof NoteConflictError) {
            saveFailuresRef.current = 0;
            setConflictBody(err.currentBody);
            setSaveState("conflict");
          } else {
            saveFailuresRef.current += 1;
            logger.warn("note", "autosave failed", { path, attempt: saveFailuresRef.current, err });
            setSaveState("error");
          }
        });
    }, delay);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, open, note, baseMtime, saveState]);

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

  const lockPriorModeRef = useRef<"view" | "edit" | null>(null);
  const toggleToolbarLock = useCallback(() => {
    const next = !toolbarLocked;
    // Always set (not just on the "view" branch) so a lock-from-edit-mode
    // clears any stale prior value instead of inheriting it.
    if (next) {
      lockPriorModeRef.current = mode === "view" ? "view" : null;
      if (mode === "view") setMode("edit");
    } else if (lockPriorModeRef.current === "view") {
      setMode("view");
      lockPriorModeRef.current = null;
    }
    setToolbarLocked(next);
  }, [toolbarLocked, mode]);

  // -- Escape: close a drawer/radial first, else close the editor --
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (menuOpen) { setMenuOpen(false); return; }
      if (toolbarLocked) { toggleToolbarLock(); return; }
      if (pinnedDrawer) { setPinnedDrawer(null); return; }
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, menuOpen, toolbarLocked, pinnedDrawer, onClose, toggleToolbarLock]);

  const applyFmt = useCallback((kind: FormatKind) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const r = applyMarkdownFormat(body, ta.selectionStart, ta.selectionEnd, kind);
    setBody(r.value);
    setFiredFmt(kind);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(r.selStart, r.selEnd);
    });
    setTimeout(() => setFiredFmt(null), reducedMotion ? 0 : 260);
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

  const togglePin = useCallback((key: DrawerKey) => {
    setPinnedDrawer((cur) => (cur === key ? null : key));
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
        // Collapse the overlay (DUR/SETTLE, matches its own entry curve) before
        // unmounting, then confirm via the shared toast — an instant unmount
        // read as a hard cut with nothing to say resolution succeeded.
        setConflictClosing(true);
        setTimeout(() => {
          setConflictBusy(false);
          setConflictOpen(false);
          setConflictClosing(false);
          setConflict(null);
          if (action === "theirs") reloadFromDisk();
        }, DUR);
        setHistoryToast("Conflict resolved");
        setTimeout(() => setHistoryToast(null), 2400);
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

  // F-10 (GUI half): a note with no frontmatter at all -- a file dropped into the vault by hand
  // or by another tool, never opened through Second Thought's own create-note path -- can never
  // carry the `id` field note_editor.py's add_attachment requires, and 400s the instant the user
  // tries. NoteContent never exposes `id` itself, but `has_frontmatter` is a safe proxy: its
  // absence *guarantees* no id (no false "can attach" here), so gate the affordance on it and
  // tell the user before they reach for it, instead of after a failed request.
  const canAttach = note?.has_frontmatter ?? true;

  // GUI-07: `/note/attachment` is behind X-Omni-Secret, and a DOM-issued
  // `src`/`href` GET carries no headers -- inline attachments 403'd and never
  // rendered. Fetch each one with the auth header and hand the DOM a `blob:`
  // URL instead. Keyed on (note.path, filenames); every URL created here is
  // revoked on cleanup, so blob lifetime is bounded by one open note.
  const notePath = note?.path ?? null;
  const attachmentKey = attachments.map((a) => a.filename).join(" ");
  const [attachmentUrls, setAttachmentUrls] = useState<Record<string, string>>({});
  // View-mode only: in edit mode the raw `[attachment: filename]` line is shown
  // as plain text in the textarea and no attachment component renders, so
  // fetching blobs there is pure waste. `mode` is a dependency so switching
  // modes revokes/re-fetches exactly like the existing cleanup below does.
  useEffect(() => {
    if (mode !== "view" || !notePath || attachments.length === 0) { setAttachmentUrls({}); return; }
    let cancelled = false;
    const created: string[] = [];
    Promise.all(
      attachments.map(async (a) => {
        try {
          const url = await fetchAttachmentBlob(notePath, a.filename);
          if (cancelled) { URL.revokeObjectURL(url); return null; }
          created.push(url);
          return [a.filename, url] as const;
        } catch {
          return null; // one bad attachment must not blank the others
        }
      }),
    ).then((pairs) => {
      if (cancelled) return;
      setAttachmentUrls(Object.fromEntries(pairs.filter((p): p is readonly [string, string] => p !== null)));
    });
    return () => {
      cancelled = true;
      for (const url of created) URL.revokeObjectURL(url);
      setAttachmentUrls({});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, notePath, attachmentKey]);

  const blocks = useMemo(() => parseBlocks(body), [body]);

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
          setAttachError(err instanceof Error ? attachErrorMessage(err.message) : "Failed to attach file");
        }
      });
  }, [note, baseMtime, reloadFromDisk]);

  // -- New Note: create on the first keystroke, never on open/click (locked
  // decision, s135). `path` prop stays null throughout -- the created note's
  // path lives only in `note.path` once loaded, exactly like every other
  // note-identity read in this file (see the attachments block above), so
  // the load-reset effect keyed on `[open, path]` never re-fires for this
  // transition and can't clobber whatever the user has typed since. --
  const handleNewNoteChange = useCallback((text: string) => {
    setBody(text);
    if (note || creatingRef.current) return;
    creatingRef.current = true;
    createNote()
      .then((created) => getNoteContent(created.path).then((content) => ({ content })))
      .then(({ content }) => {
        if (!mountedRef.current) {
          // Navigated away while the create was in flight -- the file was
          // never shown to the user and autosave never armed for it, so it
          // must not silently persist (mirrors CompactQuickNote's
          // generation-orphan guard).
          void moveToTrash(content.path).catch(() => {});
          return;
        }
        setNote(content);
        // Do NOT setBody(content.body) here -- content.body is the freshly
        // created (empty) server copy; the user may have kept typing during
        // the round trip and that local `body` state is authoritative.
        lastSavedBodyRef.current = content.body;
        setBaseMtime(content.mtime);
      })
      .catch((err) => {
        logger.error("note", "failed to create note", err);
        setSaveState("error");
      })
      .finally(() => { creatingRef.current = false; });
  }, [note]);

  // -- Task 9 (C1): header controls, lifted into FullWindow's shared topbar --
  // These styles used to live in the "-- styles --" block below (they were
  // NoteEditor's own topbar/corner-menu). They move up here, above the
  // `if (!open) return null` early return, because the effect that forwards
  // them via `onHeaderActionsChange` is a hook and every hook in this
  // component must run unconditionally on every render (same reason all the
  // other useState/useEffect calls above are unconditional too).
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
  const menuBtnStyle = (active: boolean): CSSProperties => ({
    width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
    color: active ? "var(--text-1)" : "var(--text-2)",
    // Finding 4 (re-review): only set an inline background for the active
    // state, which should dominate over hover -- leaving it unset otherwise
    // lets .ne-toolbar-btn:hover apply (an inline style always beats a class rule).
    background: active ? "var(--surface)" : undefined,
    border: `1px solid ${active ? "var(--accent)" : "transparent"}`, cursor: "pointer",
    transition: `background 160ms ${SETTLE}, border-color 160ms ${SETTLE}, color 160ms ${SETTLE}`,
  });
  // Re-anchored (Task 9): used to hang off the old vertically-stacked
  // corner column at a hardcoded `top:56`. Now anchored to its own
  // `position:relative` wrapper (just the "More" button, 26px tall)
  // wherever FullWindow's topbar happens to place it, so it tracks the
  // button instead of a value sized for the deleted layout.
  const menuDropStyle = (open: boolean): CSSProperties => ({
    position: "absolute", top: "calc(100% + 8px)", right: 0, width: 138, background: "var(--surface)",
    border: "1px solid var(--border)", zIndex: 20, boxShadow: "0 8px 20px rgba(0,0,0,0.35)",
    opacity: open ? 1 : 0, transform: open ? "translateY(0) scale(1)" : "translateY(-6px) scale(0.98)",
    pointerEvents: open ? "auto" : "none",
    transition: `opacity ${reducedMotion ? 1 : 190}ms ${SETTLE}, transform ${reducedMotion ? 1 : 190}ms ${SETTLE}`,
  });
  const menuRowStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 9, padding: "7px 11px", fontSize: 11.5,
    color: "var(--text-2)", cursor: "pointer", width: "100%", textAlign: "left",
    // Finding 4 (re-review): background reset moved to the .ne-menu-row base
    // rule in index.css -- an inline "none" here would beat :hover the same
    // way it beat :active before.
    border: "none", font: "inherit",
    transition: `background 140ms ${SETTLE}, color 140ms ${SETTLE}`,
  };

  // Back, title, sync, then (once a note is loaded) the mode toggle /
  // open-external / more-menu trio -- left to right, matching the locked
  // order (fork C1). Built fresh every render like InboxPanel's own
  // `headerActionButtons`; the effect below doesn't list every closure this
  // captures (note/mode/menuOpen/pinnedDrawer/...) as a dep for the same
  // reason InboxPanel's doesn't -- they're always current at call time.
  const headerActions = (
    <>
      <button style={iconBtnStyle} onClick={onClose} aria-label="Back" title="Back">
        <IconBack />
      </button>
      <span style={titleStyle}>{note?.title ?? "…"}</span>
      <span style={syncStyle}><span style={dotStyle} /> {syncLabel}</span>
      {note && (
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept={attachFilter}
            style={{ display: "none" }}
            onChange={(e) => { handleAttachFile(e.target.files?.[0] ?? null); e.target.value = ""; }}
          />
          <button
            style={iconBtnStyle}
            onClick={() => setMode((m) => (m === "view" ? "edit" : "view"))}
            aria-label={mode === "view" ? "Switch to edit" : "Switch to view"}
            title={mode === "view" ? "Switch to edit" : "Switch to view"}
          >
            {mode === "view" ? <IconPencil size={15} /> : <IconEye size={15} />}
          </button>
          <button className="ne-toolbar-btn" style={menuBtnStyle(false)} aria-label="Open in external editor" title="Open in your set markdown editor"
            onClick={() => onOpenExternal(note.path)}
          >
            <IconExternal />
          </button>
          {/* Corner overflow menu (replaces the old always-visible Instrument rail) */}
          <div style={{ position: "relative" }}>
            <button className="ne-toolbar-btn" style={menuBtnStyle(menuOpen)} aria-label="More" aria-haspopup="true" aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
            >
              <MoreIcon size={16} />
            </button>
            {/* ponytail: Connections and Outline both open the existing combined "conn" drawer
                rather than splitting ConnectionsDrawer's content into two components. Two menu
                entries satisfy the phone-parity ask without a drawer-content refactor; split the
                drawer for real if Outline needs its own scroll position or the combined view gets
                too busy. */}
            <div style={menuDropStyle(menuOpen)} role="menu" aria-hidden={!menuOpen}>
              <button className="ne-menu-row" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); togglePin("remind"); }}>
                <BellIcon size={13} />Reminder
              </button>
              <button className="ne-menu-row" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); if (pinnedDrawer !== "conn") togglePin("conn"); }}>
                <IconConnections size={13} />Connections
              </button>
              <button className="ne-menu-row" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); if (pinnedDrawer !== "conn") togglePin("conn"); }}>
                <OutlineIcon size={13} />Outline
              </button>
              {historyStatus !== "offline" && (
                <button className="ne-menu-row" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); togglePin("history"); }}>
                  <ClockIcon size={13} />History
                </button>
              )}
              <button className="ne-menu-row" style={menuRowStyle} role="menuitem" tabIndex={menuOpen ? 0 : -1} onClick={() => { setMenuOpen(false); togglePin("meta"); }}>
                <IconMeta size={13} />Metadata
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );

  useEffect(() => {
    onHeaderActionsChange?.(open ? headerActions : null);
    return () => onHeaderActionsChange?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onHeaderActionsChange, open, note, mode, saveState, menuOpen, pinnedDrawer, historyStatus, attachFilter]);
  // `onClose`/`onOpenExternal` are deliberately NOT in the deps above: FullWindow
  // passes `onClose` as a fresh inline arrow every render (not useCallback'd),
  // so listing it here would re-fire this effect -> re-push a new headerActions
  // object -> parent re-renders -> a new `onClose` reference -> loop, forever.
  // Both closures are read directly out of the current render's props inside
  // `headerActions` above (always current), and neither closes over anything
  // that varies independently of the state already listed, so omitting them
  // costs nothing -- the one thing it can't do is decide to skip a push that
  // was otherwise needed, since `note`/`mode`/etc. already cover every case
  // where the *content* of a click handler actually changes.

  if (!open) return null;

  const activeDrawer = pinnedDrawer;
  const drawerOpen = activeDrawer !== null;

  // -- styles --
  // Task 8: no longer an absolutely-positioned overlay -- it's an ordinary
  // keyed view inside FullWindow's `.fw-view-panel` switch now, so it fills
  // that flex parent instead of covering it from above.
  const wrapStyle: CSSProperties = {
    flex: 1, minHeight: 0,
    background: "var(--bg)",
    display: "flex", flexDirection: "column",
    opacity: visible ? 1 : 0,
    transform: visible ? "translateY(0)" : (reducedMotion ? "none" : "translateY(8px)"),
    pointerEvents: visible ? "auto" : "none",
    transition: `opacity ${reducedMotion ? 1 : DUR}ms ${TRAVEL}, transform ${reducedMotion ? 1 : DUR}ms ${TRAVEL}`,
  };

  const bodyRowStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", position: "relative" };
  const contentStyle: CSSProperties = { flex: 1, minWidth: 0, overflowY: "auto", position: "relative" };
  const measureStyle: CSSProperties = { maxWidth: "62ch", margin: "0 auto", width: "100%", padding: "24px 70px 96px 24px" };
  const h1Style: CSSProperties = { fontSize: 21, fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 16px", color: "var(--text-1)" };
  const paperStyle: CSSProperties = {
    width: "100%", minHeight: 380, background: "transparent", border: "none", color: "var(--text-1)",
    font: "inherit", fontSize: 13.5, lineHeight: 1.75, resize: "none", padding: 0, outline: "none",
  };

  const drawerStyle: CSSProperties = {
    position: "absolute", top: 0, right: 0, bottom: 0,
    width: drawerOpen ? 236 : 0, overflow: "hidden",
    background: "var(--surface)", borderLeft: drawerOpen ? "1px solid var(--border)" : "1px solid transparent",
    transition: `width ${DUR}ms ${TRAVEL}`, zIndex: 6,
  };
  const drawerInnerStyle: CSSProperties = { width: 236, height: "100%", overflowY: "auto", paddingBottom: 14 };
  const drawerHeadStyle: CSSProperties = {
    fontSize: 11, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase",
    padding: "12px 14px 8px", borderBottom: "1px solid var(--border-2)", marginBottom: 4,
  };

  // Finding 1: anchored against bodyRowStyle (non-scrolling), flush against
  // its right edge -- the corner overflow-menu column this used to be offset
  // from was deleted in Task 9 (its controls moved into FullWindow's topbar).
  // Task 10 (E): `overflow: hidden` is the actual fix for the peek-edge bug --
  // nothing local clipped the translated-out toolbar before (only `fw-shell`
  // at the very top of the tree did), so it always showed a sliver at the
  // body's right edge even fully "hidden". The peek arrow (`peekArrowStyle`
  // below) sits at `right:6` inside this box, well within its bounds, so it
  // stays visible after the clip -- only the toolbar column, which
  // deliberately translates itself past the box's right edge, gets cut off.
  const fmtEdgeStyle: CSSProperties = { position: "absolute", top: 0, right: 0, bottom: 0, width: TOOLBAR_EDGE_W, overflow: "hidden" };
  const peekArrowStyle: CSSProperties = {
    position: "absolute", top: "50%", right: 6,
    width: 16, height: 16, display: "flex", alignItems: "center", justifyContent: "center",
    color: "var(--text-3)", cursor: "pointer",
    background: "none", border: "none", padding: 0,
    transition: `opacity ${reducedMotion ? 1 : 200}ms ${SETTLE}, color ${reducedMotion ? 1 : 200}ms ${SETTLE}`,
  };
  const toolbarColStyle: CSSProperties = {
    position: "absolute", top: "50%", right: 8, display: "flex", flexDirection: "column",
    alignItems: "stretch", gap: 5,
    transform: toolbarOut ? "translate(0px, -50%)" : `translate(${TOOLBAR_EDGE_W}px, -50%)`,
    transition: `transform ${reducedMotion ? 1 : 260}ms ${SETTLE}`,
    pointerEvents: toolbarOut ? "auto" : "none",
  };
  const fmtStripStyle: CSSProperties = {
    display: "flex", flexDirection: "column", background: "var(--glass-bg)",
    border: "1px solid var(--border)", boxShadow: "-8px 0 18px rgba(0,0,0,0.3)",
  };
  const fmtRowStyle = (kind: FormatKind): CSSProperties => ({
    width: 28, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
    color: firedFmt === kind ? "var(--green)" : "var(--text-2)",
    borderBottom: "1px solid var(--border-2)", position: "relative", cursor: "pointer",
    transition: `background ${reducedMotion ? 1 : 140}ms ${SETTLE}, color ${reducedMotion ? 1 : 140}ms ${SETTLE}`,
  });
  // Finding 5: Mic/Camera attach rows share fmtRowStyle's geometry but must not
  // react to firedFmt -- fmtRowStyle("tag") made them flash green whenever the
  // real Tag format button fired. Plain color, no firedFmt dependency.
  // F-10: `disabled` (no id on this note, see `canAttach` above) dims to --text-3 and swaps the
  // cursor -- the same muted-not-red treatment the rest of this file uses for "unavailable,
  // not broken" (never red/yellow, those are reserved for actual error/warn state).
  const attachRowStyle = (disabled: boolean): CSSProperties => ({
    width: 28, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
    color: disabled ? "var(--text-3)" : "var(--text-2)",
    borderBottom: "1px solid var(--border-2)", position: "relative",
    cursor: disabled ? "not-allowed" : "pointer",
    transition: `background ${reducedMotion ? 1 : 140}ms ${SETTLE}, color ${reducedMotion ? 1 : 140}ms ${SETTLE}`,
  });
  const lockBtnStyle: CSSProperties = {
    width: 30, height: 18, display: "flex", alignItems: "center", justifyContent: "center",
    color: toolbarLocked ? "var(--accent)" : "var(--text-3)",
    background: toolbarLocked ? "var(--accent-d)" : "var(--surface)",
    border: `1px solid ${toolbarLocked ? "var(--accent)" : "var(--border)"}`,
    cursor: "pointer", alignSelf: "center",
  };

  return (
    <div style={wrapStyle} role="dialog" aria-label="Note editor">
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

      {/* New Note, pre-creation: a bare textarea, no toolbar/corner-menu/drawers
          (all of those read `note.*`, and there is no note until the first
          keystroke creates one via handleNewNoteChange). Disappears the
          instant `note` is set -- the block below takes over seamlessly. */}
      {!note && path === null && (
        <div style={bodyRowStyle}>
          <div style={contentStyle}>
            <div style={measureStyle}>
              <textarea
                ref={textareaRef}
                style={paperStyle}
                aria-label="Note body (editable)"
                spellCheck={false}
                placeholder="Start typing to create a note…"
                autoFocus
                value={body}
                onChange={(e) => handleNewNoteChange(e.target.value)}
              />
            </div>
          </div>
        </div>
      )}

      {note && (
        <div style={bodyRowStyle}>
          <div style={contentStyle}>
            <div style={measureStyle}>
              <h1 style={h1Style}>{note.title}</h1>
              {mode === "view" && note.tags.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "0 0 16px" }}>
                  {note.tags.map((t) => <TagChip key={t} label={t} />)}
                </div>
              )}
              {mode === "edit" ? (
                <textarea
                  ref={textareaRef}
                  style={paperStyle}
                  aria-label="Note body (editable)"
                  spellCheck={false}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
              ) : (
                <Markdown blocks={blocks} attachmentUrls={attachmentUrls} />
              )}
            </div>
          </div>

          {/* Finding 1: hangs off bodyRowStyle (non-scrolling) instead of contentStyle
              (which scrolls with note content) so the peek chevron/strip/lock stay
              reachable on notes long enough to scroll. Flush against the body's
              right edge (Task 11 removed the dead corner-menu-column reserve). */}
          <div
            style={fmtEdgeStyle}
            onMouseEnter={() => setToolbarPeeking(true)}
            onMouseLeave={() => setToolbarPeeking(false)}
            onFocus={() => setToolbarPeeking(true)}
            onBlur={() => setToolbarPeeking(false)}
          >
            <button
              className="ne-toolbar-btn ne-peek-arrow"
              style={peekArrowStyle}
              data-hidden={toolbarLocked || toolbarOut}
              onClick={() => setToolbarPeeking(true)}
              aria-label="Show formatting toolbar"
            >
              <svg width="9" height="13" viewBox="0 0 9 13" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round">
                <path d="M7 1.5L2 6.5l5 5" />
              </svg>
            </button>
            <div style={toolbarColStyle}>
              {mode === "edit" && (
                <div style={fmtStripStyle}>
                  {FMT_ORDER.map(({ kind, label, Icon }) => (
                    <button key={kind} className="ne-toolbar-btn" style={fmtRowStyle(kind)} aria-label={label} title={label} onClick={() => applyFmt(kind)}>
                      <Icon size={19} />
                    </button>
                  ))}
                  <button
                    className="ne-toolbar-btn" style={attachRowStyle(!canAttach)}
                    aria-label="Attach voice memo" title={canAttach ? "Attach voice memo" : NO_ATTACH_HINT}
                    disabled={attachBusy || !canAttach}
                    onClick={() => { flushSync(() => setAttachFilter("audio/*")); fileInputRef.current?.click(); }}
                  >
                    <MicIcon size={19} />
                  </button>
                  <button
                    className="ne-toolbar-btn" style={{ ...attachRowStyle(!canAttach), borderBottom: "none" }}
                    aria-label="Attach photo" title={canAttach ? "Attach photo" : NO_ATTACH_HINT}
                    disabled={attachBusy || !canAttach}
                    onClick={() => { flushSync(() => setAttachFilter("image/*")); fileInputRef.current?.click(); }}
                  >
                    <CameraIcon size={19} />
                  </button>
                </div>
              )}
              <button
                className="ne-toolbar-btn"
                style={lockBtnStyle}
                aria-pressed={toolbarLocked}
                title={toolbarLocked ? "Unlock toolbar" : "Lock toolbar open"}
                onClick={toggleToolbarLock}
              >
                {/* Task 10 (E): was hardcoded 12x12 with no size prop -- the odd one
                    out once the other toolbar icons grew 13px -> 19px. Scaled by the
                    same ~1.46x so it stays proportional, not just re-picked to look right. */}
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
                  <rect x="5" y="10.5" width="14" height="9" rx="0.5" />
                  <path d={toolbarLocked ? "M8 10.5V7a4 4 0 0 1 8 0v3.5" : "M8 10.5V7a4 4 0 0 1 8 0"} />
                </svg>
              </button>
            </div>
          </div>

          {/* Drawers — Wave 6 (O-8c): each target's content is keyed-remount
              swapped via the shared fw-view-panel/fwViewIn recipe (240ms) so
              switching meta/conn/history/remind reads as a content swap-in,
              not an instant snap (the outer width morph already ships). */}
          <div style={drawerStyle}>
            {drawerOpen && activeDrawer === "meta" && (
              <div key="meta" className="fw-view-panel" style={drawerInnerStyle}>
                <div style={drawerHeadStyle}>METADATA</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "8px 14px", fontSize: 11.5, color: "var(--text-3)" }}>
                  <span>project: <b style={{ color: "var(--text-2)" }}>{displayProject(note.project)}</b></span>
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
              <div key="conn" className="fw-view-panel" style={{ width: "100%", height: "100%" }}>
                <ConnectionsDrawer body={body} mentions={mentions} onJump={scrollToLine} onOpenExternal={onOpenExternal} />
              </div>
            )}
            {drawerOpen && activeDrawer === "history" && (
              <div key="history" className="fw-view-panel" style={{ width: "100%", height: "100%" }}>
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
              </div>
            )}
            {drawerOpen && activeDrawer === "remind" && (
              <div key="remind" className="fw-view-panel" style={drawerInnerStyle}>
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
          closing={conflictClosing}
          onResolve={resolveConflict}
          onClose={() => setConflictOpen(false)}
        />
      )}

      {historyToast && (
        <div style={{ position: "absolute", left: "50%", bottom: 18, transform: "translateX(-50%)", zIndex: 30 }}>
          <div className="toast-rise" style={{
            background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-1)",
            fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 8,
          }}>
            <IconCheck size={13} /> {historyToast}
          </div>
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
            {/* Wave 6 (O-8c): row expand rides the same 0fr->1fr disclosure
                idiom as Settings Diagnostics/Sync (index.css .sync-disclose),
                260ms travel — was a plain conditional mount/unmount. */}
            {!rev.current && (
              <div className="sync-disclose" data-open={open}>
                <div style={{ padding: "0 14px 12px" }}>
                  <div style={{
                    background: "var(--glass-bg)", border: "1px solid var(--glass-border)",
                    fontSize: 11, lineHeight: 1.6, color: "var(--text-2)", padding: 8,
                    maxHeight: 128, overflowY: "auto", whiteSpace: "pre-wrap", marginBottom: 8,
                  }}>
                    {preview === undefined ? (
                      <span aria-hidden="true" style={{ display: "block", width: "70%", height: 11, background: "var(--surface-2)", animation: "pulse 1.2s ease-in-out infinite" }} />
                    ) : (preview || "(empty)")}
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
  conflict, busy, closing, onResolve, onClose,
}: {
  conflict: NoteConflict;
  busy: boolean;
  closing?: boolean;
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
    <div
      className={closing ? undefined : "fw-view-panel"}
      style={{
        position: "absolute", inset: 0, zIndex: 25, background: "var(--bg)", display: "flex", flexDirection: "column",
        opacity: closing ? 0 : 1,
        transform: closing ? "scale(0.98)" : "scale(1)",
        transition: closing ? `opacity ${DUR}ms ${SETTLE}, transform ${DUR}ms ${SETTLE}` : undefined,
      }}
      role="dialog"
      aria-label="Resolve conflict"
    >
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

function ConnectionsDrawer({ body, mentions, onJump, onOpenExternal }: { body: string; mentions: SearchResult[] | null; onJump: (line: number) => void; onOpenExternal: (path: string) => void }) {
  const links = parseWikilinks(body);
  const outline = parseOutline(body);
  const rowStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "7px 14px", fontSize: 12,
    color: "var(--text-2)", cursor: "pointer", border: "none", background: "none", font: "inherit",
    width: "100%", textAlign: "left",
  };
  // FR-14: [[wikilink]] targets are bare strings (parseWikilinks) with no path
  // resolution anywhere in the app -- Markdown.tsx renders the same targets
  // inline as inert underlined text too, never a click target. No real
  // navigation destination exists for a Connections row, so it gets the
  // "loose" cursor of a plain row instead of the false pointer affordance.
  const inertRowStyle: CSSProperties = { ...rowStyle, cursor: "default" };
  const groupStyle: CSSProperties = { fontSize: 10.5, letterSpacing: "0.08em", color: "var(--text-3)", padding: "10px 14px 4px", textTransform: "uppercase" };
  return (
    <div style={{ width: 236, height: "100%", overflowY: "auto", paddingBottom: 14 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.06em", color: "var(--text-3)", textTransform: "uppercase", padding: "12px 14px 8px", borderBottom: "1px solid var(--border-2)", marginBottom: 4 }}>
        CONNECTIONS
      </div>
      {links.length === 0 && <div style={{ padding: "6px 14px", fontSize: 11.5, color: "var(--text-3)" }}>No linked notes yet.</div>}
      {links.map((l) => <div key={l} style={inertRowStyle}>{l}</div>)}

      {/* ponytail: unlinked-mention "LINK" one-click action (in the approved
          mock) would need a backend endpoint that mutates the *mentioning*
          note's body to insert a wikilink — real scope, deferred. This shows
          mentions read-only via the existing /search endpoint (no new
          backend surface) rather than half-building that mutation. */}
      {mentions === null && <div style={{ padding: "6px 14px", fontSize: 11, color: "var(--text-3)" }}>…</div>}
      {mentions !== null && mentions.length > 0 && (
        <>
          <div style={groupStyle}>MENTIONS</div>
          {/* FR-14: a mention IS a real vault file (m.path, from /search) -- unlike
              wikilinks above, a genuine target exists. NoteEditor has no in-app
              cross-note jump (only onJump, which scrolls within THIS note's own
              body), so this reuses the toolbar's existing "open in external
              editor" action -- the one real, already-wired way this component can
              act on another note's path -- rather than leaving the row inert or
              inventing new plumbing. Real <button> (not a div) for the same
              keyboard reachability and a11y Outline's rows already have below. */}
          {mentions.map((m) => (
            <button key={m.path} type="button" style={rowStyle} title={m.path} onClick={() => onOpenExternal(m.path)}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.filename ?? m.path}</span>
            </button>
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
