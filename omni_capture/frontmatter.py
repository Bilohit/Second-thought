"""
frontmatter.py — Minimal YAML-frontmatter helpers shared across the pipeline.
"""
from __future__ import annotations
import re
from typing import Optional


_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    """Return *text* with the leading YAML frontmatter block removed."""
    return _FM_RE.sub("", text, count=1)


def read_field(text: str, name: str) -> Optional[str]:
    """Return the value of *name* from the frontmatter block, or None."""
    m = _FM_RE.match(text)
    block = m.group(1) if m else ""
    hit = re.search(r"^" + re.escape(name) + r":\s*(.+)$", block, re.MULTILINE)
    if hit:
        return hit.group(1).strip().strip('"').strip("'")
    return None
