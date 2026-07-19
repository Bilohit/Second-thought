"""
Desktop sync agent — bidirectionally reconciles vault notes with the Drive hub.

D1 = one-way mirror (push local → hub). D2 = pull + field-aware three-way reconcile via reconcile.py
when the hub head has advanced past our last-synced revision.

Contract: data-model-and-contracts.md §1 (frontmatter), §2 (hub tree), §6 (reconcile),
§10 (Drive REST), §12 (checklist). Version token is headRevisionId, never mtime.
Body is sacred: the merge engine never fabricates a body (merged body is verbatim one input),
and every upload asserts the body is byte-identical to its source.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from googleapiclient.http import MediaInMemoryUpload

from frontmatter import add_fields, read_all_fields, strip_frontmatter
from note_model import parse_note, serialize_note
from reconcile import reconcile
from sync_ignore import filter_ignored_notes

# D4 note-enrichment seam collaborators (patched as module attributes in tests).
from llm_engine import run_llm_engine
from storage_engine import build_category_descriptions
from tag_vocab import load_vocab
from index_writer import get_db_path
from reminders import sync_reminders_from_notes
from vector_store import index_note
from models import EnrichedPayload

HUB_FOLDER_NAME = "SecondThoughtVault"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_RESERVED_FOLDERS = {"_trash", "_mobile_inbox", "_attachments", "_templates", ".sync"}

# Stand-in body for "the common ancestor is UNKNOWN" (see reconcile_changes' adopt path).
# reconcile() derives body_changed_local/body_changed_remote by comparing against base.body, so a
# base body equal to NEITHER side is exactly a 2-way merge: identical bodies merge, divergent ones
# are a body-vs-body conflict → keep-both. It is never chosen as a merged body, so it never reaches
# disk or the hub.
# ponytail: a NUL-wrapped marker no editor can type stands in for a real "no base" sentinel type;
# swap for an Optional[Note] base parameter in reconcile() only if a body could ever hold these bytes.
_NO_BASE_BODY = "\x00<no common base — sidecar lost>\x00"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_ILLEGAL_NAME = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_RESERVED_STEMS = {"CON", "PRN", "AUX", "NUL",
                   *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


_UNTITLED_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")


def _created_stamp(created_at: str) -> str:
    """A note's `created` as its LITERAL written wall-clock digits `YYYY-MM-DD HHMM` (NO timezone
    conversion — desktop writes naive-local `created`, phone writes UTC-Z; slicing the digits is the
    only rule that agrees on both), or "" if unparseable. Used by BOTH the Untitled fallback and the
    clash-loser suffix. MUST match phone createdStamp() exactly."""
    m = _UNTITLED_TS.match(created_at or "")
    if not m:
        return ""
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d} {h}{mi}"


def _untitled(created_at: str) -> str:
    """Blank-title filename fallback. MUST match phone untitled()."""
    stamp = _created_stamp(created_at)
    return f"Untitled {stamp}" if stamp else "Untitled"


def _hub_filename(title: str, created_at: str) -> str:
    """Pure: a note's hub/local filename from its title. MUST match phone hubFilename() exactly."""
    base = (title or "").strip()
    if not base:
        base = _untitled(created_at)
    base = _ILLEGAL_NAME.sub("-", base)
    base = re.sub(r"-{2,}", "-", base)
    base = base.strip(" .-")[:120].strip(" .-")
    if base.upper() in _RESERVED_STEMS:
        base = base + "_"
    if not base:
        base = _untitled(created_at)
    return base + ".md"


def _resolve_hub_names(notes: list) -> dict:
    """Pure: assign each note its hub/local filename, resolving same-folder clashes. The later-created
    note (tie -> larger id) is suffixed with its `created` date+time ` (YYYY-MM-DD HHMM)`; the winner
    keeps the clean name. If two losers share the title AND the same minute, the second also gets its
    short id appended (` (YYYY-MM-DD HHMM <last6 id>)`) so the LOCAL filename stays unique — a
    same-named local file would overwrite, losing a body. MUST match phone resolveHubNames() exactly."""
    groups: dict = {}
    for n in notes:
        name = _hub_filename(n["title"], n["created"])
        groups.setdefault((n.get("category"), name), []).append(n)
    out: dict = {}
    for (_cat, name), members in groups.items():
        members.sort(key=lambda n: (n["created"], n["id"]))
        used: set = set()
        for i, n in enumerate(members):
            if i == 0:
                out[n["id"]] = name
                used.add(name)
            else:
                stem = name[:-3]  # drop ".md"
                stamp = _created_stamp(n["created"]) or n["id"][-6:]
                cand = f"{stem} ({stamp}).md"
                if cand in used:  # two losers, same title, same minute → disambiguate by id
                    cand = f"{stem} ({stamp} {n['id'][-6:]}).md"
                out[n["id"]] = cand
                used.add(cand)
    return out


def _atomic_write_note(path: str, content: str) -> None:
    """Write a SYNC-OWNED vault note atomically: temp sibling + os.replace (save_state's /
    provisional_store._save_state's idiom). Path.write_text truncates the target and streams, so a
    kill mid-write used to leave a valid-parsing note with a TRUNCATED body — the next scan cannot
    tell that from a real edit (the hash differs → local_changed), so reconcile treated the mangled
    body as authoritative and UPLOADED it: a body no editor ever authored became the note's
    canonical hub head (body-sacred violation, S4-1). The rename is atomic — the note is either its
    last complete bytes or the new ones, never a torn one.

    Sync-owned writes only: note_editor.py is the user's sanctioned body writer and owns its path.
    newline="" is load-bearing (the s23 CRLF fix) — default translation rewrites a hub \\r\\n body
    as \\r\\r\\n on Windows (body-sacred violation + spurious re-upload loop). The temp is a
    SIBLING: os.replace is only atomic within a filesystem, and a cross-device rename fails.
    """
    tmp = path + ".tmp"   # sibling, and not *.md — read_vault_notes' rglob never picks it up
    Path(tmp).write_text(content, encoding="utf-8", newline="")
    os.replace(tmp, path)   # atomic


def _mint_capture_id() -> str:
    # ponytail: uuid4-hex id (opaque sync identity, only needs uniqueness), matching the same
    # ULID-substitute convention already used for conflicted-copy ids in reconcile_changes().
    # Swap for a real ULID minter if lexical time-ordering of capture ids ever matters.
    return uuid.uuid4().hex[:26]


def read_vault_notes(vault_path: str, mirror_captures: bool = False) -> Dict[str, Dict]:
    """Scan the vault, return {frontmatter-id: note}.

    A file is a NOTE iff frontmatter `origin == "note"`; otherwise it is a desktop CAPTURE
    (origin absent or == "capture") — data-model-and-contracts.md §2 "Desktop captures (K-2)".

    - mirror_captures=False (default): capture files are skipped entirely (unchanged prior
      behaviour) — they never reach the hub while the user hasn't opted in.
    - mirror_captures=True: capture files ARE included. A capture that has no `id` yet gets one
      minted (ULID-style) and `id`/`origin: capture` written back as a FRONTMATTER-ONLY edit
      (body byte-identical — enforced below) so it gains a stable sync identity (closes B-15).

    Notes (origin: note) are always included when they have an id, regardless of the flag."""
    notes: Dict[str, Dict] = {}
    vault_dir = Path(vault_path)
    if not vault_dir.exists():
        return notes

    for md_file in vault_dir.rglob("*.md"):
        if any(part in _RESERVED_FOLDERS for part in md_file.relative_to(vault_dir).parts[:-1]):
            continue  # e.g. .sync/provisional/<op_id>.md — LAN staging, not a real vault note
        try:
            # newline="" → byte-verbatim read: universal-newline translation would turn \r\n
            # into \n, making `hash` disagree with disk/hub bytes (body-sacred, spurious re-upload).
            content = md_file.read_text(encoding="utf-8", newline="")
        except Exception as e:  # unreadable file — skip, never crash the mirror
            print(f"[mobile_sync_agent] skip {md_file}: {e}")
            continue
        fields = read_all_fields(content)
        is_capture = fields.get("origin") != "note"
        if is_capture and not mirror_captures:
            continue  # opt-in mirroring off (default) — captures stay desktop-local

        note_id = fields.get("id")
        if is_capture and mirror_captures and not note_id:
            new_id = _mint_capture_id()
            new_content = add_fields(content, {"id": new_id, "origin": "capture"})
            if strip_frontmatter(new_content) != strip_frontmatter(content):
                print(f"[mobile_sync_agent] mint-id would alter body, skip {md_file}")
                continue
            try:
                _atomic_write_note(str(md_file), new_content)   # atomic: never a torn note
            except Exception as e:
                print(f"[mobile_sync_agent] mint-id write failed {md_file}: {e}")
                continue
            content = new_content
            fields = read_all_fields(content)
            note_id = new_id

        if not note_id:
            print(f"[mobile_sync_agent] no id, skip {md_file}")
            continue
        parent = md_file.parent
        folder_cat = parent.name if parent != vault_dir else None
        notes[note_id] = {
            "id": note_id,
            "path": str(md_file),
            "content": content,
            "body": strip_frontmatter(content),
            "hash": _sha256(content),
            "category": fields.get("category") or folder_cat,
            "title": fields.get("title", ""),
            "created": fields.get("created", ""),
        }
    return notes


def load_state(state_path: str) -> Dict[str, Dict]:
    """Load the derived, rebuildable sync sidecar. Absent/corrupt → empty."""
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        # ValueError is the shared base of json.JSONDecodeError AND
        # UnicodeDecodeError -- a byte-flip in the sidecar raises the latter, which
        # used to escape and park the sync pass in `error` forever (and crash
        # note_history._sync_entry, the other caller).
        return {}  # derived cache — safe to rebuild from files


def save_state(state_path: str, state: Dict[str, Dict]) -> None:
    """Write the sidecar atomically: temp sibling + os.replace (provisional_store._save_state's
    idiom). A crash mid-write used to truncate the live file; load_state rebuilds from empty, so
    the next pass re-uploaded every note blind. The rename is atomic — the sidecar is either the
    old state or the new one, never a half-written one."""
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, state_path)   # atomic


def ensure_hub_folder(drive, name: str = HUB_FOLDER_NAME) -> str:
    """Return the hub root folder id, creating it on first run (data-model §2)."""
    q = f"name='{name}' and mimeType='{_FOLDER_MIME}' and trashed=false"
    found = drive.files().list(q=q, fields="files(id,name)").execute().get("files", [])
    if found:
        return found[0]["id"]
    created = (
        drive.files()
        .create(body={"name": name, "mimeType": _FOLDER_MIME}, fields="id")
        .execute()
    )
    return created["id"]


def _list_children(drive, parent_id: str, mime_is_folder: Optional[bool] = None):
    """Yield every non-trashed child of parent_id, following pagination.

    mime_is_folder: True → folders only, False → non-folders only, None → all.
    """
    q = f"'{parent_id}' in parents and trashed=false"
    if mime_is_folder is True:
        q += f" and mimeType='{_FOLDER_MIME}'"
    elif mime_is_folder is False:
        q += f" and mimeType!='{_FOLDER_MIME}'"
    page_token = None
    while True:
        res = (
            drive.files()
            .list(
                q=q,
                fields="nextPageToken, files(id, name, headRevisionId, appProperties, mimeType, md5Checksum)",
                pageToken=page_token,
            )
            .execute()
        )
        for f in res.get("files", []):
            yield f
        page_token = res.get("nextPageToken")
        if not page_token:
            break


def list_hub_tree(drive, hub_folder_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Split the hub root's subfolders into (categories{name:id}, reserved{name:id})."""
    categories: Dict[str, str] = {}
    reserved: Dict[str, str] = {}
    for f in _list_children(drive, hub_folder_id, mime_is_folder=True):
        target = reserved if f["name"] in _RESERVED_FOLDERS else categories
        target[f["name"]] = f["id"]
    return categories, reserved


def _find_or_create_subfolder(drive, parent_id: str, name: str) -> str:
    """Return the id of the `name` subfolder under parent_id, creating it if absent."""
    q = (
        f"name='{name}' and mimeType='{_FOLDER_MIME}' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    found = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    if found:
        return found[0]["id"]
    created = (
        drive.files()
        .create(
            body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
            fields="id",
        )
        .execute()
    )
    return created["id"]


def upload_sync_file(drive, hub_folder_id: str, filename: str, content: str,
                     mimetype: str = "application/json") -> None:
    """Upload/overwrite ONE advisory file in the hub's `.sync/` folder (contract §11.8-B:
    `lan_endpoint.json`). The rest of `.sync/` stays device-local — this is the single `.sync/`
    file the phone reads for LAN discovery. Not a note (no id/appProperties); matched by name.
    Best-effort, accelerator-only: a failure here never affects canonical Drive sync."""
    sync_id = _find_or_create_subfolder(drive, hub_folder_id, ".sync")
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mimetype)
    existing = next(
        (f for f in _list_children(drive, sync_id, mime_is_folder=False) if f["name"] == filename),
        None,
    )
    if existing:
        drive.files().update(fileId=existing["id"], media_body=media).execute()
    else:
        drive.files().create(
            body={"name": filename, "parents": [sync_id]}, media_body=media, fields="id"
        ).execute()


def _download_bytes(drive, file_id: str) -> bytes:
    """Fetch a hub file's current bytes UNDECODED (for binary captures)."""
    return drive.files().get_media(fileId=file_id).execute()


def _delete_file(drive, file_id: str) -> None:
    drive.files().delete(fileId=file_id).execute()


def get_hub_notes(drive, hub_folder_id: str) -> Dict[str, Dict]:
    """List every .md note across the hub's category subfolders (2-level walk, contract §2).

    Reserved folders (_trash/_mobile_inbox/_attachments/_templates/.sync) are skipped.
    Keyed by note id: appProperties.noteId when present, else the filename stem — this
    normalizes phone-origin `<id>.md` (no appProperties) and desktop-origin `<id>` to one
    key so reconcile can match them against the vault (which is keyed by frontmatter id).
    Each record carries its `category` (parent folder name). headRevisionId is the only
    version token; no modifiedTime is ever read.
    """
    categories, _reserved = list_hub_tree(drive, hub_folder_id)
    files: Dict[str, Dict] = {}
    for cat_name, cat_id in categories.items():
        for f in _list_children(drive, cat_id, mime_is_folder=False):
            if not f["name"].endswith(".md"):
                continue
            props = f.get("appProperties") or {}
            note_id = props.get("noteId")
            if not note_id:
                note_id = Path(f["name"]).stem
                print(f"[mobile_sync_agent] hub file {f.get('id')} ({f['name']}) has no "
                      f"appProperties.noteId; keying by filename stem {note_id} (legacy/foreign)")
            key = note_id
            f["category"] = cat_name
            # ponytail: assumes hub-level note-id uniqueness (ids are ULIDs). Two files sharing an
            # id stem across category folders would collide here, last-wins; add a warn/dedup pass
            # only if a corrupted hub ever produces duplicate ids.
            files[key] = f
    # B-5: also scan root-level .md notes. `_resolve_dest_folder` uploads uncategorised notes to the
    # hub ROOT; without this pass get_hub_notes never saw them → invisible to the phone AND never
    # reconciled (remote edits to an uncategorised note were silently never pulled). category=None marks
    # uncategorised. setdefault so a category-folder note always wins a same-id root duplicate.
    for f in _list_children(drive, hub_folder_id, mime_is_folder=False):
        if not f["name"].endswith(".md"):
            continue
        props = f.get("appProperties") or {}
        note_id = props.get("noteId")
        if not note_id:
            note_id = Path(f["name"]).stem
            print(f"[mobile_sync_agent] hub file {f.get('id')} ({f['name']}) has no "
                  f"appProperties.noteId; keying by filename stem {note_id} (legacy/foreign)")
        key = note_id
        f["category"] = None
        files.setdefault(key, f)
    return files


def _resolve_dest_folder(drive, hub_folder_id: str, category: Optional[str], cache: Dict[str, str]) -> str:
    """Category folder id for a note (find-or-create, cached per run). Falsy category → hub root.

    ponytail: uncategorised notes land at the hub root; give them a default category folder
    only if the vault ever forbids root-level notes.
    """
    if not category:
        return hub_folder_id
    if category not in cache:
        cache[category] = _find_or_create_subfolder(drive, hub_folder_id, category)
    return cache[category]


def _upload_note(drive, note: Dict, dest_folder_id: str, existing: Optional[Dict],
                 *, hub_name: Optional[str] = None) -> Dict:
    """Create or update one note on the hub. Returns the Drive file resource
    (with id + headRevisionId). Asserts the body is byte-identical to the source.

    hub_name: the note's resolved title-based filename (data-model-and-contracts.md §2 v1.2+;
    normally from `_resolve_hub_names` over the note's folder). Defaults to `_hub_filename` on
    the note's own title/created for callers that have not resolved clashes (legacy/test paths).
    On an update, the file is renamed in place (same Drive file id, `files().update`) — never
    re-created — UNLESS its previously-synced name (existing["hub_name"]) already matches, in
    which case `name` is dropped from the update body to avoid a needless headRevisionId bump.
    """
    content = note["content"]
    # Body-sacred: we upload the source bytes verbatim; the body must be unchanged.
    # Explicit check (not `assert`) — must not be strippable under python -O.
    if strip_frontmatter(content) != note["body"]:
        raise RuntimeError("body-sacred violation: body bytes changed before upload")

    name = hub_name or _hub_filename(note.get("title") or "", note.get("created") or "")
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown")
    metadata = {"name": name, "appProperties": {"noteId": note["id"]}}

    if existing and existing.get("drive_file_id"):
        # ponytail: update-in-place by file id — a note whose category changed stays in its
        # original hub folder (no move). Wire a parents add/remove here if per-category hub
        # placement must track category edits.
        prev_name = existing.get("hub_name")
        if prev_name is not None and prev_name == name:
            metadata.pop("name")  # unchanged name — skip the rename, avoid a needless rev bump
        elif prev_name is not None:
            print(f"[mobile_sync_agent] renamed {note['id']}: {prev_name!r} -> {name!r}")
        return (
            drive.files()
            .update(
                fileId=existing["drive_file_id"],
                body=metadata,
                media_body=media,
                fields="id, headRevisionId, name",
            )
            .execute()
        )
    metadata["parents"] = [dest_folder_id]
    return (
        drive.files()
        .create(body=metadata, media_body=media, fields="id, headRevisionId, name")
        .execute()
    )


def _maybe_rename_local(local_path: str, hub_name: Optional[str],
                        prev_hub_name: Optional[str], note_id: str) -> str:
    """Local half of title-based naming (spec scope = hub+local): if the note's resolved name
    changed since the last sync recorded one, rename the vault file in place — atomic os.replace
    BEFORE any new content is written, so the note is never bodyless mid-rename and never ends up
    duplicated under both names. Returns the (possibly new) path to write/read at.

    A note with no PRIOR tracked name (never synced under this feature, e.g. a legacy `<id>.md`
    file untouched since migration) is left at its current filename here — this only fires on an
    OBSERVED name change, it does not itself bulk-rename legacy files (that one-time sweep is
    Phase 3's `migrate_hub_filenames`, not this per-note-sync path)."""
    if not hub_name or not prev_hub_name or prev_hub_name == hub_name:
        return local_path
    if Path(local_path).name == hub_name:
        return local_path
    new_path = str(Path(local_path).with_name(hub_name))
    os.replace(local_path, new_path)
    print(f"[mobile_sync_agent] local rename {note_id}: {Path(local_path).name!r} -> {hub_name!r}")
    return new_path


def _download_content(drive, file_id: str, expected_md5: Optional[str] = None) -> str:
    """Fetch a hub file's current bytes (Drive `GET ?alt=media`), decoded as UTF-8.

    OF-33: when `expected_md5` (Drive's `md5Checksum` from the file listing) is given, verify the
    downloaded bytes hash to it BEFORE decoding — a truncated/corrupt download that still parses
    would otherwise be ingested as authoritative (the desktop twin of the phone's OF-10 guard).
    Mismatch raises → the caller's `except` treats it as transient (base_rev not advanced, retried
    next pass, same as a 5xx). Omitting `expected_md5` keeps the old behavior (pure superset), which
    is why the CP2 stub read and injected test downloads are unaffected.
    """
    raw = drive.files().get_media(fileId=file_id).execute()
    if expected_md5:
        got = hashlib.md5(raw).hexdigest()
        if got != expected_md5:
            raise ValueError(
                f"download integrity check failed for {file_id}: "
                f"md5 {got} != hub {expected_md5} (transient — held for retry)"
            )
    return raw.decode("utf-8")


def _download_revision(drive, file_id: str, revision_id: str) -> str:
    """Fetch a specific past revision's bytes — used to get the BASE (last-reconciled) note text
    for a three-way merge (contract §10 "Version history")."""
    return (
        drive.revisions()
        .get_media(fileId=file_id, revisionId=revision_id)
        .execute()
        .decode("utf-8")
    )


def migrate_hub_filenames(drive, hub_folder_id: str, state: Dict[str, Dict]) -> Dict[str, Dict]:
    """One-time hub-filename migration (Task 3.1): renames every legacy hub note file to its
    resolved title-based name (data-model-and-contracts.md §2 v1.2+, `_resolve_hub_names`) and
    stamps `appProperties.noteId`, converging pre-existing hub content onto the naming scheme
    reconcile_changes/mirror_to_hub already produce for ongoing syncs. HUB-SIDE ONLY — see
    run_once for the local-vault half (deliberately kept out of this function; see below).

    Guard: `state["hub_names_migrated"]` already True -> return state unchanged, ZERO Drive calls.

    Resumable + idempotent: the flag is set True ONLY after a full clean pass over every hub note
    — an exception mid-pass propagates WITHOUT setting it, so a re-run resumes. Independent of the
    flag, each FILE is also individually idempotent: one already at its resolved name AND already
    carrying appProperties.noteId is skipped with no Drive write — this is what makes a resumed
    pass (or a redundant one before the flag is persisted) cheap, not just the top-level guard.

    Body-sacred: the one read per file is a content download solely to recover frontmatter
    id/title/created for naming (the same identity problem get_hub_notes solves) — the body is
    never altered, and the rename itself is a metadata-only `files().update(body={...})` with NO
    media_body, so the file's bytes on Drive are never re-uploaded.

    State is touched ONLY for a note this desktop already has a prior sync-state record for
    (`note_id in state`) — never for a note the hub holds that the desktop has no record of.
    Two reasons, both load-bearing:
      1. pull_new_hub_notes' "already tracked" skip is `if key in vault_notes or key in state:
         continue`. Writing a bare hub_name-only stub into state for a never-pulled note would
         make that check treat it as already-synced and permanently swallow its first pull.
      2. reconcile_changes' non-adopted path does `prior["base_rev"]` by bare-key indexing (not
         `.get`) once local AND remote have both changed; a state entry with `hub_name` but no
         `base_rev` (which is all this function could ever legitimately know) would KeyError
         there. Only touching PRE-EXISTING entries (which already carry a real base_rev) avoids
         ever constructing that malformed shape.
    A note this function renames but does not touch in state still gets its LOCAL vault mirror
    converged in run_once (see the local-rename block there — it reuses run_once's own state
    lookups, so this function does not need to write anything for that case either); a hub-only
    note nobody has ever pulled still lands at `<id>.md` via the ordinary pull_new_hub_notes path
    afterwards (unaffected by this migration — title-naming a freshly pulled note is a separate,
    not-yet-closed gap, see Task 2.4).
    """
    if state.get("hub_names_migrated"):
        return state

    new_state = dict(state)
    categories, _reserved = list_hub_tree(drive, hub_folder_id)

    entries = []  # (drive_file, category_name_or_None)
    for cat_name, cat_id in categories.items():
        for f in _list_children(drive, cat_id, mime_is_folder=False):
            if f["name"].endswith(".md"):
                entries.append((f, cat_name))
    for f in _list_children(drive, hub_folder_id, mime_is_folder=False):
        if f["name"].endswith(".md"):
            entries.append((f, None))

    parsed = []
    seen_ids: set = set()
    for f, cat_name in entries:
        content = _download_content(drive, f["id"])
        fields = read_all_fields(content)
        note_id = fields.get("id") or Path(f["name"]).stem
        if note_id in seen_ids:
            continue  # category-folder note wins over a same-id root duplicate (mirrors get_hub_notes)
        seen_ids.add(note_id)
        parsed.append({
            "file": f, "id": note_id, "category": cat_name,
            "title": fields.get("title") or "", "created": fields.get("created") or "",
        })

    hub_names = _resolve_hub_names([
        {"id": p["id"], "title": p["title"], "created": p["created"], "category": p["category"]}
        for p in parsed
    ])

    for p in parsed:
        f = p["file"]
        note_id = p["id"]
        resolved = hub_names.get(note_id, f["name"])
        has_note_id = bool((f.get("appProperties") or {}).get("noteId"))

        if f["name"] != resolved or not has_note_id:
            drive.files().update(
                fileId=f["id"],
                body={"name": resolved, "appProperties": {"noteId": note_id}},
                fields="id, headRevisionId, name",
            ).execute()
            print(f"[mobile_sync_agent] migrate rename {note_id}: {f['name']!r} -> {resolved!r}")

        if note_id in state:  # pre-existing entry only — see docstring for why
            entry = dict(new_state.get(note_id, {}))
            entry["hub_name"] = resolved
            new_state[note_id] = entry

    new_state["hub_names_migrated"] = True
    return new_state


def reconcile_changes(
    vault_notes: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    state: Dict[str, Dict],
    drive,
    hub_folder_id: str,
    write_file: Optional[Callable[[str, str], None]] = None,
    new_id: Optional[Callable[[], str]] = None,
) -> Tuple[int, int, int, Dict[str, Dict]]:
    """Pull + field-aware three-way reconcile every note whose hub head advanced past our base_rev.

    Per note (existing locally + on the hub):
      - remote head == base_rev            → skip (mirror_to_hub handles any local-only change)
      - remote advanced, local unchanged   → PULL: overwrite local with remote bytes verbatim
      - remote advanced AND local changed   → three-way reconcile() → write merged locally, upload it,
                                              and spin off a conflicted copy on a body-vs-body conflict
      - sidecar has NO record but the hub holds the note → ADOPT: no base_rev was ever observed for
                                              it, so reconcile against an unknown base (2-way)

    Body-sacred: reconcile() guarantees the merged body is a verbatim copy of one input — never
    fabricated. Returns (reconciled, conflicts, failed, new_state).

    write_file / new_id are injected so the merge logic is unit-testable without disk or randomness.
    """
    if write_file is None:
        # Atomic + byte-verbatim (_atomic_write_note owns both): a kill mid-write must never leave
        # a torn body the next scan mistakes for a local edit and pushes to the hub (S4-1).
        write_file = _atomic_write_note
    if new_id is None:
        # ponytail: uuid4-hex conflicted-copy id (opaque sync identity, only needs uniqueness).
        # Swap for a real ULID minter if lexical time-ordering of conflicted copies ever matters.
        new_id = lambda: uuid.uuid4().hex[:26]  # noqa: E731

    reconciled = 0
    conflicts = 0
    failed = 0
    new_state = dict(state)
    folder_cache: Dict[str, str] = {}
    # Resolved once per folder (via (category, name) grouping inside _resolve_hub_names) over every
    # local note — used below to rename/re-upload a note whose title changed. Based on the LOCAL
    # (pre-merge) title: the common case is a user retitling on this device; a title that changed
    # ONLY on the remote side during this same pass keeps its prior local name here (simplification —
    # the next pass's mirror/pull sees the merged title and converges it).
    hub_names = _resolve_hub_names([
        {"id": nid, "title": n.get("title", ""), "created": n.get("created", ""),
         "category": n.get("category")}
        for nid, n in vault_notes.items()
    ])

    for note_id, local in vault_notes.items():
        prior = state.get(note_id)
        hub_file = hub_files.get(note_id)
        adopted = False
        if not prior or not prior.get("drive_file_id"):
            if not hub_file:
                continue  # never synced, not on the hub → mirror_to_hub creates it
            # F-1: the sidecar (a derived cache) is absent/corrupt/stale for this note, but the
            # hub already holds it. Adopt the hub FILE ID so the note is updated in place and
            # never re-created as a duplicate orphan — but we have observed NO sync for it, so
            # there is no revision we may call the base: base_rev stays unset (it may only ever
            # hold a head we actually synced at) and the note falls through to the reconcile
            # below with an unknown ancestor. Claiming base_rev = the CURRENT head here made
            # mirror_to_hub's advanced-head guard compare the head against itself, so the
            # desktop blind-uploaded its stale body over a peer's un-pulled edit.
            prior = {"drive_file_id": hub_file["id"], "base_rev": None, "local_hash": None}
            adopted = True
        if not hub_file:
            continue  # not on the hub (or trashed) → nothing to pull
        remote_rev = hub_file.get("headRevisionId")
        if remote_rev == prior.get("base_rev"):
            continue  # remote unchanged since last sync
        local_changed = local["hash"] != prior.get("local_hash")
        file_id = prior["drive_file_id"]
        try:
            # OF-33: pass the hub's md5Checksum so a truncated/corrupt download is rejected before
            # it can be adopted — one guard covers all three outcomes below (already-synced, pull,
            # 3-way reconcile), since they all consume this single `remote_text`.
            remote_text = _download_content(drive, file_id, hub_file.get("md5Checksum"))
            if adopted and remote_text == local["content"]:
                # Already in sync, we just could not prove it: the head IS our bytes, so this is
                # a head we have now observed a sync at — record it and skip. Without the byte
                # compare the sidecar rebuild re-uploads identical content and burns a
                # headRevisionId (which makes every peer re-pull an unchanged note).
                new_state[note_id] = {
                    "drive_file_id": file_id,
                    "base_rev": remote_rev,
                    "local_hash": local["hash"],
                }
                continue
            if not local_changed:
                # PULL: remote-only change. Verbatim propagation of the other device's edit.
                write_file(local["path"], remote_text)
                new_state[note_id] = {
                    "drive_file_id": file_id,
                    "base_rev": remote_rev,
                    "local_hash": _sha256(remote_text),
                }
                reconciled += 1
                continue

            # BOTH changed → three-way field-aware reconcile.
            local_note = parse_note(local["content"])
            if adopted:
                # No base: nothing ever recorded a sync for this note, so there is no revision
                # that is the common ancestor. Reconcile against a base whose body matches
                # NEITHER side (_NO_BASE_BODY) — a 2-way merge: equal bodies merge cleanly,
                # divergent bodies are a body-vs-body conflict → conflicted copy, both intact.
                # Everything else on the base is the local note, so a frontmatter divergence
                # falls to the hub — the canonical side — since we cannot tell who edited what.
                base = replace(local_note, body=_NO_BASE_BODY)
            else:
                base = parse_note(_download_revision(drive, file_id, prior["base_rev"]))
            merged_result = reconcile(
                base, local_note, parse_note(remote_text), new_id()
            )
            merged_text = serialize_note(merged_result.merged)
            hub_name = hub_names.get(note_id)
            local_path = _maybe_rename_local(
                local["path"], hub_name, prior.get("hub_name"), note_id
            )
            write_file(local_path, merged_text)
            dest = _resolve_dest_folder(drive, hub_folder_id, local.get("category"), folder_cache)
            up = _upload_note(
                drive,
                {"id": note_id, "content": merged_text, "body": merged_result.merged.body},
                dest,
                {"drive_file_id": file_id, "hub_name": prior.get("hub_name")},
                hub_name=hub_name,
            )
            new_state[note_id] = {
                "drive_file_id": up["id"],
                "base_rev": up.get("headRevisionId"),
                "local_hash": _sha256(merged_text),
                "hub_name": hub_name,
            }
            reconciled += 1

            if merged_result.conflicted_copy is not None:
                cc = merged_result.conflicted_copy
                cc_text = serialize_note(cc)
                cc_path = str(Path(local_path).with_name(f"{cc.id}.md"))
                write_file(cc_path, cc_text)
                up_cc = _upload_note(
                    drive,
                    {"id": cc.id, "content": cc_text, "body": cc.body},
                    dest,
                    None,
                    # ponytail: conflicted copies keep the old <id>.md naming (out of Task 2.4 scope —
                    # title-based names risk colliding with the note they diverged from; the id
                    # suffix is what makes a conflicted copy recognizable as one).
                    hub_name=f"{cc.id}.md",
                )
                new_state[cc.id] = {
                    "drive_file_id": up_cc["id"],
                    "base_rev": up_cc.get("headRevisionId"),
                    "local_hash": _sha256(cc_text),
                }
                conflicts += 1
        except Exception as e:
            print(f"[mobile_sync_agent] reconcile {note_id} failed: {e}")
            failed += 1

    return reconciled, conflicts, failed, new_state


def mirror_to_hub(
    vault_notes: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    state: Dict[str, Dict],
    drive,
    hub_folder_id: str,
) -> Tuple[int, int, Dict[str, Dict]]:
    """Upload notes that are new or whose local content changed since last sync.

    Upload decision is local-content-hash vs the sidecar's last-synced hash — NEVER
    modifiedTime. A note the sidecar has no record of is only CREATED here (hub-absent);
    if the hub already holds it, no sync was ever observed for it and reconcile_changes
    owns it. Returns (uploaded, failed, new_state).
    """
    uploaded = 0
    failed = 0
    new_state = dict(state)
    folder_cache: Dict[str, str] = {}
    # _resolve_hub_names groups by (category, name) internally, so one pass over every note
    # being mirrored already scopes clash resolution per hub folder.
    hub_names = _resolve_hub_names([
        {"id": nid, "title": n.get("title", ""), "created": n.get("created", ""),
         "category": n.get("category")}
        for nid, n in vault_notes.items()
    ])

    for note_id, note in vault_notes.items():
        prior = state.get(note_id)
        # Skip only if we have synced this exact content before.
        if prior and prior.get("local_hash") == note["hash"] and prior.get("drive_file_id"):
            continue
        if not prior or not prior.get("drive_file_id"):
            # F-1: sidecar absent/corrupt/stale for this note. If the hub already holds it we
            # have observed NO sync for it — no base_rev, so no evidence our body is newer than
            # the head — and uploading here would silently revert a peer's un-pulled edit.
            # reconcile_changes owns this case: it adopts the hub file id (so the note is still
            # updated in place, never re-created as a duplicate orphan) and resolves a body
            # divergence into a conflicted copy. Only a note the hub does NOT have is created here.
            if note_id in hub_files:
                continue
        hub_file = hub_files.get(note_id)
        if (
            prior
            and prior.get("base_rev")
            and hub_file
            and hub_file.get("headRevisionId") != prior.get("base_rev")
        ):
            # Hub head advanced past our base — a blind upload would discard the remote edit
            # from the canonical head. Leave it for the next reconcile pass.
            continue
        try:
            dest = _resolve_dest_folder(drive, hub_folder_id, note.get("category"), folder_cache)
            hub_name = hub_names.get(note_id)
            prev_hub_name = prior.get("hub_name") if prior else None
            local_path = _maybe_rename_local(note["path"], hub_name, prev_hub_name, note_id)
            if local_path != note["path"]:
                note = dict(note, path=local_path)  # keep this pass's in-memory note consistent
            result = _upload_note(drive, note, dest, prior, hub_name=hub_name)
            new_state[note_id] = {
                "drive_file_id": result["id"],
                "base_rev": result.get("headRevisionId"),
                "local_hash": note["hash"],
                "hub_name": hub_name,
            }
            uploaded += 1
        except Exception as e:
            print(f"[mobile_sync_agent] upload {note_id} failed: {e}")
            failed += 1

    return uploaded, failed, new_state


def _safe_path_component(name: str) -> str:
    """Reject a hub-supplied value that is unsafe as a single vault path component
    (separator, traversal, drive colon) — mirrors provisional_store's B-12 guard."""
    if not name or name in (".", "..") or any(c in name for c in ("/", "\\", ":")):
        raise ValueError(f"unsafe hub path component: {name!r}")
    return name


def pull_new_hub_notes(
    vault_notes: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    state: Dict[str, Dict],
    drive,
    vault_root: str,
    scratchpad_folder: str,
    write_file: Optional[Callable[[str, str], None]] = None,
    download: Optional[Callable[[str], str]] = None,
) -> Tuple[int, int, Dict[str, Dict]]:
    """Pull hub notes the desktop has never seen (phone-created / first sync) into the vault.

    'New' = id in neither the local vault nor the state sidecar. Placement:
    vault/<category-from-frontmatter>/<hub-name>.md; missing/empty category → the scratchpad.
    <hub-name> mirrors the hub file's OWN resolved `name` (get_hub_notes already carries it,
    clash-unique on the hub) — this function never recomputes `_resolve_hub_names`, it just
    matches the local filename to the hub's. Falls back to `<id>.md` only if the hub record's
    name is missing/unsafe (never crash on an untrusted Drive listing).
    Bytes are written verbatim (body-sacred — we never touch a pulled body).
    Returns (pulled, failed, new_state).
    """
    if write_file is None:
        def write_file(path: str, content: str) -> None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_note(path, content)  # atomic + byte-verbatim (body-sacred)
    if download is None:
        # OF-33: verify each pulled file against its hub md5Checksum (transient reject on mismatch,
        # caught below → failed++, retried). The injectable `download` seam stays one-arg for tests.
        _md5_by_id = {hf["id"]: hf.get("md5Checksum") for hf in hub_files.values() if hf.get("id")}
        def download(file_id: str) -> str:
            return _download_content(drive, file_id, _md5_by_id.get(file_id))

    pulled = 0
    failed = 0
    new_state = dict(state)

    for key, hub_file in hub_files.items():
        if key in vault_notes or key in state:
            continue
        try:
            content = download(hub_file["id"])
            fields = read_all_fields(content)
            note_id = fields.get("id") or key
            if note_id in vault_notes or note_id in new_state:
                continue  # id-level dedupe (key may have been a filename stem)
            category = fields.get("category")
            sub = category if category else scratchpad_folder
            # Hub frontmatter is untrusted input — `id`/`category` become path components (B-12
            # class). Reject anything that could step outside vault/<category>/<local_name>.
            _safe_path_component(note_id)
            _safe_path_component(sub)
            hub_name = hub_file.get("name")
            try:
                if hub_name:
                    _safe_path_component(hub_name)
            except ValueError:
                hub_name = None
            local_name = hub_name or f"{note_id}.md"
            dest = str(Path(vault_root) / sub / local_name)
            write_file(dest, content)
            new_state[note_id] = {
                "drive_file_id": hub_file["id"],
                "base_rev": hub_file.get("headRevisionId"),
                "local_hash": _sha256(content),
                "hub_name": hub_name,
            }
            pulled += 1
        except Exception as e:
            print(f"[mobile_sync_agent] pull {key} failed: {e}")
            failed += 1

    return pulled, failed, new_state


_AUDIO_EXTS = {"m4a", "mp3", "wav", "ogg", "aac", "flac"}
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "heic"}
_ATTACH_RE = re.compile(r"^\[capture attachment: (.+)\]\s*$")


def intake_mobile_inbox(
    drive,
    inbox_folder_id: str,
    run_pipeline: Callable[..., Dict],
    *,
    download_bytes: Optional[Callable[[str], bytes]] = None,
    delete_file: Optional[Callable[[str], None]] = None,
    stage_dir: Optional[str] = None,
) -> Tuple[int, int, int]:
    """Drain `_mobile_inbox/`: pair each stub with its sibling, feed the capture to run_pipeline,
    then delete the ingested file(s). CP2 contract (plans/CP2-capture-contract.md).

    - text/URL capture = a lone `<base>.md` (body is the content) → run_pipeline(text=body).
    - binary capture = `<base>.<ext>` (bytes) + `<base>.md` stub whose body is
      `[capture attachment: <base>.<ext>]` → stage the bytes to a temp file and
      run_pipeline(audio=path) (audio ext) / run_pipeline(image=path) (image ext).
    - a stub referencing a MISSING sibling → skip this cycle (retry later); never hard-fail,
      never ingest the stub text as the capture.

    Captures enter the pipeline UNCHANGED (dedup/merge/scratchpad apply — the notes-are-not-
    captures lock). Returns (ingested, skipped, failed).
    """
    if download_bytes is None:
        download_bytes = lambda fid: _download_bytes(drive, fid)  # noqa: E731
    if delete_file is None:
        delete_file = lambda fid: _delete_file(drive, fid)        # noqa: E731

    files = list(_list_children(drive, inbox_folder_id, mime_is_folder=False))
    by_name = {f["name"]: f for f in files}

    ingested = skipped = failed = 0
    for f in files:
        name = f["name"]
        if not name.endswith(".md"):
            continue  # a sibling payload; handled via its stub
        try:
            stub_text = _download_content(drive, f["id"])
            body = strip_frontmatter(stub_text).strip()
            m = _ATTACH_RE.match(body)
            if m:
                sibling_name = m.group(1)
                sibling = by_name.get(sibling_name)
                if sibling is None:
                    skipped += 1          # bytes not arrived yet — retry next cycle
                    continue
                ext = sibling_name.rsplit(".", 1)[-1].lower()
                data = download_bytes(sibling["id"])
                staged = Path(stage_dir or tempfile.gettempdir()) / sibling_name
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)
                if ext in _AUDIO_EXTS:
                    run_pipeline(audio=str(staged))
                elif ext in _IMAGE_EXTS:
                    run_pipeline(image=str(staged))
                else:
                    # unknown binary kind — leave it, flag once, don't fake-ingest
                    print(f"[mobile_sync_agent] intake: unknown ext {ext!r} for {sibling_name}, skip")
                    skipped += 1
                    continue
                delete_file(f["id"])
                delete_file(sibling["id"])
                ingested += 1
            else:
                run_pipeline(text=body)   # text/URL capture; the router shape-detects URLs
                delete_file(f["id"])
                ingested += 1
        except Exception as e:
            print(f"[mobile_sync_agent] intake {name} failed: {e}")
            failed += 1

    return ingested, skipped, failed


# ponytail: ingested inbox files are deleted (the capture now lives in the vault; the phone never
# deletes and re-push skips by name). Swap _delete_file for a move into _mobile_inbox/_ingested/
# if an archive trail is ever wanted.
# ponytail: text vs URL captures both go through run_pipeline(text=...) and rely on the enrichment
# router's URL shape-detection; CP2 frontmatter carries no text/url discriminator.


def enrich_notes(
    vault_notes: Dict[str, Dict],
    vault_root: str,
    classify: Callable[[str], Tuple[List[str], str]],
    vocab: Dict[str, str],
    embed: Optional[Callable[[str, str], None]] = None,
) -> Tuple[int, int]:
    """Note-only enrichment (contract §7). For every origin:note, enriched:false note,
    refine tags + pick a category via `classify`, embed via `embed`, and write a
    frontmatter-ONLY patch { tags, category, enriched:true, enrich_source:desktop-llm }.

    Body is sacred: asserted byte-identical before every write. NEVER touches run_pipeline
    (notes-are-not-captures lock). Fail-soft per note: a classify/write error leaves the note
    enriched:false for the next pass. `vault_notes` is mutated in place so a later mirror in
    the same run_once sees the new content. Returns (enriched_count, failed)."""
    from tag_vocab import normalize_tags

    enriched_count = 0
    failed = 0
    # ponytail: no per-note enrich backoff — a note that keeps failing classify (model down,
    # transient error) is retried every run_once. Fine at current volumes; add a fail-count sidecar
    # if a poison note ever wastes LLM calls. (The empty-body poison case — nothing to classify,
    # model times out synthesizing from nothing — is guarded below without a backoff.)
    for note_id, entry in vault_notes.items():
        try:
            note = parse_note(entry["content"])
        except Exception as e:
            print(f"[mobile_sync_agent] enrich parse skip {entry.get('path')}: {e}")
            continue
        if note.origin != "note" or note.enriched:
            continue

        try:
            if note.body.strip():
                key_signals, category = classify(note.body)
                note.tags = normalize_tags(list(note.tags) + list(key_signals), vocab)
                note.category = category
                note.enrich_source = "desktop-llm"
            # else: empty body → nothing to classify. Fall through to mark enriched WITHOUT an LLM
            # call so this note stops re-hitting Ollama every pass — an empty content block makes
            # llama3.2 synthesize every required schema field from nothing and ramble past
            # request_timeout_s (the recurring "enrich failed … Request timed out" poison note).
            # enrich_source/category/tags are left as-is (enrich_source has a closed contract enum;
            # keeping the note's prior value stays truthful — no desktop-LLM pass actually ran).
            # ponytail: if an empty note later gains a body, whatever flips enriched:false on edit
            # re-triggers a real pass; marking it enriched now only skips the pointless empty enrich.
            note.enriched = True
            new_content = serialize_note(note)
            # BODY SACRED — refuse to write if the body changed by a single byte.
            if strip_frontmatter(new_content) != note.body:
                raise RuntimeError(f"enrich would alter body of {note_id}")
            _atomic_write_note(entry["path"], new_content)   # atomic: never a torn note
        except Exception as e:
            print(f"[mobile_sync_agent] enrich failed {note_id}: {e}")
            failed += 1
            continue

        # File is written + enriched. Update the in-memory dict for the same-pass mirror.
        entry["content"] = new_content
        entry["hash"] = _sha256(new_content)
        entry["category"] = note.category
        enriched_count += 1

        # Embedding is best-effort — a failure here must not un-enrich the note.
        # ponytail: enriched-but-unembedded on embed failure; a re-embed sweep can backfill
        # if RAG ever misses notes.
        if embed is not None:
            try:
                embed(entry["path"], new_content)
            except Exception as e:
                print(f"[mobile_sync_agent] embed failed {note_id}: {e}")

    return enriched_count, failed


def run_once(
    vault_path: str,
    state_path: str,
    drive,
    vault_root: Optional[str] = None,
    scratchpad_folder: str = "_scratchpad",
    run_pipeline: Optional[Callable[..., Dict]] = None,
    enrich_fn: Optional[Callable[[Dict, str], Tuple[int, int]]] = None,
    reminders_fn: Optional[Callable[[Dict], dict]] = None,
    provisional_fn: Optional[Callable[[str], None]] = None,
    mirror_captures: bool = False,
) -> Tuple[int, int, int, int, int, int, int]:
    """One full bidirectional pass:
      1. reconcile notes changed on both sides (three-way merge / conflicted copy),
      2. pull hub-only notes the desktop has never seen into the vault,
      3. drain _mobile_inbox/ captures through run_pipeline,
      4. enrich origin:note, enriched:false notes (frontmatter-only; never run_pipeline),
      5. mirror local-only new/changed notes up to the hub.

    Reconcile + pull run before mirror so merged/pulled bodies are on disk and re-read;
    intake writes captures into the vault via the pipeline. Enrich runs after the re-read
    and before mirror so enriched frontmatter uploads the same pass. Returns
    (uploaded, failed, reconciled, conflicts, pulled, ingested, enriched)."""
    hub_id = ensure_hub_folder(drive)
    vault_root = vault_root or vault_path
    state = load_state(state_path)

    # Task 3.1: one-time hub-filename migration, guarded on state["hub_names_migrated"] so it is
    # zero-cost on every pass after the first. Runs BEFORE list_hub_tree/get_hub_notes below so
    # the rest of this pass sees the POST-migration hub names, instead of racing a stale
    # pre-rename snapshot.
    first_migration_pass = not state.get("hub_names_migrated")
    if first_migration_pass:
        state = migrate_hub_filenames(drive, hub_id, state)

    _categories, reserved = list_hub_tree(drive, hub_id)
    vault_notes = read_vault_notes(vault_path, mirror_captures)
    hub_files = get_hub_notes(drive, hub_id)

    if first_migration_pass:
        # Local half of Task 3.1: rename each already-tracked note's local vault mirror to the
        # hub_name migrate_hub_filenames just resolved for it — os.replace, body untouched. Done
        # HERE (reusing the vault_notes just read above) rather than inside
        # migrate_hub_filenames, which must not perform its own vault scan
        # (test_run_once_threads_mirror_captures_into_both_reads pins read_vault_notes to exactly
        # two calls per pass, both honouring mirror_captures). A note with no prior state entry
        # (never pulled here) has nothing to rename locally yet — pull_new_hub_notes below still
        # claims it fresh.
        for note_id, local in vault_notes.items():
            prior = state.get(note_id)
            resolved = prior.get("hub_name") if prior else None
            if not resolved or Path(local["path"]).name == resolved:
                continue
            new_path = str(Path(local["path"]).with_name(resolved))
            os.replace(local["path"], new_path)
            print(f"[mobile_sync_agent] migrate local rename {note_id}: "
                  f"{Path(local['path']).name!r} -> {resolved!r}")
            local["path"] = new_path
        save_state(state_path, state)

    # Snapshot per-note base_rev so we can tell which notes reached canonical this pass
    # (Drive is the sole canonical/version authority — LAN provisional never advances base_rev).
    # isinstance guard: state may also carry the flat "hub_names_migrated" bool flag (Task 3.1)
    # alongside per-note dicts — skip it here, it is not a note record.
    pre_revs = {nid: s.get("base_rev") for nid, s in state.items() if isinstance(s, dict)}

    # F-5: local-only sync-ignore -- ignored notes never leave this machine
    # in either direction of outbound sync (see sync_ignore.py docstring).
    reconciled, conflicts, r_failed, state = reconcile_changes(
        filter_ignored_notes(vault_notes, Path(vault_root)), hub_files, state, drive, hub_id
    )
    pulled, p_failed, state = pull_new_hub_notes(
        vault_notes, hub_files, state, drive, vault_root, scratchpad_folder
    )

    ingested = i_failed = 0
    inbox_id = reserved.get("_mobile_inbox")
    if inbox_id and run_pipeline is not None:
        ingested, _skipped, i_failed = intake_mobile_inbox(drive, inbox_id, run_pipeline)

    # Re-read: reconcile/pull wrote merged/pulled bodies; the pipeline wrote captures.
    vault_notes = read_vault_notes(vault_path, mirror_captures)

    # Enrich AFTER the re-read (so pulled/ingested notes are visible) and BEFORE mirror
    # (so enriched frontmatter is in vault_notes when mirror computes uploads). enrich_notes
    # mutates vault_notes in place. Notes are not captures — this never touches run_pipeline.
    enriched = e_failed = 0
    if enrich_fn is not None:
        enriched, e_failed = enrich_fn(vault_notes, vault_root)

    # Reconcile the reminders table from each note's remind_at (files are the source of
    # truth — DB-only, never writes a note .md). Fail-soft: a reminders error must never
    # abort the sync pass. Not folded into the return tuple (scheduling state, not sync counts).
    if reminders_fn is not None:
        try:
            rem = reminders_fn(vault_notes)
            print(f"[mobile_sync_agent] reminders: {rem['created']} created, "
                  f"{rem['updated']} updated, {rem['removed']} removed")
        except Exception as exc:
            print(f"[mobile_sync_agent] reminders reconcile failed: {exc}")

    uploaded, u_failed, new_state = mirror_to_hub(
        filter_ignored_notes(vault_notes, Path(vault_root)), hub_files, state, drive, hub_id
    )
    save_state(state_path, new_state)

    # A note reached canonical this pass iff its Drive base_rev advanced (pull/reconcile/mirror
    # all bump base_rev when they write the canonical mirror). Drop its LAN provisional overlay —
    # once per note (base_rev diff dedupes; a brand-new conflicted-copy id simply has nothing staged).
    # ponytail: supersede is best-effort per-pass -- a raising provisional_fn is swallowed
    # per-note-id (logged, not re-raised) so one bad fs/sqlite op never aborts the rest of the
    # pass or the caller's later refresh_outbound/sweep calls; the TTL sweep is the backstop
    # for any drop this pass misses either way.
    # The live caller (main(), _build_provisional_fn) constructs provisional_fn to call BOTH
    # provisional_store.supersede(sync_dir, note_id) AND, for each dropped op_id it returns,
    # index_writer.clear_provisional(db, op_id) -- so the search/RAG index (T13) and the
    # on-disk staging (T7/T8) drop together, gated on `[lan] enabled`. This module still only
    # owns the per-note-id callback contract, not the caller that builds it.
    if provisional_fn is not None:
        for nid, s in new_state.items():
            if not isinstance(s, dict):
                continue  # skip the flat "hub_names_migrated" flag (Task 3.1) — not a note record
            if s.get("base_rev") != pre_revs.get(nid):
                try:
                    provisional_fn(nid)
                except Exception as exc:
                    print(f"[mobile_sync_agent] provisional supersede failed for {nid}: {exc}")

    return (
        uploaded,
        u_failed + r_failed + p_failed + i_failed + e_failed,
        reconciled, conflicts, pulled, ingested, enriched,
    )


def _build_enrich_fn(cfg, vault_root: str) -> Callable[[Dict, str], Tuple[int, int]]:
    """Bind the real LLM classifier + vault vocab + live category enum + vector-store embed
    into an enrich_fn(vault_notes, vault_root) for run_once. Kept thin: all logic is in
    enrich_notes; this only wires the seams (notes-are-not-captures — never run_pipeline)."""
    root = Path(vault_root)
    scratchpad = getattr(cfg.vault, "scratchpad_folder", "_scratchpad")

    try:
        vocab = load_vocab(get_db_path(root))
    except Exception:
        vocab = {}   # derived cache; absent vocab just means no normalization this pass

    def classify(body: str):
        # Live category enum built from the vault's current folders every pass (hard rule).
        category_descriptions = build_category_descriptions(root, scratchpad)
        payload = EnrichedPayload(raw_input=body, input_type="note", enriched_text=body)
        out = run_llm_engine(payload, category_descriptions)
        return (out.key_signals or [], out.category)

    def embed(path: str, content: str):
        index_note(cfg.vault.root, Path(path), content, cfg.ollama.base_url, cfg.vector.embed_model)

    def enrich_fn(vault_notes: Dict, vr: str) -> Tuple[int, int]:
        return enrich_notes(vault_notes, vr, classify, vocab, embed=embed)

    return enrich_fn


def _build_reminders_fn(vault_root: str) -> Callable[[Dict], dict]:
    """Bind db_path into a reminders_fn(vault_notes) for run_once. Reconciles the pending
    reminders table from each note's remind_at frontmatter (files are the source of truth —
    DB-only, never writes a note .md; the server's due-checker thread delivers what lands here)."""
    db_path = get_db_path(Path(vault_root))

    def reminders_fn(vault_notes: Dict) -> dict:
        notes = [(n["path"], n["content"]) for n in vault_notes.values()]
        return sync_reminders_from_notes(db_path, notes)

    return reminders_fn


def _build_provisional_fn(vault_path: str) -> Callable[[str], None]:
    """Bind the LAN sync dir + provisional index db into a provisional_fn(note_id) for
    run_once (LAN accelerator, contract §11). Fires once per canonical note pulled this
    pass: drops the note's staged LAN-provisional overlay from BOTH the on-disk staging
    (T7/T8, provisional_store.supersede) and the search/RAG provisional index row (T13,
    index_writer.clear_provisional) together, so a Drive-canonical arrival always supersedes
    any earlier LAN-provisional version of the same note. Only constructed by the caller when
    `[lan] enabled` -- this module still only owns the per-note-id callback contract.
    # ponytail: supersede fires per pulled canonical note each pass; TTL sweep is the backstop.
    """
    import provisional_store as ps
    from index_writer import clear_provisional, init_db

    sync_dir = os.path.join(vault_path, ".sync")
    db = init_db(Path(vault_path))

    def provisional_fn(note_id: str) -> None:
        for op_id in ps.supersede(sync_dir, note_id):
            clear_provisional(db, op_id)

    return provisional_fn


def run_pass() -> dict:
    """One bidirectional sync pass, wired with real Drive auth/config/pipeline/enrichment, returning
    a summary dict for the in-server scheduler (sync_scheduler.py) AND the CLI. Raises on auth/Drive
    failure — the caller (scheduler) surfaces it as a 'paused/error' status; Drive stays the sole
    canonical authority, this only schedules the existing run_once()."""
    from functools import partial
    from drive_auth import get_drive_service
    from config import reload_config
    from main import run_pipeline

    cfg = reload_config()  # pick up GUI [sync]/[lan] toggles each pass
    vault_path = os.environ.get("OMNI_VAULT", str(cfg.vault.root))
    # B-4: default the sync-state sidecar under <vault>/.omni_capture/ — NOT a CWD-relative path.
    # A CWD-relative default lost every note's base_rev when run from another dir, turning the next
    # pass into blind uploads over advanced hub heads. The vault is a stable, single anchor.
    _default_state = Path(vault_path) / ".omni_capture" / "mobile_sync_state.json"
    _default_state.parent.mkdir(parents=True, exist_ok=True)
    state_path = os.environ.get("OMNI_SYNC_STATE", str(_default_state))
    drive = get_drive_service()

    bound_pipeline = partial(run_pipeline, vault_root=vault_path)
    enrich_fn = _build_enrich_fn(cfg, vault_path)
    reminders_fn = _build_reminders_fn(vault_path)
    lan_enabled = bool(cfg.lan.enabled)
    provisional_fn = _build_provisional_fn(vault_path) if lan_enabled else None
    mirror_captures = bool(cfg.sync.mirror_captures)

    uploaded, failed, reconciled, conflicts, pulled, ingested, enriched = run_once(
        vault_path, state_path, drive,
        vault_root=vault_path,
        scratchpad_folder=cfg.vault.scratchpad_folder,
        run_pipeline=bound_pipeline,
        enrich_fn=enrich_fn,
        reminders_fn=reminders_fn,
        provisional_fn=provisional_fn,
        mirror_captures=mirror_captures,
    )
    print(
        f"[mobile_sync_agent] synced: {uploaded} uploaded, {reconciled} reconciled, "
        f"{conflicts} conflicted-copies, {pulled} pulled, {ingested} captures ingested, "
        f"{enriched} enriched, {failed} failed"
    )

    if lan_enabled:
        # ponytail: refresh_outbound runs once per sync pass (after, so it serves the settled
        # post-pull/mirror vault state); tighten cadence if desktop->phone LAN latency matters.
        try:
            from lan_sync import refresh_outbound
            refresh_outbound(vault_path)
        except Exception as e:
            print(f"[mobile_sync_agent] lan refresh_outbound failed: {e}")
        try:
            import provisional_store as ps
            ps.sweep(os.path.join(vault_path, ".sync"), now_ts=time.time(), ttl_seconds=86400.0)
        except Exception as e:
            print(f"[mobile_sync_agent] lan provisional sweep failed: {e}")
        try:
            # Hub endpoint hint (contract §11.8-B) — piggyback the LAN host:port onto each sync
            # pass so the phone can refresh a paired desktop's drifting LAN IP from the hub.
            import lan_discovery
            device_id = lan_discovery.get_or_create_device_id(vault_path)
            ep_path = lan_discovery.write_lan_endpoint(vault_path, device_id, cfg.lan.host, cfg.lan.port)
            # Upload that single `.sync/` file to the hub so the phone (Option B) can read the paired
            # desktop's current LAN host:port. ONLY this one file uploads; the rest of `.sync/` stays
            # device-local. Skip when write returned None (no LAN host configured yet).
            if ep_path:
                upload_sync_file(
                    drive, ensure_hub_folder(drive), "lan_endpoint.json",
                    Path(ep_path).read_text(encoding="utf-8"),
                )
        except Exception as e:
            print(f"[mobile_sync_agent] lan endpoint hint write failed: {e}")

    return {
        "uploaded": uploaded, "pushed": uploaded, "reconciled": reconciled,
        "conflicts": conflicts, "pulled": pulled, "inbox_ingested": ingested,
        "enriched": enriched, "errors": failed,
    }


def main():
    """CLI single-shot pass (unchanged behaviour) — delegates to run_pass()."""
    run_pass()
    return


if __name__ == "__main__":
    main()
