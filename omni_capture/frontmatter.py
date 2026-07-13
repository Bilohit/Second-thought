"""
frontmatter.py — Minimal YAML-frontmatter helpers shared across the pipeline.
"""
from __future__ import annotations
import re


_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    """Return *text* with the leading YAML frontmatter block removed."""
    return _FM_RE.sub("", text, count=1)


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
        hit = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if hit:
            fields[hit.group(1)] = hit.group(2).strip().strip('"').strip("'")
    return fields
