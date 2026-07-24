"""ISS-051 §3: the machine-managed trailing `tags:` body line — the ONE body region a machine may
write (desktop-origin content only), and the highest-risk body-sacred path. These tests pin the two
invariants that keep it safe:
  1. Round-trip: strip(apply(body, tags)) == strip(body)  — the user body is recovered byte-exact.
  2. Idempotence: apply(apply(body, tags), tags) == apply(body, tags).
"""
from machine_tags import apply_trailing_tags_line, strip_trailing_tags_line


def test_apply_appends_trailing_tags_line_with_blank_separator():
    body = "My note body.\n"
    out = apply_trailing_tags_line(body, ["coding", "python"])
    assert out == "My note body.\n\ntags: #coding #python\n"


def test_apply_with_no_tags_returns_base_unchanged():
    assert apply_trailing_tags_line("plain body\n", []) == "plain body\n"


def test_strip_recovers_user_body_byte_exact():
    body = "Line one.\nLine two.\n"
    applied = apply_trailing_tags_line(body, ["a", "b"])
    assert strip_trailing_tags_line(applied) == body


def test_strip_is_noop_when_no_machine_line():
    assert strip_trailing_tags_line("just a body\n") == "just a body\n"


def test_apply_is_idempotent():
    body = "content\n"
    once = apply_trailing_tags_line(body, ["x", "y"])
    twice = apply_trailing_tags_line(once, ["x", "y"])
    assert twice == once


def test_re_enrich_replaces_the_line_user_body_survives():
    body = "The sacred body.\n"
    first = apply_trailing_tags_line(body, ["old"])
    second = apply_trailing_tags_line(first, ["new", "fresh"])
    assert second == "The sacred body.\n\ntags: #new #fresh\n"
    assert strip_trailing_tags_line(second) == body


def test_apply_empty_tags_strips_an_existing_line():
    body = "body\n"
    tagged = apply_trailing_tags_line(body, ["a"])
    assert apply_trailing_tags_line(tagged, []) == body


def test_user_tags_line_not_at_end_is_left_untouched():
    # a `tags:` line in the MIDDLE of the body is user content, never the machine's trailing line
    body = "tags: #mine\n\nmore body below\n"
    assert strip_trailing_tags_line(body) == body


def test_preserves_namespaced_and_context_tags():
    out = apply_trailing_tags_line("b\n", ["area/health", "@work", "project:x"])
    assert out == "b\n\ntags: #area/health #@work #project:x\n"
    assert strip_trailing_tags_line(out) == "b\n"
