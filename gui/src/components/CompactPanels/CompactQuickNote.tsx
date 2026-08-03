/**
 * CompactQuickNote.tsx
 * ---------------------
 * Compact Desktop Shell Rework, Task 7: the Sticky-Notes-style quick pad
 * that replaces Hide in the six-item menu. Hosted by `CompactShell` exactly
 * like every other compact panel (a sibling of CompactVault/CompactInbox/…),
 * B2 layout: ONE band of chrome, entirely inside CompactShell's
 * `headerActions` slot — `[+] [B] [checklist]` left, `[pin] [discard]`
 * right. The body is the text area and nothing else.
 *
 * Locked behaviour (s135 DECISIONS §5, user-approved — see quickPad.ts):
 *  - ONE pad, reopening to the last note it made.
 *  - The note is created on the FIRST KEYSTROKE, never on open, never on
 *    click. `quickPad.ts`'s reducer owns that decision; this component only
 *    ever calls `reduce` once the async work it triggers has resolved.
 *  - "+" clears the pad for a fresh note without deleting the outgoing one.
 *  - Discard deletes (moveToTrash) the note, but only if it was written to.
 *  - Pin toggles real OS always-on-top via `setAlwaysOnTop` (Task 5).
 *  - Exactly two formatting actions: bold and checklist — reuses
 *    `noteFormat.ts`'s `applyMarkdownFormat`, the same pure helper
 *    NoteEditor's own toolbar uses, rather than re-deriving the wrapping
 *    logic here.
 *
 * The `expected_mtime` gap (Task 6/7 interface note): `POST /note`
 * (`createNote`) returns `{id, path, title}` with NO mtime, but
 * `saveNoteContent` is optimistic-concurrency guarded on `expected_mtime`.
 * NoteEditor.tsx resolves the identical problem on open by following its
 * `getNoteContent(path)` load with `saveNoteContent`'s `expected_mtime` set
 * from the loaded `NoteContent.mtime` (see NoteEditor.tsx's load effect,
 * `getNoteContent(path).then((n) => { ...; setBaseMtime(n.mtime); })`). This
 * component does the same: after `createNote` resolves, it immediately
 * calls `getNoteContent(created.path)` once to obtain a valid starting
 * mtime before the first autosave can fire. No Python change needed.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  createNote,
  getNoteContent,
  saveNoteContent,
  moveToTrash,
  NoteConflictError,
} from "../../lib/api";
import { setAlwaysOnTop } from "../../lib/tauri";
import { applyMarkdownFormat, type FormatKind } from "../../lib/noteFormat";
import { isSaveRetry, saveRetryDelayMs } from "../../lib/saveRetry";
import { initialPadState, reduce, loadLastNoteId, saveLastNoteId, type PadState } from "../../lib/quickPad";
import { PlusIcon, TrashIcon } from "../PillMenu/icons";
import { BTN_GHOST } from "../ui/styles";
import { logger } from "../../lib/logger";

interface Props {
  onHeaderActionsChange?: (actions: ReactNode | null) => void;
}

// -- local glyphs: Bold/Checklist mirror NoteEditor.tsx's own local (non-
// exported) toolbar icons pixel-for-pixel so the pad's two format actions
// read identically to the full editor's. Pin has no existing export
// anywhere in the app; icons.tsx is out of this task's scope (Task 2/5
// territory), so it is defined locally here per the same
// feature-specific-glyph convention NoteEditor.tsx already uses for its own
// corner-menu icons. --

function BoldIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 5v14M8 5h3a3 3 0 010 6H8M8 12h4a3.5 3.5 0 010 7H8" />
    </svg>
  );
}

function ChecklistIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} aria-hidden="true">
      <rect x="3" y="9" width="6" height="6" rx="1" />
      <path d="M4.5 12l1.3 1.3L8 10.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 10.5h9M12 14.5h9" strokeLinecap="round" />
    </svg>
  );
}

function PinIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 2v7" />
      <path d="M7 9h10l1.5 5H5.5z" />
      <path d="M12 14v8" />
    </svg>
  );
}

type SaveState = "idle" | "saving" | "saved" | "error" | "conflict";

export default function CompactQuickNote({ onHeaderActionsChange }: Props) {
  const [pad, setPad] = useState<PadState>(() => initialPadState(loadLastNoteId()));
  const [mtime, setMtime] = useState<number | null>(null);
  const [pinned, setPinned] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [loadingReopen, setLoadingReopen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const creatingRef = useRef(false);
  // Bumped by "+"/discard so a create that was already in flight when the
  // user detached from it can tell, once it resolves, that it is now
  // orphaned — see handleChange's gen check below.
  const generationRef = useRef(0);
  const lastSavedRef = useRef("");
  const lastAttemptedRef = useRef<string | null>(null);
  const failuresRef = useRef(0);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // -- reopen: load the last note's body/mtime once on mount. Read-only —
  // never creates anything, matching "never on open". If the persisted note
  // vanished (trashed/purged elsewhere), fall back to a fresh empty pad
  // rather than surfacing a load error in a 288px surface. --
  useEffect(() => {
    const path = pad.noteId;
    if (!path) return;
    let cancelled = false;
    setLoadingReopen(true);
    getNoteContent(path)
      .then((n) => {
        if (cancelled) return;
        setPad((s) => ({ ...s, text: n.body }));
        lastSavedRef.current = n.body;
        setMtime(n.mtime);
      })
      .catch(() => {
        if (cancelled) return;
        setPad(initialPadState(null));
        saveLastNoteId(null);
      })
      .finally(() => { if (!cancelled) setLoadingReopen(false); });
    return () => { cancelled = true; };
    // Mount-only reopen load — CompactShell/PillOverlay key-remounts this
    // component on every target switch, so "on open" already means "on mount".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); }, []);

  // Reverts always-on-top on unmount so leaving the pad pinned can never
  // strand the whole app above every other window after the panel closes.
  useEffect(() => () => { if (pinned) void setAlwaysOnTop(false); }, [pinned]);

  const resetLocal = useCallback(() => {
    setMtime(null);
    setSaveState("idle");
    lastSavedRef.current = "";
    lastAttemptedRef.current = null;
    failuresRef.current = 0;
    if (saveTimerRef.current) { clearTimeout(saveTimerRef.current); saveTimerRef.current = null; }
  }, []);

  // -- create-on-first-keystroke + typing. `creatingRef` guards re-entrant
  // calls while the create+getNoteContent round trip is in flight; any
  // keystrokes typed during that window are preserved locally and folded
  // into the note by the very next autosave once noteId resolves. --
  const handleChange = useCallback((text: string) => {
    setPad((s) => ({ ...s, text, dirty: true }));
    if (pad.noteId !== null || creatingRef.current) return;
    creatingRef.current = true;
    const gen = generationRef.current;
    createNote()
      .then((created) => getNoteContent(created.path).then((content) => ({ created, content })))
      .then(({ created, content }) => {
        if (gen !== generationRef.current) {
          // "+"/discard detached from this pad session while the create was
          // in flight — the note it made was never shown to the user and
          // autosave never fired for it, so it must not silently persist.
          void moveToTrash(created.path).catch(() => {});
          return;
        }
        setMtime(content.mtime);
        lastSavedRef.current = "";
        saveLastNoteId(created.path);
        setPad((s) => reduce(s, { type: "type", text: s.text }, { create: () => created.path }));
      })
      .catch((err) => {
        logger.error("quickPad", "failed to create note", err);
        setSaveState("error");
      })
      .finally(() => { creatingRef.current = false; });
  }, [pad.noteId]);

  // -- debounced autosave, mirrors NoteEditor.tsx's autosave effect
  // (same saveRetry backoff helpers) once a note + a valid mtime exist. --
  useEffect(() => {
    if (!pad.noteId || mtime === null) return;
    if (saveState === "conflict") return;
    if (pad.text === lastSavedRef.current) return;
    const retrying = isSaveRetry(pad.text, lastAttemptedRef.current);
    if (!retrying) failuresRef.current = 0;
    const delay = saveRetryDelayMs(failuresRef.current);
    const path = pad.noteId;
    const body = pad.text;

    setSaveState("saving");
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      lastAttemptedRef.current = body;
      saveNoteContent(path, body, mtime)
        .then((r) => {
          failuresRef.current = 0;
          lastSavedRef.current = body;
          setMtime(r.mtime);
          setSaveState("saved");
        })
        .catch((err) => {
          if (err instanceof NoteConflictError) {
            failuresRef.current = 0;
            setSaveState("conflict");
          } else {
            failuresRef.current += 1;
            logger.warn("quickPad", "autosave failed", { path, attempt: failuresRef.current, err });
            setSaveState("error");
          }
        });
    }, delay);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pad.text, pad.noteId, mtime, saveState]);

  const applyFmt = useCallback((kind: FormatKind) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const r = applyMarkdownFormat(pad.text, ta.selectionStart, ta.selectionEnd, kind);
    handleChange(r.value);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(r.selStart, r.selEnd);
    });
  }, [pad.text, handleChange]);

  const handleNew = useCallback(() => {
    generationRef.current += 1;
    setPad(reduce(pad, { type: "new" }, {}));
    resetLocal();
    saveLastNoteId(null);
  }, [pad, resetLocal]);

  const handleDiscard = useCallback(() => {
    generationRef.current += 1;
    const next = reduce(pad, { type: "discard" }, {
      del: (id) => { void moveToTrash(id).catch((err) => logger.warn("quickPad", "discard failed", err)); },
    });
    setPad(next);
    resetLocal();
    saveLastNoteId(null);
  }, [pad, resetLocal]);

  const togglePin = useCallback(() => {
    setPinned((cur) => {
      const next = !cur;
      void setAlwaysOnTop(next);
      return next;
    });
  }, []);

  useEffect(() => {
    onHeaderActionsChange?.(
      <>
        <button type="button" className="btn-hover" style={BTN_GHOST} title="New note" aria-label="New note" onClick={handleNew}>
          <PlusIcon size={13} />
        </button>
        <button type="button" className="btn-hover" style={BTN_GHOST} title="Bold" aria-label="Bold" onClick={() => applyFmt("bold")}>
          <BoldIcon />
        </button>
        <button type="button" className="btn-hover" style={BTN_GHOST} title="Checklist" aria-label="Checklist" onClick={() => applyFmt("checklist")}>
          <ChecklistIcon />
        </button>
        <span className="quickpad-header-divider" aria-hidden="true" />
        <button
          type="button"
          className="btn-hover quickpad-pin-btn"
          style={BTN_GHOST}
          title={pinned ? "Unpin (always-on-top off)" : "Pin (always-on-top)"}
          aria-label="Pin"
          aria-pressed={pinned}
          onClick={togglePin}
        >
          <PinIcon />
        </button>
        <button type="button" className="btn-hover hover-danger" style={BTN_GHOST} title="Discard" aria-label="Discard" onClick={handleDiscard}>
          <TrashIcon size={13} />
        </button>
      </>,
    );
    return () => onHeaderActionsChange?.(null);
  }, [onHeaderActionsChange, handleNew, applyFmt, togglePin, pinned, handleDiscard]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minWidth: 0 }}>
      <textarea
        ref={textareaRef}
        className="quickpad-textarea"
        aria-label="Quick note"
        placeholder="Jot something down…"
        spellCheck={false}
        disabled={loadingReopen}
        value={pad.text}
        onChange={(e) => handleChange(e.target.value)}
      />
      {saveState === "conflict" && (
        <div className="quickpad-conflict">
          This note changed elsewhere — close and reopen the pad to see the latest.
        </div>
      )}
    </div>
  );
}
