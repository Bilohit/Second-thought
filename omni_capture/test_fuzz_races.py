"""test_fuzz_races.py — §3.1 desktop concurrency / race fuzz. SLOW, OPT-IN.

Plain `pytest` SKIPS this whole module (no pytest.ini/pyproject in this repo, so the opt-in
is an env var, not a marker registration):

    FUZZ=1 pytest test_fuzz_races.py -q          # Git Bash
    $env:FUZZ=1; pytest test_fuzz_races.py -q    # PowerShell

Optional knobs (all have reproducible defaults):
    FUZZ_SEED=<int>       hypothesis seed          (default 20260715)
    FUZZ_EXAMPLES=<int>   sequences to generate    (default 2000)
    FUZZ_STEPS=<int>      rules per sequence       (default 12)

The seed is FIXED and PRINTED at import so any failure reproduces exactly.

What this models
----------------
A synthetic vault (a real tmp dir, real byte-verbatim file IO) reconciling against a FAKE HUB:
an in-memory Drive whose files carry a monotonic fake `headRevisionId` and a full revision
history. The fake extends the hand-rolled `_Files`/`_Drive` fake already used by
`test_mobile_sync_agent.py::test_upload_sync_file_creates_then_updates` (stateful, query-
dispatched) rather than adding a second competing fake; note-text builders (`_note_text`) are
imported from that file too.

`RuleBasedStateMachine` interleaves: local body edit · local frontmatter edit · hub-side edit
(rev bump) · hub-side new note · reconcile pass · mirror pass · pull pass · full run_once pass ·
capture-pipeline write landing MID-pass (via the real `run_pipeline` intake seam) · editor save
landing MID-pass (via the real `reminders_fn` seam, which run_once calls between its re-read and
its mirror) · crash-resume (sidecar lost, replay).

Oracles (see the numbered `_check_*` / `@invariant` methods):
  1 body-sacred        — every body byte-string on disk is verbatim one an editor authored
  2 op order           — base_rev never regresses; hub revisions are monotonic
  3 no op dropped      — at quiescence every local note's bytes are on the hub
  4 no blind upload    — mirror never overwrites a hub file whose head != our base_rev
  5 base_rev provenance— base_rev is only ever a head the hub actually issued
  6 conflicts keep both— a body-vs-body divergence keeps BOTH bodies (copy, never overwrite)
  7 replay idempotent  — crash-resume never duplicates a hub file for a note id
  + LOST-EDIT detector — a body that reached the hub head and was never seen locally may not
    vanish from both sides; a local body that never reached the hub may not vanish either.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUZZ"),
    reason="slow race fuzz — opt in with FUZZ=1 (see module docstring)",
)

from hypothesis import HealthCheck, seed, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from frontmatter import strip_frontmatter
from mobile_sync_agent import (
    HUB_FOLDER_NAME,
    _FOLDER_MIME,
    _sha256,
    get_hub_notes,
    load_state,
    mirror_to_hub,
    pull_new_hub_notes,
    read_vault_notes,
    reconcile_changes,
    run_once,
    save_state,
)
from note_model import parse_note, serialize_note

# Reuse the existing suite's note-text builder rather than authoring a second one.
from test_mobile_sync_agent import _note_text

SEED = int(os.environ.get("FUZZ_SEED", "20260715"))
MAX_EXAMPLES = int(os.environ.get("FUZZ_EXAMPLES", "2000"))
STEP_COUNT = int(os.environ.get("FUZZ_STEPS", "12"))
if os.environ.get("FUZZ"):
    print(f"[test_fuzz_races] seed={SEED} max_examples={MAX_EXAMPLES} stateful_step_count={STEP_COUNT}")

CATEGORIES = ["Personal", "Work"]
SCRATCHPAD = "Scratchpad"

# The adopt-clobber quarantine is REMOVED: F-1 is fixed (mobile_sync_agent.py:397-410 + :500-506),
# so the lost-edit oracle below now runs live against the sidecar-loss shape it used to suppress —
# which is the whole point of the fuzz. mirror_to_hub no longer answers a missing sidecar entry by
# adopting the hub listing with base_rev = the CURRENT head (a revision it never synced at, which
# defeated its own advanced-head guard); reconcile_changes adopts the file id with NO base and
# resolves the divergence by keep-both. Deterministic pins: `test_sync_sidecar_recovery.py`
# (plain pytest, always runs) + the three `test_*replay*`/`test_sidecar_loss_*` cases below.
# History, if this ever regresses: it shrank to `new_local_note · crash_resume · hub_edit ·
# crash_resume` and does NOT reproduce at 300-400 examples — re-check at the full 2000, never a
# smoke budget.


# ---------------------------------------------------------------------------
# Fake hub — extends the stateful `_Files`/`_Drive` fake shape from
# test_mobile_sync_agent.py::test_upload_sync_file_creates_then_updates with a
# monotonic headRevisionId + revision history (needed for the three-way base fetch).
# ---------------------------------------------------------------------------
_Q_NAME = re.compile(r"name='([^']*)'")
_Q_PARENT = re.compile(r"'([^']*)' in parents")
_Q_MIME_EQ = re.compile(r"mimeType='([^']*)'")   # `mimeType!='x'` cannot match: `!` breaks the literal
_Q_MIME_NE = re.compile(r"mimeType!='([^']*)'")


class _Exec:
    def __init__(self, r):
        self._r = r

    def execute(self):
        return self._r


class FakeHub:
    """In-memory Drive: {fileId: record} + a monotonic fake headRevisionId."""

    def __init__(self):
        self.recs: dict[str, dict] = {}
        self._fid = 0
        self._rev = 0
        self.root = "HUB"
        self.recs["HUB"] = {
            "id": "HUB", "name": HUB_FOLDER_NAME, "mimeType": _FOLDER_MIME,
            "parents": [], "trashed": False,
        }
        self.issued_revs: set[str] = set()   # every head the hub ever handed out (oracle 5)

    # -- minting ------------------------------------------------------------
    def _next_fid(self) -> str:
        self._fid += 1
        return f"F{self._fid:04d}"

    def _next_rev(self) -> str:
        self._rev += 1
        r = f"r{self._rev:05d}"          # zero-padded → lexical order == issue order (oracle 2)
        self.issued_revs.add(r)
        return r

    # -- direct (test-side) manipulation ------------------------------------
    def folder(self, name: str, parent: str = "HUB") -> str:
        for r in self.recs.values():
            if r["mimeType"] == _FOLDER_MIME and r["name"] == name and parent in r["parents"]:
                return r["id"]
        fid = self._next_fid()
        self.recs[fid] = {"id": fid, "name": name, "mimeType": _FOLDER_MIME,
                          "parents": [parent], "trashed": False}
        return fid

    def put(self, name: str, content: str, parent: str, note_id: str | None = None) -> str:
        """Hub-side create (models the phone pushing a new note)."""
        fid = self._next_fid()
        rev = self._next_rev()
        self.recs[fid] = {
            "id": fid, "name": name, "mimeType": "text/markdown", "parents": [parent],
            "trashed": False, "headRevisionId": rev,
            "appProperties": {"noteId": note_id} if note_id else {},
            "content": content.encode("utf-8"), "revisions": {rev: content.encode("utf-8")},
        }
        return fid

    def overwrite(self, fid: str, content: str) -> str:
        """Hub-side edit (models the phone editing an existing note). Bumps the head."""
        rec = self.recs[fid]
        rev = self._next_rev()
        rec["content"] = content.encode("utf-8")
        rec["headRevisionId"] = rev
        rec["revisions"][rev] = rec["content"]
        return rev

    def text(self, fid: str) -> str:
        return self.recs[fid]["content"].decode("utf-8")

    def note_files(self) -> dict[str, dict]:
        """{noteId: record} for every live .md the hub holds, keyed the way get_hub_notes keys."""
        out = {}
        for r in self.recs.values():
            if r["mimeType"] == _FOLDER_MIME or r["trashed"] or not r["name"].endswith(".md"):
                continue
            key = (r.get("appProperties") or {}).get("noteId") or Path(r["name"]).stem
            out.setdefault(key, r)
        return out

    def all_note_recs(self) -> list[dict]:
        return [r for r in self.recs.values()
                if r["mimeType"] != _FOLDER_MIME and not r["trashed"] and r["name"].endswith(".md")]

    # -- Drive API surface ---------------------------------------------------
    def files(self):
        return _FakeFiles(self)

    def revisions(self):
        return _FakeRevisions(self)


class _FakeFiles:
    def __init__(self, hub: FakeHub):
        self.h = hub

    def list(self, q=None, fields=None, pageToken=None):
        q = q or ""
        name = _Q_NAME.search(q)
        parent = _Q_PARENT.search(q)
        mime_ne = _Q_MIME_NE.search(q)
        mime_eq = _Q_MIME_EQ.search(q)
        out = []
        for r in self.h.recs.values():
            if r["trashed"]:
                continue
            if name and r["name"] != name.group(1):
                continue
            if parent and parent.group(1) not in r["parents"]:
                continue
            if mime_eq and r["mimeType"] != mime_eq.group(1):
                continue
            if mime_ne and r["mimeType"] == mime_ne.group(1):
                continue
            out.append({k: v for k, v in r.items() if k not in ("content", "revisions")})
        return _Exec({"files": out, "nextPageToken": None})   # one page; pagination tested elsewhere

    def create(self, body=None, media_body=None, fields=None):
        body = body or {}
        fid = self.h._next_fid()
        rec = {
            "id": fid, "name": body.get("name", fid), "mimeType": body.get("mimeType", "text/markdown"),
            "parents": list(body.get("parents", [])), "trashed": False,
            "appProperties": dict(body.get("appProperties") or {}),
        }
        if rec["mimeType"] != _FOLDER_MIME:
            data = media_body.getbytes(0, media_body.size()) if media_body else b""
            rev = self.h._next_rev()
            rec.update(content=data, headRevisionId=rev, revisions={rev: data})
        self.h.recs[fid] = rec
        return _Exec({"id": fid, "headRevisionId": rec.get("headRevisionId")})

    def update(self, fileId=None, media_body=None, fields=None):
        rec = self.h.recs[fileId]
        data = media_body.getbytes(0, media_body.size()) if media_body else rec["content"]
        rev = self.h._next_rev()
        rec.update(content=data, headRevisionId=rev)
        rec["revisions"][rev] = data
        return _Exec({"id": fileId, "headRevisionId": rev})

    def get_media(self, fileId=None):
        return _Exec(self.h.recs[fileId]["content"])

    def delete(self, fileId=None):
        self.h.recs[fileId]["trashed"] = True
        return _Exec({})


class _FakeRevisions:
    def __init__(self, hub: FakeHub):
        self.h = hub

    def get_media(self, fileId=None, revisionId=None):
        return _Exec(self.h.recs[fileId]["revisions"][revisionId])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _note_with_category(nid, body, category, **kw) -> str:
    """`_note_text` (reused from test_mobile_sync_agent) + an explicit category line.
    Frontmatter-only splice — the body bytes are untouched."""
    txt = _note_text(nid=nid, body=body, **kw)
    head, _, rest = txt.partition("\n---\n")
    return f"{head}\ncategory: {category}\n---\n{rest}"


def _bodies_on_disk(vault: Path) -> set[str]:
    out = set()
    for p in vault.rglob("*.md"):
        try:
            out.add(strip_frontmatter(p.read_text(encoding="utf-8", newline="")))
        except Exception:
            pass
    return out


class RaceViolation(AssertionError):
    """A fuzz oracle fired. Message carries the invariant + the suspected production defect."""


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------
@seed(SEED)
class VaultHubMachine(RuleBasedStateMachine):
    notes = Bundle("notes")          # note ids that exist in the local vault
    hub_notes = Bundle("hub_notes")  # note ids that exist on the hub

    def __init__(self):
        super().__init__()
        self.tmp = Path(tempfile.mkdtemp(prefix="fuzzrace_"))
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        for c in CATEGORIES + [SCRATCHPAD]:
            (self.vault / c).mkdir()
        self.state_path = str(self.tmp / "state.json")
        self.hub = FakeHub()
        for c in CATEGORIES:
            self.hub.folder(c)
        self.gen = 0
        self.n_notes = 0
        self.local_path: dict[str, str] = {}   # nid -> vault path
        self.hub_fid: dict[str, str] = {}      # nid -> fake-hub file id
        self.authored: set[str] = set()        # every body bytes an editor ever wrote (oracle 1)
        self.local_seen: set[str] = set()      # every body that was ever on local disk
        self.hub_seen: set[str] = set()        # every body that was ever at a hub head
        self.max_base_rev: dict[str, str] = {} # nid -> highest base_rev ever recorded (oracle 2)

    def teardown(self):
        try:
            self._check_quiescent_convergence()   # oracle 3
            self._check_replay_idempotent()       # oracle 7
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    # -- body minting -------------------------------------------------------
    def _body(self, who: str, eol: str) -> str:
        self.gen += 1
        b = f"{who} edit {self.gen}{eol}second line — café ☕{eol}"
        self.authored.add(b)
        return b

    # ============================ RULES ====================================
    @rule(target=notes, cat=st.sampled_from(CATEGORIES), eol=st.sampled_from(["\n", "\r\n"]))
    def new_local_note(self, cat, eol):
        self.n_notes += 1
        nid = f"n{self.n_notes:03d}"
        body = self._body("local", eol)
        path = self.vault / cat / f"{nid}.md"
        path.write_text(_note_with_category(nid, body, cat), encoding="utf-8", newline="")
        self.local_path[nid] = str(path)
        return nid

    @rule(target=hub_notes, cat=st.sampled_from(CATEGORIES), eol=st.sampled_from(["\n", "\r\n"]))
    def new_hub_note(self, cat, eol):
        self.n_notes += 1
        nid = f"h{self.n_notes:03d}"
        body = self._body("hub", eol)
        fid = self.hub.put(f"{nid}.md", _note_with_category(nid, body, cat),
                           self.hub.folder(cat), note_id=nid)
        self.hub_fid[nid] = fid
        self.hub_seen.add(body)
        return nid

    @rule(nid=notes, eol=st.sampled_from(["\n", "\r\n"]))
    def local_body_edit(self, nid, eol):
        p = Path(self.local_path[nid])
        if not p.exists():
            return
        note = parse_note(p.read_text(encoding="utf-8", newline=""))
        self.local_seen.add(note.body)   # the editor read it off disk before replacing it
        note.body = self._body("local", eol)
        p.write_text(serialize_note(note), encoding="utf-8", newline="")

    @rule(nid=notes, tag=st.sampled_from(["ml", "finance", "todo"]),
          cat=st.sampled_from(CATEGORIES), remind=st.sampled_from([None, "2030-01-01T09:00"]))
    def local_frontmatter_edit(self, nid, tag, cat, remind):
        p = Path(self.local_path[nid])
        if not p.exists():
            return
        raw = p.read_text(encoding="utf-8", newline="")
        note = parse_note(raw)
        before = note.body
        note.tags = sorted(set(note.tags) | {tag})
        note.category = cat
        note.remind_at = remind
        note.modified = f"2026-02-{(self.gen % 27) + 1:02d}T00:00:00Z"
        new = serialize_note(note)
        # frontmatter-only edit: prove the editor itself never touched the body
        assert strip_frontmatter(new) == before, "test bug: fm edit altered the body"
        p.write_text(new, encoding="utf-8", newline="")

    @rule(nid=st.one_of(notes, hub_notes), eol=st.sampled_from(["\n", "\r\n"]))
    def hub_edit(self, nid, eol):
        """The other peer edits the note on the hub → head advances past our base_rev."""
        fid = self.hub_fid.get(nid)
        if fid is None:
            return
        note = parse_note(self.hub.text(fid))
        note.body = self._body("hub", eol)
        note.device = "phone"
        note.modified = f"2026-03-{(self.gen % 27) + 1:02d}T00:00:00Z"
        self.hub.overwrite(fid, serialize_note(note))
        self.hub_seen.add(note.body)

    # -- passes -------------------------------------------------------------
    def _pre_pass(self):
        hub_files = self.hub.note_files()
        return {
            "hub_head_body": {nid: strip_frontmatter(self.hub.text(r["id"]))
                              for nid, r in hub_files.items()},
            "local_body": {nid: strip_frontmatter(Path(p).read_text(encoding="utf-8", newline=""))
                           for nid, p in self.local_path.items() if Path(p).exists()},
            "local_seen": set(self.local_seen),
            "hub_seen": set(self.hub_seen),
        }

    def _post_pass(self, pre, label):
        self._sync_hub_fids()
        disk = _bodies_on_disk(self.vault)
        hub_bodies = {strip_frontmatter(self.hub.text(r["id"])) for r in self.hub.all_note_recs()}
        alive = disk | hub_bodies

        # LOST-EDIT: a body that was at the hub head, that this machine had never seen locally,
        # must not vanish from both sides — that is a remote edit silently discarded.
        for nid, b in pre["hub_head_body"].items():
            if b in alive or b in pre["local_seen"]:
                continue
            self._fail(f"{label}: hub body for {nid!r} vanished unseen (remote edit discarded, "
                       f"no conflicted copy) — invariant 6 / non-destructive lock")

        # LOST-EDIT: a local body that never reached the hub must not vanish either.
        for nid, b in pre["local_body"].items():
            if b in alive or b in pre["hub_seen"]:
                continue
            self._fail(f"{label}: local body for {nid!r} vanished before reaching the hub "
                       f"— invariant 3 (op dropped)")

        for r in self.hub.all_note_recs():
            self.hub_seen.add(strip_frontmatter(self.hub.text(r["id"])))

    def _fail(self, msg):
        raise RaceViolation(msg)

    def _sync_hub_fids(self):
        for nid, rec in self.hub.note_files().items():
            self.hub_fid[nid] = rec["id"]
        for nid in list(self.local_path):
            if not Path(self.local_path[nid]).exists():
                for p in self.vault.rglob(f"{nid}.md"):
                    self.local_path[nid] = str(p)
                    break
        for p in self.vault.rglob("*.md"):
            try:
                n = parse_note(p.read_text(encoding="utf-8", newline=""))
            except Exception:
                continue
            if n.id and n.id not in self.local_path:
                self.local_path[n.id] = str(p)

    @rule()
    def reconcile_pass(self):
        pre = self._pre_pass()
        vault_notes = read_vault_notes(str(self.vault))
        hub_files = get_hub_notes(self.hub, "HUB")
        state = load_state(self.state_path)
        expect_conflict = self._expected_conflicts(vault_notes, hub_files, state)

        rec, con, failed, new_state = reconcile_changes(
            vault_notes, hub_files, state, self.hub, "HUB")
        save_state(self.state_path, new_state)
        assert failed == 0, "fake hub must never fail a reconcile — a raise here is a real defect"

        # oracle 6: a body-vs-body divergence keeps BOTH bodies on disk.
        disk = _bodies_on_disk(self.vault)
        for nid, (lb, rb) in expect_conflict.items():
            if lb not in disk or rb not in disk:
                self._fail(f"reconcile_pass: body-vs-body conflict on {nid!r} did not keep both "
                           f"bodies (local_kept={lb in disk} remote_kept={rb in disk}) "
                           f"— invariant 6, mobile_sync_agent.py:419")
        self._post_pass(pre, "reconcile_pass")

    def _expected_conflicts(self, vault_notes, hub_files, state):
        out = {}
        for nid, local in vault_notes.items():
            prior = state.get(nid)
            hf = hub_files.get(nid)
            if not (prior and prior.get("drive_file_id") and hf):
                continue
            if hf.get("headRevisionId") == prior.get("base_rev"):
                continue
            if local["hash"] == prior.get("local_hash"):
                continue   # local unchanged → pull branch, not a conflict
            fid = prior["drive_file_id"]
            base_rev = prior.get("base_rev")
            if fid not in self.hub.recs or base_rev not in self.hub.recs[fid].get("revisions", {}):
                continue
            bb = strip_frontmatter(self.hub.recs[fid]["revisions"][base_rev].decode("utf-8"))
            lb = strip_frontmatter(local["content"])
            rb = strip_frontmatter(self.hub.text(fid))
            if lb != bb and rb != bb and lb != rb:
                out[nid] = (lb, rb)
        return out

    @rule()
    def mirror_pass(self):
        pre = self._pre_pass()
        vault_notes = read_vault_notes(str(self.vault))
        hub_files = get_hub_notes(self.hub, "HUB")
        state = load_state(self.state_path)
        # oracle 4: snapshot every hub file whose head has advanced past our base_rev.
        frozen = {}
        for nid in vault_notes:
            prior = state.get(nid)
            hf = hub_files.get(nid)
            if prior and prior.get("base_rev") and hf and hf.get("headRevisionId") != prior["base_rev"]:
                frozen[nid] = (hf["id"], self.hub.text(hf["id"]))

        uploaded, failed, new_state = mirror_to_hub(vault_notes, hub_files, state, self.hub, "HUB")
        save_state(self.state_path, new_state)
        assert failed == 0, "fake hub must never fail an upload — a raise here is a real defect"

        for nid, (fid, before) in frozen.items():
            if self.hub.text(fid) != before:
                self._fail(f"mirror_pass: blind upload over an ADVANCED hub head for {nid!r} "
                           f"— invariant 4, mobile_sync_agent.py:477-485")
        self._post_pass(pre, "mirror_pass")

    @rule()
    def pull_pass(self):
        pre = self._pre_pass()
        vault_notes = read_vault_notes(str(self.vault))
        hub_files = get_hub_notes(self.hub, "HUB")
        state = load_state(self.state_path)
        pulled, failed, new_state = pull_new_hub_notes(
            vault_notes, hub_files, state, self.hub, str(self.vault), SCRATCHPAD)
        save_state(self.state_path, new_state)
        assert failed == 0, "fake hub must never fail a pull — a raise here is a real defect"
        self._post_pass(pre, "pull_pass")

    @rule()
    def full_pass(self):
        pre = self._pre_pass()
        self._run_once()
        self._post_pass(pre, "full_pass")

    @rule(eol=st.sampled_from(["\n", "\r\n"]))
    def full_pass_with_capture_midflight(self, eol):
        """A capture-pipeline write lands MID-pass: run_once drains `_mobile_inbox/` through
        run_pipeline, which writes a capture .md into the vault between the reconcile/pull and
        the re-read+mirror. Notes-are-not-captures: it must not perturb note sync."""
        pre = self._pre_pass()
        inbox = self.hub.folder("_mobile_inbox")
        self.hub.put("20260101T000000Z-cap.md", "---\norigin: capture\ndevice: p\n---\nclipped text",
                     inbox)

        def fake_pipeline(**kw):
            self.gen += 1
            p = self.vault / SCRATCHPAD / f"cap{self.gen}.md"
            # a real desktop capture: category frontmatter, NO id, NO origin (origin absent == capture)
            p.write_text(f"---\ncategory: {SCRATCHPAD}\n---\ncaptured {self.gen}{eol}",
                         encoding="utf-8", newline="")
            return {}

        self._run_once(run_pipeline=fake_pipeline)
        self._post_pass(pre, "full_pass_with_capture_midflight")

    @rule(nid=notes, eol=st.sampled_from(["\n", "\r\n"]))
    def full_pass_with_editor_save_midflight(self, nid, eol):
        """The user saves a note MID-pass. `reminders_fn` is a real run_once seam that fires
        AFTER the re-read and BEFORE the mirror — the narrowest live interleaving point."""
        pre = self._pre_pass()
        path = Path(self.local_path.get(nid, ""))

        def reminders_fn(vault_notes):
            if path.exists():
                note = parse_note(path.read_text(encoding="utf-8", newline=""))
                # The editor READ this body off disk before replacing it — so it was genuinely
                # seen locally and is legitimately superseded, even if it only lived on disk
                # transiently inside this pass (e.g. reconcile pulled it moments ago). Without
                # this the lost-edit oracle mis-reports a lawful supersede.
                self.local_seen.add(note.body)
                note.body = self._body("local", eol)
                path.write_text(serialize_note(note), encoding="utf-8", newline="")
            return {"created": 0, "updated": 0, "removed": 0}

        self._run_once(reminders_fn=reminders_fn)
        self._post_pass(pre, "full_pass_with_editor_save_midflight")

    @rule()
    def crash_resume(self):
        """Crash mid-sync → the derived sidecar is lost. Replay must be idempotent and must not
        clobber the canonical head (files are the source of truth; the sidecar is a cache)."""
        if os.path.exists(self.state_path):
            os.remove(self.state_path)
        pre = self._pre_pass()   # snapshot AFTER the loss — that is the state the pass starts from
        self._run_once()
        self._post_pass(pre, "crash_resume")

    def _run_once(self, **kw):
        run_once(str(self.vault), self.state_path, self.hub,
                 vault_root=str(self.vault), scratchpad_folder=SCRATCHPAD, **kw)
        self._sync_hub_fids()

    # ========================== INVARIANTS =================================
    @invariant()
    def i1_body_sacred(self):
        """Every body on disk is byte-verbatim one an editor authored — never fabricated,
        never newline-translated (\\r\\n → \\r\\r\\n is the recurring Windows corruption)."""
        for p in self.vault.rglob("*.md"):
            raw = p.read_text(encoding="utf-8", newline="")
            body = strip_frontmatter(raw)
            # NOTE: deliberately does NOT add to self.local_seen. `local_seen` means "an editor
            # read this body off disk and superseded it" (recorded explicitly by local_body_edit /
            # the mid-flight editor save), NOT merely "was on disk once". Blanket-adding here made
            # every pulled remote body permanently immune to the lost-edit oracle in _post_pass.
            if body.startswith("captured ") or body == "":
                continue   # pipeline-written capture / empty
            if body not in self.authored:
                self._fail(f"i1 body-sacred: {p.name} holds a body no editor authored "
                           f"(corruption/fabrication): {body!r}")

    @invariant()
    def i2_i5_base_rev(self):
        state = load_state(self.state_path)
        for nid, s in state.items():
            rev = s.get("base_rev")
            if rev is None:
                continue
            # oracle 5: base_rev is only ever a head the hub actually issued.
            if rev not in self.hub.issued_revs:
                self._fail(f"i5 base_rev provenance: {nid!r} base_rev={rev!r} was never issued "
                           f"by the hub — invariant 5")
            # oracle 2: base_rev never regresses (revs are zero-padded → lexical == issue order).
            prev = self.max_base_rev.get(nid)
            if prev is not None and rev < prev:
                self._fail(f"i2 op order: {nid!r} base_rev regressed {prev!r} -> {rev!r} "
                           f"— invariant 2")
            self.max_base_rev[nid] = max(rev, prev) if prev else rev

    @invariant()
    def i7_no_duplicate_hub_files(self):
        """Oracle 7: exactly one hub file per note id — replay must never create an orphan."""
        seen: dict[str, str] = {}
        for r in self.hub.all_note_recs():
            key = (r.get("appProperties") or {}).get("noteId") or Path(r["name"]).stem
            if key in seen:
                self._fail(f"i7 replay idempotence: duplicate hub files for note {key!r} "
                           f"({seen[key]} and {r['id']}) — invariant 7")
            seen[key] = r["id"]

    # ======================= TEARDOWN ORACLES ==============================
    def _check_quiescent_convergence(self):
        """Oracle 3: with no further edits, repeated passes must land every local note's exact
        bytes on the hub. A note still diverging after 6 quiet passes is a dropped/stuck op."""
        for _ in range(6):
            self._run_once()
        vault_notes = read_vault_notes(str(self.vault))
        hub_files = get_hub_notes(self.hub, "HUB")
        for nid, note in vault_notes.items():
            hf = hub_files.get(nid)
            if hf is None:
                self._fail(f"oracle 3: note {nid!r} never reached the hub after 6 quiet passes")
            if _sha256(self.hub.text(hf["id"])) != note["hash"]:
                self._fail(f"oracle 3: note {nid!r} still diverges from the hub after 6 quiet "
                           f"passes (local edit never landed)")

    def _check_replay_idempotent(self):
        """Oracle 7: drop the derived sidecar and replay. No duplicate hub files, and — the
        destructive form — no CONTENT change for a note that was already in sync.

        NOTE: the benign form (replay re-uploads byte-identical content, churning
        headRevisionId) is a real but separate defect, pinned deterministically by
        `test_crash_replay_reuploads_identical_bytes` below; it is deliberately NOT a hard fuzz
        failure or it would mask every deeper race behind the same shallow shrink."""
        before = {r["id"]: (r["headRevisionId"], r["content"]) for r in self.hub.all_note_recs()}
        if os.path.exists(self.state_path):
            os.remove(self.state_path)
        self._run_once()
        after = {r["id"]: (r["headRevisionId"], r["content"]) for r in self.hub.all_note_recs()}
        if set(after) - set(before):
            self._fail(f"oracle 7: crash-replay created new hub files "
                       f"{sorted(set(after) - set(before))} for already-synced notes")
        clobbered = [f for f in before if after.get(f, (None, None))[1] != before[f][1]]
        if clobbered:
            self._fail(f"oracle 7: crash-replay CHANGED hub content for already-synced notes "
                       f"{clobbered} — invariant 7 + non-destructive lock")
        self.i7_no_duplicate_hub_files()


# ---------------------------------------------------------------------------
# Deterministic pins for the minimal sequences the fuzz shrank to. These are the
# report artifacts — each one is a hand-minimised repro of a fuzz failure.
# ---------------------------------------------------------------------------
def _sync_note(hub: FakeHub, vault: Path, state_path: str, nid="s01", body="orig body\n"):
    """One note, in sync on both sides, sidecar written. Returns (fid, local_path)."""
    fid = hub.put(f"{nid}.md", _note_with_category(nid, body, "Personal"),
                  hub.folder("Personal"), note_id=nid)
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)
    return fid, str(vault / "Personal" / f"{nid}.md")


def _fresh(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Personal").mkdir()
    (vault / SCRATCHPAD).mkdir()
    hub = FakeHub()
    hub.folder("Personal")
    return hub, vault, str(tmp_path / "state.json")


def test_crash_replay_reuploads_identical_bytes(tmp_path):
    """FIXED (was LOW): sidecar lost → mirror_to_hub's hub-adopt fallback set local_hash=None, so
    the very next mirror re-uploaded BYTE-IDENTICAL content and burned a headRevisionId — a Drive
    write per note per sidecar loss, and the bumped head made every peer re-pull an unchanged
    note. reconcile_changes' adopt path now compares the hub bytes against ours and records the
    head instead of re-uploading. Invariant 7 (replay idempotence)."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, _ = _sync_note(hub, vault, state_path)
    rev_before, content_before = hub.recs[fid]["headRevisionId"], hub.recs[fid]["content"]

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    assert hub.recs[fid]["content"] == content_before          # content is fine...
    assert hub.recs[fid]["headRevisionId"] == rev_before, (
        "replay re-uploaded identical bytes and bumped headRevisionId — not idempotent")


def test_sidecar_loss_does_not_revert_a_remote_edit(tmp_path):
    """FIXED (was HIGH): the minimal sequence the fuzz shrank to, un-quarantined at 2000 examples:

        new_local_note() · crash_resume() · hub_edit() · crash_resume()

    NO local edit is involved — the desktop never touches its copy. Sidecar loss alone was enough:
    mirror_to_hub's hub-adopt fallback defeated BOTH safety nets in one move — `local_hash: None`
    made the already-synced skip miss, and `base_rev = hub_file["headRevisionId"]` (the CURRENT
    head) made the advanced-head guard compare the head against itself, so it could never fire.
    The desktop then uploaded its stale body over the peer's edit: the hub head REVERTED, the
    remote edit was gone from both sides, and no conflicted copy was written.

    This strictly dominated test_crash_replay_does_not_clobber_advanced_hub_head below (which
    needs a local edit and so reads as a conflict-resolution defect). It was not one — it was
    unconditional silent data loss on any sidecar loss with an un-pulled remote edit.
    Invariants 3 + 4 + 6. Also pinned, outside this FUZZ-gated module, by
    test_sync_sidecar_recovery.py."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)
    body_before = strip_frontmatter(Path(local_path).read_text(encoding="utf-8", newline=""))

    remote = parse_note(hub.text(fid))
    remote.body = "phone edit — never pulled to this desktop\n"
    hub.overwrite(fid, serialize_note(remote))

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    # The desktop never edited its own BODY (the recovery may merge machine-owned frontmatter
    # into the local file — that is reconcile's normal both-changed write, not a body edit).
    assert strip_frontmatter(
        Path(local_path).read_text(encoding="utf-8", newline="")) == body_before
    surviving = _bodies_on_disk(vault) | {
        strip_frontmatter(hub.text(r["id"])) for r in hub.all_note_recs()}
    assert "phone edit — never pulled to this desktop\n" in surviving, (
        "remote edit REVERTED by a sidecar loss alone, with no local edit and no conflicted copy "
        "— hub head rolled back to the desktop's stale body; non-destructive lock violated")


def test_crash_replay_does_not_clobber_advanced_hub_head(tmp_path):
    """FIXED (was HIGH): sidecar lost AND the peer edited the note. mirror_to_hub adopted the hub
    listing as `prior` with base_rev = the CURRENT head, so the advanced-head guard compared the
    head against itself and could never fire. The desktop then blind-uploaded its stale local body
    over the peer's edit — the remote body gone from the canonical head with NO conflicted copy.
    Now: no sidecar record means no observed base, so the divergence goes to reconcile_changes'
    baseless adopt path and both bodies are kept. Invariants 4 + 6."""
    hub, vault, state_path = _fresh(tmp_path)
    fid, local_path = _sync_note(hub, vault, state_path)

    # peer edits the note on the hub; desktop edits it locally too
    remote = parse_note(hub.text(fid))
    remote.body = "remote body — typed on the phone\n"
    hub.overwrite(fid, serialize_note(remote))
    local = parse_note(Path(local_path).read_text(encoding="utf-8", newline=""))
    local.body = "local body — typed on the desktop\n"
    Path(local_path).write_text(serialize_note(local), encoding="utf-8", newline="")

    os.remove(state_path)                      # crash: derived sidecar lost
    run_once(str(vault), state_path, hub, vault_root=str(vault), scratchpad_folder=SCRATCHPAD)

    surviving = _bodies_on_disk(vault) | {
        strip_frontmatter(hub.text(r["id"])) for r in hub.all_note_recs()}
    assert "local body — typed on the desktop\n" in surviving
    assert "remote body — typed on the phone\n" in surviving, (
        "remote body destroyed: mirror blind-uploaded over an advanced head after sidecar loss, "
        "no conflicted copy — non-destructive lock violated")


VaultHubMachine.TestCase.settings = settings(
    max_examples=MAX_EXAMPLES,
    stateful_step_count=STEP_COUNT,
    deadline=None,
    print_blob=True,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)

TestVaultHubRaces = VaultHubMachine.TestCase
