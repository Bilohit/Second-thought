from note_model import parse_note, serialize_note

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
