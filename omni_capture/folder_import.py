"""folder_import.py -- FR-23 Option C's pure planner.

A vault that predates the s127 tag model organises notes in folders and carries no
`#project@` tags at all, so the tidy pass correctly concludes every note belongs in
`_loose/` and flattens the tree. This module plans the other repair: keep the tree and
make it legitimate, by tagging the notes and registering the folder names.

Pure by design, exactly like project_tidy.py: it reads the vault and returns a plan.
Nothing here writes a byte -- the applier lives in vault_admin.py behind an explicit
user confirmation, because this is the one surface in the product that edits note
bodies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from note_model import parse_note
from projects import LOOSE_DIR, is_valid_project_name, parse_project_tag

# Mirrors vault_admin._TIDY_EXEMPT, plus `_loose` -- a loose note is not mis-filed, it is
# exactly where the model says an untagged note belongs, so it is never an import candidate.
_EXEMPT = {"_scratchpad", "_trash", "_attachments", "_mobile_inbox", LOOSE_DIR}

_ILLEGAL_RUN = re.compile(r"[^A-Za-z0-9_-]+")
_EDGE_DASHES = re.compile(r"^[-_]+|[-_]+$")


@dataclass
class FolderCandidate:
    folder: str
    suggested: str
    valid: bool
    existing: bool
    note_paths: list[Path] = field(default_factory=list)


def sanitise_name(folder: str) -> str:
    """A SUGGESTION for an unusable folder name -- never applied without the user seeing it.

    Collapses every illegal run to one `-` and trims the edges, because a project name must
    start with an alphanumeric. Returns "" when nothing usable survives, which the UI shows
    as an empty field for the user to fill rather than a bad guess."""
    candidate = _EDGE_DASHES.sub("", _ILLEGAL_RUN.sub("-", folder))
    return candidate if is_valid_project_name(candidate) else ""


def tag_line_insert(body: str, name: str) -> str:
    """Insert `#project@<name>` as its own line directly under the first `# ` heading, or
    as the first line when there is none.

    The same placement `today_view._daily_body` uses for `#daily`: ordinary body text the
    user can see and delete, deliberately NOT the trailing machine `tags:` line, which
    enrichment replaces wholesale (mobile_sync_agent.py:1484-1487)."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(i + 1, f"#project@{name}")
            return "\n".join(lines)
    return f"#project@{name}\n{body}"


def plan_import(root: Path, reg: dict) -> list[FolderCandidate]:
    """Every top-level folder holding at least one untagged note, in directory order.

    A note that already carries a `#project@` tag is not a candidate -- it already has a
    project, and re-tagging it would be the product overwriting the user's own answer."""
    registered = set(reg.get("projects", {}))
    out: list[FolderCandidate] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _EXEMPT:
            continue
        notes = []
        for path in sorted(entry.iterdir()):
            if not (path.is_file() and path.suffix == ".md"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # parse_project_tag's regex is bare and whitespace-anchored (projects.py's own
            # docstring warns it can false-match inside a URL fragment); every other caller in
            # this codebase passes it a note BODY, never raw file text. Frontmatter can carry
            # arbitrary unknown keys verbatim (note_model.py preserves them byte-for-byte), so
            # scanning the whole file risks a false "already tagged" positive from a frontmatter
            # value -- strip frontmatter via the shared codec first.
            body = parse_note(text).body
            if parse_project_tag(body) is None:
                notes.append(path)
        if not notes:
            continue
        valid = is_valid_project_name(entry.name)
        out.append(FolderCandidate(
            folder=entry.name,
            suggested=entry.name if valid else sanitise_name(entry.name),
            valid=valid,
            existing=entry.name in registered,
            note_paths=notes,
        ))
    return out
