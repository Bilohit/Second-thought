from frontmatter import add_fields, read_all_fields, strip_frontmatter


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


def test_add_fields_inserts_and_preserves_body():
    text = "---\ncategory: Tech_Notes\n---\nBody line\nmore body\n"
    out = add_fields(text, {"id": "abc123", "origin": "capture"})
    fields = read_all_fields(out)
    assert fields["id"] == "abc123"
    assert fields["origin"] == "capture"
    assert fields["category"] == "Tech_Notes"          # existing field untouched
    assert strip_frontmatter(out) == strip_frontmatter(text)  # body byte-identical


def test_add_fields_no_frontmatter_is_noop():
    assert add_fields("no frontmatter here", {"id": "x"}) == "no frontmatter here"
