/**
 * quickPad.ts
 * -----------
 * Pure state machine for the compact-mode quick pad (Sticky-Notes-style
 * scratch note, s135 Task 6). Encodes the locked behaviour as a reducer over
 * plain data — no fetch/localStorage/DOM inside `reduce` itself, so it stays
 * synchronously testable:
 *
 *  - ONE pad: reopening shows the last note it made (`initialPadState`'s
 *    `lastNoteId` argument), until a new one is created.
 *  - The note is created on the FIRST KEYSTROKE, never on open and never on
 *    click — `reduce`'s "type" case only calls `deps.create` the one time
 *    `noteId` is still null; every later keystroke is a no-op on that front.
 *  - "+" (the "new" action) clears the pad and arms a fresh create, but does
 *    NOT delete the note being left behind — it stays saved on disk exactly
 *    as autosave last wrote it.
 *  - Discard deletes the note, but ONLY if something was actually typed
 *    (`dirty`) — an untouched pad never called `create`, so it never became
 *    a vault note in the first place and there is nothing to delete.
 *
 * `create`/`del` are injected via `PadDeps` rather than imported directly
 * (Task 6 interface note) so this module never imports `lib/api.ts` and stays
 * a plain, side-effect-free function of (state, action, deps) -> state. The
 * REAL async orchestration — calling `createNote`, then `getNoteContent` for
 * the `expected_mtime` a save needs (POST /note returns no mtime; see
 * CompactQuickNote.tsx) — lives in the component, which only calls into this
 * reducer once an id/path is actually known. `deps.create`/`deps.del` are
 * therefore synchronous by contract: the component resolves the async work
 * itself and hands `reduce` the already-known result.
 */

export interface PadState {
  /** The vault note's path once one exists for this pad session; null before
   *  the first keystroke (or right after "+"/discard). */
  noteId: string | null;
  text: string;
  /** True once the user has actually typed/formatted something THIS session
   *  — gates discard so reopening an untouched note and hitting discard
   *  immediately does not delete content from a prior session. */
  dirty: boolean;
}

export type PadAction =
  | { type: "open" }
  | { type: "type"; text: string }
  | { type: "new" }
  | { type: "discard" };

export interface PadDeps {
  /** Called at most once per note — only when `noteId` is still null.
   *  Returns the newly-created note's id (its vault path in the real
   *  wiring). */
  create?: (text: string) => string;
  /** Called only when discarding a pad that actually got written to. */
  del?: (id: string) => void;
}

export function initialPadState(lastNoteId: string | null): PadState {
  return { noteId: lastNoteId, text: "", dirty: false };
}

export function reduce(state: PadState, action: PadAction, deps: PadDeps): PadState {
  switch (action.type) {
    case "open":
      // Opening the pad is never a write — the whole point of create-on-
      // first-keystroke is that clicking around must not litter the vault.
      return state;
    case "type": {
      const noteId = state.noteId ?? deps.create?.(action.text) ?? null;
      return { ...state, text: action.text, dirty: true, noteId };
    }
    case "new":
      // Leaves the outgoing note exactly as autosave last wrote it — "new"
      // detaches from it, it does not delete it. See discard for the
      // delete path.
      return initialPadState(null);
    case "discard":
      if (state.dirty && state.noteId !== null) deps.del?.(state.noteId);
      return initialPadState(null);
  }
}

const LAST_NOTE_KEY = "quickpad.lastNoteId";

// ponytail: last note id only, in localStorage. A real recents list if the pad ever grows tabs.
export function loadLastNoteId(): string | null {
  try {
    return localStorage.getItem(LAST_NOTE_KEY);
  } catch {
    return null;
  }
}

export function saveLastNoteId(id: string | null): void {
  try {
    if (id === null) localStorage.removeItem(LAST_NOTE_KEY);
    else localStorage.setItem(LAST_NOTE_KEY, id);
  } catch {
    /* best-effort — a private/blocked localStorage just means no reopen */
  }
}
