"""
frontmatter.py — Minimal YAML-frontmatter helpers shared across the pipeline.
"""
from __future__ import annotations
import re


_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    """Return *text* with the leading YAML frontmatter block removed."""
    return _FM_RE.sub("", text, count=1)


def add_fields(text: str, fields: dict[str, str]) -> str:
    """Insert additional top-level `key: value` lines into the frontmatter block, appended just
    before the closing `---`. Frontmatter-ONLY edit: everything outside the matched block (the
    body, and any frontmatter fields already present) is left byte-for-byte untouched. No-op
    (returns *text* unchanged) if there is no frontmatter block to insert into."""
    m = _FM_RE.match(text)
    if not m:
        return text
    block = m.group(1)
    insert = "\n".join(f"{k}: {v}" for k, v in fields.items())
    new_block = (block + "\n" + insert) if block else insert
    return text[: m.start(1)] + new_block + text[m.end(1):]


def read_all_fields(text: str) -> dict[str, str]:
    """Return every top-level `key: value` pair in the frontmatter block.

    Values are trimmed and surrounding quotes stripped.
    List/nested YAML is returned as its raw one-line string. Empty dict if no
    frontmatter block is present.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        # SYNC-29: hyphenated keys (`remind-at`, foreign/plugin keys) were dropped entirely by the
        # narrower `[A-Za-z0-9_]+` class, while note_model._KEY_LINE — the peer-parity codec, a port
        # of the phone's frontmatter.ts — accepts them. Widen to match it. Only this key class
        # changes: _FM_RE is deliberately untouched because note_editor._split uses its `m.end()`
        # as the frontmatter/body boundary on the body-sacred write path.
        hit = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if hit:
            fields[hit.group(1)] = hit.group(2).strip().strip('"').strip("'")
    return fields
