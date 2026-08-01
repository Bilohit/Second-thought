from note_model import parse_note, serialize_note
from project_registry import empty_registry

SAMPLE = """---
id: 01J8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8
title: Call mom re taxes
origin: note
created: 2026-07-07T10:00:00Z
modified: 2026-07-07T10:05:00Z
device: phone-a1b2
tags: [family, finance]
category: personal
aliases: []
attachments:
  - audio-100500.m4a
enriched: false
enrich_source: phone-heuristic
remind_at: 2026-07-08T09:00:00Z
custom_user_key: keep me
---
# Heading

Body line with a colon: not frontmatter.

- checklist item
"""


# --- parse ---
def test_parses_scalar_fields():
    n = parse_note(SAMPLE)
    assert n.id == "01J8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8"
    assert n.title == "Call mom re taxes"
    assert n.origin == "note"
    assert n.category == "personal"
    assert n.enriched is False
    assert n.enrich_source == "phone-heuristic"
    assert n.remind_at == "2026-07-08T09:00:00Z"


def test_parses_flow_and_block_lists():
    n = parse_note(SAMPLE)
    assert n.tags == ["family", "finance"]
    assert n.aliases == []
    assert n.attachments == ["audio-100500.m4a"]


def test_preserves_unknown_keys_verbatim():
    n = parse_note(SAMPLE)
    assert n.extra["custom_user_key"] == " keep me"


def test_keeps_body_verbatim_with_colon_and_trailing_newline():
    n = parse_note(SAMPLE)
    assert n.body == "# Heading\n\nBody line with a colon: not frontmatter.\n\n- checklist item\n"


# --- round-trip ---
def test_body_byte_identical_after_roundtrip():
    n = parse_note(SAMPLE)
    out = serialize_note(n)
    assert parse_note(out).body == n.body


def test_unknown_key_survives_reserialize():
    out = serialize_note(parse_note(SAMPLE))
    assert "custom_user_key: keep me" in out


def test_known_fields_roundtrip_losslessly():
    a = parse_note(SAMPLE)
    b = parse_note(serialize_note(a))
    assert b.tags == a.tags
    assert b.attachments == a.attachments
    assert b.remind_at == a.remind_at
    assert b.enrich_source == a.enrich_source
    assert b.extra["custom_user_key"] == a.extra["custom_user_key"]


def test_quotes_special_char_title_and_reads_back():
    a = parse_note(SAMPLE)
    a.title = "Re: taxes, part #2"
    b = parse_note(serialize_note(a))
    assert b.title == "Re: taxes, part #2"


def test_omits_remind_at_when_null():
    a = parse_note(SAMPLE)
    a.remind_at = None
    assert "remind_at:" not in serialize_note(a)


def test_enriched_emits_lowercase_bool():
    # parity trap: Python bool stringifies True/False — must round-trip as YAML true/false
    a = parse_note(SAMPLE)
    a.enriched = True
    out = serialize_note(a)
    assert "enriched: true" in out
    assert "enriched: True" not in out
    assert parse_note(out).enriched is True


# --- edge cases ---
def test_no_frontmatter_is_pure_body():
    n = parse_note("just body\nno frontmatter\n")
    assert n.body == "just body\nno frontmatter\n"
    assert n.id == ""


def test_block_form_tag_list():
    n = parse_note("---\nid: x\ntags:\n  - a\n  - b\n---\nbody")
    assert n.tags == ["a", "b"]


def test_crlf_body_preserved():
    n = parse_note("---\r\nid: x\r\n---\r\nline1\r\nline2\r\n")
    assert n.id == "x"
    assert n.body == "line1\r\nline2\r\n"


def test_does_not_swallow_dashes_in_body():
    n = parse_note("---\nid: x\n---\nbefore\n---\nafter\n")
    assert n.body == "before\n---\nafter\n"


def test_recognizes_empty_frontmatter_block():
    n = parse_note("---\n---\nbody\n")
    assert n.body == "body\n"
    assert n.id == ""


def test_serialize_reconcile_roundtrip_body_sacred():
    # the sync loop parses -> reconciles -> serializes; body must survive that path byte-exact
    n = parse_note(SAMPLE)
    round_tripped = parse_note(serialize_note(n))
    assert round_tripped.body == n.body


# v2.2 / ISS-051 §2.1: origin_device provenance field round-trip (mirrors the phone codec).
def test_parses_origin_device():
    n = parse_note("---\nid: x\norigin_device: desktop\n---\nbody\n")
    assert n.origin_device == "desktop"


def test_origin_device_absent_is_none():
    assert parse_note("---\nid: x\n---\nbody\n").origin_device is None


def test_origin_device_invalid_is_none():
    assert parse_note("---\nid: x\norigin_device: martian\n---\nbody\n").origin_device is None


def test_origin_device_serializes_and_round_trips_all_values():
    for v in ("phone", "desktop", "shared"):
        n = parse_note("---\nid: x\n---\nbody\n")
        n.origin_device = v
        out = serialize_note(n)
        assert f"origin_device: {v}" in out
        assert parse_note(out).origin_device == v


def test_origin_device_omitted_when_none():
    n = parse_note("---\nid: x\n---\nbody\n")
    assert "origin_device:" not in serialize_note(n)


def test_origin_device_not_leaked_into_extra():
    n = parse_note("---\nid: x\norigin_device: phone\n---\nbody\n")
    assert "origin_device" not in n.extra


# v2.2 (2026-07-24, DESKTOP-FIRST): category is folder-derived — never serialized on desktop.
# Legacy `category:` is still parsed (ignored) but dropped at first save; `category_source` too.
def test_category_never_serialized_even_when_set():
    n = parse_note(SAMPLE)          # SAMPLE carries `category: personal`
    assert n.category == "personal"  # still parsed into the struct (legacy read)
    out = serialize_note(n)
    assert "category:" not in out    # ...but never written back to disk


def test_category_source_dropped_from_disk_at_first_save():
    n = parse_note("---\nid: x\ncategory: work\ncategory_source: user\n---\nbody\n")
    out = serialize_note(n)
    assert "category:" not in out
    assert "category_source:" not in out
    # the round-trip is clean — neither legacy field survives
    assert "category_source" not in parse_note(out).extra


def test_programmatically_set_category_is_not_written():
    n = parse_note("---\nid: x\n---\nbody\n")
    n.category = "ideas"             # a reader may stamp the folder name onto the struct
    assert "category:" not in serialize_note(n)


# v3.1 (2026-08-01, s125): `project` is a derived body cache, recomputed at serialize_note's same
# trigger point as `tags`/`attachments` — resolved from note.body via resolve_project(body, registry).
def _registry_with(*names: str) -> dict:
    reg = empty_registry()
    for name in names:
        reg["projects"][name] = {"description": "", "created": "", "modified": "", "device": ""}
    return reg


def test_project_line_is_written_bracketed_when_resolved():
    reg = _registry_with("research")
    n = parse_note("---\nid: x\n---\n#project@research\n\nbody\n")
    serialized = serialize_note(n, reg)
    assert "project: [research]" in serialized


def test_loose_notes_get_an_explicit_marker_never_an_absent_line():
    reg = _registry_with("research")
    n = parse_note("---\nid: x\n---\nno project tag here\n")
    serialized = serialize_note(n, reg)
    assert "project: [-]" in serialized


def test_a_dangling_tag_caches_as_loose():
    # The value written is the RESOLVED project, so an unregistered tag caches as [-] —
    # because that note IS loose (contract §1.3).
    reg = _registry_with("research")   # "unregistered" is NOT in the registry
    n = parse_note("---\nid: x\n---\n#project@unregistered\n\nbody\n")
    serialized = serialize_note(n, reg)
    assert "project: [-]" in serialized


def test_hand_edited_project_line_is_overwritten_from_the_body():
    # Identical to how `tags:` behaves today: the frontmatter is a cache, the body is truth.
    reg = _registry_with("research")
    n = parse_note("---\nid: x\nproject: [some-other-project]\n---\n#project@research\n\nbody\n")
    serialized = serialize_note(n, reg)
    assert "project: [research]" in serialized
    assert "project: [some-other-project]" not in serialized


def test_deleting_the_project_line_rebuilds_it_losslessly():
    reg = _registry_with("research")
    # no `project:` line at all in the source text
    n = parse_note("---\nid: x\n---\n#project@research\n\nbody\n")
    assert "project" not in n.extra
    serialized = serialize_note(n, reg)
    assert "project: [research]" in serialized


def test_the_body_is_byte_identical_after_a_recompute():
    # Mandatory on every non-editor op, both repos.
    reg = _registry_with("research")
    before = parse_note("---\nid: x\nproject: [stale]\n---\n#project@research\n\nbody\n")
    before_body_bytes = before.body
    after = parse_note(serialize_note(before, reg))
    after_body_bytes = after.body
    assert after_body_bytes == before_body_bytes


def test_project_omitted_when_no_registry_given():
    # Pre-existing callers (not yet wired to a registry) keep today's behaviour unchanged.
    n = parse_note("---\nid: x\n---\n#project@research\n\nbody\n")
    assert "project:" not in serialize_note(n)
