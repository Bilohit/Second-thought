# Note editor toolbar rework — corner menu + hover-peek formatting strip (2026-07-31)

## Problem

`NoteEditor.tsx` has two crowded, mismatched controls:

1. **Formatting radial** (bottom-right "+" dial, `FMT_ORDER` at `NoteEditor.tsx:171-178`): 6 spokes
   on a 96px quarter-arc (`FAN_OFFSETS`, `:180-182`) whose adjacent centers land ~29-31px apart —
   every pair of 36px spokes overlaps by 5-7px, measured. Also renders unconditionally, in both
   view AND edit mode (no gate around `fmtZoneStyle`, `:734`), even though view mode has no textarea
   and every action there is a no-op.
2. **Instrument rail** (right-edge vertical strip, `railStyle`/`instBtnStyle`, `:781-813`): Metadata,
   Connections & outline (one combined drawer), Remind me, Version history (conditional), Open in
   external editor. Always visible, occupies a permanent 34px column.

Phone's equivalent (`app/note/[id].tsx`) uses a different action set entirely (Bold/Checklist/
Link/Tag/Attach voice/Attach photo vs desktop's Bold/Italic/Heading/List/Link/Code — only Bold and
Link overlap) and a different structure (contextual float toolbar + a `MoreIcon` overflow menu with
Reminder/Connections/Outline/History). The two platforms feel foreign to each other.

## Decision (user-approved, mocks: scratchpad `note-editor-toolbar-interactive.html`,
`radial-fix-mocks.html`, `formatting-toolbar-mocks.html`)

Split into two independent, differently-shaped controls, matched to what each actually does.

### 1. Formatting actions → hover-peek / lock right-edge strip

**Action set swaps to match phone exactly:** Bold, Checklist, Link, Tag, Attach voice, Attach photo
(drops Italic/Heading/List/Code). Icons/labels borrowed from phone's `BoldIcon`/`ChecklistIcon`/
`LinkIcon`/`TagIcon`/`MicIcon`/`CameraIcon` (`phone/src/components/icons.tsx`), same 1.7 stroke
convention desktop already uses.

- **Collapsed (default):** no box, no border — a bare ~16px chevron at ~40% opacity near the
  vertical center of the right edge, brightening to full opacity on hover/focus. Same
  dim-then-brighten motif as phone's focus-mode rail.
- **Peek (hover or focus, not locked):** the strip slides in via `transform: translate()` only
  (never `width`/`right`, so no layout reflow), 260ms, `cubic-bezier(0.16,1,0.3,1)` — the project's
  existing `--hover-ease-out`, matching the timing the pill radial already uses
  (`RADIAL_ANIM_MS`/`RADIAL_STAGGER_MS` = 260ms/45ms). Retracts the instant the pointer/focus leaves,
  unless locked.
- **Lock (click):** a short 30×18px button directly under the strip, sliding as one unit with it
  (single shared `transform`, never a 7th row inside the strip). Icon is the existing `IconLock`
  glyph (`NoteEditor.tsx:119-126`) toggling between its shackle-open (unlocked) and shackle-closed
  (locked) states — not a star, not a new icon family.
- **Locking forces edit mode** if the note was in view mode, because none of these 6 actions do
  anything to statically-rendered Markdown. Unlocking restores whatever mode the note was in before.
- **No content reflow in either state.** At real proportions (a 62ch `measureStyle` column inside a
  480-920px logical window, `tauri.conf.json`), the margin outside the text column already clears
  the strip's reach — confirmed by the user against the mock's proportions. Both peek and lock stay
  pure overlay; `.content` padding never changes. Caveat carried into implementation: re-check this
  assumption visually at the narrow end of the window range before shipping.
  **Amended 2026-07-31 (as built):** the toolbar zone (chevron + lock) renders in BOTH view and edit
  mode — requirement #3 above makes lock reachable from view mode — so the right-edge padding that
  clears it is constant across modes. That is this promise being kept, not broken; the padding must
  NOT be gated on edit mode (see `BUILD-STATE/PROGRESS/DECISIONS.md` §5, "finding 11 closed as invalid").
- **Per-row tooltip** on hover/focus, exact phone wording, replacing the old single floating "Select
  text, then pick an action" caption.
- **Feedback:** every row gets a hover tint AND a fast (~90ms) `:active` scale-down, so a click reads
  as registered before the format-apply effect completes.
- **Accessibility:** chevron, lock button, and every format row are real `<button>`s — Tab reaches
  them, Enter/Space activates, focus itself triggers the peek (not hover-only), `aria-pressed` on the
  lock communicates toggle state. `prefers-reduced-motion` collapses slide/press transitions to an
  instant state swap (color transitions, not being motion, stay).

### 2. Everything else → one corner overflow menu

Replaces the always-visible Instrument rail. A `More` (kebab, new `MoreIcon` borrowed from
`phone/src/components/icons.tsx`) button opens a dropdown, mirroring phone's real `OverflowMenu`
(`app/note/[id].tsx:1195-1255`) closely:

- **5 uniform rows, no divider:** Reminder, Connections, Outline, History, Metadata. Connections and
  Outline split into separate rows (desktop currently combines them in one `ConnectionsDrawer`) —
  new `OutlineIcon` borrowed from phone for parity; Metadata folds into this menu (phone keeps it as
  a separate always-there `StatusFlyout` — desktop's version differs here, by user's explicit call).
- **Open in external editor stays its own button**, beside the `More` button, not inside the menu.
- Each row: hover tint + fast `:active` press feedback, same treatment as the format rows.
- History row still conditionally hidden when `historyStatus === "offline"` (unchanged behavior).

## Non-goals (deferred to a later spec — editor UX uplift)

Explicitly out of scope for this pass, named so they aren't silently dropped:

- Clickable mentions/links in the Connections drawer (currently dead text)
- Checklist tap-toggle in view mode
- Slash-command menu (`/todo /link /date /tpl`)
- Focus/typewriter mode
- Any redesign of the Metadata/Connections/Remind/History drawer CONTENTS — only their entry point
  (rail → menu) changes here

## Changes (implementation pointers)

- `gui/src/components/NoteEditor.tsx`: replace `FMT_ORDER`/`FAN_OFFSETS`/the radial dial JSX with the
  hover-peek/lock strip; replace the always-rendered `railStyle` nav with the `More` button + dropdown
  + a separate external-editor button; gate the whole formatting strip on `mode === "edit"` (closing
  the dead view-mode render this spec's investigation found); split the existing `ConnectionsDrawer`
  entry into two menu rows (Connections, Outline) feeding the same drawer content, or split the drawer
  itself if that reads cleaner during implementation.
- `gui/src/components/PillMenu/icons.tsx` (or a new local file in `NoteEditor.tsx`, matching existing
  convention of file-local `Icon*` helpers there): add `MoreIcon`, `OutlineIcon`, and the 6 phone-
  matched formatting icons (`BoldIcon`/`ChecklistIcon`/`LinkIcon`/`TagIcon`/`MicIcon`/`CameraIcon`),
  ported from `phone/src/components/icons.tsx` paths.
- Sibling test coverage: a pure geometry/state test for the peek/lock transform logic (mirroring the
  existing `reconcileApply.test.ts` pattern of testing branch logic, not pixels), following the repo's
  "non-trivial logic ships one runnable check" rule.

## Gates to run before calling this done

`gui: npm test` + `npm run build` (both must stay green), plus a manual `launch.ps1` pass cycling
Minimal→Capsule→Full and exercising hover/lock/unlock/mode-switch on the new strip and the new menu,
per the desktop `CLAUDE.md` manual-QA rule for GUI lifecycle changes.
