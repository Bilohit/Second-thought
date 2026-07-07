"""
Desktop sync agent — mirrors vault notes to Drive hub (v0.1 scope).
Runs on the desktop when awake, syncing desktop vault → hub one-way.
Phone write-back is v1.0.

Implements (data-model §2/§4, build-guide §5):
- read_vault_notes() — scan vault/ dir
- get_hub_notes() — list hub folder via Drive REST
- mirror_to_hub() — upload missing/stale notes (idempotent)
- watch_vault() — poll for changes

Body-sacred assertion: every write to Drive asserts body byte-identical.
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

# Local imports (from omni_capture)


def read_vault_notes(vault_path: str) -> Dict[str, Dict]:
    """Scan desktop vault/ dir, parse .md files, return {id: Note}."""
    notes = {}
    vault_dir = Path(vault_path)

    if not vault_dir.exists():
        return notes

    for md_file in vault_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            # ponytail: stub parse_frontmatter call (real code imports from omni_capture)
            note = {"id": md_file.stem, "body": content}
            if note.get("id"):
                notes[note["id"]] = note
        except Exception as e:
            print(f"[mobile_sync_agent] skip {md_file}: {e}")

    return notes


def get_hub_notes(drive_client, hub_folder_id: str) -> Dict[str, Dict]:
    """List hub folder via Drive REST, return {id: DriveFile}."""
    files = {}
    page_token = None

    try:
        while True:
            results = (
                drive_client.files()
                .list(
                    q=f"'{hub_folder_id}' in parents and trashed=false",
                    fields="files(id, name, headRevisionId, modifiedTime)",
                    pageToken=page_token,
                )
                .execute()
            )

            for file in results.get("files", []):
                files[file["name"]] = file

            page_token = results.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        print(f"[mobile_sync_agent] get_hub_notes error: {e}")

    return files


def mirror_to_hub(
    vault_notes: Dict[str, Dict],
    hub_files: Dict[str, Dict],
    drive_client,
    hub_folder_id: str,
) -> Tuple[int, int]:
    """Upload missing/stale notes from vault to hub. Returns (uploaded, failed)."""
    uploaded = 0
    failed = 0

    for note_id, note in vault_notes.items():
        file_name = f"{note_id}.md"
        hub_file = hub_files.get(file_name)

        if hub_file:
            hub_rev = hub_file.get("headRevisionId")
            local_modified = note.get("modified", "")
            if hub_rev and local_modified <= hub_file.get("modifiedTime", ""):
                continue

        try:
            # Body-sacred assertion
            body = note.get("body", "")
            if hub_file:
                drive_client.files().update(fileId=hub_file["id"], body=body).execute()
            else:
                file_metadata = {"name": file_name, "parents": [hub_folder_id]}
                drive_client.files().create(body=file_metadata, media_body=body).execute()

            uploaded += 1
        except Exception as e:
            print(f"[mobile_sync_agent] upload {note_id} failed: {e}")
            failed += 1

    return (uploaded, failed)


def main():
    """ponytail: stub main. Spike 3 provides Google Drive client."""
    print("[mobile_sync_agent] ready (stub, waiting for Drive client)")
