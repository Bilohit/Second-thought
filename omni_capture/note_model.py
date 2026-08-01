"""
note_model.py — note-text ↔ Note codec (data-model §1, §11). Python port of the phone's
frontmatter.ts; the SAME format on both peers so a note round-trips across devices byte-for-byte.

Two hard invariants (asserted in test_note_model.py):
  1. The body below the frontmatter is byte-identical after a parse → serialize round-trip.
  2. Unknown frontmatter keys are never dropped — preserved verbatim in Note.extra.

Hand-rolled for this narrow schema (scalars, flow/block string lists, arbitrary user keys). A full
YAML engine is not a dependency we need. ponytail: nested-map frontmatter values are not expected on
notes; unknown keys are preserved as raw text, so an exotic value still round-trips verbatim rather
than being reformatted — upgrade to a YAML lib only if a real nested case appears.
"""
from __future__ import annotations

import re

from reconcile import Note
from project_registry import Registry, resolve_project
from projects import project_cache_value

# Canonical known-key serialize order (mirrors note.ts KNOWN_KEY_ORDER).
# v2.2 (2026-07-24, DESKTOP-FIRST): `category` is NOT serialized — the parent folder IS the
# category (data-model §1.2). Legacy `category:` is still parsed into note.category (ignored) but
# dropped at the note's first save; `category_source` (an unknown key riding `extra`) is filtered
# out on serialize. The phone still emits `category:` during the interim; the desktop ignores it.
# v3.1 (2026-08-01, s125): `project` joins `tags`/`attachments` as a derived body cache (contract
# §1.3) — resolved via `resolve_project(note.body, registry)` at serialize time, never stored on
# the Note struct. A legacy/hand-edited `project:` line is parsed and dropped (see parse_note),
# exactly like `category`, because the frontmatter is a cache and the body is truth.
_KNOWN_KEY_ORDER = [
    "id", "title", "origin", "created", "modified", "device", "tags", "project",
    "origin_device", "aliases", "attachments", "enriched", "enrich_source", "remind_at",
]

_KEY_LINE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_-]*):(.*)$")
# Opening `---`, the (optional) interior, closing `---`, and its trailing newline. Body = whatever
# follows (sliced past the match) so its exact bytes / line-endings survive untouched. The interior
# is one OPTIONAL group so a truly-empty block (`---\n---\n`) is recognized, not folded into the body.
_FM_BLOCK = re.compile(r"^---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|$)", re.DOTALL)


def _split_entries(fm_text: str) -> list[tuple[str, str]]:
    lines = re.split(r"\r?\n", fm_text)
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        km = _KEY_LINE.match(lines[i])
        if not km:
            i += 1
            continue  # blank / stray line
        key, raw = km.group(1), km.group(2)
        j = i + 1
        cont: list[str] = []
        while j < len(lines) and not _KEY_LINE.match(lines[j]):
            cont.append(lines[j])
            j += 1
        if cont:
            raw += "\n" + "\n".join(cont)
        entries.append((key, raw))
        i = j
    return entries


def _strip_quotes(s: str) -> str:
    t = s.strip()
    if len(t) >= 2:
        q = t[0]
        if q in ('"', "'") and t[-1] == q:
            return re.sub(r"\\([\"'\\])", r"\1", t[1:-1])
    return t


def _parse_scalar(raw: str):
    t = raw.strip()
    if t == "" or t == "null" or t == "~":
        return None
    return _strip_quotes(t)


def _split_flow(inner: str) -> list[str]:
    """Split a flow-sequence body on top-level commas, respecting quotes."""
    out: list[str] = []
    cur = ""
    quote = ""
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in ('"', "'"):
            quote = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip() != "" or out:
        out.append(cur)
    return out


def _parse_list(raw: str) -> list[str]:
    t = raw.strip()
    if t == "" or t == "[]":
        return []
    if t.startswith("[") and t.endswith("]"):
        return [x for x in (_strip_quotes(y) for y in _split_flow(t[1:-1])) if x != ""]
    items: list[str] = []
    for line in re.split(r"\r?\n", raw):
        m = re.match(r"^\s*-\s+(.*)$", line)
        if m:
            items.append(_strip_quotes(m.group(1)))
    if items:
        return items
    one = _strip_quotes(t)  # single bare scalar → one-element list
    return [] if one == "" else [one]


def parse_note(raw_file: str) -> Note:
    """Parse a note file's text into a Note. Body is captured verbatim (byte-preserved)."""
    m = _FM_BLOCK.match(raw_file)
    fm_text = (m.group(1) or "") if m else ""  # group(1) is None for an empty `---\n---\n` block
    body = raw_file[m.end():] if m else raw_file

    note = Note(
        id="", created="", origin="note", title="", aliases=[], tags=[], remind_at=None,
        category=None, origin_device=None, enriched=False, enrich_source=None, modified="", device="",
        attachments=[], extra={}, body=body,
    )

    for key, raw in _split_entries(fm_text):
        if key == "id":
            note.id = _parse_scalar(raw) or ""
        elif key == "created":
            note.created = _parse_scalar(raw) or ""
        elif key == "modified":
            note.modified = _parse_scalar(raw) or ""
        elif key == "device":
            note.device = _parse_scalar(raw) or ""
        elif key == "title":
            note.title = _parse_scalar(raw) or ""
        elif key == "origin":
            note.origin = "capture" if _parse_scalar(raw) == "capture" else "note"
        elif key == "category":
            note.category = _parse_scalar(raw)
        elif key == "project":
            # v3.1: derived cache, never trusted from disk — dropped on read exactly like
            # `category`. Re-derived from the body at serialize_note's next save.
            pass
        elif key == "origin_device":
            v = _parse_scalar(raw)
            note.origin_device = v if v in ("phone", "desktop", "shared") else None
        elif key == "enriched":
            note.enriched = _parse_scalar(raw) == "true"
        elif key == "enrich_source":
            v = _parse_scalar(raw)
            note.enrich_source = v if v in ("phone-heuristic", "desktop-llm") else None
        elif key == "remind_at":
            note.remind_at = _parse_scalar(raw)
        elif key == "tags":
            note.tags = _parse_list(raw)
        elif key == "aliases":
            note.aliases = _parse_list(raw)
        elif key == "attachments":
            note.attachments = _parse_list(raw)
        else:
            note.extra[key] = raw  # preserve unknown key verbatim (raw includes leading space)
    return note


def _needs_quote(v: str) -> bool:
    return (
        v == ""
        or re.search(r'[:#\[\]{}",\n]', v) is not None
        or re.search(r"^\s|\s$", v) is not None
    )


def _emit_scalar(v: str) -> str:
    if not _needs_quote(v):
        return v
    return '"' + re.sub(r'([\\"])', r"\\\1", v) + '"'


def _emit_list(items: list[str]) -> str:
    return "[" + ", ".join(_emit_scalar(x) for x in items) + "]"


def serialize_note(note: Note, registry: Registry | None = None) -> str:
    """Serialize a Note back to note-file text in canonical key order. Body appended byte-exact.

    `registry` is optional (v3.1, s125): when given, `project:` is written as the RESOLVED,
    ALWAYS-bracketed cache of the body's `#project@<name>` tag — `[research]` when it resolves,
    `[-]` when the note is loose (contract §1.3). When omitted (every pre-existing caller), no
    `project:` line is emitted — unchanged behaviour for callers that have not been wired to a
    registry yet.
    """
    lines: list[str] = []
    for key in _KNOWN_KEY_ORDER:
        if key == "id":
            lines.append(f"id: {_emit_scalar(note.id)}")
        elif key == "title":
            lines.append(f"title: {_emit_scalar(note.title)}")
        elif key == "origin":
            lines.append(f"origin: {note.origin}")
        elif key == "created":
            lines.append(f"created: {_emit_scalar(note.created)}")
        elif key == "modified":
            lines.append(f"modified: {_emit_scalar(note.modified)}")
        elif key == "device":
            lines.append(f"device: {_emit_scalar(note.device)}")
        elif key == "tags":
            lines.append(f"tags: {_emit_list(note.tags)}")
        elif key == "project":
            if registry is not None:
                lines.append(f"project: {project_cache_value(resolve_project(note.body, registry))}")
        elif key == "origin_device":
            if note.origin_device is not None:
                lines.append(f"origin_device: {note.origin_device}")
        elif key == "aliases":
            lines.append(f"aliases: {_emit_list(note.aliases)}")
        elif key == "attachments":
            lines.append(f"attachments: {_emit_list(note.attachments)}")
        elif key == "enriched":
            # parity: emit YAML lowercase, NOT Python's "True"/"False".
            lines.append(f"enriched: {'true' if note.enriched else 'false'}")
        elif key == "enrich_source":
            if note.enrich_source is not None:
                lines.append(f"enrich_source: {note.enrich_source}")
        elif key == "remind_at":
            if note.remind_at is not None:
                lines.append(f"remind_at: {_emit_scalar(note.remind_at)}")
    for k, raw in note.extra.items():
        # v2.2: `category_source` is a dead field (category is folder-derived) — never write it back,
        # so a legacy note carrying it drops it at first save.
        if k == "category_source":
            continue
        # Parsed extras keep the raw text after ":" (leading space included) — emit verbatim for
        # byte-stable round-trips. A programmatically-set value has no leading whitespace — add the
        # YAML space so the output stays valid YAML.
        sep = "" if raw == "" or raw[0] in (" ", "\t", "\n") else " "
        lines.append(f"{k}:{sep}{raw}")
    return "---\n" + "\n".join(lines) + "\n---\n" + note.body
