# Phone project membership — design

**Date:** 2026-08-07 (s157) · **Status:** design, awaiting user approval · **No code written.**

Successor to `2026-08-01-projects-rework-design.md`. That document designed the *desktop* half and the
registry; this one designs how the **phone** joins it, and how a project change made on one device
reaches a note the other device authored.

---

## 1. What is actually true today (verified at source this session, not carried)

Three claims the ledger carried were wrong or incomplete. All three were checked in the code before
this design was written.

| Claim carried | What the source says |
|---|---|
| "`category` and `project` coexist by design on both sides" | **The desktop has retired `category` entirely.** `note_model.py:145` drops both `category` and `project` on read; `reconcile.py:12` calls category "the dead v2.2 field". Only the phone still carries `category` as a live machine field. `note_model.py:25` states the interim out loud: *"The phone may still emit `category:` during the interim; the desktop ignores it."* |
| "The wire format is DONE and round-trips" | **Asymmetric.** The phone emits the bracketed `[name]`/`[-]` form unconditionally (`frontmatter.ts:72-79`). The desktop emits `project:` **only when a registry is passed** — `note_model.py:214-216`, `if registry is not None` — and most callers pass none. |
| "The gap is registry resolution" | Right gap, wrong side. The desktop **has** `resolve_project` wired (`project_registry.py:245`, called from `note_model.py:216`). The **phone** has no `.projects.toml` reader at all — zero references in `phone/src`, as contract §13.1 itself records. |

And one contradiction that matters more than any of them:

> `project_tidy.py`'s module docstring asserts **"DESKTOP ALONE RE-PATHS A FILE. The phone never moves
> a file and never creates a directory — that is the load-bearing safety property of the rework."**

The phone does both, at five sites in `driveSync.ts`, all keyed on the retired `category`:
`pushCreate:389` · dedup-adopt `:348` · soft-trash `:510` · `pushMove:559` · `pushRestore:639`.
Each calls `findOrCreateFolder`, which creates Drive directories.

**The desktop's design leans on a safety property that is not yet true.** Making it true is the point
of this work. (The ledger named `pushMove:559` as "the only" re-parent site; it is one of five.)

## 2. Rulings this design is built on

Two from the user, this session:

1. **The phone stops re-parenting files on Drive.** Membership stops being folder-shaped on the phone.
2. **Either device may re-project any note, including one the other device authored, and it syncs.**
   No capability is lost. (An earlier framing that accepted losing foreign-note re-projection was
   explicitly rejected.)

And the standing contract, which this design does **not** reopen: §13's registry, its per-entry
three-way merge, `dir`, `_loose/`, and the rule that the body `#project@<name>` tag is truth while
frontmatter `project:` is a derived cache.

## 3. The problem in one paragraph

Membership lives in the body. The body is sacred, and provenance-gating means no device writes into a
note the other platform authored. So on the phone, re-projecting *its own* note is trivial — write the
tag. Re-projecting a **desktop-authored** note is forbidden by the same lock that makes the product
safe. Today the phone dodges this by moving the file on Drive instead, which is exactly the behaviour
ruling 1 removes. Something has to carry the intent across.

## 4. The mechanism — a based request in machine-owned frontmatter

A single machine-owned frontmatter key on the note itself. The requesting device writes it; the
**authoring** device consumes it, writes the body tag, re-paths the file, and clears the key.

```yaml
project_request: [research]        # desired project, or [-] for loose
project_request_base: [inbox]      # the project the requester believed it was in
project_request_at: 2026-08-07T21:40:00Z
```

Chosen over the two alternatives:

- **A sidecar request file in `.sync/`** — adds a file, a merge rule, a lock and a
  garbage-collection story for one interaction. Rejected on cost.
- **Extending `op_queue` / `_mobile_inbox/`** — that is a *capture intake* path. Routing a note
  mutation through it violates the notes-are-not-captures lock. Rejected outright.

Frontmatter needs no new transport, no new lock, and no new merge rule: field-aware frontmatter merge
already exists and already round-trips unknown keys. The body stays byte-identical, so the
body-sacred assertion that every non-editor op already asserts continues to hold unchanged.

### 4.1 Three clauses, all non-negotiable

**(1) A request carries its base, and a stale request is DISCARDED, not applied.**
If the note's body tag no longer matches `project_request_base`, the request is dropped silently and
the body wins. Without this clause the mechanism can reverse a newer decision: a user re-projects a
foreign note from the phone, the desktop stays shut for three weeks, and on day 21 a three-week-old
request lands on a note whose tag the user already changed on day 4 — and the sync log shows a normal,
successful, field-aware merge. **That is the failure mode that would only ever be found in
production**, and clause 1 is what closes it. Every other multi-writer surface in this product
already refused a base-less write; this one is not special.

**(2) The requester surfaces "not applied", rather than trusting the peer to report.**
Contract §10/§13.1's *"unknown keys are round-tripped, never stripped"* is a good rule that here
guarantees the worst outcome: an older desktop build preserves `project_request:` faithfully and
forever, and never applies it. Sync is green, the file is intact, the key is present, and the feature
simply does not happen — a failure invisible to every layer that could detect it. So the requesting
device tracks `project_request_at` and, past a threshold, shows the request as unapplied. The device
that made the request is the only one that can notice nothing happened.

**(3) The applier is whoever AUTHORED the note — not "the desktop".**
The user's ruling is symmetric and the mechanism must be too. This collapses more than it costs:

| Note authored by | Change made on | Path |
|---|---|---|
| phone | phone | write the body tag directly — **no request at all** |
| desktop | desktop | write the body tag directly — **no request at all** |
| desktop | phone | request → desktop applies on next reconcile |
| phone | desktop | request → **phone** applies on next reconcile |

Row 4 is the one a desktop-centric reading misses. The phone must therefore gain a small applier —
but note what it does *not* need: applying a request to a note the phone authored means writing that
note's own body tag, which the phone is already allowed to do, and **no file move** (the desktop's
tidy pass re-paths it later). So row 4 costs a body-tag write and a key clear. It does not cost the
phone the folder machinery this work is removing.

### 4.2 What the phone does NOT need

**No registry.** Contract §13.3 is explicit that a project's *existence* derives from any note
carrying its tag, and its *membership* from the tags across the vault — the registry holds only the
**description**. So the phone can set membership with the tag alone. A `#project@x` naming a project
with no registry entry is a valid, self-healing state the desktop resolves when it next writes.

This is the single biggest simplification available here, and it is what keeps sub-project 5
(the phone's `.projects.toml` reader, per-entry merge, and resolver) genuinely deferred rather than
secretly required. The phone gains project *membership* now and project *descriptions* later.

### 4.3 Concurrency

Two devices requesting different projects for one note in one batch window is an ordinary field-aware
frontmatter merge: newest `project_request_at` wins, and the loser's request is discarded by clause 1
the moment the winner's tag lands. The user edits the body tag directly while a request is pending —
also clause 1: the body moved, the request is stale, it is dropped. Both cases resolve without a new
rule.

## 5. What the user sees

**The phone must not lie about where a note is.** Batched sync at a user-set interval, plus a desktop
that may be shut for a week, makes "pending" a normal state rather than an edge. If the phone
optimistically files the note under its new project while the folder and the desktop still show the
old one, the user's model of where their note lives breaks — and they re-do the action, producing
three conflicting requests authored by one confused person.

So: show the note where it **is**, with a quiet pending marker, using the quiet-dot vocabulary that
already ships. No new UI language. The "unapplied" state from clause 2 escalates that same marker
rather than introducing a second one.

**This is the part of the design least settled by reasoning and most settled by use.** It is called
out as such rather than asserted.

## 6. Sequencing

The two rulings cannot ship in either order alone — removing the phone's file moves without the
request mechanism *is* the capability loss the user rejected. So slice 1 carries both.

**Slice 1 — membership moves off folders (this design).**
Phone writes body tags for its own notes; requests for foreign ones; the five `driveSync.ts` re-parent
sites go; desktop and phone each gain the applier for notes they authored. **Ends with
`project_tidy.py`'s docstring being true** — and that docstring gets a test, not a promise.

**Slice 2 — the interim asymmetry closes.** The desktop's registry-gated `project:` emission
(`note_model.py:214`) becomes unconditional, and the phone stops emitting `category:`. Both sides then
agree on the field set for the first time.

**Slice 3 — the registry reaches the phone.** Sub-project 5: `.projects.toml` read, per-entry merge
per §13.2, descriptions, project create/rename from the phone. Unchanged in scope by this design, and
genuinely deferred by §4.2.

## 7. Testing

- The body-sacred assertion already mandatory on every non-editor op covers the request write; it must
  be asserted explicitly on both the request write and the request apply.
- **Clause 1 needs a test that has been seen RED**: a request whose base no longer matches must not
  apply. Probe it by removing the base check and confirming the test fails.
- The five removed re-parent sites need a test that the phone issues **no** Drive parent mutation —
  the invariant `project_tidy.py` claims. A grep is not a test; assert at the Drive-request seam that
  `addParents`/`removeParents` is never sent by the phone.
- Row 4 of §4.1 (desktop requests against a phone-authored note) is the row most likely to be built
  last and tested least. It gets its own test.
- `fuzzRaces.test.ts` must run (`FUZZ=1`) — this touches `driveSync`/`opqueue`.

## 8. Open questions

1. **The pending marker's threshold** (clause 2) — how long before "pending" becomes "not applied"?
   Depends on the user's sync interval; probably a multiple of it rather than a constant.
2. **Does removing `op_queue.category` move ops orphan queued ops on an upgrade?** An in-flight move
   op minted before the upgrade has no meaning after it. Needs a drain-or-discard rule.
3. **The Outsider's question, recorded and not answered:** nobody hand-types `#project@research` — a
   UI writes it on both platforms. So the body-is-truth rule is protecting *device* authorship here,
   not *human* authorship, and this whole mechanism is downstream of storing a machine-managed
   pointer inside sacred text. Worth asking before the next field inherits the same workaround.
   **Not a reason to delay this work** — the contract is ruled and this design implements it.
