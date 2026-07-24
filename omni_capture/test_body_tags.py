"""ISS-004 / ISS-051 (§1.1): body-#tag extractor. Ports every vector from the phone's
bodyTags.test.ts (same inputs -> same outputs) so the two parsers never drift."""
from body_tags import extract_body_tags, parse_body_attachment_refs


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
