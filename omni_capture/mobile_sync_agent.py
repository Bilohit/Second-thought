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
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from googleapiclient.http import MediaInMemoryUpload

from frontmatter import read_all_fields, strip_frontmatter
from note_model import parse_note, serialize_note
from reconcile import reconcile

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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_vault_notes(vault_path: str) -> Dict[str, Dict]:
    """Scan the vault, return {frontmatter-id: note}. Files without an id are skipped."""
    notes: Dict[str, Dict] = {}
    vault_dir = Path(vault_path)
    if not vault_dir.exists():
        return notes

    for md_file in vault_dir.rglob("*.md"):
        if any(part in _RESERVED_FOLDERS for part in md_file.relative_to(vault_dir).parts[:-1]):
            continue  # e.g. .sync/provisional/<op_id>.md — LAN staging, not a real vault note
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:  # unreadable file — skip, never crash the mirror
            print(f"[mobile_sync_agent] skip {md_file}: {e}")
            continue
        fields = read_all_fields(content)
        note_id = fields.get("id")
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
        }
    return notes


def load_state(state_path: str) -> Dict[str, Dict]:
    """Load the derived, rebuildable sync sidecar. Absent/corrupt → empty."""
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}  # derived cache — safe to rebuild from files


def save_state(state_path: str, state: Dict[str, Dict]) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


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
                fields="nextPageToken, files(id, name, headRevisionId, appProperties, mimeType)",
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
            key = (f.get("appProperties") or {}).get("noteId") or Path(f["name"]).stem
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
        key = (f.get("appProperties") or {}).get("noteId") or Path(f["name"]).stem
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


def _upload_note(drive, note: Dict, dest_folder_id: str, existing: Optional[Dict]) -> Dict:
    """Create or update one note on the hub. Returns the Drive file resource
    (with id + headRevisionId). Asserts the body is byte-identical to the source."""
    content = note["content"]
    # Body-sacred: we upload the source bytes verbatim; the body must be unchanged.
    # Explicit check (not `assert`) — must not be strippable under python -O.
    if strip_frontmatter(content) != note["body"]:
        raise RuntimeError("body-sacred violation: body bytes changed before upload")

    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown")
    metadata = {"name": f"{note['id']}.md", "appProperties": {"noteId": note["id"]}}

    if existing and existing.get("drive_file_id"):
        # ponytail: update-in-place by file id — a note whose category changed stays in its
        # original hub folder (no move). Wire a parents add/remove here if per-category hub
        # placement must track category edits.
        return (
            drive.files()
            .update(
                fileId=existing["drive_file_id"],
                media_body=media,
                fields="id, headRevisionId",
            )
            .execute()
        )
    metadata["parents"] = [dest_folder_id]
    return (
        drive.files()
        .create(body=metadata, media_body=media, fields="id, headRevisionId")
        .execute()
    )


def _download_content(drive, file_id: str) -> str:
    """Fetch a hub file's current bytes (Drive `GET ?alt=media`), decoded as UTF-8."""
    return drive.files().get_media(fileId=file_id).execute().decode("utf-8")


def _download_revision(drive, file_id: str, revision_id: str) -> str:
    """Fetch a specific past revision's bytes — used to get the BASE (last-reconciled) note text
    for a three-way merge (contract §10 "Version history")."""
    return (
        drive.revisions()
        .get_media(fileId=file_id, revisionId=revision_id)
        .execute()
        .decode("utf-8")
    )


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

    Body-sacred: reconcile() guarantees the merged body is a verbatim copy of one input — never
    fabricated. Returns (reconciled, conflicts, failed, new_state).

    write_file / new_id are injected so the merge logic is unit-testable without disk or randomness.
    """
    if write_file is None:
        def write_file(path: str, content: str) -> None:
            Path(path).write_text(content, encoding="utf-8")
    if new_id is None:
        # ponytail: uuid4-hex conflicted-copy id (opaque sync identity, only needs uniqueness).
        # Swap for a real ULID minter if lexical time-ordering of conflicted copies ever matters.
        new_id = lambda: uuid.uuid4().hex[:26]  # noqa: E731

    reconciled = 0
    conflicts = 0
    failed = 0
    new_state = dict(state)
    folder_cache: Dict[str, str] = {}

    for note_id, local in vault_notes.items():
        prior = state.get(note_id)
        if not prior or not prior.get("drive_file_id"):
            continue  # never synced → not a remote-advance case (mirror_to_hub creates it)
        hub_file = hub_files.get(note_id)
        if not hub_file:
            continue  # not on the hub (or trashed) → nothing to pull
        remote_rev = hub_file.get("headRevisionId")
        if remote_rev == prior.get("base_rev"):
            continue  # remote unchanged since last sync
        local_changed = local["hash"] != prior.get("local_hash")
        file_id = prior["drive_file_id"]
        try:
            remote_text = _download_content(drive, file_id)
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
            base = parse_note(_download_revision(drive, file_id, prior["base_rev"]))
            merged_result = reconcile(
                base, parse_note(local["content"]), parse_note(remote_text), new_id()
            )
            merged_text = serialize_note(merged_result.merged)
            write_file(local["path"], merged_text)
            dest = _resolve_dest_folder(drive, hub_folder_id, local.get("category"), folder_cache)
            up = _upload_note(
                drive,
                {"id": note_id, "content": merged_text, "body": merged_result.merged.body},
                dest,
                {"drive_file_id": file_id},
            )
            new_state[note_id] = {
                "drive_file_id": up["id"],
                "base_rev": up.get("headRevisionId"),
                "local_hash": _sha256(merged_text),
            }
            reconciled += 1

            if merged_result.conflicted_copy is not None:
                cc = merged_result.conflicted_copy
                cc_text = serialize_note(cc)
                cc_path = str(Path(local["path"]).with_name(f"{cc.id}.md"))
                write_file(cc_path, cc_text)
                up_cc = _upload_note(
                    drive,
                    {"id": cc.id, "content": cc_text, "body": cc.body},
                    dest,
                    None,
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
    modifiedTime. Returns (uploaded, failed, new_state).
    """
    uploaded = 0
    failed = 0
    new_state = dict(state)
    folder_cache: Dict[str, str] = {}

    for note_id, note in vault_notes.items():
        prior = state.get(note_id)
        # Skip only if we have synced this exact content before.
        if prior and prior.get("local_hash") == note["hash"] and prior.get("drive_file_id"):
            continue
        if not prior or not prior.get("drive_file_id"):
            # Sidecar absent/corrupt/stale for this note — files/Drive are the
            # source of truth. Fall back to the hub listing so an existing hub
            # file is updated, never re-created as a duplicate orphan.
            hub_file = hub_files.get(note_id)
            if hub_file:
                prior = {
                    "drive_file_id": hub_file["id"],
                    "base_rev": hub_file.get("headRevisionId"),
                    "local_hash": None,
                }
        try:
            dest = _resolve_dest_folder(drive, hub_folder_id, note.get("category"), folder_cache)
            result = _upload_note(drive, note, dest, prior)
            new_state[note_id] = {
                "drive_file_id": result["id"],
                "base_rev": result.get("headRevisionId"),
                "local_hash": note["hash"],
            }
            uploaded += 1
        except Exception as e:
            print(f"[mobile_sync_agent] upload {note_id} failed: {e}")
            failed += 1

    return uploaded, failed, new_state


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
    vault/<category-from-frontmatter>/<id>.md; missing/empty category → the scratchpad.
    Bytes are written verbatim (body-sacred — we never touch a pulled body).
    Returns (pulled, failed, new_state).
    """
    if write_file is None:
        def write_file(path: str, content: str) -> None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    if download is None:
        def download(file_id: str) -> str:
            return _download_content(drive, file_id)

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
            dest = str(Path(vault_root) / sub / f"{note_id}.md")
            write_file(dest, content)
            new_state[note_id] = {
                "drive_file_id": hub_file["id"],
                "base_rev": hub_file.get("headRevisionId"),
                "local_hash": _sha256(content),
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
            Path(entry["path"]).write_text(new_content, encoding="utf-8")
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
    _categories, reserved = list_hub_tree(drive, hub_id)
    vault_notes = read_vault_notes(vault_path)
    hub_files = get_hub_notes(drive, hub_id)
    state = load_state(state_path)
    # Snapshot per-note base_rev so we can tell which notes reached canonical this pass
    # (Drive is the sole canonical/version authority — LAN provisional never advances base_rev).
    pre_revs = {nid: s.get("base_rev") for nid, s in state.items()}
    vault_root = vault_root or vault_path

    reconciled, conflicts, r_failed, state = reconcile_changes(
        vault_notes, hub_files, state, drive, hub_id
    )
    pulled, p_failed, state = pull_new_hub_notes(
        vault_notes, hub_files, state, drive, vault_root, scratchpad_folder
    )

    ingested = i_failed = 0
    inbox_id = reserved.get("_mobile_inbox")
    if inbox_id and run_pipeline is not None:
        ingested, _skipped, i_failed = intake_mobile_inbox(drive, inbox_id, run_pipeline)

    # Re-read: reconcile/pull wrote merged/pulled bodies; the pipeline wrote captures.
    vault_notes = read_vault_notes(vault_path)

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

    uploaded, u_failed, new_state = mirror_to_hub(vault_notes, hub_files, state, drive, hub_id)
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


def main():
    """One bidirectional sync pass. Wires real Drive auth, config, capture pipeline, enrichment."""
    from functools import partial
    from drive_auth import get_drive_service
    from config import get_config
    from main import run_pipeline

    cfg = get_config()
    vault_path = os.environ.get("OMNI_VAULT", str(cfg.vault.root))
    # B-4: default the sync-state sidecar under <vault>/.omni_capture/ — NOT a CWD-relative path.
    # A CWD-relative default meant running the agent from a different directory lost every note's
    # base_rev, turning the next pass into blind uploads over advanced hub heads (remote edits lost
    # from the head, recoverable only via Drive revisions). The vault is a stable, single anchor.
    _default_state = Path(vault_path) / ".omni_capture" / "mobile_sync_state.json"
    _default_state.parent.mkdir(parents=True, exist_ok=True)
    state_path = os.environ.get("OMNI_SYNC_STATE", str(_default_state))
    drive = get_drive_service()

    # Captures ingest into the SAME vault we sync (route_and_enrich writes via run_pipeline).
    bound_pipeline = partial(run_pipeline, vault_root=vault_path)
    enrich_fn = _build_enrich_fn(cfg, vault_path)
    reminders_fn = _build_reminders_fn(vault_path)

    # LAN accelerator (contract §11) is fully additive and gated on `[lan] enabled` -- when
    # disabled, provisional_fn stays None and run_once's 7-tuple/behavior is exactly as before.
    lan_enabled = bool(cfg.lan.enabled)
    provisional_fn = _build_provisional_fn(vault_path) if lan_enabled else None

    uploaded, failed, reconciled, conflicts, pulled, ingested, enriched = run_once(
        vault_path, state_path, drive,
        vault_root=vault_path,
        scratchpad_folder=cfg.vault.scratchpad_folder,
        run_pipeline=bound_pipeline,
        enrich_fn=enrich_fn,
        reminders_fn=reminders_fn,
        provisional_fn=provisional_fn,
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

        # ponytail: no dedicated [lan] sync-interval knob exists yet (this is a single-shot
        # per-invocation script, not an internal loop) -- fixed 24h TTL as a sane default
        # backstop for orphaned provisionals; revisit if a configurable cadence is added.
        try:
            import provisional_store as ps
            ps.sweep(os.path.join(vault_path, ".sync"), now_ts=time.time(), ttl_seconds=86400.0)
        except Exception as e:
            print(f"[mobile_sync_agent] lan provisional sweep failed: {e}")


if __name__ == "__main__":
    main()
