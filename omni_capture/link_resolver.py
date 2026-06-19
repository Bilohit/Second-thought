"""
link_resolver.py
----------------
Vault-aware wikilink injector for Second Thought.

Two public functions:

  build_link_index(vault_root)
      Walk all .md files in the vault and build a mapping of
      {display_name → vault-relative stem path} for every note that is
      specific enough to auto-link (multi-word names, or any CRM entry).
      Also reads YAML `aliases` frontmatter when present.

  inject_wikilinks(content, link_index, exclude_stems=None)
      Insert [[wikilinks]] into *content* wherever a known display name
      appears as a whole word, while leaving the following regions untouched:
        • YAML frontmatter  (--- ... ---)
        • Fenced code blocks  (``` ... ```)
        • Inline code spans  (`...`)
        • Existing wikilinks  ([[...]])
        • Markdown links  ([text](...))

The injector is idempotent: running it twice on the same content produces
the same result (existing wikilinks are protected in the first pass).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ── Minimum word count for auto-linking ──────────────────────────────────────
# Single-word note names (e.g. "Python") are too broad and cause false
# positives.  Only CRM entries are linked regardless of word count because
# they are always proper names.
_MIN_WORDS_NON_CRM = 2

# Minimum character length of the display name to link
_MIN_DISPLAY_LEN = 4


# ── Frontmatter / code-block protection ──────────────────────────────────────

_FRONTMATTER_RE   = re.compile(r"\A---\n[\s\S]*?\n---\n", re.MULTILINE)
_FENCED_CODE_RE   = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE   = re.compile(r"`[^`\n]+`")
_EXISTING_WIKI_RE = re.compile(r"\[\[.*?\]\]", re.DOTALL)
_MD_LINK_RE       = re.compile(r"\[([^\]]+)\]\([^)]+\)")

# Placeholder tokens — use null bytes so they never collide with real text
_PLACEHOLDER_RE   = re.compile(r"\x00[A-Z]+\d+\x00")


def _protect(text: str) -> tuple[str, dict[str, str]]:
    """
    Replace protected regions with unique placeholder tokens.
    Returns the scrubbed text and a restore map {token → original}.
    """
    store: dict[str, str] = {}
    counter = [0]

    def _sub(pattern: re.Pattern, prefix: str, t: str) -> str:
        def _repl(m: re.Match) -> str:
            key = f"\x00{prefix}{counter[0]}\x00"
            counter[0] += 1
            store[key] = m.group(0)
            return key
        return pattern.sub(_repl, t)

    text = _sub(_FRONTMATTER_RE,   "FM",   text)
    text = _sub(_FENCED_CODE_RE,   "FC",   text)
    text = _sub(_INLINE_CODE_RE,   "IC",   text)
    text = _sub(_EXISTING_WIKI_RE, "WL",   text)
    text = _sub(_MD_LINK_RE,       "ML",   text)
    return text, store


def _restore(text: str, store: dict[str, str]) -> str:
    """Substitute placeholder tokens back with their original content."""
    for key, original in store.items():
        text = text.replace(key, original)
    return text


# ── YAML alias extraction ─────────────────────────────────────────────────────

def _parse_aliases(md_path: Path) -> list[str]:
    """
    Read a note's YAML frontmatter and return the `aliases` list, if present.

    Expects:
        aliases:
          - "Alias One"
          - "Alias Two"
    or inline:
        aliases: ["Alias One"]
    """
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            return []
        fm_block = m.group(0)
        # Simple line-based parse — avoids pulling in a YAML library
        aliases: list[str] = []
        in_aliases = False
        for line in fm_block.splitlines():
            if re.match(r"^aliases\s*:", line):
                in_aliases = True
                # inline list: aliases: ["foo", "bar"]
                inline = re.findall(r'"([^"]+)"', line)
                aliases.extend(inline)
                continue
            if in_aliases:
                item = re.match(r'^\s+-\s+"?([^"]+)"?\s*$', line)
                if item:
                    aliases.append(item.group(1).strip())
                elif line.strip() and not line.startswith(" "):
                    in_aliases = False
        return aliases
    except OSError:
        return []


# ── Index builder ─────────────────────────────────────────────────────────────

def build_link_index(vault_root: Path) -> dict[str, str]:
    """
    Return a mapping of ``{display_name: vault_relative_stem}`` for every
    .md file in *vault_root* that is specific enough to auto-link.

    vault_relative_stem examples:
        "CRM/john-smith"
        "Tech_Notes/python-asyncio-notes"

    The display name for "john-smith.md" is "John Smith".
    Aliases declared in frontmatter are also indexed.
    """
    index: dict[str, str] = {}

    for md in sorted(vault_root.rglob("*.md")):
        # Skip hidden / system files
        if any(part.startswith(".") for part in md.parts):
            continue
        if md.name.startswith("_"):
            continue

        try:
            rel = md.relative_to(vault_root)
        except ValueError:
            continue

        category = rel.parts[0] if len(rel.parts) > 1 else ""
        stem = md.stem  # e.g. "john-smith"

        # Build display name: "john-smith" → "John Smith"
        display = " ".join(
            w.capitalize() for w in re.split(r"[-_]+", stem) if w
        )
        word_count = len(display.split())
        rel_stem = rel.with_suffix("").as_posix()  # "CRM/john-smith" (POSIX separators on every OS)

        # Apply auto-link filter
        if len(display) >= _MIN_DISPLAY_LEN:
            if category == "CRM" or word_count >= _MIN_WORDS_NON_CRM:
                index[display] = rel_stem

        # Also index any frontmatter aliases
        for alias in _parse_aliases(md):
            alias = alias.strip()
            if len(alias) >= _MIN_DISPLAY_LEN:
                a_words = len(alias.split())
                if category == "CRM" or a_words >= _MIN_WORDS_NON_CRM:
                    index[alias] = rel_stem

    return index


# ── Wikilink injector ─────────────────────────────────────────────────────────

def inject_wikilinks(
    content: str,
    link_index: dict[str, str],
    exclude_stems: Optional[set[str]] = None,
) -> str:
    """
    Insert ``[[wikilinks]]`` into *content* where known note names appear.

    Parameters
    ----------
    content:
        Markdown body text to process (may or may not include frontmatter).
    link_index:
        Mapping built by :func:`build_link_index`.
    exclude_stems:
        Set of vault-relative stems (e.g. ``{"CRM/john-smith"}``) to skip
        so a note does not wikilink to itself.

    Returns
    -------
    str
        Modified content with ``[[stem|Display Name]]`` wikilinks injected.
    """
    if not link_index or not content:
        return content

    exclude_stems = exclude_stems or set()

    # ── 1. Protect regions that must not be modified ──────────────────────────
    scrubbed, store = _protect(content)

    # ── 2. Sort by display length descending so longer names match first ──────
    # ("John Smith Jr" before "John Smith")
    sorted_entries = sorted(link_index.items(), key=lambda kv: -len(kv[0]))

    # ── 3. Inject links ───────────────────────────────────────────────────────
    for display, rel_stem in sorted_entries:
        if rel_stem in exclude_stems:
            continue

        pattern = re.compile(
            rf"(?<!\x00)\b({re.escape(display)})\b(?!\x00)",
            re.IGNORECASE,
        )

        def _replace(m: re.Match, _stem: str = rel_stem, _display: str = display) -> str:
            # Preserve original capitalisation in the display label
            return f"[[{_stem}|{m.group(1)}]]"

        scrubbed = pattern.sub(_replace, scrubbed)

    # ── 4. Restore protected regions ──────────────────────────────────────────
    return _restore(scrubbed, store)


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        vault = pathlib.Path(tmp)
        (vault / "CRM").mkdir()
        (vault / "Tech_Notes").mkdir()

        (vault / "CRM" / "john-smith.md").write_text("# John Smith\n")
        (vault / "CRM" / "jane-doe.md").write_text(
            "---\naliases:\n  - \"Jane D\"\n---\n# Jane Doe\n"
        )
        (vault / "Tech_Notes" / "python-asyncio-notes.md").write_text("# Asyncio Notes\n")

        index = build_link_index(vault)
        print("[T1] Link index:", index)
        assert "John Smith" in index, "John Smith not in index"
        assert "Jane Doe"   in index, "Jane Doe not in index"
        assert "Jane D"     in index, "Alias 'Jane D' not in index"
        assert "Python Asyncio Notes" in index, "Multi-word tech note not in index"
        print("[T1] build_link_index  PASS")

        # T2: wikilink injection
        body = "Had a meeting with John Smith about python asyncio notes today."
        result = inject_wikilinks(body, index)
        assert "[[CRM/john-smith|John Smith]]" in result, f"Missing John Smith link:\n{result}"
        assert "[[Tech_Notes/python-asyncio-notes|python asyncio notes]]" in result or \
               "Python Asyncio Notes" in result or "python-asyncio-notes" in result, \
               f"Missing tech note link:\n{result}"
        print(f"[T2] inject_wikilinks  PASS\n  → {result}")

        # T3: code blocks are protected
        body3 = "```python\nprint('John Smith')\n```\nOutside: John Smith."
        result3 = inject_wikilinks(body3, index)
        assert "```python\nprint('John Smith')\n```" in result3, "Code block was modified!"
        assert "[[CRM/john-smith|John Smith]]" in result3, "Missing link outside code block"
        print(f"[T3] Code block protection  PASS")

        # T4: existing wikilinks not double-wrapped
        body4 = "See [[CRM/john-smith|John Smith]] for details."
        result4 = inject_wikilinks(body4, index)
        assert result4.count("[[") == 1, f"Double-wrapped: {result4}"
        print(f"[T4] No double-wrapping  PASS")

        # T5: exclude_stems prevents self-linking
        body5 = "This note is about John Smith."
        result5 = inject_wikilinks(body5, index, exclude_stems={"CRM/john-smith"})
        assert "[[" not in result5, f"Self-link not excluded: {result5}"
        print(f"[T5] exclude_stems  PASS")

        # T6: alias linking
        body6 = "Talked to Jane D about the project."
        result6 = inject_wikilinks(body6, index)
        assert "CRM/jane-doe" in result6, f"Alias not linked: {result6}"
        print(f"[T6] Alias linking  PASS")

    print("\nAll link_resolver.py smoke tests passed.")
