# Sub-project 3 — desktop full-window projects UI (design, CLOSED 2026-08-02)

**Parent:** `2026-08-01-projects-rework-design.md` (§6 item 1 = layout A3, CLOSED; §7 = compact, CLOSED
and owned by sub-project 4). **Contract:** `data-model-and-contracts.md` v3.1 §1.3, §13.
**Predecessor:** S1 desktop tag/registry core, CLOSED s126.

**Status: the design gate is CLOSED.** The user confirmed the live board on 2026-08-02 after three
feedback rounds. The board is `gui/mocks/2026-08-01-projects-fullwindow-v3.html` (untracked) and is the
visual source of truth for everything below. Where this document and the board disagree, **the board
wins and this document is wrong** — it was written from the board, not the other way round.

---

## 1. Scope

Replace the desktop full-window Vault page with the project management page. One screen, no drill-in.

**In scope:** browse projects · browse tags · read a project's or a tag's notes · create · rename ·
edit description · delete · handle one Inbox suggestion · sort the note list.

**Out of scope, explicitly:** the compact/capsule surfaces (sub-project 4), every phone surface
(sub-project 5), the note editor itself (opening a note hands off to the existing editor unchanged),
and any change to how tags or projects are *derived*. This sub-project is a **view over routes that
already exist**. It adds no Python.

---

## 2. The one thing to know before reading further

**Every endpoint this screen needs already ships.** VERIFIED 2026-08-02 by reading
`omni_capture/vault_admin.py`; all live on the router mounted into `server.py`:

| Need | Route | Notes |
|---|---|---|
| project list + counts | `GET /vault/projects` | returns `name`, `description`, `renamed_from`, `created`, `modified`, `file_count` |
| create | `POST /vault/projects` | |
| edit description | `PATCH /vault/projects/{name}/description` | |
| rename | `PATCH /vault/projects/{name}` | writes the transitional `renamed_from` (contract §13) |
| delete | `DELETE /vault/projects/{name}` | registry entry only; notes survive and become loose |
| a project's notes | `GET /search?project=<name>` | |
| tag list + counts | `GET /tags` | tag tree, scanned from files by `tag_index.scan_tag_paths` |
| a tag's notes | `GET /search?q=tag:<name>` | `_extract_tag_filter` strips the token and applies it as an exact-tag filter; the semantic tier is skipped for a tag-only query, so results are exact, not fuzzy |
| the Inbox suggestion | `GET /inbox/{note_id}/suggest-projects` | the engine proposes; it never creates |

**So SP3 is a `gui/` sub-project.** If a task in the plan wants to edit a `.py` file, that task is
wrong and must be stopped and reported, not bent.

> **★ ONE AUTHORIZED EXCEPTION, granted by the user 2026-08-02 and already landed (s129).** `GET /search`
> now also publishes **`modified`** — the note file's mtime, epoch-seconds float, `null` when the file
> cannot be stat'ed — on **both** row tiers. Without it §4.5's third sort arrangement had no data at all:
> `_SEARCH_ROW_FIELDS` carried no mtime and `captures.db` has no such column. **This exception is closed.
> Every other `.py` edit in SP3 is still stopped and reported.** Detail: `DECISIONS.md` §5, s129 item 1.

### 2.1 Why s127's index fix is load-bearing here, not incidental

`/search` publishes `project` on **every** row (`_SEARCH_ROW_FIELDS`, `vault_admin.py:544`). That field
is the `captures.project` column — the exact column s127 corrected from `p.parent.name` to the body tag
resolved against `.projects.toml`. The tag view's per-row project chip (§5.3) reads it directly.

**Before s127 this screen could not have been built truthfully:** it would have drawn a chip saying
`personal` or `recipes` for legacy folders no registry has ever held, and confident note counts for
projects that do not exist.

### 2.2 The sentinel

The index stores loose notes under the internal sentinel string `_loose`. **No surface may ever render
it.** The UI says *loose*, styled as the dashed-border variant. This applies to the tile, the pane head,
and the tag view's project chip. A test must pin it.

---

## 3. Layout — A3 split panel (CLOSED in the parent spec, not reopened)

```
┌ Vault · projects ─────────────────────────────── ↻  ✕ ┐
│ ┌── rail 260px ──┐ ┌──────── pane ──────────────────┐ │
│ │ [Projects|Tags]│ │  head: name + rename/delete    │ │
│ ├────────────────┤ │        + description editor    │ │
│ │  (scrolls)     │ │ ───────────────────────────────│ │
│ │  tiles / tags  │ │  N notes            [sort ⟳]   │ │
│ │                │ │ ───────────────────────────────│ │
│ ├────────────────┤ │  note rows (scroll)            │ │
│ │ [ suggestion ] │ │                                │ │
│ ├────────────────┤ │                                │ │
│ │ [+ New project]│ │                                │ │
└─┴────────────────┴─┴────────────────────────────────┴─┘
```

The rail is a **three-band column**. Band 1 (toggle) and band 3 (New project) never scroll and never
move. Only band 2 scrolls. The suggestion sits directly above band 3, so **New project is the last
thing in the rail in every state** — it never floats above the suggestion and is never pushed around by
how many projects exist.

---

## 4. Decisions taken during the design rounds (binding on the components)

These are decisions, not mock styling. Each one exists because a specific weaker alternative was
rejected.

### 4.1 The rail toggle is two-way, using the real component

Exactly two positions, `Projects | Tags`, built from the actual `SegmentedToggle` markup and motion —
not a lookalike. It is the one control shared across all three shells (parent spec §6), so a
divergence here forks the product's most repeated affordance.

### 4.2 Suggestion-row button geometry (user-specified, round 2)

- **One control height, declared once** on the suggestion container (`--ctl: 30px`), governing all
  three buttons. Not three padding values that happen to agree.
- `Create` and `Rename` are **equal width by construction**: `flex: 1 1 0` + `min-width: 0`, labels in
  a span that ellipsises. A long label can never make one wider than the other.
- The dismiss is a **true square**: `width == height == var(--ctl)`, excluded from the flex growth.
- Gap 6px.

### 4.3 The suggestion is a box, not a band (user-specified, round 3)

It sits in the **same 8px gutter the New project button sits in**, so the two are the same width by
construction (rail width minus the same gutter on both sides), and it touches no rail edge. The
previous full-bleed band with a top hairline read as another *region* of the rail; a bordered box reads
as **one pending decision resting in** the rail, which is what it is.

### 4.4 Controls stopped borrowing the input colour (user-specified, round 3)

The sort button was drawn on `--bg` — the same value the description `textarea` uses for its field — so
an instrument looked like a second text box. **One rule now separates them:**

> **inputs are RECESSED** (`--bg`) · **controls are RAISED** (`--ctl-face`)

**Two new tokens land in `gui/src/index.css`** (and, per the workspace token lock, are mirrored into
`phone/src/lib/tokens.ts` + `design-system.md` only if a phone surface ever adopts them — SP3 itself
does not touch the phone):

```css
--ctl-face: #404040;         /* raised control face */
--ctl-face-hover: #4d4d4d;
```

Applies to: the sort button, `New project`, `Rename`, and the dismiss square. **`Create` keeps the
accent** — making all four match would flatten the primary out of the row.

**Contrast, checked not assumed:** `--text-2` on `--ctl-face` measures **3.9:1**, under the 4.5:1 body
floor, so control labels sit at `--text-1` (**10:1**). The sort button's cycle glyph moved from
`--text-3` (2.4:1, under the 3:1 non-text floor) to `--text-2`.

Grayscale only. No new hue. Green/yellow/red stay semantic.

### 4.5 Sorting is an instrument

One button cycling three arrangements: **newest first → oldest first → recently edited**.

- **Three distinct icon silhouettes**, not one glyph rotated.
- The button **restates itself** on click: new icon (`icPop`, 260ms), new label, and one 360° turn of
  the cycle glyph as the acknowledgement that the click landed.
- The right-hand meta column **reports the field actually being sorted on** (`added …` vs `edited …`),
  so the list never claims to be ordered by something it is not.
- **The rows travel** — FLIP: measure (First), re-parent the existing nodes into the new order (Last),
  invert each row by its delta, release on the next frame with a stagger **capped at 110ms**, 380ms
  `--ease-travel`. Nodes are **moved, never re-created**, so hover and focus survive the transition.
- Sort order is **stable**: original index is the tiebreak, so equal timestamps never shuffle at random
  between cycles.
- Under `prefers-reduced-motion` the entire invert/play half is skipped and the DOM simply ends up in
  the new order.

### 4.6 The description field

- Saves as you type (debounced), no Save button on this surface.
- **No quality gauge.** Deleted in round 3 with the user's agreement. It scored a character count and
  drew it as three bands of match quality — a measurement this product cannot make, and the spec has
  never defined a threshold. Parent spec §4 also notes the matcher blends in the notes' own centroid
  once a project holds enough notes, so the gauge measured a dependency that shrinks on its own.
- **What replaced it:** one line stating what the field is for — *"This is what your phone matches new
  notes against."* — plus a **yellow** variant for the single checkable fact: *"Empty. Your phone has
  nothing to match new notes against yet."* Emptiness is real and has a real consequence; quality is
  not measurable, so nothing implies a score.

### 4.7 Delete is explained at the point of decision

The confirm strip states the actual consequence: *"Its N notes become loose. None is deleted, trashed
or edited."* This is true — `DELETE /vault/projects/{name}` removes the registry entry only.

### 4.8 Loose is a destination, not a queue

Loose gets its own tile with a dashed dot, and the pane head reads *"no project tag, nothing to set
up"*. The overflow row says *"Loose is normal and permanent, not a queue."* Nothing counts down,
nothing is red, nothing nags.

---

## 5. The Tags view (NEW in round 3 — this did not exist)

Before this round the tag rows were **labels**. Clicking one did nothing.

### 5.1 Behaviour

A tag row is a real control (`role="option"` in a `role="listbox"`). Clicking it lists that tag's notes
in the main pane, driven by the **same** sort instrument. Selected state uses the **same visual
language as a project tile** (accent wash + 2px accent left edge), because *"this is what the right
side is showing"* must not mean two different things on two halves of one toggle.

### 5.2 Switching to Tags selects the first tag

Flipping a view must not hand back a dead right-hand panel that needs a second click before the screen
says anything.

### 5.3 Every row reports its project

A tag **cuts across** projects: a note has exactly one project and any number of tags. So the tag list
answers the one question a project list never has to — *where does this note actually live* — with a
per-row chip showing the project name, or dashed **loose**. Text and border, not a coloured pill;
colour there would be decoration.

### 5.4 A tag head is not a project head

**No description editor, no rename, no delete.** Tags are body-authoritative — recomputed from the body
`#hashtags` on save (workspace lock) — so this panel *cannot* write one, and must not imply it can. The
head is the tag name and its vault-wide count, nothing else. An explainer paragraph was drafted and
**cut at the user's instruction in round 3**: the per-row chip already demonstrates that tags span
projects, so the sentence restated what the list itself shows.

### 5.5 The list is COMPLETE — never "N of M" (user's call, round 3)

**A tag view lists every note carrying that tag.** The count in the rail, the count in the head, and the
number of rows on screen are **one number**. The list *scrolls*; it does not truncate, and there is no
"N more" row and no "5 of 11" label — a label like that claims the view is showing a subset, which is
not what this screen does.

**★ THE IMPLEMENTATION TRAP THIS EXPOSES — the single most likely way to ship this wrong.**
`GET /search` takes `limit: int = 25`, clamped to `min(max(1, limit), 200)` (`vault_admin.py:580`,
`:599`). **A caller that relies on the default silently truncates at 25 notes**, and the screen will
look perfect on a small vault and quietly lie on a real one. The call **must pass an explicit limit**.

- **Requirement:** the tag and project note requests pass an explicit `limit`, and the UI **must not**
  render a count it did not receive rows for.
### 5.5.1 Paging — DECIDED by the user 2026-08-02

> **"if more than 200 notes, add page system. no page ui if less than 200 notes"**

- **Fetch `limit=200`.** This is the server's own hard clamp (`min(max(1, limit), 200)`), so 200 is not
  an arbitrary page size — it is the largest single response the route can produce.
- **Under 200 notes: there is no pager, and no trace of one.** No disabled arrows, no "Page 1 of 1", no
  reserved space that collapses. The overwhelmingly common case must look exactly as it does today.
- **At 200 or more: a page control appears** and the list becomes page 1 of N. Pages, not infinite
  scroll — the user's explicit call.
- **The count label stays honest either way.** It reports the *total*, and when a pager is present the
  screen must make clear you are looking at one page of that total. It must never print `N of M` in a
  way that implies truncation with no way to reach the rest, which is the failure §5.5 exists to stop.
- **Detection rule:** the pager exists **iff** the total exceeds one page. Do not infer "there might be
  more" from a full 200-row response alone without knowing the total — `GET /tags` gives the tag's true
  count, and a project's true total comes from **`GET /stats`'s `by_project`**, so the total is available
  without guessing.
  > **★ CORRECTED 2026-08-02 (s130). This clause originally read "`/vault/projects` gives `file_count`",
  > and that was wrong.** `file_count` is `_project_file_count` (`vault_admin.py:98-102`) — the number of
  > `.md` files **in the directory** `root/<name>`. That is the directory-derived semantics s127 ripped
  > out of the index, and the board calls it out by name (line 448: *"The number on every tile comes from
  > the index's `project` column… it is derived from the body tag now"*). `GET /stats`'s `by_project` is
  > `SELECT project, COUNT(*) FROM captures WHERE provisional = 0 GROUP BY project`
  > (`index_writer.py:1041-1051`) — the same tag-derived column `/search?project=` filters on, so the
  > total and the list it pages through cannot drift apart. **A project registered but holding no notes
  > has no `by_project` row at all and counts 0** — it must not vanish from the rail.
- **Not yet drawn.** The pager's visual is the one piece of this screen with no mock. It uses the
  existing raised-control tokens (§4.4) and the existing `.btn-hover` utility, and it must satisfy §7's
  a11y floors. **Show the user a mock of it before it ships** — but it is deliberately last, because on
  today's real vault (17 notes, largest tag 11) it will never render.

### 5.6 Counts must agree

`GET /tags` and `GET /search?q=tag:<x>` resolve through the same `tag_index` scan by design
(`vault_admin.py:699` docstring), so a row's count matches the number of notes its click lists. **A
test must pin this**, because the two halves disagreeing by construction is exactly the bug that
docstring records having already been fixed once.

**The board now enforces this structurally rather than by hand:** tag counts are *derived* from the note
lists (`tagCount(name) = TAG_NOTES[name].length`), so the rail number and the list length cannot drift
apart. The real component should do the same — **derive the displayed count from the rows it holds, and
never render a count from one source beside a list from another.**

> **★ ADDED 2026-08-02 (s130) — the project half of this rule, learned by shipping it wrong once.**
> A project's tile cannot derive its count from rows the rail holds, because the rail holds rows for no
> project. **Its count comes from `GET /stats`'s `by_project`** — the index's tag-derived `project`
> column, the same column `GET /search?project=` filters on — so the tile number and the pane's list
> length still cannot drift apart. **It must never come from `/vault/projects`'s `file_count`**, which
> counts `.md` files in the directory `root/<name>` and would put s127's directory-derived bug back on
> screen. The registry (`/vault/projects`) stays the authority on **which** projects exist; `/stats` is
> the authority on **how many notes** each holds. See §5.5.1's corrected detection rule.

---

## 6. States that must ship

| State | Behaviour |
|---|---|
| No projects (today's real vault) | Calm empty head: *"No projects yet"*, all notes loose, no error, no nag, **no suggestion**. Rail holds the one loose tile, spanning the row so a 2-col grid has no hole. Sort still works — a loose list is still a list you want to arrange. |
| Project with no description | Tile reads *"N notes, no description"* in yellow; pane shows the empty-description line. |
| Suggestion pending | The box. `Create` / `Rename` / dismiss. |
| Suggestion approved | Box turns green, header reads *Created*. |
| Suggestion dismissed | Collapses in place (`grid-template-rows: 1fr → 0fr`, 240ms) then drops from state. Instant under reduced motion. |
| Delete confirm | Red-tinted strip with the true consequence and two buttons. |
| Tag selected | §5. |

---

## 7. Accessibility (checked against the board, not aspirational)

- Every interactive element is a real `<button>`; tag list is `listbox`/`option`, rail toggle is
  `tablist`/`tab`.
- Visible `:focus-visible` outline on every control; the note row is `tabindex="0"`.
- The sort button's `aria-label` **restates the current arrangement** after each cycle, so a screen
  reader is never told the old order.
- Icon-only controls (dismiss, rename, delete, refresh, close) all carry `aria-label` **and** `title`.
- Colour is never the only signal: loose is dashed *and* labelled; the empty-description warning is
  yellow *and* says so in words.
- Contrast floors are met per §4.4.

---

## 8. Motion inventory (all of it, so nothing is hand-rolled later)

| What | Spec |
|---|---|
| segmented pill | `transform` in whole 100% steps, 200ms `--ease-settle`, DOM node persists across toggles so the transform has a "from" state |
| view swap | entrance-only keyed fade+slide, 220ms `--ease-travel`, direction by `--swap-dir` |
| note re-order | FLIP, 380ms `--ease-travel`, stagger 14ms/row **capped at 110ms** |
| sort icon swap | `icPop` 260ms `--ease-travel`; cycle glyph 360° over 320ms |
| suggestion collapse | `grid-template-rows` 240ms `--ease-travel` + opacity 180ms |
| dismiss hover | `xPulse` 340ms + red border/glow |
| button hover | the existing `.btn-hover` utility from `index.css`, unchanged |
| everything above | collapses to instant or a crossfade under `prefers-reduced-motion` |

**No new easing curve or duration may be invented during implementation.** Anything not in this table
goes back to the user via a mock, per the standing four-design-skill mandate.

---

## 9. Verification — what "done" means

1. `npm test` and `npm run build` green in `gui/`. **Gate to beat: 545 + build exit 0.**
2. New sibling `*.test.ts` for every non-trivial pure module extracted (sort ordering + stable tiebreak,
   the `_loose` → *loose* mapping, tag-count agreement). Component tests use the **opt-in**
   `// @vitest-environment happy-dom` docblock — `vite.config.ts` must **not** be given a global
   `test.environment`, or the 534 existing Node-env tests move underneath us.
3. **No Python file changes.** `git diff --stat` must show `gui/` only.
4. Desktop pytest re-run anyway as a regression check. **Gate to beat: 1262 · 4 skipped.**
5. **Live QA is required and has never been run on this rework.** The release exe goes stale silently —
   check its mtime before believing anything on screen. happy-dom has no layout engine, so geometry is
   CDP-only; measure rects and computed styles rather than screenshotting.

---

## 10. Open, and owned by nobody yet

1. **`project_registry.rebuild_from_vault` has zero non-test callers** (VERIFIED by grep, s127). It is
   contract §13.3's registry-recovery path. This screen is the natural home for a *"rebuild from the
   tags in my vault"* action, but **it was not designed and must not be invented during
   implementation** — it needs its own mock round.
2. **`today_view.create_daily_note(folder="Daily")`** — the user decided a real registered `Daily`
   project (DECISIONS §5, s127 item 1). **Decided, not built.** SP3 implements it.
3. Two things deliberately **not** built, offered and not taken up: a *"make a project from this tag"*
   action in the tag head, and clicking a row's project chip to jump to that project.
