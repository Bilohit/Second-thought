import pytest

from projects import (
    LOOSE_DIR,
    is_structural_tag,
    is_valid_project_dir,
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


# -- FR-33: a project's HANDLE (its tag) vs its HOME (its directory), contract §13.1 v3.2 -----

def _reg(**entries):
    return {"schema": 1, "projects": {k: dict(v) for k, v in entries.items()}}


@pytest.mark.parametrize(
    "dirname",
    # A space is the whole point: `#project@My Notes` would parse as `My`, a DIRECTORY has no
    # such constraint. Dots, unicode and inner dashes are ordinary folder names too.
    ["My Notes", "Work", "v1.2 drafts", "café", "a-b_c", "2026 Q1", "R and D"],
)
def test_valid_dirs(dirname):
    assert is_valid_project_dir(dirname) is True


@pytest.mark.parametrize(
    "dirname",
    [
        "", "_loose", "_trash", "_mobile_inbox",   # reserved, by the same leading-`_` rule as names
        ".", "..", ".hidden",                      # `.`-leading: hidden, and dotfiles are sidecars
        "a/b", "a\\b", "../evil", "C:evil",        # never more than one path segment
        "Ideas.", "Ideas ", " Ideas",              # Windows silently strips these into another name
        "R&D", "Notes (2026)",                     # `safe_name` would REWRITE these -> see below
        None, 5, [],                               # a hand-edited or foreign-peer value, not a str
    ],
)
def test_invalid_dirs(dirname):
    assert is_valid_project_dir(dirname) is False


def test_a_dir_safe_name_would_rewrite_is_refused_not_silently_rewritten():
    # scratchpad.approve_scratchpad_item joins the note dir through path_safety.safe_subdir,
    # which NEUTRALIZES rather than refuses. A `dir` that survives validation but not safe_name
    # would send that one path to a different directory than tidy/sync compute -- the exact
    # silent-relocation defect `dir` exists to prevent.
    from path_safety import safe_name
    for dirname in ("My Notes", "v1.2 drafts", "2026 Q1"):
        assert safe_name(dirname) == dirname


def test_note_dir_without_a_registry_is_unchanged():
    # The default keeps today_view's `note_dir_for(None)` calls working untouched.
    assert note_dir_for("research") == "research"
    assert note_dir_for("research", None) == "research"
    assert note_dir_for(None, None) == LOOSE_DIR


def test_note_dir_with_a_registry_that_carries_no_dir_is_unchanged():
    reg = _reg(research={"description": ""})
    assert note_dir_for("research", reg) == "research"
    assert note_dir_for(None, reg) == LOOSE_DIR
    # An unregistered name still answers with itself; resolve_project is what makes it loose.
    assert note_dir_for("elsewhere", reg) == "elsewhere"


def test_note_dir_honours_a_projects_dir():
    reg = _reg(**{"My-Notes": {"dir": "My Notes"}})
    assert note_dir_for("My-Notes", reg) == "My Notes"


def test_an_unusable_dir_is_ignored_rather_than_honoured_or_raised_on():
    # A hand-edited or foreign-peer registry must never leave a note homeless, and must never
    # hand a traversal to the caller that joins this onto the vault root.
    for bad in ("../evil", "_trash", "", None, 7):
        reg = _reg(research={"dir": bad})
        assert note_dir_for("research", reg) == "research"
