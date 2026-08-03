"""ISS-004 / ISS-051 (§1.1): body-#tag extractor. Ports every vector from the phone's
bodyTags.test.ts (same inputs -> same outputs) so the two parsers never drift."""
from body_tags import (
    attachment_ref_text,
    derive_body_attachments,
    extract_body_tags,
    is_valid_body_tag,
    parse_body_attachment_refs,
)


def test_single_tag_at_start():
    assert extract_body_tags("#welcome") == ["welcome"]


def test_multiple_tags_separated_by_whitespace():
    assert extract_body_tags("Some note text. #demo #howto") == ["demo", "howto"]


def test_dedupes_repeated_tags_first_seen_order():
    assert extract_body_tags("#work later #life then back to #work") == ["work", "life"]


def test_nested_and_hyphenated_tags():
    assert extract_body_tags("#work/planning/q3 and #well-being") == ["work/planning/q3", "well-being"]


def test_never_matches_markdown_heading():
    assert extract_body_tags("## Notes\nSome body text.") == []
    assert extract_body_tags("# Title\nBody.") == []


def test_never_matches_url_fragment():
    assert extract_body_tags("See https://example.com/page#section for details.") == []


def test_ignores_hash_inside_fenced_code_block():
    body = "Before\n```\n#define FOO 1\n```\nAfter #real"
    assert extract_body_tags(body) == ["real"]


def test_ignores_hash_inside_inline_code_span():
    assert extract_body_tags("Use `#notatag` here but #real works") == ["real"]


# ISS-051 §1.1: full action-tag grammar vectors (mirrors the phone parser's exact vectors).
def test_finds_plain_tags():
    assert extract_body_tags("#work #python") == ["work", "python"]


def test_excludes_markdown_heading_hash_and_space():
    assert extract_body_tags("# Heading") == []


def test_excludes_bare_hex_color_tokens():
    assert extract_body_tags("pick #fff or #a1b2c3") == []


def test_supports_namespaced_tag():
    assert extract_body_tags("#area/health") == ["area/health"]


def test_supports_key_value_action_meta_tags():
    assert extract_body_tags("#project:work #status:next") == ["project:work", "status:next"]


def test_supports_gtd_context_tag():
    assert extract_body_tags("#@work") == ["@work"]


def test_supports_alias_tag():
    assert extract_body_tags("#alias:call-mom") == ["alias:call-mom"]


def test_supports_ttl_and_priority_tags():
    assert extract_body_tags("#ttl:30d #priority:p1") == ["ttl:30d", "priority:p1"]


def test_excludes_url_fragment():
    assert extract_body_tags("see https://x.com/p#frag") == []


def test_excludes_tags_inside_fenced_code_block():
    assert extract_body_tags("```\n#notag\n```") == []


def test_excludes_tags_inside_inline_code_span():
    assert extract_body_tags("inline `#notag` here") == []


def test_captures_tags_on_trailing_tags_line_not_the_word_itself():
    assert extract_body_tags("tags: #code #python") == ["code", "python"]


def test_dedupes_a_a_to_single_tag():
    assert extract_body_tags("#a #a") == ["a"]


def test_excludes_mid_word_hash():
    assert extract_body_tags("word#notag") == []


# Task 7: structural tags (contract v3.1 §1, §1.3) are excluded from the derived `tags:` cache.
def test_project_tag_is_excluded_from_the_derived_cache():
    # `tags:` holds DESCRIPTIVE vocabulary only — what a note is ABOUT. `#project@x` is
    # STRUCTURAL: it says where the note is FILED.
    tags = extract_body_tags("#research and #project@cancer-imaging")
    assert "research" in tags
    assert not any(t.startswith("project@") for t in tags)


def test_sys_tags_are_excluded():
    assert "sys/llm-failed" not in extract_body_tags("#sys/llm-failed #real")


def test_gtd_context_tags_still_survive():
    # `@` is in the token charset FOR these; the exclusion must not over-reach.
    assert "@work" in extract_body_tags("call them #@work")


def test_a_tag_merely_starting_with_project_is_not_structural():
    assert "projects" in extract_body_tags("#projects")


# v2.2 (data-model §1.2): inline attachment refs → derived `attachments:`. Mirrors the phone's
# parseBodyAttachmentRefs vectors so the two derivations never drift.
def test_attachment_ref_extracts_filename():
    body = "before\n\n![a memo](../_attachments/note1/memo-0712.m4a)\n\nafter"
    assert parse_body_attachment_refs(body) == ["memo-0712.m4a"]


def test_attachment_refs_multiple_first_seen_order():
    body = "![](../_attachments/n/a.png)\ntext\n![cap](../_attachments/n/b.jpg)"
    assert parse_body_attachment_refs(body) == ["a.png", "b.jpg"]


def test_attachment_ref_dedupes_repeat():
    body = "![](../_attachments/n/a.png)\n![again](../_attachments/n/a.png)"
    assert parse_body_attachment_refs(body) == ["a.png"]


def test_attachment_ref_ignores_non_attachment_images():
    body = "![x](https://example.com/y.png)\n![z](images/z.png)\n![w](../other/w.png)"
    assert parse_body_attachment_refs(body) == []


def test_attachment_ref_ignores_malformed_no_filename():
    body = "![x](../_attachments/)\n![y](../_attachments/idonly)"
    assert parse_body_attachment_refs(body) == []


def test_attachment_ref_filename_with_spaces():
    assert parse_body_attachment_refs("![beach](../_attachments/n/beach day.jpg)") == ["beach day.jpg"]


def test_attachment_ref_none_returns_empty():
    assert parse_body_attachment_refs("just prose with a #tag") == []


# derive_body_attachments: union of inline refs + legacy `[attachment: file]` lines, first-seen
# order, deduped. Mirrors the phone's deriveBodyAttachments vectors (attachments.ts:68).
def test_derive_inline_only():
    body = "before\n![a memo](../_attachments/n/memo.m4a)\nafter"
    assert derive_body_attachments(body) == ["memo.m4a"]


def test_derive_legacy_only():
    body = "before\n[attachment: memo.m4a]\nafter"
    assert derive_body_attachments(body) == ["memo.m4a"]


def test_derive_both_inline_first_then_legacy():
    body = (
        "![a](../_attachments/n/a.png)\n"
        "[attachment: b.jpg]\n"
        "![c](../_attachments/n/c.png)\n"
        "[attachment: d.m4a]"
    )
    assert derive_body_attachments(body) == ["a.png", "c.png", "b.jpg", "d.m4a"]


def test_derive_dedupes_across_both_forms():
    body = "![x](../_attachments/n/shared.png)\n[attachment: shared.png]"
    assert derive_body_attachments(body) == ["shared.png"]


def test_derive_ignores_external_and_other_dir_images():
    body = "![x](https://example.com/y.png)\n![z](images/z.png)\n![w](../other/w.png)"
    assert derive_body_attachments(body) == []


def test_derive_legacy_filename_with_space_survives():
    body = "[attachment: beach day.jpg]"
    assert derive_body_attachments(body) == ["beach day.jpg"]


# attachment_ref_text: inverse of derive_body_attachments; round-trip must recover the filename.
def test_attachment_ref_text_default_alt_audio():
    assert attachment_ref_text("note1", "memo.m4a") == "![voice memo](../_attachments/note1/memo.m4a)"


def test_attachment_ref_text_default_alt_non_audio():
    assert attachment_ref_text("note1", "pic.png") == "![photo](../_attachments/note1/pic.png)"


def test_attachment_ref_text_explicit_alt():
    assert attachment_ref_text("note1", "pic.png", "beach") == "![beach](../_attachments/note1/pic.png)"


def test_attachment_ref_text_round_trips_through_derive():
    text = attachment_ref_text("note1", "beach day.jpg", "beach")
    assert derive_body_attachments(text) == ["beach day.jpg"]
    assert parse_body_attachment_refs(text) == ["beach day.jpg"]


# -- is_valid_body_tag (SP3 Task 10) ------------------------------------------
# The settings field lets the user name the daily tag, so validation must agree with what the
# scanner above ACTUALLY keeps -- including its two silent drops.

def test_valid_body_tag_accepts_ordinary_shapes():
    for t in ("daily", "work", "area/health", "@work", "project:work", "a-b", "x_1", "D"):
        assert is_valid_body_tag(t), t


def test_valid_body_tag_rejects_what_the_scanner_would_mangle():
    for t in ("", "my tag", "two words", "#daily", "-lead", "/lead", "tag!", "tag.md"):
        assert not is_valid_body_tag(t), t


def test_valid_body_tag_rejects_the_hex_colour_silent_drop():
    # The scanner drops these as bare colours, so saving one would give a tag line indexing nothing.
    for t in ("abc", "fff", "a1b2c3", "DEADBE"):
        assert not is_valid_body_tag(t), t
    assert is_valid_body_tag("abcd")      # 4 digits is not a colour shape
    assert is_valid_body_tag("daily")     # letters outside hex are fine


def test_valid_body_tag_rejects_structural_tags():
    # project@x would FILE the note into a project -- this field is never a back door into that.
    for t in ("sys", "sys/llm-failed", "project@work", "project@_loose"):
        assert not is_valid_body_tag(t), t


def test_valid_body_tag_agrees_with_the_scanner_round_trip():
    """The property that makes the two impossible to drift: a tag is valid IFF writing `#<tag>`
    into a body yields exactly that tag back."""
    candidates = [
        "daily", "work", "area/health", "@work", "project:work", "a-b", "x_1", "abcd", "D",
        "abc", "fff", "a1b2c3", "sys", "sys/x", "project@work",
        "my tag", "", "#daily", "-lead", "tag!", "tag.md", "two words",
    ]
    for t in candidates:
        assert is_valid_body_tag(t) == (extract_body_tags("#" + t) == [t]), t
