# Project Membership Slice 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move project membership off Drive folders on the phone, and let either device re-project any note — including one the other device authored — via a based request in machine-owned frontmatter.

**Architecture:** A note's project is its body tag `#project@<name>`. The device that authored a note is the only one that writes that tag. A device that wants to re-project a foreign note writes `project_request` / `project_request_base` / `project_request_at` into frontmatter; the authoring device applies it, writes the tag, and clears the keys. A request whose base no longer matches the note's current tag is discarded, not applied. Notes with ambiguous provenance (`shared` or legacy `null`) are claimed outright by the acting device, but only on an explicit user action.

**Tech Stack:** TypeScript strict (phone, Expo SDK 54 / RN 0.81, vitest), Python 3 typed (desktop, pytest), SQLite (`expo-sqlite`), Google Drive REST.

**Source spec:** `docs/superpowers/specs/2026-08-07-phone-project-membership-design.md` — approved 2026-08-08. Read §4, §4.4 and §7 before starting. This plan implements slice 1 only.

## Global Constraints

- **The body is sacred.** Every non-editor op asserts the body is byte-identical before/after, ABOVE the one sanctioned trailing machine tag line. Every task that touches a note asserts this.
- **`project_tidy.py`'s invariant, as narrowed by the spec §6:** the phone never re-paths a file **for project membership**, and never creates a directory. Trash (`driveSync.ts:510`) and create-into-inbox (`:348`) keep their fixed-parent moves — **do not remove them.**
- **Only three re-parent sites are in scope:** `driveSync.ts:389` (`pushCreate`), `:559` (`pushMove`), `:639` (`pushRestore`) — the three `findOrCreateFolder` callers.
- **Valid project name (both platforms, identical):** `^[A-Za-z0-9][A-Za-z0-9_-]*$`. Desktop: `projects.py:60 is_valid_project_name`, regex at `projects.py:37`. Reuse; never re-declare.
- **Authorship** is `originDevice` (`note.ts:33`, values `"phone" | "desktop" | "shared" | null`). The effective-origin fallback expression already exists on both sides and must not be re-invented: phone `noteStore.ts:154`, desktop `mobile_sync_agent.py:1478-1484`.
- **Claiming happens only on an explicit user action.** Never in a background pass, never in reconcile, never in enrichment.
- **`project_request_at` is set from the ORIGINATING action's timestamp**, never from migration time.
- **Never edit a baseline file to make a check pass.** `tools/identity-baseline.txt`, `tools/reachability-baseline.txt`.
- **Gates:** agents run `python check.py 0` after every edit and `python check.py 1` before reporting done. Agents never run tier 2 or 3, and never commit. The main thread runs `python check.py 2` before every commit, in the foreground, exit code read.
- **`FUZZ=1` is mandatory for this slice** — it touches `driveSync`/`opqueue`. Phone: `npm run test:fuzz`. Desktop: `FUZZ=1 pytest test_fuzz_races.py -q`.
- **No emoji anywhere.** Inline SVG icons only, from each repo's icon module.
- **RN components cannot be rendered under vitest** (RN 0.81 ships untranspiled Flow). Pure helper + test the helper. Never fake a render test; never narrow `vitest.config.ts`'s include.

---

## File Structure

**Phone — create**
- `phone/src/lib/projectTag.ts` — pure: read/write the `#project@<name>` body tag. Sibling `projectTag.test.ts`.
- `phone/src/lib/projectRequest.ts` — pure: build, parse, and staleness-check a request. Sibling `projectRequest.test.ts`.
- `phone/src/lib/projectMigration.ts` — pure: turn a queued `category` op into a tag write or a request. Sibling `projectMigration.test.ts`.

**Phone — modify**
- `phone/src/lib/note.ts` — the two stale comments (spec §4.4).
- `phone/src/lib/frontmatter.ts` — typed parse/emit of the three request keys.
- `phone/src/lib/noteStore.ts` — `setProject` replaces `setCategory`'s role; the applier; claim-on-action.
- `phone/src/lib/driveSync.ts` — remove the three project re-parent sites.
- `phone/src/lib/syncConfig.ts` — the not-applied threshold, mirroring `provisionalTtlSec`.
- `phone/src/db/index.ts` — `SCHEMA_VERSION` bump + the migration hook.
- `phone/src/lib/noteList.ts` + `phone/src/components/QuietDot.tsx` — the pending/not-applied marker.

**Desktop — modify**
- `omni_capture/note_model.py` — typed read/emit of the request keys.
- `omni_capture/mobile_sync_agent.py` — the desktop applier, beside the existing provenance-gated pass.
- `omni_capture/project_tidy.py` — narrow the docstring, and give it a test.

---

### Task 1: The body-tag writer (phone)

Nothing on the phone writes `#project@<name>` today — `bodyTags.ts:57 extractBodyTags` only reads. The desktop's equivalent writer is `machine_tags.py:28 apply_trailing_tags_line`, which maintains ONE trailing `tags: #a #b` line. This task is its phone counterpart, restricted to the project tag.

**Files:**
- Create: `phone/src/lib/projectTag.ts`
- Test: `phone/src/lib/projectTag.test.ts`

**Interfaces:**
- Consumes: `extractBodyTags(body: string): string[]` from `phone/src/lib/bodyTags.ts`
- Produces: `readProjectTag(body: string): string | null`, `writeProjectTag(body: string, project: string | null): string`

- [ ] **Step 1: Write the failing test**

```ts
// phone/src/lib/projectTag.test.ts
import { describe, it, expect } from "vitest";
import { readProjectTag, writeProjectTag } from "./projectTag";

describe("projectTag", () => {
  it("reads the project tag from a trailing machine line", () => {
    expect(readProjectTag("hello\n\ntags: #project@research #idea")).toBe("research");
  });

  it("returns null when there is no project tag", () => {
    expect(readProjectTag("hello\n\ntags: #idea")).toBeNull();
    expect(readProjectTag("hello")).toBeNull();
  });

  it("adds a trailing tags line when none exists", () => {
    expect(writeProjectTag("hello", "research")).toBe("hello\n\ntags: #project@research");
  });

  it("replaces an existing project tag in place, keeping other tags and their order", () => {
    const before = "hello\n\ntags: #idea #project@old #later";
    expect(writeProjectTag(before, "new")).toBe("hello\n\ntags: #idea #project@new #later");
  });

  it("removes the project tag when passed null, keeping the other tags", () => {
    const before = "hello\n\ntags: #idea #project@old";
    expect(writeProjectTag(before, null)).toBe("hello\n\ntags: #idea");
  });

  it("removes the whole trailing line when the project tag was the only tag", () => {
    expect(writeProjectTag("hello\n\ntags: #project@old", null)).toBe("hello");
  });

  it("is idempotent", () => {
    const once = writeProjectTag("hello", "research");
    expect(writeProjectTag(once, "research")).toBe(once);
  });

  it("leaves the text ABOVE the trailing line byte-identical", () => {
    const body = "line one\nline two\n\ntags: #project@old";
    const out = writeProjectTag(body, "new");
    expect(out.split("\n\ntags:")[0]).toBe("line one\nline two");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/projectTag.test.ts`
Expected: FAIL — "Failed to resolve import ./projectTag"

- [ ] **Step 3: Write minimal implementation**

```ts
// phone/src/lib/projectTag.ts
// The phone's writer for the ONE sanctioned machine body line (contract v3.1 §1.3, the s140 carve-out):
// a single trailing `tags: #a #b` line at the very end of a note this device authored. Mirrors the
// desktop's machine_tags.py:28 apply_trailing_tags_line, narrowed to the project tag.
//
// BODY-SACRED: everything above the trailing line is returned byte-identical. That is asserted in
// projectTag.test.ts and re-asserted at every call site.

const TRAILING_RE = /\n*\ntags:[^\n]*$/;

function splitTrailing(body: string): { above: string; tags: string[] } {
  const m = TRAILING_RE.exec(body);
  if (!m) return { above: body, tags: [] };
  const line = m[0].slice(m[0].indexOf("tags:") + "tags:".length).trim();
  const tags = line.split(/\s+/).filter((t) => t.startsWith("#")).map((t) => t.slice(1));
  return { above: body.slice(0, m.index), tags };
}

function joinTrailing(above: string, tags: string[]): string {
  if (tags.length === 0) return above;
  return `${above}\n\ntags: ${tags.map((t) => `#${t}`).join(" ")}`;
}

export function readProjectTag(body: string): string | null {
  const hit = splitTrailing(body).tags.find((t) => t.startsWith("project@"));
  return hit ? hit.slice("project@".length) : null;
}

// `project === null` clears membership (loose). Order of unrelated tags is preserved: a replace
// happens in place, so a project change never reshuffles the user's visible tag line.
export function writeProjectTag(body: string, project: string | null): string {
  const { above, tags } = splitTrailing(body);
  const idx = tags.findIndex((t) => t.startsWith("project@"));
  const next = [...tags];
  if (project === null) {
    if (idx !== -1) next.splice(idx, 1);
  } else if (idx === -1) {
    next.push(`project@${project}`);
  } else {
    next[idx] = `project@${project}`;
  }
  return joinTrailing(above, next);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/projectTag.test.ts`
Expected: PASS, 8 tests

- [ ] **Step 5: Reflex gate, then commit**

```bash
python check.py 0
git add phone/src/lib/projectTag.ts phone/src/lib/projectTag.test.ts
git commit -m "feat(project): phone-side writer for the #project@ body tag"
```

---

### Task 2: The request record — build, parse, staleness (phone)

Clause 1 of the spec: a request carries the project the requester believed the note was in, and a request whose base no longer matches is **discarded, not applied**. This task is that rule as a pure module, because it is the one piece whose failure mode is invisible in production.

**Files:**
- Create: `phone/src/lib/projectRequest.ts`
- Test: `phone/src/lib/projectRequest.test.ts`

**Interfaces:**
- Consumes: `readProjectTag` from Task 1
- Produces: `ProjectRequest`, `buildRequest(desired, base, atIso)`, `readRequest(extra)`, `writeRequest(extra, req)`, `clearRequest(extra)`, `requestOutcome(body, req)`

- [ ] **Step 1: Write the failing test**

```ts
// phone/src/lib/projectRequest.test.ts
import { describe, it, expect } from "vitest";
import { buildRequest, readRequest, writeRequest, clearRequest, requestOutcome } from "./projectRequest";

const AT = "2026-08-08T10:00:00.000Z";

describe("projectRequest", () => {
  it("round-trips through the frontmatter extra bag in the bracketed wire shape", () => {
    const req = buildRequest("research", "inbox", AT);
    const extra = writeRequest({}, req);
    expect(extra.project_request).toBe(" [research]");
    expect(extra.project_request_base).toBe(" [inbox]");
    expect(readRequest(extra)).toEqual(req);
  });

  it("encodes a loose target and a loose base as [-]", () => {
    const extra = writeRequest({}, buildRequest(null, null, AT));
    expect(extra.project_request).toBe(" [-]");
    expect(readRequest(extra)).toEqual({ desired: null, base: null, at: AT });
  });

  it("returns null when the bag holds no request", () => {
    expect(readRequest({})).toBeNull();
    expect(readRequest({ tags: " [a]" })).toBeNull();
  });

  it("clearRequest removes all three keys and leaves unrelated keys untouched", () => {
    const extra = writeRequest({ custom: " keep" }, buildRequest("research", "inbox", AT));
    const cleared = clearRequest(extra);
    expect(cleared).toEqual({ custom: " keep" });
  });

  // CLAUSE 1 — the failure this whole mechanism exists to avoid.
  it("APPLIES when the note's current tag still matches the base", () => {
    const req = buildRequest("research", "inbox", AT);
    expect(requestOutcome("note\n\ntags: #project@inbox", req)).toBe("apply");
  });

  it("DISCARDS when the note's tag moved since the request was made", () => {
    const req = buildRequest("research", "inbox", AT);
    expect(requestOutcome("note\n\ntags: #project@archive", req)).toBe("discard");
  });

  it("APPLIES a loose-base request against a note with no project tag", () => {
    expect(requestOutcome("note", buildRequest("research", null, AT))).toBe("apply");
  });

  it("DISCARDS a loose-base request once the note has acquired a project", () => {
    expect(requestOutcome("note\n\ntags: #project@x", buildRequest("research", null, AT))).toBe("discard");
  });

  it("DISCARDS a request that asks for what the note already has", () => {
    const req = buildRequest("research", "research", AT);
    expect(requestOutcome("note\n\ntags: #project@research", req)).toBe("discard");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/projectRequest.test.ts`
Expected: FAIL — "Failed to resolve import ./projectRequest"

- [ ] **Step 3: Write minimal implementation**

```ts
// phone/src/lib/projectRequest.ts
// A BASED request for a project change on a note this device did not author (spec §4).
// Machine-owned frontmatter only — the body is never touched by the requester.
//
// The wire shape mirrors `project:` exactly: always bracketed, `[name]` or `[-]` (frontmatter.ts:67-79),
// so a reader that already understands `project:` needs no new parse rule. Values carry the leading
// space the frontmatter emitter uses for every scalar, which is why writeRequest emits " [x]".
import { readProjectTag } from "./projectTag";

export interface ProjectRequest {
  desired: string | null; // the requested project; null = loose
  base: string | null;    // the project the requester believed the note was in; null = loose
  at: string;             // ISO8601 of the ORIGINATING user action, never of a migration
}

const K_DESIRED = "project_request";
const K_BASE = "project_request_base";
const K_AT = "project_request_at";

function enc(v: string | null): string {
  return v ? ` [${v}]` : " [-]";
}

function dec(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  const inner = raw.trim().replace(/^\[/, "").replace(/\]$/, "").trim();
  return inner === "" || inner === "-" ? null : inner;
}

export function buildRequest(desired: string | null, base: string | null, atIso: string): ProjectRequest {
  return { desired, base, at: atIso };
}

export function readRequest(extra: Record<string, string>): ProjectRequest | null {
  if (!(K_DESIRED in extra) || !(K_AT in extra)) return null;
  return { desired: dec(extra[K_DESIRED]), base: dec(extra[K_BASE]), at: extra[K_AT].trim() };
}

export function writeRequest(extra: Record<string, string>, req: ProjectRequest): Record<string, string> {
  return { ...extra, [K_DESIRED]: enc(req.desired), [K_BASE]: enc(req.base), [K_AT]: ` ${req.at}` };
}

export function clearRequest(extra: Record<string, string>): Record<string, string> {
  const next = { ...extra };
  delete next[K_DESIRED];
  delete next[K_BASE];
  delete next[K_AT];
  return next;
}

// CLAUSE 1. The body wins. A request is applied ONLY if the note is still where the requester thought
// it was. Without this, a request that sat in a shut-desktop's inbox for three weeks silently reverses
// a decision the user already made on day 4 — and the sync log shows a normal, successful merge.
// "already there" is also a discard: applying it would be a no-op write to a sacred body.
export function requestOutcome(body: string, req: ProjectRequest): "apply" | "discard" {
  const current = readProjectTag(body);
  if (current !== req.base) return "discard";
  if (current === req.desired) return "discard";
  return "apply";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/projectRequest.test.ts`
Expected: PASS, 9 tests

- [ ] **Step 5: PROVE CLAUSE 1 CAN GO RED**

A check never seen red is not a check. Temporarily change `requestOutcome`'s first line to `if (false) return "discard";` and re-run.
Expected: the two DISCARD tests FAIL. **Revert the edit**, re-run, confirm 9 PASS again.

- [ ] **Step 6: Reflex gate, then commit**

```bash
python check.py 0
git add phone/src/lib/projectRequest.ts phone/src/lib/projectRequest.test.ts
git commit -m "feat(project): based project-change request with staleness discard"
```

---

### Task 3: Frontmatter carries the request keys typed (phone)

The three keys already survive a round trip via the `extra` bag (`frontmatter.ts:208` parse, `:285-298` serialize). This task does **not** add new `Note` fields — it adds a test pinning that survival, so a future refactor of `extra` cannot silently break the mechanism.

**Files:**
- Modify: `phone/src/lib/frontmatter.test.ts`

**Interfaces:**
- Consumes: `parseNote`, `serializeNote` from `phone/src/lib/frontmatter.ts`; `writeRequest`, `readRequest` from Task 2

- [ ] **Step 1: Write the failing test**

```ts
// append to phone/src/lib/frontmatter.test.ts
import { buildRequest, readRequest, writeRequest } from "./projectRequest";

it("round-trips a project_request through parse/serialize without loss", () => {
  const raw = [
    "---", "id: 01", "origin: note", "created: 2026-08-08T10:00:00.000Z",
    "modified: 2026-08-08T10:00:00.000Z", "device: phone",
    "project_request: [research]", "project_request_base: [inbox]",
    "project_request_at: 2026-08-08T10:00:00.000Z",
    "---", "", "body text",
  ].join("\n");

  const note = parseNote(raw);
  expect(readRequest(note.extra)).toEqual({
    desired: "research", base: "inbox", at: "2026-08-08T10:00:00.000Z",
  });

  const out = serializeNote(note);
  expect(out).toContain("project_request: [research]");
  expect(out).toContain("project_request_base: [inbox]");
  expect(parseNote(out).body).toBe("body text");
});

it("a request write leaves the body byte-identical", () => {
  const note = parseNote("---\nid: 01\norigin: note\n---\n\nuntouched body");
  const before = note.body;
  const next = { ...note, extra: writeRequest(note.extra, buildRequest("x", null, "2026-08-08T10:00:00.000Z")) };
  expect(parseNote(serializeNote(next)).body).toBe(before);
});
```

- [ ] **Step 2: Run test to verify it passes or fails**

Run: `cd phone && npx vitest run src/lib/frontmatter.test.ts`
Expected: PASS. **If it FAILS, stop and report** — the whole mechanism assumes this round trip and the spec asserts it at `frontmatter.ts:208`/`:285-298`. A failure here means the spec's premise is wrong, which is a finding, not a bug to patch around.

- [ ] **Step 3: Commit**

```bash
python check.py 0
git add phone/src/lib/frontmatter.test.ts
git commit -m "test(project): pin project_request survival through the frontmatter round trip"
```

---

### Task 4: The not-applied threshold (phone)

Clause 2: the requester surfaces "not applied" rather than trusting the peer to report. Ruled 2026-08-08: **a multiple of the sync interval, not a constant.** `syncConfig.ts:90 provisionalTtlSec` already does exactly this shape (3 intervals, `"off"` falling back to a 1h basis, mirroring the desktop). Reuse the shape; do not invent a second one.

**Files:**
- Modify: `phone/src/lib/syncConfig.ts`
- Test: `phone/src/lib/syncConfig.test.ts`

**Interfaces:**
- Consumes: `SyncInterval`, `intervalMs` from `phone/src/lib/syncConfig.ts`
- Produces: `requestNotAppliedSec(interval: SyncInterval): number`

- [ ] **Step 1: Write the failing test**

```ts
// append to phone/src/lib/syncConfig.test.ts
import { requestNotAppliedSec } from "./syncConfig";

it("derives the not-applied threshold from the sync interval, not a constant", () => {
  expect(requestNotAppliedSec("15m")).toBe(5 * 15 * 60);
  expect(requestNotAppliedSec("1h")).toBe(5 * 60 * 60);
  expect(requestNotAppliedSec("6h")).toBe(5 * 6 * 60 * 60);
});

it("falls back to the 1h basis when auto-sync is off, like provisionalTtlSec", () => {
  expect(requestNotAppliedSec("off")).toBe(5 * 60 * 60);
});

it("is always longer than the provisional TTL, so the quieter signal never fires first", () => {
  for (const i of ["15m", "1h", "6h", "daily"] as const) {
    expect(requestNotAppliedSec(i)).toBeGreaterThan(provisionalTtlSec(i));
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/syncConfig.test.ts`
Expected: FAIL — `requestNotAppliedSec is not a function`

- [ ] **Step 3: Write minimal implementation**

```ts
// append to phone/src/lib/syncConfig.ts, directly below provisionalTtlSec

// Clause 2 (spec §4.1): past this age a still-pending request is shown as NOT APPLIED, because an
// older peer round-trips `project_request:` faithfully and forever without ever applying it — sync
// green, file intact, key present, feature silently absent. The requesting device is the only one
// that can notice nothing happened.
//
// N=5 intervals, deliberately longer than provisionalTtlSec's N=3: a request legitimately waits for
// the peer to WAKE, which is slower than the peer merely being late. Same "off" -> 1h basis, same
// derived-not-hardcoded shape, so both self-scale with the user's cadence.
const NOT_APPLIED_INTERVALS = 5;

export function requestNotAppliedSec(interval: SyncInterval): number {
  const ms = intervalMs(interval) ?? intervalMs("1h")!;
  return (NOT_APPLIED_INTERVALS * ms) / 1000;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/syncConfig.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
python check.py 0
git add phone/src/lib/syncConfig.ts phone/src/lib/syncConfig.test.ts
git commit -m "feat(project): not-applied threshold derived from the sync interval"
```

---

### Task 5: `setProject` — write, request, or claim (phone)

Replaces `setCategory`'s role (`noteStore.ts:884`). This is where spec §4.1 clause 3 and §4.4 become code. Three outcomes, decided by provenance.

**Files:**
- Modify: `phone/src/lib/noteStore.ts`
- Create: `phone/src/lib/projectAuthority.ts`
- Test: `phone/src/lib/projectAuthority.test.ts`

**Interfaces:**
- Consumes: `Note` from `phone/src/lib/note.ts`
- Produces: `projectAction(note: Note, actingDevice: "phone" | "desktop"): "write" | "request" | "claim"`

The decision is extracted to a pure module because `noteStore` cannot be unit-tested at the store level, and this rule is the one a future reader will most want to check in isolation.

- [ ] **Step 1: Write the failing test**

```ts
// phone/src/lib/projectAuthority.test.ts
import { describe, it, expect } from "vitest";
import { projectAction } from "./projectAuthority";
import type { Note } from "./note";

const base = { enrichSource: null } as unknown as Note;
const n = (over: Partial<Note>): Note => ({ ...base, ...over } as Note);

describe("projectAction", () => {
  it("writes directly when the acting device authored the note", () => {
    expect(projectAction(n({ originDevice: "phone" }), "phone")).toBe("write");
  });

  it("requests when the other device authored the note", () => {
    expect(projectAction(n({ originDevice: "desktop" }), "phone")).toBe("request");
    expect(projectAction(n({ originDevice: "phone" }), "desktop")).toBe("request");
  });

  it("claims a shared note (spec 4.4)", () => {
    expect(projectAction(n({ originDevice: "shared" }), "phone")).toBe("claim");
    expect(projectAction(n({ originDevice: "shared" }), "desktop")).toBe("claim");
  });

  it("claims a legacy note with no originDevice", () => {
    expect(projectAction(n({ originDevice: null }), "phone")).toBe("claim");
  });

  it("still writes directly on a legacy note the phone demonstrably enriched", () => {
    expect(projectAction(n({ originDevice: null, enrichSource: "phone-heuristic" }), "phone")).toBe("write");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/projectAuthority.test.ts`
Expected: FAIL — "Failed to resolve import ./projectAuthority"

- [ ] **Step 3: Write minimal implementation**

```ts
// phone/src/lib/projectAuthority.ts
// Who may write a note's project tag (spec §4.1 clause 3 + §4.4).
//
// "claim" exists because originDevice does not always name an author: `shared` is transitional
// (note.ts:11) and legacy notes are null. Ruled 2026-08-08: on an EXPLICIT USER ACTION the acting
// device claims such a note outright rather than sending a request nobody would apply.
// The caller is responsible for the "explicit user action" half — this function does not know about
// background passes, and MUST NOT be called from one.
import type { Note } from "./note";

export function projectAction(note: Note, actingDevice: "phone" | "desktop"): "write" | "request" | "claim" {
  // A legacy note the phone itself heuristically enriched is phone-authored in all but the stamp —
  // the same inference noteStore.ts:154 already ships. Not a new rule.
  if (note.originDevice === null && note.enrichSource === "phone-heuristic") {
    return actingDevice === "phone" ? "write" : "request";
  }
  if (note.originDevice === null || note.originDevice === "shared") return "claim";
  return note.originDevice === actingDevice ? "write" : "request";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/projectAuthority.test.ts`
Expected: PASS, 5 tests

- [ ] **Step 5: Wire it into the store**

Replace `setCategory` (`noteStore.ts:884`) with `setProject`. Keep `setCategory` exported as a thin deprecated wrapper ONLY if a caller still needs it — grep first; if there are no remaining callers, delete it and remove its import sites in the same commit.

```ts
// phone/src/lib/noteStore.ts — replaces setCategory
// Membership is the body tag, never a folder (spec §3). Three outcomes, per projectAuthority:
//   write  — we authored it: write the tag.
//   claim  — provenance is ambiguous and this is an explicit user action: write the tag AND take
//            ownership. Only ever reached from a user-initiated call (spec §4.4).
//   request— the peer authored it: write a based request into machine-owned frontmatter and wait.
export async function setProject(id: string, project: string | null): Promise<Note> {
  await initStore();
  const list = views ?? [];
  const idx = list.findIndex((v) => v.note.id === id);
  if (idx === -1) throw new Error(`setProject: no note with id ${id}`);
  const prev = list[idx].note;
  const now = new Date().toISOString();
  const device = await getDeviceId();
  const action = projectAction(prev, "phone");

  let note: Note;
  if (action === "request") {
    // BODY-SACRED: frontmatter only. The body is carried over by spread, untouched.
    const req = buildRequest(project, readProjectTag(prev.body), now);
    note = { ...prev, extra: writeRequest(prev.extra, req), modified: now, device };
  } else {
    const body = writeProjectTag(prev.body, project);
    note = {
      ...prev,
      body,
      project,
      // Claiming is permanent (originDevice is immutable once set, reconcile.ts:159), which is why
      // it is confined to this user-initiated path and never runs in a background pass.
      originDevice: action === "claim" ? "phone" : prev.originDevice,
      modified: now,
      device,
    };
  }

  assertBodySacred(note);
  await mirror.writeNote(base(), note);
  await indexNote(note);
  const baseRev = syncCache.get(id)?.baseRev ?? null;
  await enqueueOutbound(note, "update", baseRev);
  replaceView(id, { note, state: "queued" });
  notify();
  return note;
}
```

**`assertBodySacred` must be given the claim/write case explicitly.** Its existing contract compares against the previous body; for `write`/`claim` the body legitimately changes below the trailing tag line. Assert the text ABOVE that line instead — reuse `writeProjectTag`'s own guarantee, tested in Task 1 step 1's last case. If the existing helper cannot express that, extend the helper; **do not skip the assertion.**

- [ ] **Step 6: Run the gate**

Run: `python check.py 0` then `python check.py 1`
Expected: both exit 0

- [ ] **Step 7: Commit**

```bash
git add phone/src/lib/projectAuthority.ts phone/src/lib/projectAuthority.test.ts phone/src/lib/noteStore.ts
git commit -m "feat(project): setProject writes, requests, or claims by provenance"
```

---

### Task 6: The phone applier

Spec §4.1 clause 3 row 4 — "the row most likely to be built last and tested least. It gets its own test." A request written by the desktop against a **phone-authored** note is applied by the phone.

**Files:**
- Modify: `phone/src/lib/noteStore.ts`
- Test: `phone/src/lib/projectRequest.test.ts` (extend)

**Interfaces:**
- Consumes: `requestOutcome`, `readRequest`, `clearRequest` (Task 2); `writeProjectTag`, `readProjectTag` (Task 1); `projectAction` (Task 5)
- Produces: `applyPendingRequest(note: Note, actingDevice: "phone" | "desktop"): Note | null` — exported from `phone/src/lib/projectRequest.ts`, returns `null` when there is nothing to do

Put the applier in the pure module, not the store, so it is testable and so the desktop's mirror of it has an exact reference.

- [ ] **Step 1: Write the failing test**

```ts
// append to phone/src/lib/projectRequest.test.ts
import { applyPendingRequest } from "./projectRequest";
import type { Note } from "./note";

const noteWith = (over: Partial<Note>): Note =>
  ({ body: "b", extra: {}, originDevice: "phone", enrichSource: null, ...over } as Note);

it("ROW 4: the phone applies a desktop-written request against a PHONE-authored note", () => {
  const req = buildRequest("research", null, AT);
  const n = noteWith({ originDevice: "phone", extra: writeRequest({}, req) });
  const out = applyPendingRequest(n, "phone")!;
  expect(out.body).toBe("b\n\ntags: #project@research");
  expect(out.extra.project_request).toBeUndefined();
  expect(out.project).toBe("research");
});

it("does NOT apply a request against a note the acting device did not author", () => {
  const n = noteWith({ originDevice: "desktop", extra: writeRequest({}, buildRequest("x", null, AT)) });
  expect(applyPendingRequest(n, "phone")).toBeNull();
});

it("clears a STALE request without touching the body (clause 1)", () => {
  const req = buildRequest("research", "inbox", AT);
  const n = noteWith({ body: "b\n\ntags: #project@archive", extra: writeRequest({}, req) });
  const out = applyPendingRequest(n, "phone")!;
  expect(out.body).toBe("b\n\ntags: #project@archive");
  expect(out.extra.project_request).toBeUndefined();
});

it("returns null when there is no request at all", () => {
  expect(applyPendingRequest(noteWith({}), "phone")).toBeNull();
});

it("never claims: an ambiguous note is left for the user action path, not applied here", () => {
  const n = noteWith({ originDevice: null, extra: writeRequest({}, buildRequest("x", null, AT)) });
  expect(applyPendingRequest(n, "phone")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/projectRequest.test.ts`
Expected: FAIL — `applyPendingRequest is not a function`

- [ ] **Step 3: Write minimal implementation**

```ts
// append to phone/src/lib/projectRequest.ts
import type { Note } from "./note";
import { projectAction } from "./projectAuthority";
import { writeProjectTag } from "./projectTag";

// The applier. Runs in a BACKGROUND pass, which is exactly why it must never claim: claiming is
// permanent and is reserved for explicit user actions (spec §4.4). An ambiguous note is therefore
// left alone here — its request waits for a user action or for clause 2 to surface it.
//
// A stale request is CLEARED, not applied: leaving it would re-evaluate forever, and clause 2 would
// eventually report a request that was correctly refused as if it were stuck.
export function applyPendingRequest(note: Note, actingDevice: "phone" | "desktop"): Note | null {
  const req = readRequest(note.extra);
  if (!req) return null;
  if (projectAction(note, actingDevice) !== "write") return null;
  if (requestOutcome(note.body, req) === "discard") {
    return { ...note, extra: clearRequest(note.extra) };
  }
  return {
    ...note,
    body: writeProjectTag(note.body, req.desired),
    project: req.desired,
    extra: clearRequest(note.extra),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/projectRequest.test.ts`
Expected: PASS, 14 tests total

- [ ] **Step 5: Call it from the store's reconcile path**

Wire `applyPendingRequest(note, "phone")` into the post-reconcile per-note pass in `noteStore.ts`. When it returns non-null: `assertBodySacred`, write the mirror, index, and `enqueueOutbound(note, "update", baseRev)` so the cleared keys reach the hub. When it returns null, do nothing — no write, no queue entry.

- [ ] **Step 6: Gate and commit**

```bash
python check.py 1
git add phone/src/lib/projectRequest.ts phone/src/lib/projectRequest.test.ts phone/src/lib/noteStore.ts
git commit -m "feat(project): phone applies requests against notes it authored"
```

---

### Task 7: Remove the three project re-parent sites (phone)

**Files:**
- Modify: `phone/src/lib/driveSync.ts` (lines 389, 559, 639 — the three `findOrCreateFolder` callers)
- Test: `phone/src/lib/driveSync.test.ts`

**★ Do NOT touch line 348 (`pushCreate` dedup-adopt, fixed `createParentId`) or line 510 (`pushDelete` soft-trash, fixed `trashFolderId`).** They re-parent into fixed config folders, are not project-related, and removing them breaks create and trash. This is a user ruling of 2026-08-08.

**Interfaces:**
- Consumes: `DriveDeps` from `phone/src/lib/driveSync.ts`

- [ ] **Step 1: Write the failing test**

The spec §7 is explicit that a grep is not a test — assert at the Drive-request seam.

```ts
// append to phone/src/lib/driveSync.test.ts
it("the phone issues NO project re-parent: addParents/removeParents never carry a project folder", async () => {
  const seen: unknown[] = [];
  const deps = makeDeps({
    // makeDeps is this file's existing fixture builder — reuse it, do not write a new one.
    fetchJson: async (req: { body?: string }) => {
      if (req.body) seen.push(JSON.parse(req.body));
      return { ok: true, data: {} };
    },
    findOrCreateFolder: async () => {
      throw new Error("findOrCreateFolder must never be called for project membership");
    },
  });

  await pushCreate({ ...baseOp, type: "create", category: "research" }, deps);

  const parentMutations = seen.filter((b) => b && typeof b === "object" && ("addParents" in b || "removeParents" in b));
  expect(parentMutations).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/driveSync.test.ts`
Expected: FAIL — `findOrCreateFolder must never be called for project membership`

- [ ] **Step 3: Remove the three sites**

At `:389` and `:639`, drop the `findOrCreateFolder` call and its conditional; the file goes to `deps.createParentId`, which both paths already use as their fallback. At `:559`, `pushMove` loses its reason to exist for project membership — see Task 8 for the op type itself.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/driveSync.test.ts`
Expected: PASS. Existing trash and dedup-adopt tests must remain green — if any goes red, you touched 348 or 510.

- [ ] **Step 5: Gate and commit**

```bash
python check.py 1
git add phone/src/lib/driveSync.ts phone/src/lib/driveSync.test.ts
git commit -m "feat(project): phone stops re-parenting files for project membership"
```

---

### Task 8: Migrate queued `category` ops (phone)

Spec §8.2, ruled 2026-08-08: **convert, and surface the residue.** Discarding silently loses an offline user action, because `category` is never serialized to the `.md` (`frontmatter.ts:259-261`) — the intent exists only in the queue.

Two op classes: a `move` op, and a never-uploaded `create` carrying `category` (`opqueue.ts:149-156`).

**Files:**
- Create: `phone/src/lib/projectMigration.ts`, `phone/src/lib/projectMigration.test.ts`
- Modify: `phone/src/db/index.ts` (`SCHEMA_VERSION` 3 → 4)

**Interfaces:**
- Consumes: `Op` from `phone/src/lib/opqueue.ts`; `buildRequest` (Task 2); `projectAction` (Task 5)
- Produces: `planMigration(ops: Op[], notes: Map<string, Note>): MigrationPlan`

- [ ] **Step 1: Write the failing test**

```ts
// phone/src/lib/projectMigration.test.ts
import { describe, it, expect } from "vitest";
import { planMigration } from "./projectMigration";
import type { Op } from "./opqueue";
import type { Note } from "./note";

const op = (over: Partial<Op>): Op =>
  ({ opId: "o1", noteId: "n1", type: "move", baseRev: null, bodyHash: null, payload: null,
     category: "research", attempts: 0, nextAt: null, status: "pending", createdAt: 1000, ...over } as Op);
const note = (over: Partial<Note>): Note =>
  ({ id: "n1", body: "b", extra: {}, originDevice: "phone", enrichSource: null, ...over } as Note);

describe("planMigration", () => {
  it("converts a move on a phone-authored note into a direct tag write", () => {
    const plan = planMigration([op({})], new Map([["n1", note({ originDevice: "phone" })]]));
    expect(plan.tagWrites).toEqual([{ noteId: "n1", project: "research" }]);
    expect(plan.requests).toEqual([]);
    expect(plan.unmigratable).toEqual([]);
  });

  it("converts a move on a desktop-authored note into a request carrying the ORIGINAL createdAt", () => {
    const plan = planMigration([op({ createdAt: 1000 })], new Map([["n1", note({ originDevice: "desktop" })]]));
    expect(plan.requests).toEqual([
      { noteId: "n1", request: { desired: "research", base: null, at: new Date(1000).toISOString() } },
    ]);
  });

  it("folds a never-uploaded create's category into a tag write", () => {
    const plan = planMigration([op({ type: "create", category: "ideas" })], new Map([["n1", note({})]]));
    expect(plan.tagWrites).toEqual([{ noteId: "n1", project: "ideas" }]);
  });

  it("reports an invalid project name as unmigratable rather than dropping it", () => {
    const plan = planMigration([op({ category: "bad name!" })], new Map([["n1", note({})]]));
    expect(plan.unmigratable).toEqual([{ noteId: "n1", category: "bad name!", reason: "invalid-name" }]);
    expect(plan.tagWrites).toEqual([]);
  });

  it("reports a vanished note as unmigratable rather than dropping it", () => {
    const plan = planMigration([op({})], new Map());
    expect(plan.unmigratable).toEqual([{ noteId: "n1", category: "research", reason: "note-missing" }]);
  });

  it("ignores ops that carry no category", () => {
    const plan = planMigration([op({ type: "update", category: null })], new Map([["n1", note({})]]));
    expect(plan).toEqual({ tagWrites: [], requests: [], unmigratable: [] });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/projectMigration.test.ts`
Expected: FAIL — "Failed to resolve import ./projectMigration"

- [ ] **Step 3: Write minimal implementation**

```ts
// phone/src/lib/projectMigration.ts
// One-time upgrade path for queued ops minted when membership was folder-shaped (spec §8.2).
//
// Discarding these silently would lose the user's action outright: `category` is parsed but NEVER
// serialized to the .md (frontmatter.ts:259-261), so a pending re-categorization exists only in the
// in-memory note, the FTS index, and this queue — all derived caches. The file records nothing.
//
// `at` is the op's ORIGINAL createdAt, never migration time. A three-week-old queued move IS three
// weeks old, and clause 2 flagging it immediately is the honest outcome; stamping "now" would launder
// a stale intent as fresh, which is precisely what clause 1 exists to prevent.
import type { Op } from "./opqueue";
import type { Note } from "./note";
import { projectAction } from "./projectAuthority";
import { readProjectTag } from "./projectTag";
import type { ProjectRequest } from "./projectRequest";

const VALID_NAME = /^[A-Za-z0-9][A-Za-z0-9_-]*$/; // contract §1.3; desktop mirror projects.py:37

export interface MigrationPlan {
  tagWrites: { noteId: string; project: string }[];
  requests: { noteId: string; request: ProjectRequest }[];
  unmigratable: { noteId: string; category: string; reason: "invalid-name" | "note-missing" }[];
}

export function planMigration(ops: Op[], notes: Map<string, Note>): MigrationPlan {
  const plan: MigrationPlan = { tagWrites: [], requests: [], unmigratable: [] };
  for (const op of ops) {
    const category = op.category;
    if (!category) continue;
    const note = notes.get(op.noteId);
    if (!note) {
      plan.unmigratable.push({ noteId: op.noteId, category, reason: "note-missing" });
      continue;
    }
    if (!VALID_NAME.test(category)) {
      plan.unmigratable.push({ noteId: op.noteId, category, reason: "invalid-name" });
      continue;
    }
    // "claim" collapses to a direct write here for the same reason it does anywhere else: the note has
    // no other owner to wait for. This is the one background context where that is sound, because the
    // op being migrated IS the user's own earlier explicit action.
    if (projectAction(note, "phone") === "request") {
      plan.requests.push({
        noteId: op.noteId,
        request: { desired: category, base: readProjectTag(note.body), at: new Date(op.createdAt).toISOString() },
      });
    } else {
      plan.tagWrites.push({ noteId: op.noteId, project: category });
    }
  }
  return plan;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/projectMigration.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Wire the migration into the schema bump**

In `phone/src/db/index.ts`, bump `SCHEMA_VERSION` 3 → 4 and add a v4 arm to `migrate()`, following the v3 arm (lines 117-129) exactly: guard with `PRAGMA user_version` **and** an existence check, and document the version in the header comment block (lines 95-100). The v4 arm loads the queue, calls `planMigration`, applies `tagWrites` and `requests` through the store, deletes the migrated ops, and persists `unmigratable` for Task 9 to surface. Then remove `"move"` from `OP_TYPES` (`opqueue.ts:18`) and drop the move branches at `opqueue.ts:147-158`, `sync.ts:610`, `noteStore.ts:167`/`:1223`.

**`loadQueue` (`db/index.ts:453`) quarantines rows whose `type` is not in `OP_TYPES`** — so removing `"move"` from that list AFTER the migration has run is safe, and removing it BEFORE would quarantine the very rows the migration needs. **Order matters: migrate first, then narrow the type union.**

- [ ] **Step 6: Gate and commit**

```bash
python check.py 1
git add phone/src/lib/projectMigration.ts phone/src/lib/projectMigration.test.ts phone/src/db/index.ts phone/src/lib/opqueue.ts phone/src/lib/sync.ts phone/src/lib/noteStore.ts
git commit -m "feat(project): migrate queued category ops to tags and requests"
```

---

### Task 9: Surface pending and not-applied (phone)

Spec §5: show the note where it **is**, with a quiet pending marker; the not-applied state escalates that same marker rather than adding a second vocabulary.

**Files:**
- Modify: `phone/src/lib/noteList.ts` (the `DotKind` union), `phone/src/components/QuietDot.tsx`
- Test: `phone/src/lib/noteList.test.ts`

**Interfaces:**
- Consumes: `requestNotAppliedSec` (Task 4); `readRequest` (Task 2)
- Produces: `DotKind` gains `"not_applied"`

**Design constraint:** this is a UI surface, so the implementing agent **must load the design skill set first** (workspace `CLAUDE.md` §"Skill sets"). No emoji. `QuietDot` is an existing shipped vocabulary — extend it, do not introduce a second marker.

- [ ] **Step 1: Write the failing test**

```ts
// append to phone/src/lib/noteList.test.ts
import { projectDotKind } from "./noteList";

const AT = "2026-08-08T10:00:00.000Z";
const at = (iso: string) => ({ project_request: " [x]", project_request_base: " [-]", project_request_at: ` ${iso}` });

it("shows nothing when there is no pending request", () => {
  expect(projectDotKind({}, Date.parse(AT), "1h")).toBeNull();
});

it("shows the quiet pending dot inside the threshold", () => {
  expect(projectDotKind(at(AT), Date.parse(AT) + 60_000, "1h")).toBe("pending");
});

it("escalates to not_applied past the threshold", () => {
  const past = Date.parse(AT) + 5 * 60 * 60 * 1000 + 1000;
  expect(projectDotKind(at(AT), past, "1h")).toBe("not_applied");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd phone && npx vitest run src/lib/noteList.test.ts`
Expected: FAIL — `projectDotKind is not a function`

- [ ] **Step 3: Write minimal implementation**

```ts
// append to phone/src/lib/noteList.ts
import { readRequest } from "./projectRequest";
import { requestNotAppliedSec, type SyncInterval } from "./syncConfig";

// Spec §5 + clause 2. The note is shown where it IS; this dot says a change is in flight. Escalating
// the SAME dot rather than adding a second marker is deliberate — the pending state is normal here,
// not exceptional, so it must stay quiet until it genuinely is not.
export function projectDotKind(
  extra: Record<string, string>, now: number, interval: SyncInterval
): "pending" | "not_applied" | null {
  const req = readRequest(extra);
  if (!req) return null;
  const ageSec = (now - Date.parse(req.at)) / 1000;
  return ageSec > requestNotAppliedSec(interval) ? "not_applied" : "pending";
}
```

Then add `"not_applied"` to `DotKind` and give it a style in `QuietDot.tsx` — semantic yellow from the Void tokens (state, not decoration), same geometry as the existing kinds.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd phone && npx vitest run src/lib/noteList.test.ts`
Expected: PASS

- [ ] **Step 5: Gate and commit**

```bash
python check.py 1
git add phone/src/lib/noteList.ts phone/src/lib/noteList.test.ts phone/src/components/QuietDot.tsx
git commit -m "feat(project): quiet pending marker escalating to not-applied"
```

---

### Task 10: Correct the two stale comments (phone)

Ruled 2026-08-08: fix both in slice 1. Each cost real investigation time in s158.

**Files:**
- Modify: `phone/src/lib/note.ts` (lines 9-10)

- [ ] **Step 1: Make the edit**

```ts
// phone/src/lib/note.ts — replaces the current lines 8-10
// v2.2 / ISS-051 §2.1: the PLATFORM that authored a note (immutable once a real platform is stamped).
// `shared` and a null legacy value both mean "no declared author". On an EXPLICIT USER ACTION the
// acting device CLAIMS such a note — writes the tag and stamps its own platform (spec §4.4, ruled
// 2026-08-08). Background passes never claim.
// ★ There is NO backfill-by-location. A legacy null is stamped only by a claim, or filled from a
// non-null peer by reconcile.ts:161. An earlier comment here promised a backfill that was never built.
```

- [ ] **Step 2: Verify nothing depended on the old wording**

Run: `python check.py 0`
Expected: exit 0. Comments are not behaviour; a failure here means you edited more than the comment.

- [ ] **Step 3: Commit**

```bash
git add phone/src/lib/note.ts
git commit -m "docs(project): correct two originDevice comments that contradicted the code"
```

---

### Task 11: The desktop applier

Mirror of Task 6, on the desktop, for notes the **desktop** authored.

**Files:**
- Modify: `omni_capture/note_model.py`, `omni_capture/mobile_sync_agent.py`
- Test: `omni_capture/test_mobile_sync_agent.py`

**Interfaces:**
- Consumes: `apply_trailing_tags_line(body: str, tags: list[str]) -> str` (`machine_tags.py:28`); `is_valid_project_name(name: str) -> bool` (`projects.py:60`)
- Produces: `apply_project_request(note: Note) -> Note | None` in `omni_capture/note_model.py`

Unknown keys already round-trip via `note.extra` (`note_model.py:167` parse, `:233-242` serialize), so **no new Note fields are needed** — read the request off `note.extra`.

- [ ] **Step 1: Write the failing test**

```python
# append to omni_capture/test_mobile_sync_agent.py
from note_model import apply_project_request, parse_note

def _note(body: str, origin: str, **extra):
    raw = "---\nid: 01\norigin: note\norigin_device: %s\n%s---\n\n%s" % (
        origin, "".join(f"{k}: {v}\n" for k, v in extra.items()), body)
    return parse_note(raw)

def test_desktop_applies_request_on_a_desktop_authored_note():
    n = _note("b", "desktop", project_request="[research]", project_request_base="[-]",
              project_request_at="2026-08-08T10:00:00Z")
    out = apply_project_request(n)
    assert "#project@research" in out.body
    assert "project_request" not in out.extra

def test_desktop_does_not_apply_against_a_phone_authored_note():
    n = _note("b", "phone", project_request="[research]", project_request_base="[-]",
              project_request_at="2026-08-08T10:00:00Z")
    assert apply_project_request(n) is None

def test_stale_request_is_cleared_without_touching_the_body():
    n = _note("b\n\ntags: #project@archive", "desktop", project_request="[research]",
              project_request_base="[inbox]", project_request_at="2026-08-08T10:00:00Z")
    out = apply_project_request(n)
    assert "#project@archive" in out.body
    assert "project_request" not in out.extra

def test_invalid_requested_name_is_refused_and_cleared():
    n = _note("b", "desktop", project_request="[bad name!]", project_request_base="[-]",
              project_request_at="2026-08-08T10:00:00Z")
    out = apply_project_request(n)
    assert "#project@" not in out.body
    assert "project_request" not in out.extra
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd omni_capture && pytest test_mobile_sync_agent.py -k project_request -v`
Expected: FAIL — `ImportError: cannot import name 'apply_project_request'`

- [ ] **Step 3: Write minimal implementation**

```python
# omni_capture/note_model.py
from machine_tags import apply_trailing_tags_line, strip_trailing_tags_line
from projects import is_valid_project_name, parse_project_tag

def _unwrap(raw: str | None) -> str | None:
    """`[name]` -> "name"; `[-]`, `[]` and None -> None. Mirrors the phone's parseProjectValue."""
    if raw is None:
        return None
    inner = raw.strip().lstrip("[").rstrip("]").strip()
    return None if inner in ("", "-") else inner


def apply_project_request(note):
    """Apply a pending project_request to a note THIS device authored (design §4).

    Returns the updated note, or None when there is nothing to do. A stale request -- one whose base no
    longer matches the note's current body tag -- is CLEARED, never applied: without that, a request
    that sat in a shut desktop's inbox for three weeks silently reverses a decision the user already
    made, and the sync log shows a normal successful merge.
    """
    desired_raw = note.extra.get("project_request")
    if desired_raw is None or "project_request_at" not in note.extra:
        return None

    # Same provenance gate the enrichment pass already ships (mobile_sync_agent.py:1478-1484).
    effective_origin = note.origin_device or (
        "phone" if note.enrich_source == "phone-heuristic" else "desktop")
    if effective_origin != "desktop":
        return None

    for key in ("project_request", "project_request_base", "project_request_at"):
        note.extra.pop(key, None)

    desired = _unwrap(desired_raw)
    base = _unwrap(note.extra.get("project_request_base"))
    current = parse_project_tag(note.body)

    if current != base or current == desired:
        return note                                    # stale or already there: cleared, body untouched
    if desired is not None and not is_valid_project_name(desired):
        return note                                    # refused, cleared, body untouched

    user_body = strip_trailing_tags_line(note.body)
    note.body = apply_trailing_tags_line(
        note.body, [f"project@{desired}"] if desired else [])
    assert strip_trailing_tags_line(note.body) == user_body, \
        "apply_project_request: body-sacred violation above the trailing tag line"
    return note
```

**`parse_project_tag`'s exact signature must be checked before use** (`projects.py:48-57`) — if it returns a list rather than a single value, adapt the comparison and say so in the commit message rather than reshaping the helper.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd omni_capture && pytest test_mobile_sync_agent.py -k project_request -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Call it from the sync pass**

Call `apply_project_request` per note in `run_once`, beside the existing enrichment step (`mobile_sync_agent.py:1800`). A note it changes is written back and re-tidied so the file lands under the new project's directory — that re-path is the desktop's job and only the desktop's.

- [ ] **Step 6: Gate and commit**

```bash
python check.py 1
git add omni_capture/note_model.py omni_capture/mobile_sync_agent.py omni_capture/test_mobile_sync_agent.py
git commit -m "feat(project): desktop applies requests against notes it authored"
```

---

### Task 12: Make `project_tidy.py`'s invariant true, and test it

The docstring at `project_tidy.py:3-5` claims *"the phone never moves a file and never creates a directory."* Sites 348 and 510 keep moving files by ruling, so that sentence can never be literally true. Narrow it, then test the narrowed version.

**Files:**
- Modify: `omni_capture/project_tidy.py` (docstring)
- Test: `omni_capture/test_project_tidy.py`

- [ ] **Step 1: Narrow the docstring**

```python
# omni_capture/project_tidy.py lines 3-5
DESKTOP ALONE RE-PATHS A FILE FOR PROJECT MEMBERSHIP. The phone never re-paths a file for project
membership and never creates a directory -- that is the load-bearing safety property of the rework,
because a path change is the one operation Drive / reconcile cannot merge field-wise (contract §1.3).
The phone DOES still re-parent into two fixed config folders -- the inbox on create and the trash on
soft-delete (driveSync.ts:348, :510). Those are lifecycle plumbing, carry no project name, and are
deliberately out of scope (user ruling 2026-08-08).
```

- [ ] **Step 2: Write the test that pins it**

```python
# append to omni_capture/test_project_tidy.py
import re, pathlib

def test_phone_has_no_project_reparent_site():
    """The invariant project_tidy's docstring asserts, checked against the phone's actual source.

    A grep is not normally a test -- but this one guards a CROSS-REPO claim that no runtime assertion
    on this side can reach. The phone-side seam assertion lives in driveSync.test.ts (plan task 7);
    this is the desktop's half, and it fails loudly if the phone regrows a project re-parent.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "Second Thought - Android App" / "phone" / "src" / "lib" / "driveSync.ts"
    if not src.exists():
        import pytest
        pytest.skip("phone repo not present alongside this one")
    text = src.read_text(encoding="utf-8")
    assert "findOrCreateFolder" not in text, \
        "the phone regrew a project folder re-parent; see design §1 and plan task 7"
```

- [ ] **Step 3: Run it**

Run: `cd omni_capture && pytest test_project_tidy.py -v`
Expected: PASS (or SKIP if the phone repo is absent). **Before Task 7 lands it must FAIL** — run it early to see it red, which is the point.

- [ ] **Step 4: Commit**

```bash
python check.py 1
git add omni_capture/project_tidy.py omni_capture/test_project_tidy.py
git commit -m "docs(project): narrow the tidy invariant to project membership, and test it"
```

---

### Task 13: Slice gate

- [ ] **Step 1: Full gate, both repos, main thread, foreground, exit code read**

```bash
python check.py 2
```
Expected: six checks, six PASS lines, counted against the check count. Baselines to match are in workspace `CLAUDE.md` §"Work standards", plus the deltas this slice adds.

- [ ] **Step 2: The fuzz that this slice specifically owes**

This touches `driveSync`/`opqueue`, so it is mandatory, not optional.

```bash
cd phone && npm run test:fuzz
cd omni_capture && FUZZ=1 pytest test_fuzz_races.py -q
```
Expected: both green. **A red here is a real finding about the migration or the applier — report it, do not retry it.**

- [ ] **Step 3: Report, do not commit**

Report the gate output verbatim to the main thread. The main thread owns the merge and any push.

---

## Self-Review

**Spec coverage.** §4 mechanism → Tasks 2, 3. §4.1 clause 1 → Task 2 (probed red, step 5). Clause 2 → Tasks 4, 9. Clause 3 rows 1-3 → Task 5; row 4 → Task 6, its own test as the spec demands. §4.2 no registry on the phone → nothing built, correct. §4.4 claim rule → Tasks 5, 10. §5 pending UX → Task 9. §6 slice 1 scope → Tasks 7, 12. §7 testing → Tasks 1 (body-sacred), 2 (clause 1 red), 7 (Drive seam), 6 (row 4), 13 (FUZZ). §8.2 migration → Task 8.

**Gap accepted deliberately:** the desktop's `project:` emission gate (`note_model.py:214`) is **slice 2**, not slice 1, and is not a task here. Slice 3, the phone registry, is untouched by design (§4.2).

**Two places an implementer must verify before coding, flagged rather than guessed:** `parse_project_tag`'s return shape (Task 11 step 3) and `makeDeps`'s exact fixture API (Task 7 step 1). Both are named at their call site with instructions to report rather than reshape.
