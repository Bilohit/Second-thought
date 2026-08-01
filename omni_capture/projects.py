"""The project tag layer (data-model contract v3.1 §1.3).

A note's project is the body tag `#project@<name>`. The tag is the ONLY truth: the `project:`
frontmatter line and the `project` index column are both derived caches of it, and both are
produced from `resolve_project` (project_registry.py) so they can never disagree.

Grammar note, deliberate: the contract writes the parser as `/#project@([^\\s]+)/` in shorthand.
This module implements it whitespace-anchored and code-stripped, matching the grammar body_tags.py
already enforces for every other tag. The bare form matches inside
`https://example.com/page#project@x`, which would file a note from a URL fragment. The phone mirror
(bodyTags.ts) must carry the identical tightening or the two peers drift. See DECISIONS §5 s125 item 7.
"""
import re

LOOSE_DIR = "_loose"

# Moved here (rather than imported from body_tags) to avoid a body_tags <-> projects import
# cycle: body_tags.py imports is_structural_tag from this module, so this module cannot import
# anything from body_tags at module level. body_tags.py imports these two back from here.
_FENCED_CODE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`[^`\n]*`")

# Whitespace-anchored, like body_tags._TAG_TOKEN. Group 2 is the name; it runs to the first
# whitespace, exactly as the contract specifies, and is NOT validated here — validity is a
# separate question (is_valid_project_name), because an invalid name must read as loose rather
# than as "no tag at all".
_PROJECT_TAG = re.compile(r"(^|\s)#project@([^\s]+)")

# Contract §1.3: narrower than the tag parser, because the name is simultaneously a tag, a TOML
# key and a directory name. The leading-character rule also makes every reserved `_`-prefixed hub
# folder (_loose, _trash, _attachments, _mobile_inbox) unreachable as a project name.
_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _strip_code(body: str) -> str:
    return _INLINE_CODE.sub(" ", _FENCED_CODE.sub(" ", body))


def parse_project_tags(body: str) -> list[str]:
    """Every `#project@` capture, in document order. Exposed so a UI can flag the two-tag case."""
    return [m.group(2) for m in _PROJECT_TAG.finditer(_strip_code(body))]


def parse_project_tag(body: str) -> str | None:
    """The note's project tag, or None. Two tags is a validation error the UI prevents; the model
    must still not crash on a hand-typed file, so the FIRST in document order wins."""
    tags = parse_project_tags(body)
    return tags[0] if tags else None


def is_valid_project_name(name: str) -> bool:
    return bool(_VALID_NAME.match(name))


def is_structural_tag(tag: str) -> bool:
    """Structural tags say where a note is FILED; descriptive tags say what it is ABOUT.
    Only descriptive tags belong in the derived `tags:` cache (contract §1, §1.3)."""
    return tag == "sys" or tag.startswith("sys/") or tag.startswith("project@")


def project_cache_value(resolved: str | None) -> str:
    """The `project:` frontmatter value. ALWAYS bracketed, ALWAYS present (contract §1)."""
    return f"[{resolved}]" if resolved else "[-]"


def note_dir_for(resolved: str | None) -> str:
    """The note's directory name. Every note stays at depth 1 so `../_attachments/` refs survive
    every move without a body rewrite (contract §1.3)."""
    return resolved if resolved else LOOSE_DIR
