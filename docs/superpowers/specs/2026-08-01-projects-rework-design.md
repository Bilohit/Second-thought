# Design — projects replace folders/categories (s124)

**Date:** 2026-08-01 · **Session:** s124 · **Status:** **design CLOSED and the contract amendment
LANDED.** Interview complete, every section user-approved; compact-mode layout settled across four
interactive mock rounds (§7 items 1–16); `data-model-and-contracts.md` amended to v3.0 and CP2 updated
(§10). **No gate remains before implementation** — the next step is decomposition into the five
sequenced sub-projects named in §11.

This is a **full rework, not a migration.** The user's instruction was explicit: *"do not care about
what already exists. this is a full rework, remove."* The `category` concept is deleted, not renamed
in place, and no back-compat path is owed to any existing vault content.

---

## 1. The concept

**A project is the sole grouping mechanism in the product.** The word "folder" disappears from the
entire ecosystem: UI copy, docs, mocks, and internal vocabulary where it is user-facing.

- **The tag is the truth.** A note's project comes from a body tag: `#project@research` puts the note
  in project `research`.
- **Syntax:** `#project@` followed by a run of characters terminated by the first whitespace. Letters,
  digits, hyphens and underscores are valid inside the name. **Case is preserved as typed.** Parser:
  `/#project@([^\s]+)/`. The directory name is that captured text **verbatim** — no slugging, no
  case-folding, no transformation to guess at.
- **Exactly one project per note.** Zero or one `#project@` tag. Two is a validation error the UI
  prevents rather than a state the model has to resolve.
- **Loose is a first-class state.** A note with no project tag is normal, permanent, and fine. It is not
  an error, not a queue, and not "unfiled work" nagging the user. **It lives in the reserved `_loose/`
  folder, never at the vault root** — see §10 item 3 and contract §1.3 for why (the depth-1 invariant
  keeps `../_attachments/` refs valid across every move). No surface ever shows the folder name; the UI
  says *loose*.
- **The directory is derived housekeeping.** The apps always group by the tag. The on-disk directory is
  a tidiness artifact maintained by desktop. **No surface may present a path as the source of truth.**

## 2. Who moves files, and when

**The UI groups by tag; desktop alone tidies the directories.**

A tag edit takes effect visually and immediately on whichever device made it, because grouping is read
from the tag, not the path. The physical move happens later, as a desktop housekeeping pass. **The
phone never moves a file and never creates a directory.**

Rationale, and this is the load-bearing safety argument of the whole rework: a path change is the one
operation Drive reconcile cannot merge field-wise, so two peers re-pathing the same note in one batch
window degrades to a conflicted copy. Confining all re-pathing to a single device removes that class
entirely. Worst case when desktop is off for a week: the vault on disk is untidy while both apps read
correctly. That is an acceptable, self-healing state.

## 3. Auto-assignment

**Scope — what may be auto-assigned at all.** Only machine-made desktop captures (hotkey clipboard
capture, URL/YouTube ingestion, and the rest of the capture pipeline). Notes hand-written in the
desktop editor or on the phone are **never** auto-enriched implicitly; the user opts in per note from
the three-dot menu on either device.

**What it may write.** A project assignment and **nothing else.** Auto-enrichment never invents
descriptive tags. This is a deliberate reduction from today's behaviour, where the LLM emits
`key_signals` that become arbitrary tags.

**It may never create a project.** The engine picks from projects that already exist. If it believes a
new project is warranted it **suggests** one on the Inbox row; that project exists only once the user
approves it, and until then the note is loose.

**Confidence bands.**

| Band | Outcome | Interrupts the user |
|---|---|---|
| Confident in one existing project | Filed silently, **skips the Inbox entirely** | No |
| Torn between candidates / weak match | **Inbox, offering the top two as one-click choices** | Yes |
| Matches nothing, no new project warranted | **Loose, silently** | No |
| A new project is warranted | **Inbox, as a suggestion awaiting approval** | Yes |

The Inbox therefore means exactly one thing: *something here needs a decision from you.*

**The engines.** Desktop uses its existing Ollama LLM. **Phone uses semantic match, not its LLM** — it
already embeds every note on-device, so it scores the note against each project's description and picks
the best above a threshold. Instant, offline, no model load, no battery cost. Loading Qwen2.5-1.5B for a
one-line classification was rejected as the heaviest possible way to answer the cheapest question.

## 4. Project metadata — `.projects.toml`

A single hidden `.projects.toml` at the **vault root** holds every project and its description.

**Why a root registry and not a per-project file.** A project can exist before any directory does: the
user can create one on the phone, which never creates directories, and a project with no notes yet has
nowhere to put a per-project file. The registry represents that state natively. It is also one file to
sync rather than N.

**Accepted cost:** two devices editing different projects in the same batch window touch the same file,
so it needs **field-aware merge** (per-project keys), not last-writer-wins. This is consistent with the
existing non-destructive conflict doctrine and must be specified in the contract doc before code.

**The description is functional, not decoration.** It is the text the phone embeds for matching, so
every surface that offers description editing should make writing a good one feel worthwhile. It must
be portable text: **never a stored embedding vector**, because desktop and phone embed with different
models and a vector written by one peer is meaningless to the other. Each device embeds the text
locally with its own model.

**Prior art, recorded so this is not mistaken for a new invention:** `.category.toml` already carries a
`description` per category folder, and `build_category_descriptions()` already feeds those descriptions
to the LLM at classification time. The hidden metadata file is an evolution of a mechanism that exists
and is already load-bearing, relocated to the root and renamed.

**Deferred, with its upgrade path named:** matching against the centroid of a project's member-note
embeddings, blended with or replacing the description embedding once a project holds enough notes. It
improves as the vault grows and stops depending on how well the description was written, but it is real
machinery on both peers for a gain that cannot be measured on a small vault. `ponytail:` it.

## 5. Deleting a project

Notes are never destroyed by a project operation. On delete: the project is removed from
`.projects.toml`, its notes become loose, and desktop's tidy pass removes the emptied directory.

**Body-sacred resolution (this was flagged and decided, do not silently re-litigate).** "Strip the tag"
is a write into a sacred body. The workspace lock allows only the user's editor to write below the
frontmatter, with one provenance-gated exception (ISS-051): the device that *originated* a note may
maintain its trailing tag line on content it authored.

Therefore: **strip where allowed, ignore the rest.** The tag is stripped from machine-authored capture
bodies, which the originating device may already touch. In a user-authored body the tag is left exactly
as typed, and **the app treats a `#project@` tag naming a project that does not exist as loose.** That
"dangling tag reads as loose" rule is required for correctness regardless, so it costs nothing. The lock
is not weakened and no contract amendment is needed.

## 6. The unifying UI principle

**One mental model, three shells.** Every surface that lists things gets the same view-mode toggle:

- **Tile mode = project groupings.**
- **List mode = the individual non-action tags.**

**Action tags** (excluded from list mode) are: system tags (`sys/*`), triggering tags such as reminders
and todos, and `#project@` itself. List mode shows only descriptive human vocabulary.

> **Scope note:** triggering-by-tag does not exist in the code today. That arm of the definition is a
> filter rule reserved for when it does; this rework builds no new triggering behaviour. Today the
> filter covers `sys/*` and `#project@`.

**Where it applies:**

1. **Desktop full window** — the Vault page becomes the project management page, layout **A3 (split
   panel)**: project list left, description editor and that project's notes right, no drill-in. The
   left rail carries the tile/list toggle.
2. **Desktop capsule and minimal** — **full parity with the full window** (user's explicit call), inside
   a **332 x 320** content area. Layout strategy is the open question in §7.
3. **Phone** — tags page tiles view becomes the project area, shape **B1 (peek tiles)**: name, count,
   two recent note titles, plus a New tile and a Loose tile. The press-hold scrub-to-open gesture
   survives unchanged. List view stays as the ordinary non-action tags. The three-dot menu carries
   "assign project", offering existing projects only.

## 7. Compact mode (capsule + minimal) — the user's composite

Full parity in 332 x 320 is a genuine space-priority problem: browse projects, browse tags, view a
project's notes, assign, create, rename, edit description, delete, and handle Inbox suggestions.

Four space strategies were prototyped **interactively at true 1:1 dimensions** (the user required
dimensional fidelity, then required the mock be operable rather than static, so the trade-offs could be
felt rather than read). The user drove all four and chose **none of them wholesale**, specifying a
composite instead. **These lines are decided, not proposals:**

1. **Tile design comes from the A2 tile grid** of the first board (`2026-08-01-projects-rework.html`).
   Simple box-like tiles, **two columns, N rows.**
2. **New project is not a tile.** It is a **plus icon in the header**, as in strategy C.
3. **The header carries exactly three icons: tiles, rows, add new.** There is **no Inbox button in the
   capsule vault title bar** — the vault panel is for projects only.
4. **Navigation is B-style drill-in** with a back chevron.
5. **Rename has two paths, both kept.** A small **edit icon appears on hover in each tile's top-right
   corner** and renames in place from the grid; opening the project and editing it there also remains.
6. **Save and delete are icon-only buttons pinned at the bottom** of the panel, to reduce clutter, and
   the description surface gets the same treatment. **Save carries no text label.**
7. **Notes must be openable from the project view**, and opening one opens the **Second Thought native
   note editor**. How that handoff presents from a 332 x 320 panel is a real interaction question and
   must be shown explicitly, not glossed.

**Round 2 settled these as well (user drove the interactive prototype):**

8. **The bottom action bar is contextual, not permanent** — it grows in only when there is something to
   save or delete, so browsing keeps the full 320px.
9. **The project screen shows the name exactly once.** The panel title area (where "Vault" sits at root)
   *is* the editable project-name field; the duplicate name field is deleted from the body. It reads as
   editable on hover and focus without shouting as an input at rest.
10. **The body is then only the notes list and the description box.** The description box is pushed down
    as notes accumulate until it meets the bottom bar; past that point **the notes list scrolls and the
    description stays pinned** directly above the action row.
11. **Deliberately asymmetric action row:** **Save** is a rectangle in the accent colour at the bottom
    right carrying both the word "Save" and its icon, because it is the action the user should take
    most. **Delete** is a small quiet square trash icon to its left.
12. **The description has an escape hatch to a full-panel edit page** (V3's idea, kept), since editing a
    paragraph in a small inline box is painful. Inline editing remains for quick edits.
13. **Hover, press and focus feedback on every interactive element** — restrained and functional, never
    decorative.

**Resolved, was a point of confusion:** the capsule bar's Inbox icon is **not new**. `ALL_TARGETS`
(`gui/src/components/PillMenu/icons.tsx`) is already `search · today · vault · settings · inbox · stats
· hide`, shared by the capsule bar and the minimal radial — and `PANEL_W = 332` is exactly 7 targets ×
44 + 24 padding. Keeping Inbox off the Vault *header* therefore required no invention at all.

**Known collision, resolved:** A2's tile already places the note count in the top-right, exactly where
the hover rename icon goes. The count **crossfades to the edit icon on hover** rather than stacking or
shrinking either one.

**Note-open handoff is a hardware constraint, not a taste call:** the native editor cannot be hosted at
332 x 320, so opening a note from the project view promotes to the full window.

**Round 3 settled the last two, and the compact-mode design is now CLOSED:**

14. **Two-column tiles must fit with no horizontal scrolling — and did not.** Measurement (not
    inspection) found the grid overflowing on ordinary short names: `scrollWidth 651` vs
    `clientWidth 312`. Cause: `1fr 1fr` lets each track's automatic minimum grow to its content's
    min-content width, and a nested `overflow:hidden` does **not** clamp the grid *item's* own
    contribution. Fix: `minmax(0, 1fr)` on both tracks, `min-width: 0` on the tile, and
    `scrollbar-gutter: stable` so the horizontal budget cannot shift when content grows vertically.
    Verified after, including a deliberately seeded 40-character unbroken name: grid `297 == 297`,
    body `330 == 330`, header `330 == 330`, and the name span's own `scrollWidth > clientWidth`,
    proving the ellipsis clips rather than the track silently absorbing the width.
    **This is a real bug class for the implementation, not a mock artifact — carry the fix into the
    component.**
15. **The description expand is an in-place takeover, not a page push.** The textbox grows
    continuously into the space the note rows vacate as they slide out; the title row stays the
    editable project name throughout; the label reads simply **"Description"**. Back plays the exact
    reverse, and only leaves the project on a second press. Implemented by measuring both panes,
    locking their current heights as explicit pixels, then transitioning to the target heights — never
    animating to `auto`. The old pushed `descEdit` screen and its dead actions were deleted.
16. **The tiles/rows toggle reuses the app's real segmented control**, not a lookalike: markup and
    motion from `gui/src/components/ui/SegmentedToggle.tsx`, the `indicatorWidth` /
    `indicatorTransform` / `slideDirection` math from `gui/src/lib/segmentedToggle.ts`, the
    `.seg-swap-panel` / `segSwapIn` keyframes from `index.css`, and `.btn-hover` for hover state. The
    pill and buttons **persist across toggles and are patched in place** — a recreated pill has no
    prior position to slide from, which is what makes the motion work at all.
    **Known and accepted:** `segSwapIn` is **entrance-only**; the outgoing panel is replaced rather
    than sliding out. That is the existing shared behaviour (Inbox/Reminders, search/chat) and this
    screen deliberately matches it rather than diverging.

**STATUS: compact-mode design CLOSED (user confirmed).** The remaining gate before any rework code is
the contract amendment in §10.

**Known wrinkle, to be surfaced rather than designed around:** hover has no touch equivalent. Capsule
mode is mouse-driven so the hover edit icon is fine there, but the same tile component must not be
carried to the phone unchanged.

## 8. What this rework deletes

- The `category` concept end to end: `category:` frontmatter, `discover_categories`,
  `build_category_descriptions`, the live category enum in `build_capture_model`, `.category.toml`,
  and every GUI surface naming a category or a folder.
- Arbitrary tag generation from `key_signals` in the enrichment path.
- **OF-6's entire failure class.** With projects, a brand-new vault is no longer broken: nothing is
  required to exist before a capture can be filed, because "loose" is a valid destination. The
  empty-vault degradation that OF-6 describes stops being reachable.

## 9. Impact on s124's already-committed work

Recorded so the next session does not have to rediscover it.

- **P1 (gui component tests), P3 (panel-geometry watchdog), P4 (phone store factory), P5-1
  (`_notify_windows`)** — untouched by this rework. They stand.
- **P2a (retry engine, committed `cd24b90`)** — the engine, its safety gate, boundedness and audit-log
  fix all stand. **Its precondition does not:** `retry_pending()` refuses to run unless
  `discover_categories()` returns at least one category folder, which is a concept that no longer
  exists. Under projects the precondition collapses to "Ollama is reachable", because a retry can
  always succeed now: worst case the repaired note lands loose.
- **P2b-2 (empty-vault mock board)** — **dead on arrival.** Its entire premise is prompting the user to
  create a first category folder, which is precisely the failure this rework deletes. Discard it.
- **P2b-3 (implement the picked empty state)** — **cancelled, never built.** Do not resurrect it.
- **P2b-1 (Retry action on failed Inbox rows)** — survives. It is about re-running enrichment, not about
  grouping.

## 10. Contract discipline — **AMENDMENT LANDED 2026-08-01 (s124)**

The gate is closed. `data-model-and-contracts.md` is amended to **v3.0** (new §1.3 *projects replace
categories* and §13 *the `.projects.toml` registry*; §1/§1.1/§1.2/§2/§4/§6.2/§7/§12 rewritten), and
`plans/CP2-capture-contract.md` follows it. Code may now be written against those sections.

**Three things surfaced only when the contract was traced byte by byte.** Each was a real collision, not
a wording choice, and each was decided by the user:

1. **Charset hole (decided in-line, no user call needed).** The tag parser is `[^\s]+`, but a project
   name is simultaneously a tag, a TOML key and a directory name — `#project@a.b` nests a TOML table,
   `#project@a/b` escapes the directory. Registry-eligible names are therefore
   `^[A-Za-z0-9][A-Za-z0-9_-]*$`; anything else is a dangling tag and reads as loose. The leading-character
   rule also makes every reserved `_`-prefixed hub folder unreachable as a project name. This costs
   nothing, because "dangling reads as loose" already had to exist for deletion (§5).
2. **Rename cannot rewrite a sacred body — user chose: rename is a user-body edit.** Machine-authored
   bodies are rewritten under the existing provenance gate with no prompt; user-authored notes are
   offered to the user, each rewrite landing as a user edit. **A permanent alias list was offered and
   rejected.** But a transitional `renamed_from` on the entry is *required for correctness*, not
   convenience: a note on an offline phone cannot be confirmed, so without it the dangling rule would
   make that note loose and **a rename would silently empty its own project.** While set, either name
   resolves; it clears when no note carries the old name, and reserves the old name meanwhile.
3. **Loose notes cannot live at the vault root — user chose: a reserved `_loose/` folder.** §1.2 pins
   the attachment ref as `![alt](../_attachments/<id>/<file>)` and states it is identical on both peers
   *because notes live at depth 1*. A note at the root makes `../` escape the vault, and repairing it on
   every move into or out of loose would mean rewriting a sacred body — which provenance-gating forbids
   for phone-origin notes. `_loose/` keeps every note at depth 1, so **the ref survives every move
   untouched.** It is reserved like `_trash/`, and no surface ever shows the name: the UI says *loose*.

**One consequence worth carrying into implementation.** Because the project rides in the body, two peers
assigning *different* projects to one note in a single batch window is now a **body-vs-body conflict**
(conflicted copy), where the old `category` field merged silently. That is louder — and correct: both
edits are user intent, and intent is never silently discarded. It also deletes machinery: §1.2's
divergent-move arm is unreachable (only desktop re-paths), and K-1 / `category_source` retire entirely,
because a user's tag simply *is* the truth and there is nothing left for the machine to revert.

## 11.5 s125 amendments (2026-08-01, user-approved) — contract now v3.1

Four decisions taken while decomposing this design into its first sub-project. Each amends the contract,
which was edited first. Detail: `data-model-and-contracts.md` §1, §1.3, §13.2 and `DECISIONS.md` §5.

1. **The project gets a derived frontmatter cache: `project: [research]`, loose is `project: [-]`.**
   v3.0 said "no project frontmatter field"; that is superseded. The body tag stays the sole truth and
   the field is recomputed from it on save, exactly as `tags:` caches body hashtags — hand-editing it
   does nothing, deleting it rebuilds losslessly. Always bracketed, always present, single-valued.
2. **Structural tags are excluded from the `tags:` cache.** `#project@x` matches the ordinary body-tag
   grammar (`@` is in the token charset for GTD `@work` tags), so without a rule it lands in `tags:` and
   then in the vocabulary each peer normalizes new tags against — where it can capture a genuine new
   tag. One shared predicate at the single derivation point; `tags:` holds descriptive vocabulary only.
3. **Sync is pure transport.** It moves bytes and writes sync bookkeeping; it never edits file content
   in either direction. Frontmatter writes are legal only from an explicit local save/enrichment pass.
   Stronger than the body-sacred lock, which constrains only the body. **Both peers must derive `tags:`
   and `project:` by the identical rule** — a file round-tripping desktop→Drive→phone→Drive→desktop
   returns byte-identical, or the rule has drifted.
4. **Four hardcoded category names are deleted** (explicit user instruction, this is a feature
   subtraction): `storage_engine._LEDGER_FILES` (`Finance`→`Expenses.md`), `pre_resolver`'s Finance/CRM
   hints, `link_resolver`'s CRM word-count special-case, `scratchpad._CATEGORY_DEFAULT_STATUS`. They
   encode a fixed taxonomy that user-named projects replace, and already contradicted the repo's own
   "vault categories are never hardcoded" rule.

**Two contract errors were also corrected.** §13.2 named `_LEDGER_FILES` as the registry's write lock —
it is a category→filename map with no lock, and this rework deletes it; the real primitive is
`dedup._vault_lock`. And §1 of this spec still placed loose notes at the vault root, contradicting its
own §10 item 3 and the depth-1 invariant; fixed.

## 11. Open risks

1. **This is a two-repo, contract-level rework.** It is far larger than one implementation plan and
   should be decomposed into sequenced sub-projects, each with its own spec and plan: ~~the contract
   amendment~~ (**DONE 2026-08-01, §10**), then the desktop tag/registry core, the desktop full-window
   UI, the desktop compact-mode UI, and the phone surfaces.
2. **Full parity in 332 x 320** is the highest-risk UI commitment in the product, and it lands in the
   compact tree that has never been QA-rendered (the long-standing O-16 remainder). Expect the mock
   round to trade something real away.
3. ~~**`.projects.toml` is a new shared-write file.**~~ **RESOLVED — the rule is written, not just
   required:** `data-model-and-contracts.md` §13.2 specifies the three-way per-entry merge (`base_projects`
   in sync state, edit-beats-delete, per-entry `modified` tiebreak, tie → remote), and §13.3 states what
   losing the file costs. **Implementation must be tested against §13.2's table directly** — a
   last-writer-wins shortcut here would silently eat a description written on the other device.
4. **Descriptions become load-bearing for phone accuracy.** A user who leaves them blank gets a matcher
   with almost nothing to embed. The UI must make writing them feel worth doing, and the matcher must
   degrade to "leave it loose" rather than guessing badly.
