"""
test_tag_index.py — A1: the Tags view's counts and its listing agree.

They used to resolve through different sources: counts from a vault scan,
listing from `captures.db WHERE tags LIKE '%"x"%'`. The `tags` column is only
ever written by log_capture_db (the capture pipeline), so every `origin: note`
file -- which reaches the DB through upsert_capture_from_file -- had it empty,
and a namespace row (`project/`) matched no literal tag at all. Both showed a
count with an empty result list. Both sides now resolve through tag_index.
"""
import tempfile
from pathlib import Path

import pytest

from index_writer import init_db, search, upsert_capture_from_file
from tag_index import parse_tags, resolve_paths, scan_tag_paths
from vault_admin import _build_tag_tree


def _note(vault: Path, category: str, name: str, tags_block: str, origin: str = "note") -> Path:
    d = vault / category
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(
        f"---\ntitle: {name}\ncategory: {category}\norigin: {origin}\n{tags_block}\n---\n"
        f"# {name}\n\nBody of {name}.\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def vault():
    """A vault whose tags previously made count and listing disagree:
    editor-created notes (tags never reach the DB column) with nested tags
    (no tag is literally spelled `project/`)."""
    tmp = Path(tempfile.mkdtemp())
    _note(tmp, "Tech_Notes", "alpha", "tags: [project/alpha, reading]")
    _note(tmp, "Tech_Notes", "beta", "tags: [project/beta]")
    _note(tmp, "Tech_Notes", "both", "tags: [project/alpha, project/beta]")
    _note(tmp, "Tech_Notes", "bare", "tags: [reading]")
    # a pipeline capture: block-form frontmatter, the shape storage_engine writes
    _note(tmp, "Tech_Notes", "cap", "tags:\n  - project/alpha\n  - deep/a/b", origin="capture")
    # index every file, exactly as vault_sync does on a real vault
    init_db(tmp)
    for md in tmp.rglob("*.md"):
        upsert_capture_from_file(tmp, md)
    return tmp


def _tree_row(tree, tag):
    for node in tree:
        if node["tag"] == tag:
            return node
        for child in node.get("children", []):
            if child["tag"] == tag:
                return child
    return None


# -- the parser ---------------------------------------------------------------

def test_parse_tags_reads_inline_form():
    """Notes (editor + phone) write `tags: [a, b]`."""
    assert parse_tags("---\ntitle: t\ntags: [work, radial]\n---\nbody\n") == ["work", "radial"]


def test_parse_tags_reads_block_form():
    """Captures (storage_engine.py) write a YAML block list -- the shape
    read_all_fields() cannot see, which is why captures needed the DB half."""
    text = "---\ntitle: t\ntags:\n  - work\n  - radial\ncategory: X\n---\nbody\n"
    assert parse_tags(text) == ["work", "radial"]


def test_parse_tags_empty_and_absent():
    assert parse_tags("---\ntitle: t\ntags: []\n---\nbody\n") == []
    assert parse_tags("---\ntitle: t\n---\nbody\n") == []
    assert parse_tags("no frontmatter at all\n") == []


# -- the regression: count vs listing -----------------------------------------

@pytest.mark.parametrize("tag", ["project/alpha", "project/beta", "reading", "deep/a/b"])
def test_count_matches_listing_for_every_leaf_tag(vault, tag):
    tree = _tree_row(_build_tag_tree(scan_tag_paths(vault)), tag)
    results = search("", vault, tag=tag, limit=100)
    assert tree is not None, f"{tag} missing from the tree"
    assert tree["count"] > 0
    assert tree["count"] == len(results)


def test_note_tags_are_listed_at_all(vault):
    """The core A1 bug: an `origin: note` tag counted but listed nothing.
    upsert_capture_from_file now DOES write the `tags` column from frontmatter
    (R-2: a rebuild used to blank it, decaying tag_vocab), so the column is no
    longer the empty thing it was -- but the listing must be right either way."""
    rows = init_db(vault).execute("SELECT tags FROM captures").fetchall()
    assert any((r["tags"] or "[]") != "[]" for r in rows), "R-2: tags column must be populated"
    assert len(search("", vault, tag="reading", limit=100)) == 2


def test_tag_membership_resolves_from_files_not_the_column(vault):
    """A1's actual lock, kept sharp now that the column is populated: captures.db is
    a cache in front of the files, never an authority over them. Poison the column so
    it DISAGREES with the frontmatter -- membership must still follow the files."""
    conn = init_db(vault)
    conn.execute("UPDATE captures SET tags = ?", ('["reading"]',))   # every row claims `reading`
    conn.commit()
    conn.close()

    assert len(search("", vault, tag="reading", limit=100)) == 2, (
        "listing followed the poisoned tags column instead of the vault files"
    )


def test_namespace_row_count_matches_its_listing(vault):
    """`project/` is a rolled-up row: no tag is spelled that, so `tags LIKE`
    matched nothing while its count said 3. It resolves by prefix now."""
    tree = _tree_row(_build_tag_tree(scan_tag_paths(vault)), "project/")
    results = search("", vault, tag="project/", limit=100)
    assert tree["count"] == 4          # alpha, beta, both + cap (the capture carries project/alpha)
    assert len(results) == tree["count"]


def test_namespace_count_is_distinct_notes_not_occurrences(vault):
    """`both` carries project/alpha AND project/beta -- it is one note under
    `project/`, not two. Summing child counts (the old shape) said 5."""
    tree = _tree_row(_build_tag_tree(scan_tag_paths(vault)), "project/")
    children = {c["tag"]: c["count"] for c in tree["children"]}
    assert children == {"project/alpha": 3, "project/beta": 2}
    assert sum(children.values()) == 5      # occurrences
    assert tree["count"] == 4               # distinct notes (incl. the capture)
    assert len(search("", vault, tag="project/", limit=100)) == 4


def test_captures_and_notes_are_both_counted(vault):
    """The capture's block-form tags and the notes' inline tags land in one
    tree -- no DB half needed."""
    tree = _build_tag_tree(scan_tag_paths(vault))
    assert _tree_row(tree, "deep/a/b")["count"] == 1
    assert len(search("", vault, tag="deep/a/b", limit=100)) == 1


def test_deep_tag_rolls_into_first_segment_namespace(vault):
    """The one-level display ceiling stays, but it no longer desyncs: `deep/`
    counts and lists the same note."""
    tree = _tree_row(_build_tag_tree(scan_tag_paths(vault)), "deep/")
    assert tree["count"] == len(search("", vault, tag="deep/", limit=100)) == 1


# -- resolution rules ---------------------------------------------------------

def test_unknown_tag_lists_nothing(vault):
    assert resolve_paths(vault, "nope") == set()
    assert search("", vault, tag="nope", limit=100) == []


def test_bare_tag_does_not_swallow_its_namespace(vault):
    """`reading` is exact; it must not prefix-match anything."""
    assert len(search("", vault, tag="reading", limit=100)) == 2


def test_reserved_folders_are_skipped(vault):
    """_trash/_mobile_inbox hold machine state, not browsable notes -- and the
    count side always skipped them, so the listing must too."""
    _note(vault, "_trash", "gone", "tags: [reading]")
    upsert_capture_from_file(vault, vault / "_trash" / "gone.md")
    assert "gone" not in str(resolve_paths(vault, "reading"))
    tree = _tree_row(_build_tag_tree(scan_tag_paths(vault)), "reading")
    assert tree["count"] == len(search("", vault, tag="reading", limit=100)) == 2


def test_tag_filter_still_composes_with_fts_and_category(vault):
    """The tag filter narrows the same rows the text/category filters do.
    `alpha` now matches 3 notes on text alone -- alpha.md by filename/body, plus
    both.md and cap.md whose `project/alpha` TAG is part of the indexed FTS body
    (the captures_ai/au triggers concatenate `tags`, and R-2's fix means note rows
    finally carry theirs, exactly as pipeline captures always did). Filtering to
    `reading` narrows that back to the one note that is both."""
    assert len(search("alpha", vault, tag="reading", limit=100)) == 1
    assert len(search("alpha", vault, limit=100)) == 3, "tags are part of the FTS body"
    assert len(search("", vault, tag="reading", category="Tech_Notes", limit=100)) == 2
    assert search("", vault, tag="reading", category="Nope", limit=100) == []
