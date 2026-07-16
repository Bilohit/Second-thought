"""
tag_index.py — the vault's tag vocabulary, read from the files (F-4).

Files are the source of truth (CLAUDE.md hard rule), so a note's tags live in
its frontmatter and nowhere else. BOTH halves of Library's Tags view resolve
through the one scan here:

  * `/tags`  (vault_admin.list_tags)      — the tree's per-row note counts
  * `/search?q=tag:<x>` (index_writer.search) — the rows a row's click lists

They used to disagree: counts came from a vault scan, but the listing filtered
`captures.db` with `tags LIKE '%"x"%'`. That column is only ever written by the
capture pipeline (`log_capture_db`) — `upsert_capture_from_file`, the path every
`origin: note` file arrives through, never sets it — so an editor-created note's
tag showed a count with an empty result list. Namespace rows (`project/`) missed
for a second reason: no tag is literally spelled `project/`, so the LIKE matched
nothing while the row's rolled-up count said otherwise.

captures.db stays a derived cache in front of the files: it supplies the rows and
the FTS text match, this scan decides tag membership. It is never authoritative.

Public API
----------
  parse_tags(text)              -> list[str]   frontmatter tags, either shape
  scan_tag_paths(vault_root)    -> dict[str, dict[str, str]]  tag -> {path: label}
  resolve_paths(vault_root, tag)-> set[str]    paths a tag (or `ns/`) covers
"""
from __future__ import annotations

import re
from pathlib import Path

from frontmatter import _FM_RE, read_all_fields

# Folders that hold machine state or staging copies, not browsable vault notes.
# Mirrors the set list_tags() scanned before this module existed.
_RESERVED = {"_trash", "_mobile_inbox", "_attachments", "_templates", ".sync", ".omni_capture"}

_TAGS_KEY_RE = re.compile(r"^tags:\s*(.*)$")
_TAGS_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$")


def parse_tags(text: str) -> list[str]:
    """Frontmatter tags, in either shape the vault actually contains:

      inline  `tags: [work, radial]`   — notes (the editor + the phone half)
      block    `tags:` / `  - work`    — the capture pipeline (storage_engine.py)

    read_all_fields() only sees the inline form (a block list's value is the
    empty string), which is exactly why captures had to be counted out of the DB
    before. Returns [] when there is no frontmatter or no tags key.
    """
    m = _FM_RE.match(text)
    if not m:
        return []
    lines = m.group(1).splitlines()
    tags: list[str] = []
    for i, line in enumerate(lines):
        hit = _TAGS_KEY_RE.match(line)
        if not hit:
            continue
        inline = hit.group(1).strip()
        if inline:
            for t in inline.strip("[]").split(","):
                t = t.strip().strip("'\"")
                if t:
                    tags.append(t)
        else:
            for nxt in lines[i + 1:]:
                item = _TAGS_ITEM_RE.match(nxt)
                if not item:
                    break  # first non-list line ends the block
                t = item.group(1).strip().strip("'\"")
                if t:
                    tags.append(t)
        break
    return tags


def scan_tag_paths(vault_root: Path) -> dict[str, dict[str, str]]:
    """Walk the vault once: `tag -> {absolute path: display label}`.

    Keyed by path (not a running count) so a tag's count is its number of
    DISTINCT notes, and so a namespace row can union its children's notes
    instead of summing occurrences — a note tagged both `project/alpha` and
    `project/beta` is one note under `project/`, which is what its click lists.

    ponytail: re-reads every vault .md per call, no memo. The Tags view already
    paid this scan for its counts; the tag-filtered search now pays it too (once
    per tag click). Add an mtime-keyed memo if a vault ever holds tens of
    thousands of notes.
    """
    index: dict[str, dict[str, str]] = {}
    if not vault_root.is_dir():
        return index
    for md_file in vault_root.rglob("*.md"):
        rel = md_file.relative_to(vault_root)
        if any(part in _RESERVED for part in rel.parts[:-1]):
            continue
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue  # unreadable file — skip, never break the browser
        tags = parse_tags(text)
        if not tags:
            continue
        label = read_all_fields(text).get("title") or md_file.stem
        for t in tags:
            index.setdefault(t, {})[str(md_file)] = label
    return index


def resolve_paths(vault_root: Path, tag: str) -> set[str]:
    """The vault paths *tag* covers.

    A trailing `/` marks a namespace row from the tree (`project/`): it has no
    notes of its own, it stands for every `project/<leaf>`, so it resolves by
    prefix — matching the union its count was built from. Any other tag is exact.
    """
    index = scan_tag_paths(vault_root)
    if tag.endswith("/"):
        return {p for t, paths in index.items() if t.startswith(tag) for p in paths}
    return set(index.get(tag, {}))
