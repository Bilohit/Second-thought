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

from machine_tags import apply_trailing_tags_line, strip_trailing_tags_line
from reconcile import Note
from project_registry import Registry, resolve_project
from projects import is_valid_project_name, parse_project_tag, project_cache_value

# Canonical known-key serialize order (mirrors note.ts KNOWN_KEY_ORDER).
# Legacy `category:` is IGNORED on read and dropped at the note's first save — Projects S1 does no
# migration (plan Step B rule 5). `category_source` (an unknown key riding `extra`) is filtered out
# on serialize. The phone may still emit `category:` during the interim; the desktop ignores it.
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
        origin_device=None, enriched=False, enrich_source=None, modified="", device="",
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
        elif key in ("category", "project"):
            # `category` is a retired concept and `project:` is a derived cache: neither is ever
            # trusted from disk. Both are dropped on read and `project:` is re-derived from the
            # body at serialize_note's next save (contract §1.3).
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
        # `category_source` is a dead field from the retired category concept — never write it
        # back, so a legacy note carrying it drops it at first save.
        if k == "category_source":
            continue
        # Parsed extras keep the raw text after ":" (leading space included) — emit verbatim for
        # byte-stable round-trips. A programmatically-set value has no leading whitespace — add the
        # YAML space so the output stays valid YAML.
        sep = "" if raw == "" or raw[0] in (" ", "\t", "\n") else " "
        lines.append(f"{k}:{sep}{raw}")
    return "---\n" + "\n".join(lines) + "\n---\n" + note.body


# --- the based project request (design §4) -------------------------------------------------
# `project_request` / `project_request_base` / `project_request_at` are MACHINE-owned frontmatter,
# so they ride `extra` verbatim through every parse/serialize and need no Note field. They are the
# only way one device asks the OTHER to re-project a note: the tag itself is written solely by the
# device that authored the note.
_REQUEST_KEYS = ("project_request", "project_request_base", "project_request_at")


def _unwrap_request_value(raw: str | None) -> str | None:
    """`[name]` -> `"name"`; `[-]`, `[]` and None -> None. Mirrors the phone's parseProjectValue.

    The `.strip()` is load-bearing, not cosmetic: `extra` keeps the raw text after the colon with
    its leading space, so ` [research]` and `[research]` must read as the same request.
    """
    if raw is None:
        return None
    inner = raw.strip().lstrip("[").rstrip("]").strip()
    return None if inner in ("", "-") else inner


def apply_project_request(note: Note) -> Note | None:
    """Apply a pending project request to a note THIS device authored (design §4).

    Returns the mutated note, or None when there is nothing to do (no request, or the note was
    authored elsewhere). A STALE request -- one whose base no longer matches the note's current
    body tag -- is CLEARED, never applied: without that, a request that sat in a shut-down
    desktop's inbox for three weeks silently reverses a decision the user already made, and the
    sync log shows a normal successful merge.

    The three keys are cleared on every outcome the desktop owns (applied, stale, refused), so a
    request is never retried forever. Body-sacred: the only write is the machine's single trailing
    `tags:` line (ISS-051 §3), and everything above it is asserted byte-identical.
    """
    desired_raw = note.extra.get("project_request")
    if desired_raw is None or "project_request_at" not in note.extra:
        return None

    # The same provenance gate the enrichment pass already ships (mobile_sync_agent.py:1481-1484).
    # Narrower by one value on purpose: `shared`/legacy notes are claimable only on an EXPLICIT
    # user action, and this applier only ever runs in a background pass.
    effective_origin = note.origin_device or (
        "phone" if note.enrich_source == "phone-heuristic" else "desktop"
    )
    if effective_origin != "desktop":
        return None

    # Read BOTH values before clearing: popping first would make `base` unconditionally None, which
    # reads as "stale" for every note that already carries a tag -- i.e. it would discard exactly
    # the requests that are freshest.
    desired = _unwrap_request_value(desired_raw)
    base = _unwrap_request_value(note.extra.get("project_request_base"))
    for key in _REQUEST_KEYS:
        note.extra.pop(key, None)

    current = parse_project_tag(note.body)
    if current != base or current == desired:
        return note  # stale, or already satisfied: cleared, body untouched
    if desired is not None and not is_valid_project_name(desired):
        return note  # refused, cleared, body untouched

    # The user's own `#project@` tag wins outright -- never reclassified, never overwritten
    # (contract §1.3: the tag IS the truth). Same clause, same idiom as the enrichment pass
    # (mobile_sync_agent.py:1490-1494): the question is asked of the body ABOVE the machine's
    # trailing tags line, because the machine's own tag lives ON that line and reading the whole
    # body would refuse every already-filed note. Without this the applier appends a SECOND
    # `#project@` -- a two-tag note (`projects.py:54`: "a validation error the UI prevents") whose
    # user tag still wins by document order, so the request reads as applied and changed nothing.
    user_body = strip_trailing_tags_line(note.body)
    if parse_project_tag(user_body) is not None:
        return note  # user-tagged, cleared, body untouched

    note.body = apply_trailing_tags_line(note.body, [f"project@{desired}"] if desired else [])
    assert strip_trailing_tags_line(note.body) == user_body, \
        "apply_project_request: body-sacred violation above the trailing tag line"
    return note
