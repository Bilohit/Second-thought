from frontmatter import read_all_fields


def test_read_all_fields_basic():
    text = "---\nid: 01J8ZQ\ntitle: Call mom\norigin: note\n---\nBody\n"
    fields = read_all_fields(text)
    assert fields["id"] == "01J8ZQ"
    assert fields["title"] == "Call mom"
    assert fields["origin"] == "note"


def test_read_all_fields_no_frontmatter():
    assert read_all_fields("no frontmatter here") == {}


def test_read_all_fields_strips_quotes():
    text = '---\nid: "01J8ZQ"\n---\nBody'
    assert read_all_fields(text)["id"] == "01J8ZQ"
