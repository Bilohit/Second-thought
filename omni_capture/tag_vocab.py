"""
tag_vocab.py — normalize new tags against the vault's existing tag vocabulary.

Reads DISTINCT tags from captures.db (a derived index — fine to read, never
authoritative over vault files). Collapses case/space/underscore and naive
plurals so "LLM Agents" reuses an existing "llm-agents" instead of forking
the vocabulary.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List


def _norm(tag: str) -> str:
    t = re.sub(r"[\s_]+", "-", tag.strip().lower())
    # ponytail: naive trailing-s plural strip; upgrade to embedding-similarity
    # matching against the vocab if synonym drift (not just plurals) shows up.
    if t.endswith("s") and len(t) > 3:
        t = t[:-1]
    return t


def load_vocab(db_path: Path) -> Dict[str, str]:
    """Map normalized form -> canonical existing tag. Empty dict on any miss."""
    vocab: Dict[str, str] = {}
    if not db_path.exists():
        return vocab
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT tags FROM captures").fetchall()
    except sqlite3.Error:
        return vocab
    finally:
        conn.close()
    for (raw,) in rows:
        try:
            tags = json.loads(raw or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            vocab.setdefault(_norm(tag), tag)
    return vocab


def normalize_tags(tags: List[str], vocab: Dict[str, str], cap: int = 10) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = _norm(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(vocab.get(key, tag))
    return out[:cap]


if __name__ == "__main__":
    assert _norm("LLM Agents") == "llm-agent"
    assert normalize_tags(["A", "a"], {}) == ["A"] or normalize_tags(["a", "A"], {}) == ["a"]
    print("tag_vocab smoke OK")
