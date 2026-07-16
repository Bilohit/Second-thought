"""
note_editor.py — read/write support for the desktop in-app note editor (F-7).

Body-sacred lock: this module only ever rewrites the body region of a note.
The frontmatter block (machine-owned) is carried through byte-for-byte on
every write — never reparsed, reordered, or regenerated here. See
frontmatter.py's `strip_frontmatter` / `_FM_RE` for the shared regex this
module reuses.

Conflict handling: files are the source of truth (workspace CLAUDE.md
"Shared locks"), and there is no per-note revision id at this layer — Drive's
`headRevisionId` three-way reconcile is owned by mobile_sync_agent.py's
periodic hub sync, not by this editor. What this module guards against is
the realistic *local* race: the user (or Obsidian, or another Second
Thought surface) touches the same file on disk while the in-app editor has
it open. That's a plain optimistic-concurrency check on `st_mtime`:
`write_note_body` takes the mtime the editor last read, and refuses to
overwrite if the file has moved on since, raising `NoteConflictError`
instead of clobbering. The next scheduled Drive sync pass reconciles the
hub side exactly as it already does for every other note.

ponytail: mtime-resolution races (two writes inside the same tick) are not
disambiguated by content hash — acceptable ceiling for a single-user local
editor; revisit if this ever gates a multi-writer path.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from frontmatter import _FM_RE, read_all_fields


class NoteConflictError(Exception):
    """Raised when a write's expected_mtime no longer matches the file on disk."""

    def __init__(self, path: Path, expected_mtime: float, current_mtime: float, current_body: str):
        super().__init__(f"{path} changed on disk since it was read (expected mtime {expected_mtime}, found {current_mtime})")
        self.path = path
        self.expected_mtime = expected_mtime
        self.current_mtime = current_mtime
        self.current_body = current_body


def resolve_note_path(vault_root: Path, path_str: str) -> Path:
    """Resolve *path_str* (as returned by any /vault or /search endpoint) and
    guarantee it stays inside the vault. Raises ValueError on escape/missing."""
    root_resolved = vault_root.resolve()
    candidate = Path(path_str)
    target = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"Path escapes vault root: {path_str!r}")
    if target.suffix != ".md":
        raise ValueError(f"Not a note file: {path_str!r}")
    return target


def _read_verbatim(path: Path) -> str:
    """Read a note byte-verbatim: newline="" disables universal-newline
    translation, so `\\r\\n` survives the read instead of collapsing to `\\n`.
    Same primitive the hub sync paths use (mobile_sync_agent.py) -- a note's
    newline convention is the file's, and this module must not churn bytes the
    user never typed."""
    return path.read_text(encoding="utf-8", errors="ignore", newline="")


def _write_verbatim(path: Path, text: str) -> None:
    """Write *text* byte-verbatim -- no newline translation. The default
    (newline=None) rewrites every `\\n` as `\\r\\n` on Windows, silently
    flipping an LF note to CRLF on the first editor save."""
    path.write_text(text, encoding="utf-8", newline="")


def _newline_of(text: str) -> str:
    """The file's existing newline convention -- CRLF if its first line break
    is `\\r\\n`, else LF. A file with no line break at all defaults to LF."""
    i = text.find("\n")
    return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def _to_lf(text: str) -> str:
    """Normalize to LF. This module works in LF internally and re-applies the
    file's own convention at write time (_apply_newlines) -- clients speak LF
    (an HTML textarea normalizes CRLF away before the body is ever POSTed
    back), so the file's bytes, not the client's, decide the convention."""
    return text.replace("\r\n", "\n")


def _apply_newlines(text: str, newline: str) -> str:
    """Re-apply *newline* to every line break in LF-normalized *text*."""
    return text if newline == "\n" else text.replace("\n", newline)


def _split(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_including_delimiters, body)."""
    m = _FM_RE.match(text)
    if not m:
        return "", text
    return text[: m.end()], text[m.end():]


def _title_from(body: str, fields: dict[str, str], fallback: str) -> str:
    if fields.get("title"):
        return fields["title"]
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
        if line:
            break
    return fallback


def read_note(vault_root: Path, path_str: str) -> dict:
    """Read a note for the editor. Never mutates the file."""
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    text = _to_lf(_read_verbatim(path))
    fm_block, body = _split(text)
    fields = read_all_fields(text)
    stat = path.stat()
    tags_raw = fields.get("tags", "")
    tags = [t.strip() for t in tags_raw.strip("[]").split(",") if t.strip()] if tags_raw else []
    return {
        "path": str(path),
        "title": _title_from(body, fields, path.stem),
        "category": path.parent.name,
        "status": fields.get("status"),
        "tags": tags,
        "body": body,
        "mtime": stat.st_mtime,
        "has_frontmatter": bool(fm_block),
    }


def write_note_body(vault_root: Path, path_str: str, new_body: str, expected_mtime: float) -> dict:
    """Overwrite only the body region of a note, preserving its frontmatter
    block byte-for-byte. Refuses (NoteConflictError) if the file's mtime has
    moved since the editor last read it."""
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    current_mtime = path.stat().st_mtime
    # Sub-second float mtimes can drift a hair on some filesystems on pure
    # re-read with no write in between; 2ms tolerance absorbs that without
    # weakening the real-conflict case (a genuine external edit moves mtime
    # by whole seconds in practice).
    if abs(current_mtime - expected_mtime) > 0.002:
        current_text = _to_lf(_read_verbatim(path))
        _, current_body = _split(current_text)
        raise NoteConflictError(path, expected_mtime, current_mtime, current_body)

    raw = _read_verbatim(path)
    newline = _newline_of(raw)
    fm_block, _old_body = _split(_to_lf(raw))
    body = _to_lf(new_body)
    body = body if body.endswith("\n") else body + "\n"
    _write_verbatim(path, _apply_newlines(fm_block + body, newline))
    return {"mtime": path.stat().st_mtime}


# -- F-13 (desktop half): attachments -----------------------------------------
# Link syntax `[attachment: <filename>]` and frontmatter key `attachments`
# MATCH the phone half exactly (workspace CLAUDE.md cross-peer parity rule).

_ATTACHMENTS_FIELD_RE = re.compile(r"^attachments:.*$", re.MULTILINE)


def attachments_dir(vault_root: Path, note_id: str) -> Path:
    d = vault_root.resolve() / "_attachments" / note_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upsert_attachments_field(fm_block: str, filenames: list[str]) -> str:
    """Frontmatter-only edit: set/replace the `attachments: [...]` line inside
    *fm_block* (the full block including its `---` delimiters). No-op if
    there's no frontmatter block to edit into."""
    if not fm_block:
        return fm_block
    value_line = "attachments: [" + ", ".join(filenames) + "]"
    if _ATTACHMENTS_FIELD_RE.search(fm_block):
        return _ATTACHMENTS_FIELD_RE.sub(value_line, fm_block, count=1)
    lines = fm_block.splitlines(keepends=True)
    if len(lines) < 2:
        return fm_block
    return "".join(lines[:-1]) + value_line + "\n" + lines[-1]


def add_attachment(vault_root: Path, path_str: str, filename: str, data: bytes, expected_mtime: float) -> dict:
    """Write *data* into `_attachments/<note-id>/<filename>`, record it in the
    note's `attachments` frontmatter list, and append a `[attachment:
    <filename>]` link line to the body. A single normal user file-write
    through this module (attach affordance), mtime-guarded exactly like
    `write_note_body` -- refuses (NoteConflictError) if the file moved on
    disk since the editor last read it.
    """
    path = resolve_note_path(vault_root, path_str)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    current_mtime = path.stat().st_mtime
    if abs(current_mtime - expected_mtime) > 0.002:
        current_text = _to_lf(_read_verbatim(path))
        _, current_body = _split(current_text)
        raise NoteConflictError(path, expected_mtime, current_mtime, current_body)

    raw = _read_verbatim(path)
    newline = _newline_of(raw)
    text = _to_lf(raw)
    fields = read_all_fields(text)
    note_id = fields.get("id")
    if not note_id:
        raise ValueError("Note has no id -- cannot attach a file")

    safe_name = re.sub(r"[^\w.\-]", "_", filename) or "attachment"
    dest_dir = attachments_dir(vault_root, note_id)
    dest = dest_dir / safe_name
    if dest.exists():
        dest = dest_dir / f"{dest.stem}.{int(time.time())}{dest.suffix}"
    dest.write_bytes(data)

    existing_raw = fields.get("attachments", "")
    existing = [t.strip() for t in existing_raw.strip("[]").split(",") if t.strip()] if existing_raw else []
    existing.append(dest.name)

    fm_block, body = _split(text)
    new_fm = _upsert_attachments_field(fm_block, existing)
    link_line = f"[attachment: {dest.name}]"
    new_body = (body.rstrip("\n") + f"\n\n{link_line}\n") if body.strip() else f"{link_line}\n"
    _write_verbatim(path, _apply_newlines(new_fm + new_body, newline))
    return {"filename": dest.name, "mtime": path.stat().st_mtime}


# ---------------------------------------------------------------------------
# Smoke test  (python note_editor.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        cat = vault / "Tech_Notes"
        cat.mkdir()
        note = cat / "example.md"
        note.write_text(
            "---\ntitle: Example note\ncategory: Tech_Notes\nstatus: active\ntags: [work, radial]\n---\n"
            "# Example note\n\nOriginal body.\n",
            encoding="utf-8",
        )

        # T1: read_note preserves body, exposes read-only frontmatter fields.
        data = read_note(vault, str(note))
        assert data["title"] == "Example note"
        assert data["category"] == "Tech_Notes"
        assert data["status"] == "active"
        assert data["tags"] == ["work", "radial"]
        assert "Original body." in data["body"]
        print("[T1] read_note  PASS")

        # T2: write_note_body preserves frontmatter byte-for-byte, only body changes.
        result = write_note_body(vault, str(note), "# Example note\n\nEdited body.\n", data["mtime"])
        new_text = note.read_text(encoding="utf-8")
        assert new_text.startswith("---\ntitle: Example note\n")
        assert "Edited body." in new_text
        assert "Original body." not in new_text
        assert result["mtime"] >= data["mtime"]
        print("[T2] write_note_body  PASS")

        # T3: stale expected_mtime raises NoteConflictError, never clobbers.
        try:
            write_note_body(vault, str(note), "# Example note\n\nClobber attempt.\n", data["mtime"])
            raise AssertionError("expected NoteConflictError")
        except NoteConflictError as exc:
            assert "Edited body." in exc.current_body
        still_on_disk = note.read_text(encoding="utf-8")
        assert "Clobber attempt." not in still_on_disk
        print("[T3] write_note_body conflict  PASS")

        # T4: path traversal outside the vault is rejected.
        try:
            resolve_note_path(vault, "../outside.md")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
        print("[T4] resolve_note_path traversal guard  PASS")

        # T5: add_attachment writes the file, records `attachments`
        # frontmatter, and appends a `[attachment: ...]` link line.
        note2 = cat / "with_id.md"
        note2.write_text(
            "---\nid: n1\ntitle: Has id\ncategory: Tech_Notes\n---\n# Has id\n\nBody text.\n",
            encoding="utf-8",
        )
        d2 = read_note(vault, str(note2))
        r = add_attachment(vault, str(note2), "memo.m4a", b"fakeaudio", d2["mtime"])
        assert r["filename"] == "memo.m4a"
        assert (vault / "_attachments" / "n1" / "memo.m4a").read_bytes() == b"fakeaudio"
        after = note2.read_text(encoding="utf-8")
        assert "attachments: [memo.m4a]" in after
        assert "[attachment: memo.m4a]" in after
        assert "Body text." in after  # original body preserved
        print("[T5] add_attachment  PASS")

        # T6: a second attachment appends rather than clobbering the list.
        d3 = read_note(vault, str(note2))
        r2 = add_attachment(vault, str(note2), "photo.jpg", b"fakejpeg", d3["mtime"])
        after2 = note2.read_text(encoding="utf-8")
        assert "attachments: [memo.m4a, photo.jpg]" in after2
        assert "[attachment: memo.m4a]" in after2 and "[attachment: photo.jpg]" in after2
        print("[T6] add_attachment second file  PASS")

    print("\nAll note_editor.py smoke tests passed.")
