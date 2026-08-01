import pytest

from projects import (
    LOOSE_DIR,
    is_structural_tag,
    is_valid_project_name,
    note_dir_for,
    parse_project_tag,
    parse_project_tags,
    project_cache_value,
)


def test_parses_a_simple_tag():
    assert parse_project_tag("some text #project@research more") == "research"


def test_no_tag_is_none():
    assert parse_project_tag("plain note with #ordinary tags") is None


def test_case_is_preserved_verbatim():
    assert parse_project_tag("#project@Cancer-Imaging") == "Cancer-Imaging"


def test_tag_ends_at_first_whitespace():
    assert parse_project_tag("#project@research and more") == "research"


def test_tag_must_be_whitespace_anchored_so_a_url_fragment_never_files_a_note():
    # The contract writes the parser as /#project@([^\s]+)/ in shorthand. Implemented bare, this
    # URL would file the note into project "x". See spec s1 §2.1 and DECISIONS s125 item 7.
    body = "see https://example.com/page#project@x for details"
    assert parse_project_tag(body) is None


def test_tag_inside_a_fenced_code_block_is_ignored():
    body = "intro\n```\n#project@fake\n```\nouttro"
    assert parse_project_tag(body) is None


def test_tag_inside_an_inline_code_span_is_ignored():
    assert parse_project_tag("type `#project@fake` to file it") is None


def test_two_tags_first_in_document_order_wins():
    assert parse_project_tag("#project@alpha then #project@beta") == "alpha"


def test_parse_project_tags_exposes_every_capture_for_the_ui_to_flag():
    assert parse_project_tags("#project@alpha then #project@beta") == ["alpha", "beta"]


def test_start_of_string_counts_as_anchored():
    assert parse_project_tag("#project@research") == "research"


@pytest.mark.parametrize("name", ["research", "R", "a-b_c", "Project2", "0start"])
def test_valid_names(name):
    assert is_valid_project_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["", "_loose", "_trash", "-lead", "a.b", "a/b", "a b", "café", "a@b"],
)
def test_invalid_names(name):
    # Leading `_` is rejected on purpose: it makes every reserved hub folder unreachable
    # as a project name (contract §1.3).
    assert is_valid_project_name(name) is False


def test_structural_tags():
    assert is_structural_tag("project@research") is True
    assert is_structural_tag("sys/llm-failed") is True
    assert is_structural_tag("sys") is True


def test_descriptive_tags_are_not_structural():
    assert is_structural_tag("research") is False
    assert is_structural_tag("@work") is False
    assert is_structural_tag("systems") is False       # prefix must not over-match
    assert is_structural_tag("projects") is False      # ditto


def test_cache_value_formatting():
    assert project_cache_value("research") == "[research]"
    assert project_cache_value(None) == "[-]"


def test_note_dir():
    assert note_dir_for("research") == "research"
    assert note_dir_for(None) == LOOSE_DIR
    assert LOOSE_DIR == "_loose"
