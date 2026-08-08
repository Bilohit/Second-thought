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
from typing import Callable, Dict, Optional, Set, Tuple

from googleapiclient.http import MediaInMemoryUpload

from dedup import _vault_lock
from frontmatter import add_fields, read_all_fields, strip_frontmatter
from note_model import apply_project_request, parse_note, serialize_note
from body_tags import extract_body_tags, derive_body_attachments
from machine_tags import apply_trailing_tags_line, strip_trailing_tags_line
from reconcile import reconcile
from sync_ignore import filter_ignored_notes
import project_registry
from project_registry import Registry, resolve_project
from projects import LOOSE_DIR, is_valid_project_name, note_dir_for, parse_project_tag

# D4 note-enrichment seam collaborators (patched as module attributes in tests).
from llm_engine import run_llm_engine
from index_writer import get_db_path
from reminders import sync_reminders_from_notes
from vector_store import index_note
from models import EnrichedPayload

HUB_FOLDER_NAME = "SecondThoughtVault"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_ATTACHMENTS_FOLDER = "_attachments"   # vault/mirror/hub sibling of the notes tree (contract §2)
_RESERVED_FOLDERS = {"_trash", "_mobile_inbox", _ATTACHMENTS_FOLDER, "_templates", ".sync"}

# Stand-in body for "the common ancestor is UNKNOWN" (see reconcile_changes' adopt path).
# reconcile() derives body_changed_local/body_changed_remote by comparing against base.body, so a
# base body equal to NEITHER side is exactly a 2-way merge: identical bodies merge, divergent ones
# are a body-vs-body conflict → keep-both. It is never chosen as a merged body, so it never reaches
# disk or the hub.
# ponytail: a NUL-wrapped marker no editor can type stands in for a real "no base" sentinel type;
# swap for an Optional[Note] base parameter in reconcile() only if a body could ever hold these bytes.
_NO_BASE_BODY = "\x00<no common base — sidecar lost>\x00"


def _strip_bom(text: str) -> str:
    """SYNC-08: a UTF-8 BOM survives `read_text(encoding="utf-8")` as U+FEFF, and
    frontmatter._FM_RE is anchored `\\A---`, so a BOM'd note parsed to `{}` fields — no id —
    and read_vault_notes skipped it. Invisible to sync forever, one log line.

    Parse AROUND the BOM, never rewrite it away: the file is not re-encoded (that would churn
    bytes the user never typed) and `content`/`hash` stay byte-verbatim against disk, so no
    re-upload loop. The BOM sits ABOVE the frontmatter, so it is not body — which is why the
    body-sacred guard in _upload_note compares de-BOM'd text too.
    """
    return text[1:] if text.startswith("﻿") else text


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


def _conflicted_copy_name(cc, folder: Path) -> str:
    """Filename for a body-vs-body conflicted copy, in the folder it lands in.

    s114/x04: this used to be `<random-id>.md`. Both bodies survived a real conflict exactly as the
    lock promises -- but an operator auditing the vault saw an unreadable hex blob beside the note
    and concluded the peer's edit had been destroyed. A conflicted copy nobody can recognise on
    disk is a data-loss report waiting to happen.

    `cc.title` already carries the whole "(conflicted copy <device> <modified>)" suffix that
    reconcile.py built, so the name can never collide with the note it diverged from, and
    `_hub_filename` is the same sanitizer every other note goes through (it maps the timestamp's
    colons to `-`). The phone already names its own conflicted copies from the title, so this also
    makes the two peers agree. Local name and hub name are one string -- see SYNC-21 at the call site.
    """
    name = _hub_filename(getattr(cc, "title", "") or "", getattr(cc, "created", "") or "")
    if (folder / name).exists():
        # Two conflicted copies of one note in the same folder: same idiom _resolve_hub_names uses
        # for a title clash -- append the short id rather than silently overwrite a body.
        name = f"{name[:-3]} ({cc.id[-6:]}).md"
    return name


def _resolve_hub_names(notes: list) -> dict:
    """Pure: assign each note its hub/local filename, resolving same-folder clashes. The later-created
    note (tie -> larger id) is suffixed with its `created` date+time ` (YYYY-MM-DD HHMM)`; the winner
    keeps the clean name. If two losers share the title AND the same minute, the second also gets its
    short id appended (` (YYYY-MM-DD HHMM <last6 id>)`) so the LOCAL filename stays unique — a
    same-named local file would overwrite, losing a body. MUST match phone resolveHubNames() exactly."""
    groups: dict = {}
    for n in notes:
        name = _hub_filename(n["title"], n["created"])
        groups.setdefault((n.get("folder"), name), []).append(n)
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


def _reap_tmp_orphans(vault_path: str) -> int:
    """OF-19: _atomic_write_note writes a `<note>.md.tmp` sibling then os.replace()s it into place.
    A kill between the two leaves an orphan `.md.tmp` that read_vault_notes' `*.md` rglob never sees
    and nothing reaps, so it lingers on disk forever. The write+replace is synchronous within one
    call, so no live `.md.tmp` survives across passes — any found at pass start is dead. Only
    _atomic_write_note produces `<path-ending-.md>.tmp` (save_state uses `state.json.tmp`), so the
    glob is exact. Reap them so they don't accumulate. Returns how many were removed."""
    reaped = 0
    for tmp in Path(vault_path).rglob("*.md.tmp"):
        try:
            tmp.unlink()
            reaped += 1
        except OSError:
            pass  # locked/gone — harmless (invisible to the *.md scan); next pass retries
    return reaped


def _mint_capture_id() -> str:
    # ponytail: uuid4-hex id (opaque sync identity, only needs uniqueness), matching the same
    # ULID-substitute convention already used for conflicted-copy ids in reconcile_changes().
    # Swap for a real ULID minter if lexical time-ordering of capture ids ever matters.
    return uuid.uuid4().hex[:26]


def read_vault_notes(vault_path: str, mirror_captures: bool = False,
                     reg: Optional[Registry] = None) -> Dict[str, Dict]:
    """Scan the vault, return {frontmatter-id: note}.

    A file is a NOTE iff frontmatter `origin == "note"`; otherwise it is a desktop CAPTURE
    (origin absent or == "capture") — data-model-and-contracts.md §2 "Desktop captures (K-2)".

    - mirror_captures=False (default): capture files are skipped entirely (unchanged prior
      behaviour) — they never reach the hub while the user hasn't opted in.
    - mirror_captures=True: capture files ARE included. A capture that has no `id` yet gets one
      minted (ULID-style) and `id`/`origin: capture` written back as a FRONTMATTER-ONLY edit
      (body byte-identical — enforced below) so it gains a stable sync identity (closes B-15).

    Notes (origin: note) are always included when they have an id, regardless of the flag.

    Each record carries `folder` — the directory the note BELONGS in, `note_dir_for(
    resolve_project(body, reg))`: its project, or `_loose` (contract §1.3). It is derived from
    the body TAG, never from where the file currently sits, because the tag is the truth and the
    path is derived housekeeping the tidy pass converges. `reg` defaults to the vault's own
    `.projects.toml`; a missing/unreadable registry is an empty one, so every note reads loose —
    a degradation the contract names explicitly, never an error."""
    notes: Dict[str, Dict] = {}
    vault_dir = Path(vault_path)
    if not vault_dir.exists():
        return notes
    if reg is None:
        reg = project_registry.load(vault_dir)

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
        parsed = _strip_bom(content)   # SYNC-08: parse around a UTF-8 BOM; content stays verbatim
        fields = read_all_fields(parsed)
        is_capture = fields.get("origin") != "note"
        if is_capture and not mirror_captures:
            continue  # opt-in mirroring off (default) — captures stay desktop-local

        note_id = fields.get("id")
        if is_capture and mirror_captures and not note_id:
            new_id = _mint_capture_id()
            new_content = add_fields(parsed, {"id": new_id, "origin": "capture"})
            if strip_frontmatter(new_content) != strip_frontmatter(parsed):
                print(f"[mobile_sync_agent] mint-id would alter body, skip {md_file}")
                continue
            try:
                _atomic_write_note(str(md_file), new_content)   # atomic: never a torn note
            except Exception as e:
                print(f"[mobile_sync_agent] mint-id write failed {md_file}: {e}")
                continue
            # SYNC-08: this path already rewrites the file (to mint the id), so the BOM is
            # dropped here as part of that single atomic write — body bytes are asserted
            # identical above. Every other path leaves the BOM on disk untouched.
            content = parsed = new_content
            fields = read_all_fields(parsed)
            note_id = new_id

        if not note_id:
            print(f"[mobile_sync_agent] no id, skip {md_file}")
            continue
        body = strip_frontmatter(parsed)
        notes[note_id] = {
            "id": note_id,
            "path": str(md_file),
            "content": content,
            "body": body,
            "hash": _sha256(content),
            # v3.0 (§1.3): the note's directory is DERIVED from its `#project@` body tag, not read
            # off disk. Legacy `category:` frontmatter and the file's current parent are both
            # ignored — the tag is the only truth.
            "folder": note_dir_for(resolve_project(body, reg), reg),
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
                fields="nextPageToken, files(id, name, headRevisionId, appProperties, mimeType, md5Checksum, modifiedTime)",
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
    """Split the hub root's subfolders into (note_dirs{name:id}, reserved{name:id}).

    A note dir is a PROJECT folder or `_loose` (contract §2, §1.3) — both hold notes, so `_loose`
    is deliberately NOT in `_RESERVED_FOLDERS`. Project folders are derived, never authoritative:
    a folder exists because notes carry that tag and the tidy pass created it."""
    note_dirs: Dict[str, str] = {}
    reserved: Dict[str, str] = {}
    for f in _list_children(drive, hub_folder_id, mime_is_folder=True):
        target = reserved if f["name"] in _RESERVED_FOLDERS else note_dirs
        target[f["name"]] = f["id"]
    return note_dirs, reserved


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


def _sync_note_attachments(drive, hub_id: str, note_id: str, body: str, vault_root: str,
                           attach_root_cache: Dict[str, str]) -> Tuple[int, int, int]:
    """PKG-ATTACH legs 3+4 (spec §4.3): carry ONE note's attachment bytes both ways between
    `<vault>/_attachments/<note-id>/` and the hub's `_attachments/<note-id>/`. Returns
    (uploaded, downloaded, failed).

    An attachment is NOT a note op: no base_rev, no reconcile entry, no sync_state row, no
    conflict class. Identity is (note_id, filename) and PRESENCE IS THE ENTIRE STATE MODEL —
    if the file is on both sides there is nothing to do, and a failure needs no retry record
    because the next pass simply sees it missing again.

    The BODY is the driver, not the `attachments:` frontmatter cache (§4.2) — correct for a
    legacy note that has never been re-saved, and impossible to poison with a stale field.
    Upload is gated on refs (an orphan is never pushed); download is NOT (the peer's bytes come
    down even if our copy of the body is momentarily behind that pass's `attach` op).

    Never overwrites existing bytes on either side, never deletes.
    # ponytail: no orphan GC (a ref dropped from a body leaves the file behind — contract §1.2
    # defers the sweep); no `.transcript.txt` sidecar sync (nothing produces them yet, and the
    # sweep is body-ref-driven); same name + different bytes on the two sides keeps BOTH,
    # untouched — prefer the older createdTime only if that collision ever actually occurs.
    """
    refs = set(derive_body_attachments(body))
    local_dir = Path(vault_root) / _ATTACHMENTS_FOLDER / note_id
    try:
        local = {p.name for p in local_dir.iterdir() if p.is_file()}
    except OSError:
        local = set()   # no dir (the overwhelmingly common case) — nothing local
    if not refs and not local:
        return (0, 0, 0)   # ZERO Drive calls: the steady state must not cost a round trip

    root_id = attach_root_cache.get(_ATTACHMENTS_FOLDER)
    if root_id is None:
        root_id = _find_or_create_subfolder(drive, hub_id, _ATTACHMENTS_FOLDER)
        attach_root_cache[_ATTACHMENTS_FOLDER] = root_id
    sub_id = _find_or_create_subfolder(drive, root_id, note_id)
    remote = {f["name"]: f["id"]
              for f in _list_children(drive, sub_id, mime_is_folder=False)}   # ONE listing

    uploaded = downloaded = failed = 0

    for name in sorted((refs & local) - set(remote)):
        try:
            media = MediaInMemoryUpload((local_dir / name).read_bytes(),
                                        mimetype="application/octet-stream")
            drive.files().create(
                body={"name": name, "parents": [sub_id]}, media_body=media, fields="id"
            ).execute()
            uploaded += 1
        except Exception as exc:  # noqa: BLE001 - fail-soft: one file never fails the note
            print(f"[mobile_sync_agent] attachment upload failed {note_id}/{name}: {exc}")
            failed += 1

    for name in sorted(set(remote) - local):
        dest = local_dir / name
        tmp = Path(str(dest) + ".tmp")   # sibling: os.replace is only atomic within a filesystem
        try:
            local_dir.mkdir(parents=True, exist_ok=True)
            # Atomic, per _atomic_write_note's discipline (spec §5, non-negotiable): a truncated
            # file that "exists" would be indistinguishable from a complete one and NEVER retried,
            # because presence is the state. Write the temp, then rename.
            tmp.write_bytes(_download_bytes(drive, remote[name]))
            os.replace(tmp, dest)
            downloaded += 1
        except Exception as exc:  # noqa: BLE001 - fail-soft; next pass retries (presence is state)
            print(f"[mobile_sync_agent] attachment download failed {note_id}/{name}: {exc}")
            failed += 1
            try:
                tmp.unlink()
            except OSError:
                pass   # never left at the FINAL path, so a stray temp is cosmetic at worst

    return (uploaded, downloaded, failed)


def _delete_file(drive, file_id: str) -> None:
    drive.files().delete(fileId=file_id).execute()


def _move_file_to_folder(drive, file_id: str, dest_folder_id: str) -> None:
    """Re-parent a hub file into `dest_folder_id` (used to move a note into the hub `_trash/` on an
    outbound soft-delete, ISS-005 A follow-up). METADATA-ONLY: no media_body, so the file's bytes on
    Drive are never re-uploaded — body-sacred holds (a delete is a MOVE, never a rewrite). Its current
    parents are read first so removeParents severs every existing link (a Drive file can be multi-parented)."""
    meta = drive.files().get(fileId=file_id, fields="parents").execute()
    prev_parents = ",".join(meta.get("parents", []))
    body = {}
    kwargs = {"fileId": file_id, "addParents": dest_folder_id, "fields": "id, parents"}
    if prev_parents:
        kwargs["removeParents"] = prev_parents
    drive.files().update(body=body, **kwargs).execute()


# OF-16: 30-day trash purge. Retention window; keep in lockstep with trash.py `_PURGE_AFTER_SECONDS`
# and the phone's trash.ts `PURGE_WINDOW_MS`.
_PURGE_AFTER_SECONDS = 30 * 24 * 3600


def _parse_drive_time(rfc3339: str) -> float:
    """Drive modifiedTime (RFC3339, e.g. '2026-07-20T12:00:00.000Z') → epoch seconds."""
    from datetime import datetime
    return datetime.fromisoformat(rfc3339.replace("Z", "+00:00")).timestamp()


def purge_expired_hub_trash(
    drive, hub_folder_id: str, now_ts: Optional[float] = None,
    ttl_seconds: float = _PURGE_AFTER_SECONDS,
) -> int:
    """OF-16: permanently delete hub `_trash/` notes trashed longer than ttl_seconds ago.

    The desktop is the single Drive-side purge authority (note-features §6: purge runs only on the
    online device); each peer separately purges its own LOCAL trash mirror. Age = Drive modifiedTime
    (the move-to-`_trash/` stamp) — a coarse retention sweep, NOT a version/conflict decision, so
    modifiedTime is the correct clock here (the headRevisionId-never-mtime lock governs merge/version
    calls, which this is not). Restore always wins: a restored note has already left `_trash/`, so it
    is never seen here. Returns how many files were purged."""
    now_ts = time.time() if now_ts is None else now_ts
    _cats, reserved = list_hub_tree(drive, hub_folder_id)
    trash_id = reserved.get("_trash")
    if not trash_id:
        return 0
    purged = 0
    for f in _list_children(drive, trash_id, mime_is_folder=False):
        mtime = f.get("modifiedTime")
        if not mtime:
            continue  # no timestamp → never purge (safe default: keep)
        if now_ts - _parse_drive_time(mtime) >= ttl_seconds:
            _delete_file(drive, f["id"])
            purged += 1
    return purged


def get_hub_notes(drive, hub_folder_id: str) -> Dict[str, Dict]:
    """List every .md note across the hub's project/`_loose` subfolders (2-level walk, contract §2).

    Reserved folders (_trash/_mobile_inbox/_attachments/_templates/.sync) are skipped.
    Keyed by note id: appProperties.noteId when present, else the filename stem — this
    normalizes phone-origin `<id>.md` (no appProperties) and desktop-origin `<id>` to one
    key so reconcile can match them against the vault (which is keyed by frontmatter id).
    Each record carries its `folder` (parent folder name). headRevisionId is the only
    version token; no modifiedTime is ever read.
    """
    note_dirs, _reserved = list_hub_tree(drive, hub_folder_id)
    files: Dict[str, Dict] = {}
    for cat_name, cat_id in note_dirs.items():
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
            f["folder"] = cat_name
            # SYNC-22 (graduates the ponytail here — ceiling reached): this dict is flat across
            # every note folder, so two files keyed to the same id in different folders used
            # to silently last-wins, and the loser became invisible to reconcile. Real for files
            # with no appProperties.noteId, which fall back to the filename stem above: two
            # legacy/foreign notes sharing a title in different folders collide. First-wins +
            # a warning, matching the root scan's `setdefault` below.
            if key in files:
                print(f"[mobile_sync_agent] duplicate hub note id {key!r}: keeping "
                      f"{files[key].get('folder')}/{files[key]['name']}, skipping "
                      f"{cat_name}/{f['name']}")
                continue
            files[key] = f
    # B-5: also scan root-level .md notes. v3.0 never PUTS a note at the hub root (a loose note goes
    # to `_loose/`, §1.3), but legacy/foreign root files must still be seen, or a remote edit to one
    # is silently never pulled. folder=None marks "at the root"; setdefault so a real note folder
    # always wins a same-id root duplicate.
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
        f["folder"] = None
        files.setdefault(key, f)
    return files


def _resolve_dest_folder(drive, hub_folder_id: str, folder: Optional[str], cache: Dict[str, str]) -> str:
    """Hub folder id for a note (find-or-create, cached per run).

    `folder` is the note's resolved project directory — `note_dir_for(resolve_project(body, reg))`,
    which is never falsy. A falsy value (a hand-built record, a legacy row) is LOOSE, and a loose
    note goes to `_loose/`, NEVER the hub root: depth 1 is what keeps every note's
    `../_attachments/<id>/…` body ref valid across every move (contract §1.3, §2).
    """
    folder = folder or LOOSE_DIR
    if folder not in cache:
        cache[folder] = _find_or_create_subfolder(drive, hub_folder_id, folder)
    return cache[folder]


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
    # SYNC-08: de-BOM before the compare — the BOM sits ABOVE the frontmatter so it is not body,
    # and read_vault_notes now derives `body` from the de-BOM'd text. The bytes UPLOADED below are
    # still `content` verbatim, BOM included, so nothing on disk or on the hub is rewritten.
    if strip_frontmatter(_strip_bom(content)) != note["body"]:
        raise RuntimeError("body-sacred violation: body bytes changed before upload")

    name = hub_name or _hub_filename(note.get("title") or "", note.get("created") or "")
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown")
    metadata = {"name": name, "appProperties": {"noteId": note["id"]}}

    if existing and existing.get("drive_file_id"):
        # Update-in-place by file id: the bytes are written here and the PARENT is never touched,
        # because a re-parent is a separate metadata-only op (`_move_file_to_folder`) that must not
        # bump headRevisionId. Callers that see the note's project change re-parent right after
        # this returns — see mirror_to_hub's base_parent comparison.
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
    # SYNC-06: os.replace silently overwrites an existing destination. _resolve_hub_names only
    # dedups among the notes IN THIS PASS — a pre-existing on-disk file at that name (a capture,
    # an untracked note, a file the user created) is unchecked, and renaming onto it destroys a
    # whole note including its body. Refuse and keep the current name; the next pass retries.
    if Path(new_path).exists():
        print(f"[mobile_sync_agent] rename {note_id} -> {hub_name!r} skipped: destination exists")
        return local_path
    os.replace(local_path, new_path)
    print(f"[mobile_sync_agent] local rename {note_id}: {Path(local_path).name!r} -> {hub_name!r}")
    return new_path


def _maybe_refile_local(local_path: str, dest_folder: Optional[str], note_id: str,
                         vault_root: Optional[str] = None) -> str:
    """Keep the local mirror in the directory the note's project TAG implies.

    v3.0 (§1.3): `dest_folder` is `note_dir_for(resolve_project(body, reg))` — the note's project,
    or `_loose`. It is NOT the hub's parent folder: the tag is the truth and the path is derived
    housekeeping, so a body arriving from the hub with a different `#project@` tag re-paths the
    local file, while a hub folder that merely disagrees with the tag does not. **Desktop alone
    re-paths a file** — the phone never moves one — which is what makes this safe to do unilaterally
    and is why §1.2's divergent-move arm is unreachable.

    This MOVES a file; it never edits one byte of it, so "sync is pure transport" holds. Mirrors
    _maybe_rename_local: atomic os.replace BEFORE any new content is written, so the note is never
    bodyless mid-move nor duplicated under both folders.

    A falsy `dest_folder` is a defensive NO-OP (a caller that could not resolve one at all); the
    real loose case is the string `_loose`, which does move.

    A folder the user made BY HAND (nesting depth >= 2 below `vault_root`, e.g.
    `vault/Work/Clients/note.md`) is never refiled — no body/tag edit, ever, and this is the same
    rule applied to a move: leaving the file exactly where the user put it is smaller AND correct,
    where "fixing" the destination arithmetic would still yank it out to `vault/_loose/` and empty
    the folder they deliberately made. `vault_root` is optional — `reconcile_changes`/`run_once`
    thread it down (it is already computed there); omitted (e.g. an unrelated/older caller), this
    guard is a no-op and the old grandparent-assumption arithmetic below runs unguarded, exactly as
    before — so passing `vault_root` is what turns the guard on, never a change in shape.

    ponytail: derives the MOVE TARGET as the file's grandparent (vault/<project>/<name>), the
    depth-1 layout read_vault_notes and the pull path both maintain; correct at depth 0-1, which is
    the only range this function ever files INTO. Returns the (possibly new) path. A path not yet
    on disk (injected-write_file unit tests, or a not-yet-materialized note) is only RESOLVED — no
    folder created, no file moved — so the compute stays side-effect-free."""
    if not dest_folder:
        return local_path  # unresolvable — leave the file where it is (see docstring)
    p = Path(local_path)
    if vault_root is not None:
        try:
            depth = len(p.parent.relative_to(Path(vault_root)).parts)
        except ValueError:
            depth = None  # p isn't under vault_root at all — can't judge, fall through unguarded
        if depth is not None and depth >= 2:
            return local_path  # user hand-made folder (see docstring) — never written, never moved
    if p.parent.name == dest_folder:
        return local_path  # already in the directory its tag implies
    new_path = p.parent.parent / dest_folder / p.name
    if not p.exists():
        return str(new_path)  # nothing on disk to move (or a fake path) — resolve only, touch nothing
    if new_path.exists():
        # SYNC-06 sibling: os.replace silently overwrites — never move onto an existing file (it
        # would destroy a whole note). Keep the current folder; the next pass retries.
        print(f"[mobile_sync_agent] refile {note_id} -> {dest_folder!r} skipped: destination exists")
        return local_path
    new_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(local_path, str(new_path))   # atomic within the vault filesystem
    print(f"[mobile_sync_agent] local refile {note_id}: {p.parent.name!r} -> {dest_folder!r}")
    return str(new_path)


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
    note_dirs, _reserved = list_hub_tree(drive, hub_folder_id)

    entries = []  # (drive_file, folder_name_or_None)
    for cat_name, cat_id in note_dirs.items():
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
            continue  # a note-folder note wins over a same-id root duplicate (mirrors get_hub_notes)
        seen_ids.add(note_id)
        parsed.append({
            "file": f, "id": note_id, "folder": cat_name,
            "title": fields.get("title") or "", "created": fields.get("created") or "",
        })

    hub_names = _resolve_hub_names([
        {"id": p["id"], "title": p["title"], "created": p["created"], "folder": p["folder"]}
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
    reg: Optional[Registry] = None,
    vault_root: Optional[str] = None,
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
    `reg` is the project registry this pass resolved (run_once merges it first); omitted → empty,
    so every note reads loose, which is the contract's own degradation, never an error.

    PURE TRANSPORT (§1.3): the only bytes written here are bytes reconcile() produced from the two
    inputs verbatim. Nothing on this path recomputes a frontmatter cache or edits a body.
    """
    if reg is None:
        reg = project_registry.empty_registry()
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
    # Resolved once per folder (via (folder, name) grouping inside _resolve_hub_names) over every
    # local note — used below to rename/re-upload a note whose title changed. Based on the LOCAL
    # (pre-merge) title: the common case is a user retitling on this device; a title that changed
    # ONLY on the remote side during this same pass keeps its prior local name here (simplification —
    # the next pass's mirror/pull sees the merged title and converges it).
    _name_rows = [
        {"id": nid, "title": n.get("title", ""), "created": n.get("created", ""),
         "folder": n.get("folder")}
        for nid, n in vault_notes.items()
    ]
    hub_names = _resolve_hub_names(_name_rows)

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
                    # base_parent = the note's hub folder at last sync, recorded at every row
                    # rewrite. v3.0: it no longer ARBITRATES anything (the divergent-move arm is
                    # unreachable — only the desktop re-paths); it is the record of whether the
                    # hub already reflects the note's project (contract §1.2 as amended).
                    "base_parent": hub_file.get("folder"),
                }
                continue
            if not local_changed:
                # PULL: remote-only change. Verbatim propagation of the other device's edit —
                # `remote_text` is written byte-for-byte, never re-serialized (pure transport).
                # The incoming body may carry a different `#project@` tag, so re-path the local
                # mirror to the directory that tag implies BEFORE the write (moving a file is not
                # editing one). Desktop alone re-paths; the phone never moves a file.
                pull_path = _maybe_refile_local(
                    local["path"],
                    note_dir_for(resolve_project(strip_frontmatter(_strip_bom(remote_text)), reg), reg),
                    note_id,
                    vault_root=vault_root,
                )
                write_file(pull_path, remote_text)
                new_state[note_id] = {
                    "drive_file_id": file_id,
                    "base_rev": remote_rev,
                    "local_hash": _sha256(remote_text),
                    "base_parent": hub_file.get("folder"),   # see above
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
                try:
                    base = parse_note(_download_revision(drive, file_id, prior["base_rev"]))
                except Exception as rev_exc:
                    # SYNC-02: Drive prunes old revisions. This raise used to reach the blanket
                    # `except` below, which never writes new_state[note_id] — so base_rev stayed
                    # the dead revision, the next pass failed identically, and mirror_to_hub's
                    # advanced-head guard kept blocking the upload: a permanent, silent two-way
                    # stall. Fall through to the same no-common-base path `adopted` uses, which
                    # is conservative (divergent bodies become a conflicted copy, both intact).
                    print(f"[mobile_sync_agent] base revision {prior.get('base_rev')!r} "
                          f"unavailable for {note_id} ({rev_exc}); reconciling with no base")
                    base = replace(local_note, body=_NO_BASE_BODY)
            merged_result = reconcile(
                base, local_note, parse_note(remote_text), new_id()
            )
            # v3.1: `project:` is a DERIVED cache dropped on parse, so the registry MUST ride this
            # re-serialization or every reconciled note silently loses the line. This is the merge
            # result being materialized, not a transported file being edited — reconcile() still
            # guarantees the merged body is a verbatim copy of one input.
            merged_text = serialize_note(merged_result.merged, reg)
            hub_name = hub_names.get(note_id)
            # SYNC-20: `hub_names` above was resolved from the PRE-merge local title, so a title
            # that changed only on the remote side named the file from the stale title and only
            # self-healed a pass later. Re-resolve post-merge with the merged title substituted,
            # over the same row set so same-folder clash resolution still holds. _resolve_hub_names
            # is pure (no Drive calls) — the second resolve costs CPU only.
            merged_title = getattr(merged_result.merged, "title", "") or ""
            if merged_title != (local.get("title") or ""):
                hub_name = _resolve_hub_names([
                    dict(row, title=merged_title) if row["id"] == note_id else row
                    for row in _name_rows
                ]).get(note_id, hub_name)
            local_path = _maybe_rename_local(
                local["path"], hub_name, prior.get("hub_name"), note_id
            )
            # The MERGED body decides the directory (its `#project@` tag may have come from either
            # side), so re-path the local mirror before writing it.
            merged_folder = note_dir_for(resolve_project(merged_result.merged.body, reg), reg)
            local_path = _maybe_refile_local(local_path, merged_folder, note_id, vault_root=vault_root)
            write_file(local_path, merged_text)
            dest = _resolve_dest_folder(drive, hub_folder_id, merged_folder, folder_cache)
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
                # _upload_note updates in place (never re-parents), so the hub folder after a
                # merge is whatever it already was — mirror_to_hub's next pass reconciles it
                # against `merged_folder` if the merge moved the note's project.
                "base_parent": hub_file.get("folder"),
            }
            reconciled += 1

            if merged_result.conflicted_copy is not None:
                cc = merged_result.conflicted_copy
                cc_text = serialize_note(cc, reg)   # v3.1: the copy carries its own `project:` cache
                cc_name = _conflicted_copy_name(cc, Path(local_path).parent)
                cc_path = str(Path(local_path).with_name(cc_name))
                write_file(cc_path, cc_text)
                up_cc = _upload_note(
                    drive,
                    {"id": cc.id, "content": cc_text, "body": cc.body},
                    dest,
                    None,
                    hub_name=cc_name,
                )
                new_state[cc.id] = {
                    "drive_file_id": up_cc["id"],
                    "base_rev": up_cc.get("headRevisionId"),
                    "local_hash": _sha256(cc_text),
                    # SYNC-21: record the name we actually uploaded under (the hub_name passed
                    # above). Without it the next pass sees prev_hub_name=None, so
                    # _maybe_rename_local returns early and _upload_note never renames — the
                    # conflicted copy's local and hub names diverge permanently.
                    "hub_name": cc_name,
                    # The conflicted copy was just CREATED under `dest` = the merged note's folder.
                    "base_parent": merged_folder,
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

    v3.0: this is also where the HUB learns a note's project changed. `note["folder"]` is derived
    from the body tag; when it disagrees with the sidecar's `base_parent` (the hub folder at last
    sync) the file is re-parented metadata-only AFTER the byte upload — Drive does not bump
    headRevisionId on a metadata patch, so the base_rev just recorded stays valid. Desktop alone
    re-paths; the phone reads the tag and never needs the hub to be tidy.
    """
    uploaded = 0
    failed = 0
    new_state = dict(state)
    folder_cache: Dict[str, str] = {}
    # _resolve_hub_names groups by (folder, name) internally, so one pass over every note
    # being mirrored already scopes clash resolution per hub folder.
    hub_names = _resolve_hub_names([
        {"id": nid, "title": n.get("title", ""), "created": n.get("created", ""),
         "folder": n.get("folder")}
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
            folder = note.get("folder") or LOOSE_DIR
            dest = _resolve_dest_folder(drive, hub_folder_id, folder, folder_cache)
            hub_name = hub_names.get(note_id)
            prev_hub_name = prior.get("hub_name") if prior else None
            local_path = _maybe_rename_local(note["path"], hub_name, prev_hub_name, note_id)
            if local_path != note["path"]:
                note = dict(note, path=local_path)  # keep this pass's in-memory note consistent
            result = _upload_note(drive, note, dest, prior, hub_name=hub_name)
            # A CREATE already landed inside `dest`. An UPDATE never re-parents, so when the note's
            # project moved since the last sync, carry the hub file across now — metadata-only, so
            # the headRevisionId just recorded above is unaffected.
            if prior and prior.get("drive_file_id"):
                hub_folder = hub_file.get("folder") if hub_file else prior.get("base_parent")
                if hub_folder != folder:
                    _move_file_to_folder(drive, result["id"], dest)
                    print(f"[mobile_sync_agent] hub reparent {note_id}: "
                          f"{hub_folder!r} -> {folder!r}")
            new_state[note_id] = {
                "drive_file_id": result["id"],
                "base_rev": result.get("headRevisionId"),
                "local_hash": note["hash"],
                "hub_name": hub_name,
                # base_parent: the hub folder the file now sits in — `folder` either way, since a
                # CREATE lands there and an UPDATE was just re-parented there if it had drifted.
                "base_parent": folder,
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
    write_file: Optional[Callable[[str, str], None]] = None,
    download: Optional[Callable[[str], str]] = None,
    local_trashed_ids: Optional[Set[str]] = None,
    reg: Optional[Registry] = None,
) -> Tuple[int, int, Dict[str, Dict]]:
    """Pull hub notes the desktop has never seen (phone-created / first sync) into the vault.

    'New' = id in neither the local vault nor the state sidecar. Placement (v3.0, §1.3):
    `vault/<note_dir_for(resolve_project(body, reg))>/<hub-name>.md` — the note's project, or
    `_loose/`. Derived from the PULLED BODY's `#project@` tag, not from the hub parent folder and
    never from frontmatter: the tag is the truth, and a loose note lands at depth 1 in `_loose/`
    rather than the vault root so its `../_attachments/<id>/…` refs stay valid.
    <hub-name> mirrors the hub file's OWN resolved `name` (get_hub_notes already carries it,
    clash-unique on the hub) — this function never recomputes `_resolve_hub_names`, it just
    matches the local filename to the hub's. Falls back to `<id>.md` only if the hub record's
    name is missing/unsafe (never crash on an untrusted Drive listing).
    Bytes are written VERBATIM — pure transport, we never touch a pulled file's content.
    Returns (pulled, failed, new_state).
    """
    if reg is None:
        reg = project_registry.empty_registry()
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
            if local_trashed_ids and note_id in local_trashed_ids:
                # ISS-046: the note is soft-deleted locally (sitting in the vault's `_trash/`). Its hub
                # copy going live again — a peer restore, or a delete arriving out of order after the
                # desktop already dropped its state row on outbound soft-delete propagation — must NOT
                # resurrect it as a fresh ACTIVE copy alongside the trashed one (the observed
                # active-in-personal/ + trashed-in-_trash/ duplicate). Honor the local soft-delete: skip.
                # If the user wants it back they restore from `_trash/`. Non-destructive (trash copy kept).
                continue
            # v3.0 (§1.3): the note's directory comes from its own body tag, resolved against the
            # registry — its project, or `_loose`. The hub's parent folder and any legacy
            # `category:`/`project:` frontmatter are both ignored.
            sub = note_dir_for(resolve_project(strip_frontmatter(_strip_bom(content)), reg), reg)
            # `note_id` is untrusted hub input and becomes a path component (B-12 class); `sub` is
            # ours by construction but is asserted with it rather than trusted silently.
            _safe_path_component(note_id)
            _safe_path_component(sub)
            hub_name = hub_file.get("name")
            try:
                if hub_name:
                    _safe_path_component(hub_name)
            except ValueError:
                hub_name = None
            local_name = hub_name or f"{note_id}.md"
            dest_path = Path(vault_root) / sub / local_name
            # SYNC-01: the skip guard at the top of this loop is keyed by hub ID, not by
            # filesystem path, and _atomic_write_note does an unconditional os.replace --
            # so a hub note whose local name collided with an UNRELATED local file
            # silently destroyed that file's content. Disambiguate rather than skip:
            # skipping would strand this note forever, since it never enters `state` and
            # so the id-level guard above would never start covering it.
            if dest_path.exists():
                dest_path = dest_path.with_name(f"{dest_path.stem}.{note_id}{dest_path.suffix}")
                if dest_path.exists():
                    raise ValueError(
                        f"pull target still occupied after disambiguation: {dest_path.name}"
                    )
            dest = str(dest_path)
            write_file(dest, content)
            new_state[note_id] = {
                "drive_file_id": hub_file["id"],
                "base_rev": hub_file.get("headRevisionId"),
                "local_hash": _sha256(content),
                "hub_name": hub_name,
                "base_parent": hub_file.get("folder"),   # the hub folder at this sync
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
    def _pipeline_wrote(result) -> bool:
        """SYNC-26: the hub file is deleted right after run_pipeline, irreversibly. The return
        value used to be discarded, so a pipeline that produced no vault file still lost the
        capture. Every non-raising path of main.run_pipeline sets `_written_to` to a real path
        (vision-fail and LLM-fail both route to the scratchpad), so this only fires on dry_run
        or an injected seam — cheap insurance on an irreversible delete.

        An EMPTY or non-dict return (None, `{}`, a test double) carries no information about
        where the capture went, so it is treated as UNKNOWN and allowed through — the pipeline
        is an injected seam and failing those closed would strand every capture in the inbox
        forever. Only a POPULATED result that reports no `_written_to` is a real "nothing was
        written", which is exactly the dry_run / injected-seam case this guards.
        """
        return not isinstance(result, dict) or not result or bool(result.get("_written_to"))

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
                # SYNC-09: `sibling_name` comes out of the stub BODY -- untrusted hub
                # content -- and is used below as a path component under stage_dir.
                # Worse than temp pollution: the staged file is then read back by
                # run_pipeline(audio=/image=), making an unguarded name a
                # write-then-read-back gadget. Same guard the block above already
                # applies to note_id / the project dir / hub_name. ValueError -> failed++.
                sibling_name = _safe_path_component(m.group(1))
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
                    result = run_pipeline(audio=str(staged))
                elif ext in _IMAGE_EXTS:
                    result = run_pipeline(image=str(staged))
                else:
                    # unknown binary kind — leave it, flag once, don't fake-ingest
                    print(f"[mobile_sync_agent] intake: unknown ext {ext!r} for {sibling_name}, skip")
                    skipped += 1
                    continue
                if not _pipeline_wrote(result):
                    failed += 1
                    continue
                delete_file(f["id"])
                delete_file(sibling["id"])
                ingested += 1
            else:
                result = run_pipeline(text=body)   # text/URL capture; the router shape-detects URLs
                if not _pipeline_wrote(result):
                    failed += 1
                    continue
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
    classify: Callable[[str], Optional[str]],
    embed: Optional[Callable[[str, str], None]] = None,
    reg: Optional[Registry] = None,
) -> Tuple[int, int]:
    """Note-only enrichment (contract §7). For every origin:note, enriched:false note the desktop
    ORIGINATED (provenance gate, §2.2), assign a PROJECT via `classify`, embed via `embed`, and
    mark enriched:true / enrich_source:desktop-llm.

    v3.0 narrows enrichment to exactly one job. `classify(user_body)` returns the name of an
    EXISTING registry project, or None. It is written as a `#project@<name>` token on the machine's
    single trailing `tags:` body line (§3, the one sanctioned body write) and **nothing else is
    written there** — the `key_signals`-derived arbitrary tag generation is deleted, so this pass
    never invents descriptive vocabulary. A note whose USER body already carries a `#project@` tag
    is left alone: the user's tag is the truth, and the machine never overrides it.

    K-1 and the v2.3 machine refile are RETIRED (§1.2 as amended): enrichment does not move a file
    and does not stamp `modified`/`device`. The tag it writes is the move — the tidy pass
    (`project_tidy.py`) and the next mirror converge the local path and the hub parent to it.

    Body is sacred: everything ABOVE the trailing tags line is asserted byte-identical before every
    write. NEVER touches run_pipeline (notes-are-not-captures lock). Fail-soft per note: a
    classify/write error leaves the note enriched:false for the next pass. `vault_notes` is mutated
    in place so a later mirror in the same run_once sees the new content.
    Returns (enriched_count, failed)."""
    if reg is None:
        reg = project_registry.load(vault_root)

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
        # Provenance (ISS-051 §2.1 backfill + §2.2 gate): the desktop authoritative pass runs ONLY on
        # content it originated. A legacy note with no origin_device is phone-origin iff it carries a
        # phone authorship marker (phone-heuristic enrichment); otherwise it is a desktop-vault note.
        effective_origin = note.origin_device or (
            "phone" if note.enrich_source == "phone-heuristic" else "desktop"
        )
        if effective_origin not in ("desktop", "shared"):
            continue  # never touch a phone-origin note — no tags, no project, no body, nothing

        try:
            # Body-sacred baseline: the user body is everything ABOVE the machine trailing tags line
            # (§3). classify sees the user body, never the machine's own prior tags line.
            user_body = strip_trailing_tags_line(note.body)
            if user_body.strip():
                # The user's own `#project@` tag wins outright — never reclassified, never
                # overwritten (contract §1.3: the tag IS the truth).
                if parse_project_tag(user_body) is None:
                    picked = classify(user_body)
                    # Untrusted LLM output: only a registry-eligible name that the registry
                    # actually holds may be written. Anything else leaves the note loose, which
                    # is a normal outcome, not a failure (§7 "degrades to loose, never a guess").
                    if (picked and is_valid_project_name(picked)
                            and picked in (reg.get("projects") or {})):
                        # ISS-051 §3: the machine's one sanctioned body write, the single trailing
                        # `tags:` line, idempotently replaced.
                        # ponytail: the line is REPLACED, not merged — §7 says auto-enrichment
                        # writes `#project@` and no other tag, so there is nothing of the machine's
                        # to preserve. Merge instead only if a second machine-owned token appears.
                        note.body = apply_trailing_tags_line(note.body, [f"project@{picked}"])
                # `tags:` is a derived cache recomputed from the WHOLE body (§1.2); structural tags
                # (`#project@`, `sys/*`) are excluded from it by body_tags (§1.3).
                note.tags = extract_body_tags(note.body)
                # v2.2 (§4.2): `attachments:` is a DERIVED cache recomputed from the body on save,
                # exactly like `tags:` above — never authored independently. Frontmatter-only; the
                # body-sacred assertion below covers this write too.
                note.attachments = derive_body_attachments(note.body)
                note.enrich_source = "desktop-llm"
            # else: empty body → nothing to classify. Fall through to mark enriched WITHOUT an LLM
            # call so this note stops re-hitting Ollama every pass — an empty content block makes
            # llama3.2 synthesize every required schema field from nothing and ramble past
            # request_timeout_s (the recurring "enrich failed … Request timed out" poison note).
            # ponytail: if an empty note later gains a body, whatever flips enriched:false on edit
            # re-triggers a real pass; marking it enriched now only skips the pointless empty enrich.
            # This device authored the enrichment, so stamp/upgrade origin_device (§2.1: the first
            # device to re-save a `shared` note stamps its own platform; a backfilled desktop note
            # persists `desktop`).
            note.origin_device = "desktop"
            note.enriched = True
            # v3.1: this is an explicit local ENRICHMENT save — the one kind of pass allowed to
            # write frontmatter — so the derived `project:` cache is recomputed here from the body.
            new_content = serialize_note(note, reg)
            # BODY SACRED (amended §3): everything ABOVE the machine trailing tags line is byte-identical.
            if strip_trailing_tags_line(strip_frontmatter(new_content)) != user_body:
                raise RuntimeError(f"enrich would alter user body of {note_id}")
            _atomic_write_note(entry["path"], new_content)   # atomic: never a torn note
        except Exception as e:
            print(f"[mobile_sync_agent] enrich failed {note_id}: {e}")
            failed += 1
            continue

        # File is written + enriched. Update the in-memory dict for the same-pass mirror —
        # body included: enrichment legitimately appends the trailing tags line, and mirror's
        # body-sacred upload check compares content against entry["body"], so a stale body
        # would fail every same-pass upload of a just-enriched note.
        entry["content"] = new_content
        entry["body"] = strip_frontmatter(new_content)
        entry["hash"] = _sha256(new_content)
        # The tag it may have just written re-derives the note's directory; mirror_to_hub reads
        # this to place/re-parent the hub file in the same pass. The FILE is moved by the tidy
        # pass, not here — enrichment never re-paths (K-1 retired, §1.2).
        entry["folder"] = note_dir_for(resolve_project(entry["body"], reg), reg)
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


def apply_project_requests(
    vault_notes: Dict,
    vault_root: str,
    reg: Optional[Registry] = None,
) -> Tuple[int, int]:
    """Apply every pending project request the DESKTOP is allowed to act on (design §4).

    The phone cannot write a `#project@` tag into a note the desktop authored, so it leaves a based
    request in machine-owned frontmatter instead; this pass is the desktop half of the applier.
    `note_model.apply_project_request` owns the whole decision (provenance gate, staleness discard,
    name validity, the one sanctioned body write); this function only does the I/O around it.

    A note it changes is written back atomically and its `folder` re-derived from the new tag, so
    `mirror_to_hub` re-parents the hub file in this same pass. The LOCAL file is moved by the tidy
    pass (`project_tidy.py`), exactly as for enrichment — sync never re-paths (§1.2, K-1 retired),
    and re-pathing at all is the desktop's job and only the desktop's.

    Fail-soft per note: a parse/write error leaves the request pending for the next pass.
    Returns (applied_count, failed)."""
    if reg is None:
        reg = project_registry.load(vault_root)

    applied = 0
    failed = 0
    for note_id, entry in vault_notes.items():
        try:
            note = parse_note(entry["content"])
        except Exception as e:  # noqa: BLE001 - one unparseable note never costs the rest
            print(f"[mobile_sync_agent] project request parse skip {entry.get('path')}: {e}")
            continue
        if note.origin != "note":
            continue

        try:
            user_body = strip_trailing_tags_line(note.body)
            if apply_project_request(note) is None:
                continue
            # The body may have gained or lost the machine trailing line, so the derived caches
            # are recomputed from it — same contract as enrichment (§1.2/§1.3).
            note.tags = extract_body_tags(note.body)
            note.attachments = derive_body_attachments(note.body)
            new_content = serialize_note(note, reg)
            # BODY SACRED (amended §3): everything ABOVE the machine trailing tags line is
            # byte-identical. Belt-and-braces over apply_project_request's own assertion, which
            # cannot see the frontmatter round-trip this serialize adds.
            if strip_trailing_tags_line(strip_frontmatter(new_content)) != user_body:
                raise RuntimeError(f"project request would alter user body of {note_id}")
            _atomic_write_note(entry["path"], new_content)
        except Exception as e:  # noqa: BLE001 - fail-soft, retried next pass
            print(f"[mobile_sync_agent] project request failed {note_id}: {e}")
            failed += 1
            continue

        entry["content"] = new_content
        entry["body"] = strip_frontmatter(new_content)
        entry["hash"] = _sha256(new_content)
        entry["folder"] = note_dir_for(resolve_project(entry["body"], reg), reg)
        applied += 1
    return applied, failed


# Sync-state keys for the registry (contract §13.2). `base_projects` is the registry as of our last
# sync — the merge BASE, exactly parallel to `base_note`/`base_parent`. Neither key is a note record:
# every state iteration in this file and delete_detect.py guards on `drive_file_id`, which they lack.
BASE_PROJECTS_KEY = "base_projects"
PROJECTS_REV_KEY = "projects_rev"


def sync_project_registry(drive, hub_folder_id: str, vault_root: str,
                          state: Dict[str, Dict]) -> Tuple[Registry, Dict[str, Dict]]:
    """Three-way merge `.projects.toml` between vault and hub (contract §13.2). Returns
    (merged_registry, new_state).

    The version token is **`headRevisionId`, never mtime** (§13): `state["projects_rev"]` is the head
    we last synced at, and a hub head still equal to it means the remote content is exactly
    `base_projects` — so the download is skipped entirely.

    NEVER last-writer-wins: two devices editing DIFFERENT projects in one batch window write this
    same file, and a whole-file rule silently discards one of them. `project_registry.merge` is
    per-entry.

    ATOMICITY: the `load -> merge -> save` cycle is held under ONE lock for its ENTIRE duration —
    `<vault_root>/.projects.lock`, via the `dedup._vault_lock(lock_path)` FileLock factory (there is
    no single shared vault lock in this codebase; every RMW cycle keys its own path). The Drive
    download and upload sit OUTSIDE it: network latency must never be held across a file lock, and
    neither call touches the local file.
    """
    new_state = dict(state)
    vault_root = Path(vault_root)

    remote_file = next(
        (f for f in _list_children(drive, hub_folder_id, mime_is_folder=False)
         if f["name"] == project_registry.REGISTRY_FILENAME),
        None,
    )
    if remote_file is None:
        # The hub has never held a registry, so nothing was ever synced from it. Treating our
        # recorded base as real here would read every base entry as "deleted remotely".
        base = remote = project_registry.empty_registry()
        remote_rev = None
    else:
        base = new_state.get(BASE_PROJECTS_KEY) or project_registry.empty_registry()
        remote_rev = remote_file.get("headRevisionId")
        if remote_rev is not None and remote_rev == new_state.get(PROJECTS_REV_KEY):
            remote = base          # hub head unmoved since our last sync — zero download
        else:
            remote = project_registry.parse(
                _download_content(drive, remote_file["id"], remote_file.get("md5Checksum"))
            )

    with _vault_lock(project_registry._registry_lock_path(vault_root)):
        local = project_registry.load(vault_root)
        merged = project_registry.merge(base, local, remote)
        if merged != local:
            project_registry.save(vault_root, merged)

    if merged != remote:
        media = MediaInMemoryUpload(
            project_registry.dumps(merged).encode("utf-8"), mimetype="text/plain")
        if remote_file is None:
            up = drive.files().create(
                body={"name": project_registry.REGISTRY_FILENAME, "parents": [hub_folder_id]},
                media_body=media, fields="id, headRevisionId",
            ).execute()
        else:
            up = drive.files().update(
                fileId=remote_file["id"], media_body=media, fields="id, headRevisionId",
            ).execute()
        rev = up.get("headRevisionId")
        # The sidecar is JSON: only a real string token may be persisted. Drive always returns one
        # for a content write; anything else records "no observed head" rather than poisoning the
        # whole state file (save_state would raise on a non-serializable value and lose every row).
        remote_rev = rev if isinstance(rev, str) else None

    new_state[BASE_PROJECTS_KEY] = merged
    new_state[PROJECTS_REV_KEY] = remote_rev
    return merged, new_state


def run_once(
    vault_path: str,
    state_path: str,
    drive,
    vault_root: Optional[str] = None,
    run_pipeline: Optional[Callable[..., Dict]] = None,
    enrich_fn: Optional[Callable[..., Tuple[int, int]]] = None,
    reminders_fn: Optional[Callable[[Dict], dict]] = None,
    provisional_fn: Optional[Callable[[str], None]] = None,
    mirror_captures: bool = False,
) -> Tuple[int, int, int, int, int, int, int]:
    """One full bidirectional pass:
      0. three-way merge `.projects.toml` with the hub, so every step below resolves projects
         against ONE settled registry,
      1. reconcile notes changed on both sides (three-way merge / conflicted copy),
      2. pull hub-only notes the desktop has never seen into the vault,
      3. drain _mobile_inbox/ captures through run_pipeline,
      4. enrich origin:note, enriched:false notes (frontmatter-only; never run_pipeline),
      4b. apply the peer's based project requests on notes THIS device authored (design §4),
      5. mirror local-only new/changed notes up to the hub.

    Reconcile + pull run before mirror so merged/pulled bodies are on disk and re-read;
    intake writes captures into the vault via the pipeline. Enrich runs after the re-read
    and before mirror so enriched frontmatter uploads the same pass. Returns
    (uploaded, failed, reconciled, conflicts, pulled, ingested, enriched)."""
    hub_id = ensure_hub_folder(drive)
    vault_root = vault_root or vault_path
    state = load_state(state_path)
    _reap_tmp_orphans(vault_path)  # OF-19: clear any crash-orphaned <note>.md.tmp from a prior pass
    # OF-16: 30-day trash purge — best-effort, must never abort a sync pass. Local vault _trash/ plus
    # the hub _trash/ (the desktop is the Drive-side purge authority; peers purge their own local copy).
    try:
        from trash import purge_expired
        purge_expired(Path(vault_path))
        purge_expired_hub_trash(drive, hub_id)
    except Exception as e:  # noqa: BLE001 - a purge failure must not break sync
        print(f"[mobile_sync_agent] trash purge failed: {e}")

    # Task 3.1: one-time hub-filename migration, guarded on state["hub_names_migrated"] so it is
    # zero-cost on every pass after the first. Runs BEFORE list_hub_tree/get_hub_notes below so
    # the rest of this pass sees the POST-migration hub names, instead of racing a stale
    # pre-rename snapshot.
    first_migration_pass = not state.get("hub_names_migrated")
    if first_migration_pass:
        state = migrate_hub_filenames(drive, hub_id, state)

    # Contract §13.2: settle the registry BEFORE anything reads a note, so every `#project@` tag in
    # this pass resolves against one merged registry instead of a half-synced one. Fail-soft — a
    # Drive/registry failure leaves the local `.projects.toml` exactly as it was (nothing is saved
    # unless the merge succeeded), and the pass continues against that local copy.
    try:
        reg, state = sync_project_registry(drive, hub_id, vault_root, state)
    except Exception as e:  # noqa: BLE001 - a registry failure must never abort a sync pass
        print(f"[mobile_sync_agent] project registry sync failed: {e}")
        reg = project_registry.load(vault_root)

    _note_dirs, reserved = list_hub_tree(drive, hub_id)
    vault_notes = read_vault_notes(vault_path, mirror_captures, reg)
    hub_files = get_hub_notes(drive, hub_id)

    # ISS-005 B/C: delete detection, best-effort and NON-DESTRUCTIVE by default (a failure must never
    # abort a sync pass). Kept OUT of reconcile_changes/mirror_to_hub so those tested loops are
    # untouched. Two signals: an out-of-band FS delete of a once-synced note (absent from the vault
    # AND local _trash/) propagates as a real hub delete, gated by a two-pass confirm; a peer's delete
    # of a note the desktop still holds raises a durable, non-destructive DELETE-PROMPT (kept in the
    # sibling delete_prompts.json). See delete_detect.process_deletes. Skips the whole pass cheaply
    # (no Drive calls) when there are no candidates and nothing is held.
    try:
        from delete_detect import process_deletes
        _now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state, _fs_del, _prompts = process_deletes(
            vault_path, state_path, state, vault_notes, hub_files,
            reserved.get("_trash"), _now_iso,
            list_children=lambda fid: _list_children(drive, fid, mime_is_folder=False),
            delete_file=lambda fid: _delete_file(drive, fid),
            # ISS-005 A follow-up: OUTBOUND soft-delete propagation (desktop local _trash/ → hub _trash/).
            # ensure_hub_trash find-or-creates the hub `_trash/` (the desktop may be the first to soft-
            # delete); move_file re-parents metadata-only (body-sacred). Both are only INVOKED when a
            # note actually sits in local _trash/ with a live hub copy — a clean pass calls neither.
            move_file=lambda fid, dest: _move_file_to_folder(drive, fid, dest),
            ensure_hub_trash=lambda: _find_or_create_subfolder(drive, hub_id, "_trash"),
            vault_root=vault_root,
        )
        if _fs_del or _prompts:
            print(f"[mobile_sync_agent] delete-detect: {_fs_del} permanent (out-of-band FS) "
                  f"delete(s), {_prompts} inbound delete-prompt(s) held")
    except Exception as e:  # noqa: BLE001 — delete detection must never break a sync pass
        print(f"[mobile_sync_agent] delete detection failed: {e}")

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
            # SYNC-23: save_state is OUTSIDE this loop, so an unguarded raise here left N notes
            # renamed with `hub_names_migrated` never persisted — the one-time migration then
            # re-ran next pass against a half-renamed vault. Log and continue so the loop always
            # reaches save_state below. Also refuses to clobber an existing file (SYNC-06 class).
            if Path(new_path).exists():
                print(f"[mobile_sync_agent] migrate local rename {note_id} skipped: "
                      f"{resolved!r} already exists")
                continue
            try:
                os.replace(local["path"], new_path)
            except OSError as exc:
                print(f"[mobile_sync_agent] migrate local rename {note_id} failed: {exc}")
                continue
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
        filter_ignored_notes(vault_notes, Path(vault_root)), hub_files, state, drive, hub_id,
        reg=reg, vault_root=vault_root,
    )
    # ISS-046: a note sitting in the local `_trash/` must never be re-pulled as a fresh active copy
    # (peer restore / out-of-order delete after the state row was dropped) — that leaves a duplicate
    # active+trashed pair. Scan the local `_trash/` ids once and let pull skip them.
    from delete_detect import local_trashed_ids as _local_trashed_ids
    pulled, p_failed, state = pull_new_hub_notes(
        vault_notes, hub_files, state, drive, vault_root,
        local_trashed_ids=_local_trashed_ids(vault_path), reg=reg,
    )

    ingested = i_failed = 0
    inbox_id = reserved.get("_mobile_inbox")
    if inbox_id and run_pipeline is not None:
        ingested, _skipped, i_failed = intake_mobile_inbox(drive, inbox_id, run_pipeline)

    # Re-read: reconcile/pull wrote merged/pulled bodies; the pipeline wrote captures.
    vault_notes = read_vault_notes(vault_path, mirror_captures, reg)

    # Enrich AFTER the re-read (so pulled/ingested notes are visible) and BEFORE mirror
    # (so enriched frontmatter is in vault_notes when mirror computes uploads). enrich_notes
    # mutates vault_notes in place. Notes are not captures — this never touches run_pipeline.
    # v3.0: enrichment assigns a PROJECT by writing a `#project@` tag; it never moves a file
    # (K-1 and the v2.3 machine-refile callback are retired, §1.2). The tag re-derives each note's
    # `folder`, which mirror_to_hub below reads to place — and if needed re-parent — the hub file.
    # The LOCAL file is moved by the tidy pass, not by sync.
    enriched = e_failed = 0
    if enrich_fn is not None:
        enriched, e_failed = enrich_fn(vault_notes, vault_root)

    # Design §4: apply the peer's based project requests against notes THIS device authored.
    # AFTER enrich so an explicit request always wins over the classifier's guess for the same
    # note in the same pass, and BEFORE mirror so the new tag, content and hub parent all ship
    # together. Like enrichment it mutates vault_notes in place and never moves the local file —
    # the tidy pass does that. Fail-soft: a request failure must never abort the sync pass.
    # ponytail: not folded into run_once's return tuple, which is 7-wide and pinned by tests;
    # the count is logged, the same posture as reminders_fn below.
    try:
        pr_applied, pr_failed = apply_project_requests(vault_notes, vault_root, reg=reg)
        if pr_applied or pr_failed:
            print(f"[mobile_sync_agent] project requests: {pr_applied} applied, "
                  f"{pr_failed} failed")
    except Exception as exc:  # noqa: BLE001 - a request failure must never abort a sync pass
        print(f"[mobile_sync_agent] project request pass failed: {exc}")

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

    # 6. Attachment bytes, both directions (PKG-ATTACH §4.3 legs 3+4). Runs AFTER mirror so it
    # sees this pass's merged/pulled bodies. Not a note op — no state row, no return-tuple entry
    # (the tuple is 7-wide and pinned by tests); fail-soft and logged, the same posture as
    # reminders_fn above. F-5: filtered exactly like mirror_to_hub, so a sync-ignored note never
    # ships its bytes either.
    try:
        attach_root_cache: Dict[str, str] = {}
        a_up = a_down = a_failed = 0
        for _nid, _entry in filter_ignored_notes(vault_notes, Path(vault_root)).items():
            try:
                u, d, f = _sync_note_attachments(
                    drive, hub_id, _nid, _entry.get("body", ""), vault_root, attach_root_cache
                )
            except Exception as exc:  # noqa: BLE001
                # Per-NOTE containment: a Drive-level failure (folder create, children list) on one
                # note must not cost every note after it in this pass. The phase guard below still
                # catches anything outside the loop. Presence is the state, so a skipped note simply
                # retries next pass with no bookkeeping.
                print(f"[mobile_sync_agent] attachment sync failed for {_nid}: {exc}")
                a_failed += 1
                continue
            a_up += u
            a_down += d
            a_failed += f
        if a_up or a_down or a_failed:
            print(f"[mobile_sync_agent] attachments: {a_up} uploaded, {a_down} downloaded, "
                  f"{a_failed} failed")
    except Exception as exc:  # noqa: BLE001 - an attachment failure must never abort a pass
        print(f"[mobile_sync_agent] attachment sync failed: {exc}")

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


def _build_enrich_fn(cfg, vault_root: str) -> Callable[..., Tuple[int, int]]:
    """Bind the real LLM project classifier + vector-store embed into an
    enrich_fn(vault_notes, vault_root) for run_once. Kept thin: all logic is in enrich_notes;
    this only wires the seams (notes-are-not-captures — never run_pipeline)."""
    root = Path(vault_root)

    def classify(body: str) -> Optional[str]:
        # The registry is re-read every call, so a project created mid-session is pickable at once
        # (contract §13: the engine may only choose an EXISTING project, never invent one).
        payload = EnrichedPayload(raw_input=body, input_type="note", enriched_text=body)
        out = run_llm_engine(payload, project_registry.load(root))
        # `out.project` is a dynamic-Enum member when the registry has projects and a plain
        # str/None otherwise; `str()` yields the bare name for both (models._ProjectBase.__str__).
        return str(out.project) if out.project else None

    def embed(path: str, content: str):
        index_note(cfg.vault.root, Path(path), content, cfg.ollama.base_url, cfg.vector.embed_model)

    def enrich_fn(vault_notes: Dict, vr: str) -> Tuple[int, int]:
        return enrich_notes(vault_notes, vr, classify, embed=embed)

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

    # SYNC-12: refuse the whole pass when the local-only ignore set does not parse. A corrupt
    # sidecar previously degraded to the empty set, which made filter_ignored_notes a
    # pass-through and uploaded every note the user marked private to Drive — silent and
    # irreversible. Raising here is recorded by sync_scheduler as an `ok:false` row.
    from sync_ignore import assert_ignore_set_readable
    assert_ignore_set_readable(Path(vault_path))

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
            # OF-7: TTL = N=3 sync intervals (contract §11.6), derived from the configured interval
            # so both peers agree and it self-scales — not a hardcoded 24h. interval_minutes==0 is the
            # never-auto-sync sentinel; fall back to the 60-min default basis so the TTL stays sane.
            interval_min = cfg.sync.interval_minutes or 60
            ps.sweep(
                os.path.join(vault_path, ".sync"),
                now_ts=time.time(),
                ttl_seconds=float(3 * interval_min * 60),
            )
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

    try:
        # FR-34 (s146 ruling; contract §2.1): the hand-made-folder census. Deliberately
        # OUTSIDE the `if lan_enabled:` block above -- Drive is the reachability plane this
        # rides (always-on), not the LAN accelerator. Read-only: writes nothing into any
        # listed folder, only the one census file. `write_census` skips the write when the
        # folder list is unchanged, so `changed` gates the upload too -- a steady-state vault
        # costs zero Drive calls here. Same failure posture as the lan-endpoint hint above:
        # never raise into the sync loop, a failed write/upload is a logged no-op.
        import hand_made_folders
        import lan_discovery
        device_id = lan_discovery.get_or_create_device_id(vault_path)
        census_path, changed = hand_made_folders.write_census(vault_path, device_id)
        if changed:
            upload_sync_file(
                drive, ensure_hub_folder(drive), hand_made_folders.CENSUS_FILENAME,
                Path(census_path).read_text(encoding="utf-8"),
            )
    except Exception as e:
        print(f"[mobile_sync_agent] hand-made-folders census failed: {e}")

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
