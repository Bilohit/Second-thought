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
from typing import Any

# The one intra-repo import this module may safely take at module level: path_safety imports
# nothing from omni_capture (only `re` + `pathlib`), so it cannot close a cycle back into here.
from path_safety import safe_name

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

# Windows silently strips trailing dots and spaces off a path component, so `Ideas.` and
# `Ideas ` both land in `Ideas` -- the same normalization path_safety.safe_subdir guards.
_DIR_TRAILING = re.compile(r"[. ]+$")


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


def is_valid_project_dir(name: Any) -> bool:
    """Contract §13.1 (v3.2): is `name` usable as a project's OPTIONAL `dir` — its home on disk?

    A project's HANDLE (its name) and its HOME (its directory) are separate. `_VALID_NAME` is a
    constraint on the TAG: a `#hashtag` ends at the first whitespace, so `#project@My Notes`
    would parse as `My` and silently lose the rest. A directory has no such constraint, so this
    rule is much wider — notably it admits SPACES, which is the entire point.

    It is nonetheless narrower than §13.1's prose ("one path segment, no `/` `\\` `..`, not
    empty, not `.`-leading, not reserved"), by exactly one clause: the value must also survive
    `path_safety.safe_name` unchanged. That is not decoration. `scratchpad.approve_scratchpad_item`
    joins this directory through `path_safety.safe_subdir`, which NEUTRALIZES rather than refuses
    (`R&D` -> `R_D`), so a `dir` that `safe_name` would rewrite makes the scratchpad approve path
    file a note into a DIFFERENT directory from the one the tidy and sync passes compute — the
    exact silent-relocation defect `dir` exists to prevent. Refusing such a name instead is
    contract-safe: §13.1's refusal path leaves the notes byte-identical and reports the folder.

    On top of `safe_name` (which already neutralizes `/`, `\\` and the drive colon, so no
    separator, traversal or anchor can survive equality):
      - no leading `_`, the SAME mechanism §1.3 uses to keep every reserved hub folder
        (`_loose`, `_trash`, `_attachments`, `_mobile_inbox`, `_scratchpad`) unreachable — a
        prefix rule, so a reserved folder added later is covered without editing a list here.
      - no leading `.`: hidden on posix, and the vault root's own sidecars are dotfiles. This
        also disposes of `.` and `..`, which `safe_name` passes through untouched.
      - no trailing dot or space, which Windows silently strips into a different directory.
    """
    if not isinstance(name, str) or not name:
        return False
    if name[0] in ("_", "."):
        return False
    if _DIR_TRAILING.sub("", name) != name:
        return False
    return safe_name(name) == name


def is_structural_tag(tag: str) -> bool:
    """Structural tags say where a note is FILED; descriptive tags say what it is ABOUT.
    Only descriptive tags belong in the derived `tags:` cache (contract §1, §1.3)."""
    return tag == "sys" or tag.startswith("sys/") or tag.startswith("project@")


def project_cache_value(resolved: str | None) -> str:
    """The `project:` frontmatter value. ALWAYS bracketed, ALWAYS present (contract §1)."""
    return f"[{resolved}]" if resolved else "[-]"


def note_dir_for(resolved: str | None, reg: dict | None = None) -> str:
    """The note's directory name. Every note stays at depth 1 so `../_attachments/` refs survive
    every move without a body rewrite (contract §1.3).

    `reg` is the loaded registry (`project_registry.Registry`, a plain dict) and is OPTIONAL:
    without it — and for every project that carries no `dir` — the directory IS the name, exactly
    as before. With a `dir` (contract §13.1, v3.2) the project's HOME is that directory instead,
    which is what lets an imported folder called `My Notes` keep its own name while its tag stays
    the whitespace-free `#project@My-Notes`.

    Read structurally rather than through `project_registry`: that module imports
    `is_valid_project_name` from this one, so importing it back here would be a cycle. Every
    production caller already computes `note_dir_for(resolve_project(body, reg))`, so `reg` is
    always in hand at the call site.

    A `dir` that fails validation is IGNORED, not honoured and not raised on — a note must still
    have a home when a hand-edited or future-peer-written registry carries a bad value.
    """
    if not resolved:
        return LOOSE_DIR
    if reg:
        entry = (reg.get("projects") or {}).get(resolved)
        if isinstance(entry, dict) and is_valid_project_dir(entry.get("dir")):
            return entry["dir"]
    return resolved
