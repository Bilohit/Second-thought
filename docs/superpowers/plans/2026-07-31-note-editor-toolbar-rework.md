# Note Editor Toolbar Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `NoteEditor.tsx`'s two crowded controls (a 6-spoke formatting radial that overlaps
itself, and an always-visible Instrument rail) with a hover-peek/lock formatting strip (phone-matched
action set) and a corner overflow menu (phone-matched structure), per the approved spec.

**Architecture:** Pure logic (the format-apply string transforms) lives in `gui/src/lib/noteFormat.ts`,
unchanged pattern from today. All new UI is inline in `NoteEditor.tsx`, matching the file's existing
convention of file-local `Icon*` helper functions and inline `CSSProperties` style objects — this file
does not use a CSS-in-JS library or Tailwind, so new styles follow the same object-literal pattern
already used for `railStyle`/`fmtZoneStyle`/etc.

**Tech Stack:** React 18 (hooks only), TypeScript strict, Vitest, no CSS framework in `gui/`.

## Global Constraints

- TypeScript `strict` + `noUnusedLocals` + `noUnusedParameters` + `noFallthroughCasesInSwitch` must
  pass (`npm run build` from `gui/`).
- Icons: inline SVG only, `stroke=currentColor`, ~1.7 stroke width, 24-grid viewBox — never emoji,
  matching every existing icon in this file.
- Motion: `transform`/`opacity` only for the new strip/menu — never `width`/`right`, so nothing
  triggers layout reflow. Duration 260ms strip, 200ms menu, both `cubic-bezier(0.16,1,0.3,1)` (this
  file already has this exact curve as its local `SETTLE` constant, `NoteEditor.tsx:33`).
- Every new interactive control is a real `<button>`, keyboard-reachable, with `aria-label`/
  `aria-pressed` as appropriate — no hover-only `<div>`.
- `npm test` + `npm run build` (from `gui/`) must stay green before any task is considered done.
- No `Co-Authored-By` in commits (standing repo convention).

---

### Task 1: Extend the pure format helper — `checklist` and `tag` kinds

**Files:**
- Modify: `gui/src/lib/noteFormat.ts:7` (the `FormatKind` union), `:16-23` (the `WRAPS` table)
- Test: `gui/src/lib/noteFormat.test.ts` (create if it doesn't already exist — check first with
  `Glob gui/src/lib/noteFormat.test.ts`; if it exists, add to it rather than replacing it)

**Interfaces:**
- Consumes: nothing new
- Produces: `FormatKind = "bold" | "checklist" | "link" | "tag"` (drops `"italic" | "heading" |
  "list" | "code"`), `applyMarkdownFormat(value, selStart, selEnd, kind)` unchanged signature, now
  handling the new kinds via the same `WRAPS` table mechanism. Task 2/3 import `FormatKind` and call
  `applyMarkdownFormat` exactly as today.

- [ ] **Step 1: Write the failing tests**

Add to `gui/src/lib/noteFormat.test.ts` (create the file with this header if it doesn't exist yet):

```ts
import { describe, it, expect } from "vitest";
import { applyMarkdownFormat } from "./noteFormat";

describe("applyMarkdownFormat — checklist", () => {
  it("prefixes the current line with '- [ ] ' when selection is collapsed", () => {
    const value = "buy milk";
    const r = applyMarkdownFormat(value, 0, 0, "checklist");
    expect(r.value).toBe("- [ ] buy milk");
    expect(r.selStart).toBe(6);
    expect(r.selEnd).toBe(6);
  });

  it("prefixes the line the selection starts on, not the document start", () => {
    const value = "first line\nsecond line";
    const secondLineStart = value.indexOf("second");
    const r = applyMarkdownFormat(value, secondLineStart, secondLineStart, "checklist");
    expect(r.value).toBe("first line\n- [ ] second line");
  });
});

describe("applyMarkdownFormat — tag", () => {
  it("inserts a bare '#' at the caret when selection is collapsed", () => {
    const value = "meeting notes";
    const r = applyMarkdownFormat(value, 8, 8, "tag");
    expect(r.value).toBe("meeting #notes");
    expect(r.selStart).toBe(9);
    expect(r.selEnd).toBe(9);
  });

  it("wraps a non-empty selection between '#' and nothing (selection becomes the tag name)", () => {
    const value = "meeting project";
    const start = value.indexOf("project");
    const end = start + "project".length;
    const r = applyMarkdownFormat(value, start, end, "tag");
    expect(r.value).toBe("meeting #project");
  });
});

describe("applyMarkdownFormat — bold and link still work (regression guard)", () => {
  it("bold wraps the selection in '**'", () => {
    const r = applyMarkdownFormat("hello world", 6, 11, "bold");
    expect(r.value).toBe("hello **world**");
  });

  it("link wraps the selection in '[' and '](url)'", () => {
    const r = applyMarkdownFormat("see docs", 4, 8, "link");
    expect(r.value).toBe("see [docs](url)");
  });
});
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run (from `gui/`): `npx vitest run src/lib/noteFormat.test.ts`
Expected: the `checklist` and `tag` tests FAIL with a TypeScript error or runtime error (`"checklist"`/
`"tag"` not assignable to `FormatKind`, or `WRAPS[kind]` is `undefined`). The `bold`/`link` regression
tests PASS (unchanged behavior).

- [ ] **Step 3: Update `FormatKind` and `WRAPS`**

Replace `gui/src/lib/noteFormat.ts:7` and `:16-23`:

```ts
export type FormatKind = "bold" | "checklist" | "link" | "tag";
```

```ts
const WRAPS: Record<FormatKind, Wrap> = {
  bold: { pre: "**", post: "**" },
  checklist: { pre: "- [ ] ", post: "", line: true },
  link: { pre: "[", post: "](url)" },
  tag: { pre: "#", post: "" },
};
```

Also update the doc comment above `applyMarkdownFormat` (currently references "the mock's `applyFmt`
… 05-desktop-viewer-refined-v2.html", `:31-33`) — that mock is superseded by this rework, so replace
the comment:

```ts
/** Apply a formatting action to `value` given the current selection
 *  [selStart, selEnd). Action set matches the phone app's contextual toolbar
 *  (bold/checklist/link/tag) — see docs/superpowers/specs/2026-07-31-note-editor-toolbar-rework-design.md. */
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/noteFormat.test.ts`
Expected: PASS, all tests including the bold/link regression guards.

- [ ] **Step 5: Fix every other caller of the old `FormatKind` values**

Run: `grep -rn "italic\|heading\|\"list\"\|\"code\"" gui/src/components/NoteEditor.tsx` to find every
site still referencing the removed kinds — Task 2 rewrites `FMT_ICON_PATHS`/`FmtIcon`/`FMT_ORDER`
entirely, so this step is a sanity check that nothing else in the file references the old kinds. If
`npm run build` (Task 2, Step 4) is clean, this step needs no separate action; just confirm the grep
above returns nothing outside the code Task 2 is about to replace.

- [ ] **Step 6: Commit**

```bash
git add gui/src/lib/noteFormat.ts gui/src/lib/noteFormat.test.ts
git commit -m "feat(gui): swap note editor format actions to bold/checklist/link/tag"
```

---

### Task 2: New icons — formatting set + menu icons

**Files:**
- Modify: `gui/src/components/NoteEditor.tsx:87` (near `IconAttach`, add the new icon functions
  alongside the existing file-local `Icon*` helpers), `:155-169` (replace `FMT_ICON_PATHS`/`FmtIcon`)

**Interfaces:**
- Consumes: `FormatKind` from Task 1 (`"bold" | "checklist" | "link" | "tag"`)
- Produces: `BoldIcon`, `ChecklistIcon`, `LinkFmtIcon` (named to avoid clashing with the existing
  `IconLink`-style naming if any — check with `grep -n "function IconLink" NoteEditor.tsx` first; if
  no clash, name it `LinkIcon`), `TagIcon`, `MicIcon`, `CameraIcon`, `MoreIcon`, `OutlineIcon` — all
  `(props: { size?: number }) => JSX.Element`, matching this file's existing icon-function signature
  exactly (see `IconAttach`, `:87-94`, for the pattern to copy).

- [ ] **Step 1: Add the six formatting icons (ported from phone, same stroke convention)**

Insert after the existing `IconAttach` function (`NoteEditor.tsx:87-94`ish — find the function's
closing `}` and insert immediately after):

```tsx
function BoldIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 5v14M8 5h3a3 3 0 010 6H8M8 12h4a3.5 3.5 0 010 7H8" />
    </svg>
  );
}
function ChecklistIcon(props: { size?: number }) {
  const size = props.size ?? 13;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
      <rect x="3" y="9" width="6" height="6" rx="1" />
      <path d="M4.5 12l1.3 1.3L8 10.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 10.5h9M12 14.5h9" strokeLinecap="round" />
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
```

- [ ] **Step 2: Replace `FMT_ICON_PATHS`/`FmtIcon`/`FMT_ORDER` (`NoteEditor.tsx:155-178`)**

Delete the old `FMT_ICON_PATHS` object, `FmtIcon` function, and `FMT_ORDER` array (they referenced
the removed `"italic"|"heading"|"list"|"code"` kinds and the old radial). Replace with:

```tsx
const FMT_ORDER: { kind: FormatKind; label: string; Icon: (p: { size?: number }) => JSX.Element }[] = [
  { kind: "bold", label: "Bold", Icon: BoldIcon },
  { kind: "checklist", label: "Checklist", Icon: ChecklistIcon },
  { kind: "link", label: "Link", Icon: LinkFmtIcon },
  { kind: "tag", label: "Tag", Icon: TagIcon },
];
```

(Attach voice/photo are handled separately in Task 3 — they are not `FormatKind` values, since they
don't go through `applyMarkdownFormat`.)

- [ ] **Step 3: Remove the now-dead `FAN_OFFSETS`/`FAN_OFFSETS_REDUCED` constants**

Delete `NoteEditor.tsx:180-185` (`FAN_OFFSETS`, `FAN_OFFSETS_REDUCED`) — Task 3 replaces the radial
fan entirely, these arrays have no remaining caller after this task.

- [ ] **Step 4: Verify the build still compiles (expected: NOT clean yet — Task 3 finishes the wiring)**

Run: `npm run build` (from `gui/`)
Expected: TypeScript errors about `radialOpen`/`firedSpoke`/`fmtZoneStyle`/`fmtDialStyle` referencing
the now-deleted spoke-rendering JSX (still present until Task 3). This is expected — do not try to
make this task compile standalone; Task 3 is the matching JSX change. Note the exact error list so
Task 3's implementer knows every remaining reference.

- [ ] **Step 5: Commit**

```bash
git add gui/src/components/NoteEditor.tsx
git commit -m "feat(gui): add phone-matched formatting icons, drop the old radial icon set"
```

(This commit is intentionally not build-clean in isolation — Task 3 completes it in the next commit.
If your workflow requires every commit green, squash Tasks 2+3 into one commit instead; either is fine,
call it out in the PR description.)

---

### Task 3: Hover-peek / lock formatting strip (replaces the radial)

**Files:**
- Modify: `gui/src/components/NoteEditor.tsx:195-206` (state), `:365-376` (`applyFmt`), `:620-625`
  (`fmtZoneStyle`/`fmtDialStyle`), `:708-778` (the JSX region rendering the old radial + textarea/
  Markdown view)

**Interfaces:**
- Consumes: `FormatKind`, `FMT_ORDER` (Task 2), `applyMarkdownFormat` (Task 1), existing
  `fileInputRef`, `handleAttachFile` (`:528-543`, unchanged)
- Produces: `toolbarPeeking` (boolean, hover/focus state), `toolbarLocked` (boolean, click-toggle
  state) — Task 4 does not consume these (the menu is independent), but keep the names in case a
  later task needs to coordinate.

- [ ] **Step 1: Replace state (`NoteEditor.tsx:201-202`)**

Replace:
```ts
  const [radialOpen, setRadialOpen] = useState(false);
  const [firedSpoke, setFiredSpoke] = useState<FormatKind | null>(null);
```
with:
```ts
  const [toolbarPeeking, setToolbarPeeking] = useState(false);
  const [toolbarLocked, setToolbarLocked] = useState(false);
  const [firedFmt, setFiredFmt] = useState<FormatKind | null>(null);
  const toolbarOut = toolbarPeeking || toolbarLocked;
```

- [ ] **Step 2: Replace `applyFmt` (`NoteEditor.tsx:365-376`)**

```ts
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

  const toggleToolbarLock = useCallback(() => {
    setToolbarLocked((locked) => {
      const next = !locked;
      if (next && mode === "view") setMode("edit");
      return next;
    });
  }, [mode]);
```

(Note: unlike the old radial, locking/unlocking does not auto-close on every format action — a
locked toolbar stays open across multiple formatting clicks, matching the "lock it open" mental
model. Only `toolbarPeeking` — the transient hover state — auto-retracts, via CSS `:hover`/`:focus-
within`, not a JS timer.)

- [ ] **Step 3: Replace `fmtZoneStyle`/`fmtDialStyle` (`NoteEditor.tsx:620-625`)**

```ts
  const fmtEdgeStyle: CSSProperties = { position: "absolute", top: 0, right: 0, bottom: 0, width: 46 };
  const peekArrowStyle: CSSProperties = {
    position: "absolute", top: "50%", right: 6, transform: "translateY(-50%)",
    width: 16, height: 16, display: "flex", alignItems: "center", justifyContent: "center",
    color: "var(--text-3)", opacity: toolbarLocked ? 0 : 0.4, cursor: "pointer",
    background: "none", border: "none", padding: 0,
    transition: `opacity ${reducedMotion ? 1 : 200}ms ${SETTLE}, color ${reducedMotion ? 1 : 200}ms ${SETTLE}`,
    pointerEvents: toolbarLocked ? "none" : "auto",
  };
  const toolbarColStyle: CSSProperties = {
    position: "absolute", top: "50%", right: 8, display: "flex", flexDirection: "column",
    alignItems: "stretch", gap: 5,
    transform: toolbarOut ? "translate(0px, -50%)" : "translate(46px, -50%)",
    transition: `transform ${reducedMotion ? 1 : 260}ms ${SETTLE}`,
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
  const lockBtnStyle: CSSProperties = {
    width: 30, height: 18, display: "flex", alignItems: "center", justifyContent: "center",
    color: toolbarLocked ? "var(--accent)" : "var(--text-3)",
    background: toolbarLocked ? "var(--accent-d)" : "var(--surface)",
    border: `1px solid ${toolbarLocked ? "var(--accent)" : "var(--border)"}`,
    cursor: "pointer", alignSelf: "center",
  };
```

(`SETTLE` is the existing local constant at `NoteEditor.tsx:33`, already `cubic-bezier(0.16,1,0.3,1)`
— reuse it, do not redeclare a new easing constant.)

- [ ] **Step 3b: Add press-feedback CSS classes (inline `style` objects can't express `:active`)**

This file has no CSS-in-JS/Tailwind for `:active`, so add two small global classes to
`gui/src/index.css` (near the existing `.spoke`/`.fw-view-panel` rules, matching that file's existing
pattern of a handful of reusable interaction classes):

```css
/* Note editor toolbar/menu — :active press feedback (inline style objects can't express :active) */
.ne-toolbar-btn:active { transform: scale(0.88); }
.ne-menu-row:active { transform: scale(0.97); background: var(--accent-glow); }
```

These are applied via `className` alongside the existing inline `style` on every new interactive
element in Steps 4 and Task 4 Step 3 below — inline `style` still owns layout/color/transform-when-
resting, the class only adds the momentary pressed transform.

- [ ] **Step 4: Replace the radial JSX (`NoteEditor.tsx:708-778` region — the part rendering
  `fmtZoneStyle`/the spoke `.map()`/the dial button)**

Read the surrounding unchanged JSX first (`measureStyle`/textarea/Markdown block stays exactly as-is
at `:710-730` — only the formatting-zone `<div>` after it changes). Replace the formatting-zone block
(everything from the `{/* Radial formatting instrument ... */}` comment through its closing `</div>`,
originally `:732-777`) with:

```tsx
            {mode === "edit" && (
              <div style={fmtEdgeStyle} onMouseEnter={() => setToolbarPeeking(true)} onMouseLeave={() => setToolbarPeeking(false)}>
                <button
                  className="ne-toolbar-btn"
                  style={peekArrowStyle}
                  aria-label="Show formatting toolbar"
                  onFocus={() => setToolbarPeeking(true)}
                  onBlur={() => setToolbarPeeking(false)}
                >
                  <svg width="9" height="13" viewBox="0 0 9 13" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round">
                    <path d="M7 1.5L2 6.5l5 5" />
                  </svg>
                </button>
                <div style={toolbarColStyle}>
                  <div style={fmtStripStyle}>
                    {FMT_ORDER.map(({ kind, label, Icon }) => (
                      <button key={kind} className="ne-toolbar-btn" style={fmtRowStyle(kind)} aria-label={label} title={label} onClick={() => applyFmt(kind)}>
                        <Icon size={13} />
                      </button>
                    ))}
                    <button className="ne-toolbar-btn" style={fmtRowStyle("tag" as FormatKind)} aria-label="Attach voice memo" title="Attach voice memo"
                      onClick={() => { attachFilter.current = "audio/*"; fileInputRef.current?.click(); }}>
                      <MicIcon size={13} />
                    </button>
                    <button className="ne-toolbar-btn" style={{ ...fmtRowStyle("tag" as FormatKind), borderBottom: "none" }} aria-label="Attach photo" title="Attach photo"
                      onClick={() => { attachFilter.current = "image/*"; fileInputRef.current?.click(); }}>
                      <CameraIcon size={13} />
                    </button>
                  </div>
                  <button
                    className="ne-toolbar-btn"
                    style={lockBtnStyle}
                    aria-pressed={toolbarLocked}
                    title={toolbarLocked ? "Unlock toolbar" : "Lock toolbar open"}
                    onClick={toggleToolbarLock}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
                      <rect x="5" y="10.5" width="14" height="9" rx="0.5" />
                      <path d={toolbarLocked ? "M8 10.5V7a4 4 0 0 1 8 0v3.5" : "M8 10.5V7a4 4 0 0 1 8 0"} />
                    </svg>
                  </button>
                </div>
              </div>
            )}
```

Note the two attach rows reuse `fmtRowStyle` with an arbitrary `FormatKind` cast purely for the shared
visual style (they are not real format kinds, so the cast is a style-only convenience, not a type
lie that leaks anywhere — `firedFmt === kind` will simply never match `"tag"` when Mic/Camera are
clicked unless the user also happens to have just tagged, which only affects the transient green
flash, not correctness). If this reads as too clever during review, extract a plain
`attachRowStyle: CSSProperties` constant instead (same object literal, minus the `firedFmt` check) —
either is acceptable, note the choice in the commit message.

- [ ] **Step 5: Add the `attachFilter` ref and wire it into the existing hidden `<input>`**

Near `fileInputRef` (`NoteEditor.tsx:229`), add:
```ts
  const attachFilter = useRef<string>("*/*");
```

Update the existing hidden file input (`:640-644`) to read the filter dynamically:
```tsx
            <input
              ref={fileInputRef}
              type="file"
              accept={attachFilter.current}
              style={{ display: "none" }}
              onChange={(e) => { handleAttachFile(e.target.files?.[0] ?? null); e.target.value = ""; }}
            />
```
(A ref read directly in `accept` won't re-render reactively on its own — since the ref is only ever
read at the moment the file dialog opens via `fileInputRef.current?.click()`, and React doesn't need
to re-render for that, this is safe. If TypeScript/lint flags reading `.current` during render, switch
`attachFilter` to a `useState<string>("*/*")` instead — either works, prefer whichever keeps
`npm run build` clean.)

- [ ] **Step 6: Remove the old standalone "Attach a file" button (`NoteEditor.tsx:653-661`)**

It's superseded by the two toolbar rows (Attach voice / Attach photo) added in Step 4. Delete the
`<button>` block; keep `fileInputRef`'s hidden `<input>` (now shared by both new attach rows).

- [ ] **Step 7: Write a sibling test for the new pure pieces**

The transform/state logic here is UI (React state + inline styles), which per the repo's own
convention (`CLAUDE.md`: "pure geometry/logic stays in `lib/*.ts`... stateful orchestration stays in
components") is not unit-tested directly — Task 1's `noteFormat.test.ts` already covers the one pure
piece (`applyMarkdownFormat`). No additional test file is needed for this task; the manual QA in
Task 5 is the runnable check for the stateful wiring, per the repo's non-trivial-logic rule (a
branch/state-machine change needs a check — here that check is the manual launch.ps1 pass, since the
logic is a UI state machine, not a pure function).

- [ ] **Step 8: Run the full gate**

Run (from `gui/`): `npm test && npm run build`
Expected: all tests pass (including Task 1's new tests), `tsc` strict + vite build clean, 0 errors.

- [ ] **Step 9: Commit**

```bash
git add gui/src/components/NoteEditor.tsx
git commit -m "feat(gui): hover-peek/lock formatting strip replaces the note editor's radial dial"
```

---

### Task 4: Corner overflow menu (replaces the Instrument rail)

**Files:**
- Modify: `gui/src/components/NoteEditor.tsx:781-813` (`railStyle`/`instBtnStyle` nav — the
  Instrument rail JSX), plus wherever `railStyle`/`instBtnStyle` are defined as `CSSProperties`
  constants (search `grep -n "const railStyle\|const instBtnStyle" NoteEditor.tsx`)

**Interfaces:**
- Consumes: existing `pinnedDrawer`, `hoverDrawer`, `showDrawer`, `clearHoverDrawer`, `togglePin`,
  `historyStatus`, `onOpenExternal` (all already defined earlier in the file — unchanged)
- Produces: `menuOpen` (boolean, new local state), no new exports

- [ ] **Step 1: Add `menuOpen` state near the other drawer state (`NoteEditor.tsx:199-200`)**

```ts
  const [menuOpen, setMenuOpen] = useState(false);
```

- [ ] **Step 2: Add menu styles alongside the other style constants (near `railStyle`)**

```ts
  const menuBtnStyle = (active: boolean): CSSProperties => ({
    width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
    color: active ? "var(--text-1)" : "var(--text-2)",
    background: active ? "var(--surface)" : "transparent",
    border: `1px solid ${active ? "var(--accent)" : "transparent"}`, cursor: "pointer",
    transition: `background 160ms ${SETTLE}, border-color 160ms ${SETTLE}, color 160ms ${SETTLE}`,
  });
  const menuDropStyle = (open: boolean): CSSProperties => ({
    position: "absolute", top: 34, right: 0, width: 138, background: "var(--surface)",
    border: "1px solid var(--border)", zIndex: 20, boxShadow: "0 8px 20px rgba(0,0,0,0.35)",
    opacity: open ? 1 : 0, transform: open ? "translateY(0) scale(1)" : "translateY(-6px) scale(0.98)",
    pointerEvents: open ? "auto" : "none",
    transition: `opacity ${reducedMotion ? 1 : 190}ms ${SETTLE}, transform ${reducedMotion ? 1 : 190}ms ${SETTLE}`,
  });
  const menuRowStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 9, padding: "7px 11px", fontSize: 11.5,
    color: "var(--text-2)", cursor: "pointer",
    transition: `background 140ms ${SETTLE}, color 140ms ${SETTLE}`,
  };
```

- [ ] **Step 3: Replace the Instrument rail JSX (`NoteEditor.tsx:781-813`)**

Replace the `<nav style={railStyle} aria-label="Instrument dock">...</nav>` block with:

```tsx
          <div style={{ position: "relative" }}>
            <button className="ne-toolbar-btn" style={menuBtnStyle(menuOpen)} aria-label="More" aria-haspopup="true" aria-expanded={menuOpen}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
            >
              <MoreIcon size={16} />
            </button>
            <button className="ne-toolbar-btn" style={menuBtnStyle(false)} aria-label="Open in external editor" title="Open in your set markdown editor"
              onClick={() => onOpenExternal(note.path)}
            >
              <IconExternal />
            </button>
            <div style={menuDropStyle(menuOpen)} role="menu">
              <div className="ne-menu-row" style={menuRowStyle} role="menuitem" onClick={() => { setMenuOpen(false); togglePin("remind"); }}>
                <BellIcon size={13} />Reminder
              </div>
              <div className="ne-menu-row" style={menuRowStyle} role="menuitem" onClick={() => { setMenuOpen(false); togglePin("conn"); }}>
                <IconConnections size={13} />Connections
              </div>
              <div className="ne-menu-row" style={menuRowStyle} role="menuitem" onClick={() => { setMenuOpen(false); togglePin("conn"); }}>
                <OutlineIcon size={13} />Outline
              </div>
              {historyStatus !== "offline" && (
                <div className="ne-menu-row" style={menuRowStyle} role="menuitem" onClick={() => { setMenuOpen(false); togglePin("history"); }}>
                  <ClockIcon size={13} />History
                </div>
              )}
              <div className="ne-menu-row" style={menuRowStyle} role="menuitem" onClick={() => { setMenuOpen(false); togglePin("meta"); }}>
                <IconMeta size={13} />Metadata
              </div>
            </div>
          </div>
```

(Deliberate simplification, named per the repo's `ponytail:` convention — add a comment above the
Connections/Outline rows:)

```tsx
          {/* ponytail: Connections and Outline both open the existing combined "conn" drawer
              rather than splitting ConnectionsDrawer's content into two components. Two menu
              entries satisfy the phone-parity ask without a drawer-content refactor; split the
              drawer for real if Outline needs its own scroll position or the combined view gets
              too busy. */}
```
Place this comment immediately above the `<div style={menuDropStyle...}>` line.

- [ ] **Step 4: Close the menu when clicking outside it**

Add a `useEffect` near the other top-level effects (after the `menuOpen` state declaration is fine):

```ts
  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = () => setMenuOpen(false);
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [menuOpen]);
```

(Step 3's "More" button already calls `e.stopPropagation()` in its `onClick` — that's what keeps this
new document listener from immediately closing the menu the same click that opened it. No further
change needed here.)

- [ ] **Step 5: Run the full gate**

Run (from `gui/`): `npm test && npm run build`
Expected: all tests pass, `tsc` strict + vite build clean.

- [ ] **Step 6: Commit**

```bash
git add gui/src/components/NoteEditor.tsx
git commit -m "feat(gui): corner overflow menu replaces the note editor's Instrument rail"
```

---

### Task 5: Manual QA (required — automated tests cannot drive the native window)

**Files:** none (verification only)

- [ ] **Step 1: Rebuild and launch**

Run (from repo root): `.\launch.ps1` (rebuilds since `gui/` sources changed)

- [ ] **Step 2: Open a note, verify the formatting strip**

Open any note in the note editor (full window). Move the mouse to the right edge — the chevron
should brighten, then the strip + lock button should slide out on hover. Move away without clicking
the lock — it should retract. Click each of the 6 rows (Bold/Checklist/Link/Tag/Attach voice/Attach
photo) with some text selected and confirm each does what its label says (Bold wraps in `**`,
Checklist prefixes `- [ ] `, Link wraps in `[](url)`, Tag inserts `#`, the two attach rows open a
native file picker filtered to audio/image respectively).

- [ ] **Step 3: Verify the lock behavior and mode-forcing**

Switch the note to view mode. Hover the strip, click the lock — confirm the note auto-switches to
edit mode and the lock icon shows the closed/shackle-closed state. Click the lock again — confirm it
returns to whatever mode was active before locking (per the spec: view mode, if that's where it
started) and the strip retracts.

- [ ] **Step 4: Verify the strip never overlaps live text**

At the window's default width and at `maxWidth` (920 logical px, per `tauri.conf.json`), confirm the
strip — peeking or locked — never sits over the rendered/edited text column. Per the spec's own
caveat, also check the narrow end of the window range; if overlap is visible there, note it as a
follow-up rather than silently shipping it.

- [ ] **Step 5: Verify the corner menu**

Click "More" — confirm the dropdown opens with exactly 5 rows (Reminder, Connections, Outline,
History, Metadata — History absent if `historyStatus === "offline"`), each opening the correct
drawer via the existing pin/hover mechanism unchanged. Click outside the menu — confirm it closes.
Click "Open in external editor" — confirm it still works exactly as before (unchanged handler).

- [ ] **Step 6: Cycle display modes**

Per the desktop `CLAUDE.md` GUI-QA rule: cycle Minimal→Capsule→Full and back, confirm no console
errors, no blank/dead window, at both 100% and 125/150% display scale if a multi-DPI display is
available (if not, note that this leg was skipped, per repo convention — never silently claim it).

- [ ] **Step 7: Re-run the automated gate one more time post-QA**

Run (from `gui/`): `npm test && npm run build`
Expected: still green (QA is observational, this step just confirms nothing regressed if any fixes
were made during manual QA).
