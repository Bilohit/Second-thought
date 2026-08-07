# Phone project membership — design

**Date:** 2026-08-07 (s157) · **Status: APPROVED AS WRITTEN by the user 2026-08-08 (s158)**, with §8's
three questions ruled — see §8. · **No code written yet; the implementation plan is the next step.**

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

The phone does both in `driveSync.ts`. **★ CORRECTED 2026-08-08 — this paragraph said "five sites,
each calls `findOrCreateFolder`" and that is wrong. Only THREE are about projects:**

| line | fn | re-parents into | project-related? |
|---|---|---|---|
| 389 | `pushCreate` | `findOrCreateFolder(op.category)` | **YES** |
| 559 | `pushMove` | `findOrCreateFolder(op.category!)` | **YES** |
| 639 | `pushRestore` | `findOrCreateFolder(op.category)` | **YES** |
| 348 | `pushCreate` dedup-adopt | fixed `deps.createParentId` — no name lookup | no |
| 510 | `pushDelete` soft-trash | fixed `deps.trashFolderId` — no name lookup | no |

**Sites 348 and 510 are lifecycle plumbing — create-into-inbox and trash. Deleting them would break
trash and create outright, and they have nothing to do with project membership.** Only the three
`findOrCreateFolder` callers create Drive directories.

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
| **`shared` or legacy `null`** | **either** | **the acting device CLAIMS it — writes the tag and stamps `originDevice` to itself. RULED 2026-08-08, see §4.4.** |

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

### 4.4 Ambiguous provenance — the acting device CLAIMS the note (RULED 2026-08-08)

`originDevice` does not always name an author. It has a third value, `shared` (`note.ts:11`), and it is
`null` on legacy notes. For those, "the authoring device" does not resolve, so §4.1 clause 3 has no
answer without this rule.

**The ruling: on an explicit user action, the acting device writes the body tag and stamps
`originDevice` to itself. No request is minted.** Scoping, which is what makes this safe:

- **Only on a deliberate user action.** Never during a background pass, never during reconcile.
- **Machine enrichment keeps its existing strict gate, unchanged.** Enrichment never claims.
- **Genuine cross-authorship is untouched.** A note explicitly stamped `phone` or `desktop` follows
  §4.1 clause 3 exactly as designed; the request mechanism is unchanged for the case it was built for.

**Why claiming beats resolving-to-desktop.** The conservative alternative (treat ambiguous provenance
as desktop-owned, which is what both shipped gates already do — `mobile_sync_agent.py:1478-1484` admits
`shared`, `noteStore.ts:154` excludes anything not `phone`) has a cost that is **not rare**: every
re-project of such a note from the phone is pending until the desktop wakes, which may be a week.
**Measured on the desktop vault 2026-08-08: 33 notes — 16 `phone`, 5 `desktop`, 12 with NO
`origin_device` at all, 0 `shared`.** So the ambiguous case is **36% of that vault** and the `shared`
case is currently empty. (Caveat: that vault is disposable test data — it describes this vault, not a
real user's.) Claiming's cost, by contrast, requires the user to re-project **the same note on both
devices inside one sync window**. This is a single-user product; that is rare, self-inflicted, and
recoverable — it yields a conflicted copy, which is non-destructive by lock.

**Frequent guaranteed friction is a worse trade than a rare recoverable conflict.** That is the whole
argument.

**The hazard, stated rather than hidden:** `originDevice` is immutable once set (`reconcile.ts:159`),
so a wrong claim is permanent, and a mis-attributed note is one the claiming device will feel entitled
to write in future. Restricting claims to deliberate user actions bounds this to notes the user
personally touched — it can never happen silently across a sweep.

**★ TWO COMMENTS CONTRADICT THE CODE AND BOTH ARE FIXED IN SLICE 1** (ruled 2026-08-08; each cost real
investigation time this session):

1. `note.ts:9` says *"the first device to re-save a `shared` note stamps its own platform."* The
   shipped gates do the opposite. **This ruling makes the comment true** — but it must still be
   rewritten to say *on an explicit user action*, which is narrower than "re-save".
2. `note.ts:10` says `originDevice` is *"null on a legacy note until backfilled-by-location on first
   recompute-on-save."* **No such backfill exists on the phone.** It is stamped once at creation
   (`noteStore.ts:568`), explicitly never rewritten (`:534`), and `reconcile.ts:161` only fills a
   `null` from a non-null peer. The comment describes a mechanism that was never built; it is
   corrected to describe what actually happens.

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
Phone writes body tags for its own notes; requests for foreign ones; claims ambiguous ones (§4.4);
**the three project re-parent sites go** (389 / 559 / 639 — NOT 348 or 510, see §1); desktop and phone
each gain the applier for notes they authored. Both stale comments in `note.ts` are corrected (§4.4).

**Ends with `project_tidy.py`'s docstring being true — but the docstring must first be NARROWED, and
that is a real change, not a formality.** It currently claims *"the phone never moves a file and never
creates a directory."* Sites 348 and 510 keep moving files (into the inbox and the trash) by design and
by the user's ruling of 2026-08-08, so the sentence can never be literally true. It becomes: **the
phone never re-paths a file for PROJECT MEMBERSHIP, and never creates a directory.** That version is
true, is what the desktop actually leans on, and is testable — and it gets a test, not a promise.

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

## 8. Questions — RULED by the user 2026-08-08 (s158)

The design as a whole was **approved as written** on 2026-08-08. The three questions below were open
at the time of writing and are now settled. They are kept (not deleted) so the reasoning survives.

### 8.1 The pending marker's threshold (clause 2) — RULED: a multiple of the sync interval

Not a constant. The threshold scales off the user's own sync interval, so a 15-minute interval flags
at ~75 minutes and a 6-hour interval flags at ~30 hours. A fixed constant is wrong at both ends:
noisy for a long interval, uselessly slow for a short one. The multiplier itself is an implementation
detail for the plan; the *shape* is ruled.

### 8.2 Queued `op_queue.category` ops on upgrade — RULED: CONVERT, and surface the residue

**★ The original framing of this question carried a false premise, corrected at source 2026-08-08
before it was ruled.** It read "the note's body tag remains correct, so nothing is lost." **On the
phone there is no body tag to fall back on:**

- `noteStore.ts:884 setCategory()` writes `{...prev, category}` to the local model and mints a `move`
  op. It never touches the body.
- `frontmatter.ts:259-261` — **`category` is parsed but deliberately never emitted:** *"category is
  DERIVED from the note's hub Drive folder, never frontmatter."*

So a pending re-categorization lives in exactly three places — the in-memory note, the FTS index, and
the queued op — and **all three are derived caches.** The `.md` file carries no record of it.
Discarding the op discards the user's action outright, silently, and specifically for actions taken
*offline*, which is the only time the queue matters. That failure has the same invisible shape clause
2 exists to close, so discard-silently was rejected.

**The rule:** at migration, each queued op carrying a `category` becomes what the new code would have
done in the first place.

| Queued op | Note authored by | Becomes |
|---|---|---|
| `move` | phone | a direct body-tag write — no request, **no file move** |
| `move` | desktop | a `project_request`, with `base` read from the local mirror's `project:` |
| `create` carrying `category` | phone (never uploaded) | the body tag folded into the note before upload |

Two supporting facts, both verified at source:

- **The names are already one namespace.** `pushMove` (`driveSync.ts:559`) passes `op.category`
  straight to `findOrCreateFolder` as a folder name — the same thing contract §13's `dir` is. The
  conversion is close to a field rename, not a translation.
- **`create.category` is a second op class the original question missed.** `coalesce`
  (`opqueue.ts:149-156`) folds a move into a pending `create`, so a never-uploaded phone note carries
  its filing there. A rule that covers only `move` would drop the project off every new offline note
  at upgrade.

**`project_request_at` is set from `op.createdAt`, NOT from migration time.** A three-week-old queued
move is three weeks old, and clause 2 flagging it immediately is the honest outcome. Stamping
migration time would launder a stale intent as fresh — precisely what clause 1 exists to prevent.

**The residue is surfaced, not swallowed.** An op whose category fails `isValidProjectName`, or whose
note has since been deleted, cannot convert. Those are reported to the user through clause 2's
existing "not applied" marker rather than a second UI vocabulary.

Reconstructing `base` is cheap and was wrongly assumed hard: it is read from the local mirror, which
is exactly where a fresh request gets it. A converted request is then an ordinary request, so clause
1's staleness test covers the migration for free.

### 8.3 The Outsider's question — RECORDED, deliberately not acted on

Nobody hand-types `#project@research` — a UI writes it on both platforms. So the body-is-truth rule
is protecting *device* authorship here, not *human* authorship, and this whole mechanism is
downstream of storing a machine-managed pointer inside sacred text.

**Ruled 2026-08-08: note it, do not act on it now.** The contract is ruled and this design implements
it. The question is recorded in `DECISIONS.md` §5 so that **the next field that inherits the same
workaround triggers the conversation**, rather than the workaround being repeated silently. It is not
a reason to delay this work.

---

## 9. What the industry actually does (researched 2026-08-08, recorded so it is not re-derived)

Prompted by the question *"isn't this the same problem Google Docs solves?"* — it is not, and the
reasons are worth keeping.

**Google Docs and Notion are NOT analogous.** Both run a **central server that is the merge
authority** (Docs uses OT; Notion a CRDT/OT hybrid), and **neither has any concept of "only the
authoring party may write this content"** — anyone with access edits anything, live, arbitrated by
the server. This product has deliberately removed both properties. Nothing to borrow.

**★ NO SHIPPED NOTES APP ENFORCES AUTHORING-DEVICE-ONLY BODY WRITES.** Obsidian, Joplin, Standard
Notes, Logseq, Anytype and SilverBullet all let every device write anything and resolve conflicts
*after* the fact — never *prevent* them with a provenance rule. **The body-sacred + provenance lock is
this product's own invention.** There is no reference implementation to copy or to diverge from. That
does not make it wrong; it does mean it must justify itself on its own merits, and that no future
session should go looking for the app we are imitating. There isn't one.

**★ THE REQUEST MECHANISM HAS STRONG PRECEDENT — FROM OUTSIDE THIS DOMAIN, AND §4 ARRIVED AT IT
INDEPENDENTLY.** Two large systems use the identical shape for the identical reason (a writer that may
be offline for a long time):

- **AWS IoT Device Shadow** splits **`desired`** (any client may write — a request) from
  **`reported`** (only the device itself writes — the applied truth), diffs them, and reconciles when
  the device reconnects.
- **Kubernetes** splits **`.spec`** (anyone proposes) from **`.status`** (only the owning controller
  writes), reconciled by an idempotent loop.

That is §4's `project_request` (desired) versus the body tag (reported), exactly. **Label it as a
cross-domain borrow if cited — it is not notes-app precedent.**

**★ THE FINDING THAT CONSTRAINS §4.4: only two conflict-resolution moves actually ship anywhere in
this space** — **last-write-wins by mtime** (Syncthing, rclone bisync, Obsidian's auto-merge) or
**both-survive as separate copies** (Joplin, Standard Notes, SilverBullet, Syncthing's own fallback).
**Nobody ships silent deterministic arbitration WITHOUT a both-survive fallback** — that is the
documented Riak-era mistake, whose own advisories warn about LWW under clock skew and partition.
This product already satisfies the rule: field-aware conflicts produce a conflicted copy, which **is**
the both-survive fallback. **Any future tiebreaker added here must keep it.**

**Honest gap: no precedent exists for ambiguous ownership as a migration-transitional state.** Nothing
in the surveyed products documents how to treat records whose ownership predates the ownership field.
The only tangentially related practice is the generic nullable-column expand/backfill/contract
migration, which is schema housekeeping and says nothing about the UX. **§4.4 was designed without a
reference implementation, and that is a property of the problem, not an oversight.**
