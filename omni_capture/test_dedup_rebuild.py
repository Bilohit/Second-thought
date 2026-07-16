"""
test_dedup_rebuild.py
---------------------
R-1: the dedup ledger must be a derived, REBUILDABLE cache.

Doctrine under test (workspace CLAUDE.md, both repos):

    "Every SQLite table, index, vector store, manifest, and dedup ledger is a
     derived, rebuildable cache."

Before this suite's fix, `dedup_index.json` was derived but unrebuildable: the
key hashes the pipeline's PRE-write text (mutated by wikilink injection +
post-processing + frontmatter before it lands on disk), and _LEDGER_FILES /
smart-merge collapse N captures into 1 file. The resolution (data-model §1.1)
persists each key into the note's `capture_keys` frontmatter, so a vault scan
rebuilds the index.

The load-bearing cases here are the ones that a naive "re-key off disk bytes"
fix could NOT have satisfied: the N->1 ledger file, and the blank capture whose
key is a random uuid4.

Run:
    python -m pytest test_dedup_rebuild.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import dedup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BODY = "# Heading\n\nSome *user* body text.\n\n- a\n- b\n\nTrailing line.\n"


def _note(vault: Path, rel: str, body: str = BODY, fm: str = "created: 2026-07-15\ncategory: Journal") -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return p


def _body_of(p: Path) -> str:
    """Everything past the frontmatter block -- the sacred bytes."""
    raw = p.read_text(encoding="utf-8")
    m = dedup._FM_BLOCK_RE.match(raw)
    return raw[m.end():] if m else raw


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    (tmp_path / ".omni_capture").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# parse / inject primitives
# ---------------------------------------------------------------------------

def test_parse_returns_empty_when_absent_or_no_frontmatter():
    assert dedup.parse_capture_keys("---\ncreated: x\n---\nbody") == []
    assert dedup.parse_capture_keys("no frontmatter at all") == []


def test_inject_then_parse_round_trips():
    raw = "---\ncreated: x\n---\nbody\n"
    out = dedup.inject_capture_keys(raw, ["aaa", "bbb"])
    assert dedup.parse_capture_keys(out) == ["aaa", "bbb"]


def test_inject_unions_and_is_idempotent():
    raw = dedup.inject_capture_keys("---\nc: x\n---\nbody\n", ["aaa"])
    again = dedup.inject_capture_keys(raw, ["aaa"])
    assert again is None, "a no-op union must not rewrite the file"
    grown = dedup.inject_capture_keys(raw, ["bbb"])
    assert dedup.parse_capture_keys(grown) == ["aaa", "bbb"]


def test_inject_returns_none_without_frontmatter():
    assert dedup.inject_capture_keys("just a body\n", ["aaa"]) is None


def test_inject_leaves_body_byte_identical():
    raw = f"---\ncreated: x\n---\n{BODY}"
    out = dedup.inject_capture_keys(raw, ["aaa"])
    assert out[out.index("---\n", 4) + 4:] == BODY


# ---------------------------------------------------------------------------
# register persists the key into the note (the actual R-1 fix)
# ---------------------------------------------------------------------------

def test_register_writes_the_key_into_the_note(vault: Path):
    p = _note(vault, "Journal/a.md")
    dedup.register_in_dedup_index("captured text", None, vault, p)
    h = dedup.content_hash("captured text", None)
    assert dedup.parse_capture_keys(p.read_text(encoding="utf-8")) == [h]


def test_register_leaves_the_body_byte_identical(vault: Path):
    p = _note(vault, "Journal/a.md")
    before = _body_of(p)
    dedup.register_in_dedup_index("captured text", "https://example.com/x", vault, p)
    assert _body_of(p) == before, "BODY-SACRED LOCK: register must touch frontmatter only"


# ---------------------------------------------------------------------------
# The headline: delete the ledger, rebuild it from the vault alone
# ---------------------------------------------------------------------------

def test_delete_ledger_then_rebuild_restores_the_mapping(vault: Path):
    p1 = _note(vault, "Journal/a.md")
    p2 = _note(vault, "Tech/b.md")
    dedup.register_in_dedup_index("alpha text", None, vault, p1)
    dedup.register_in_dedup_index("beta text", "https://example.com/b", vault, p2)
    before = dedup._load_dedup_index(vault)
    assert len(before) == 2

    dedup._dedup_index_path(vault).unlink()
    assert dedup._load_dedup_index(vault) == {}, "precondition: ledger is gone"

    recovered = dedup.rebuild_dedup_index(vault)
    assert recovered == 2
    assert dedup._load_dedup_index(vault) == before, "rebuild must reproduce the exact mapping"


def test_rebuilt_ledger_still_answers_check_duplicate(vault: Path):
    """The point of the ledger is dedup RECOGNITION -- assert the behavior, not just the bytes."""
    p = _note(vault, "Journal/a.md")
    dedup.register_in_dedup_index("alpha text", None, vault, p)
    dedup._dedup_index_path(vault).unlink()
    dedup.rebuild_dedup_index(vault)
    assert dedup.check_duplicate("alpha text", None, vault) == str(Path("Journal") / "a.md")


def test_rebuild_is_idempotent(vault: Path):
    p = _note(vault, "Journal/a.md")
    dedup.register_in_dedup_index("alpha text", None, vault, p)
    first = dedup.rebuild_dedup_index(vault)
    snapshot = dedup._load_dedup_index(vault)
    second = dedup.rebuild_dedup_index(vault)
    assert (first, snapshot) == (second, dedup._load_dedup_index(vault))


# ---------------------------------------------------------------------------
# The two cases a "re-key off disk bytes" fix could never have solved
# ---------------------------------------------------------------------------

def test_ledger_file_holding_n_captures_recovers_every_key(vault: Path):
    """_LEDGER_FILES collapses N captures into 1 file (Finance -> Expenses.md).

    One file cannot yield N pre-write texts, so no re-keying scheme could rebuild
    these. The list-shaped capture_keys can.
    """
    p = _note(vault, "Finance/Expenses.md", fm="created: 2026-07-15\ncategory: Finance")
    dedup.register_in_dedup_index("coffee 200", None, vault, p)
    dedup.register_in_dedup_index("taxi 450", None, vault, p)

    keys = dedup.parse_capture_keys(p.read_text(encoding="utf-8"))
    assert len(keys) == 2, f"both captures' keys must live on the merged file, got {keys}"

    dedup._dedup_index_path(vault).unlink()
    assert dedup.rebuild_dedup_index(vault) == 2
    rel = str(Path("Finance") / "Expenses.md")
    assert dedup.check_duplicate("coffee 200", None, vault) == rel
    assert dedup.check_duplicate("taxi 450", None, vault) == rel


def test_blank_capture_uuid_key_survives_rebuild(vault: Path):
    """A blank capture keys on a random uuid4 -- unrebuildable IN PRINCIPLE by
    recomputation. Persisting it is the only thing that can work."""
    p = _note(vault, "Journal/blank.md")
    dedup.register_in_dedup_index("   ", None, vault, p)
    key = dedup.parse_capture_keys(p.read_text(encoding="utf-8"))[0]
    assert key.startswith("blank-")

    dedup._dedup_index_path(vault).unlink()
    assert dedup.rebuild_dedup_index(vault) == 1
    assert dedup._load_dedup_index(vault)[key] == str(Path("Journal") / "blank.md")


# ---------------------------------------------------------------------------
# Rebuild must degrade honestly, never wrongly
# ---------------------------------------------------------------------------

def test_legacy_notes_without_keys_are_skipped_not_guessed(vault: Path):
    """Pre-§1.1 captures have no capture_keys. A rebuild yields a PARTIAL index
    that refills by use -- never a wrong entry."""
    _note(vault, "Journal/legacy.md")  # no register -> no keys
    tracked = _note(vault, "Journal/new.md")
    dedup.register_in_dedup_index("new text", None, vault, tracked)

    dedup._dedup_index_path(vault).unlink()
    assert dedup.rebuild_dedup_index(vault) == 1, "only the tracked note is recoverable"
    assert dedup.check_duplicate("new text", None, vault) is not None


def test_rebuild_skips_machine_dirs_and_trash(vault: Path):
    tracked = _note(vault, "Journal/a.md")
    dedup.register_in_dedup_index("alpha", None, vault, tracked)
    raw = tracked.read_text(encoding="utf-8")
    for rel in (".sync/provisional/x.md", "_trash/old.md", ".omni_capture/junk.md"):
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw, encoding="utf-8")  # same key, must NOT be indexed

    dedup.rebuild_dedup_index(vault)
    assert dedup.check_duplicate("alpha", None, vault) == str(Path("Journal") / "a.md")


def test_rebuild_never_crashes_on_a_malformed_note(vault: Path):
    tracked = _note(vault, "Journal/a.md")
    dedup.register_in_dedup_index("alpha", None, vault, tracked)
    (vault / "Journal" / "bad.md").write_text("---\nunclosed frontmatter\n", encoding="utf-8")
    (vault / "Journal" / "empty.md").write_text("", encoding="utf-8")
    assert dedup.rebuild_dedup_index(vault) == 1, "a bad neighbour must not abort the rebuild"


# ---------------------------------------------------------------------------
# Backfill: close R-1 for captures written before §1.1
# ---------------------------------------------------------------------------

def test_backfill_dry_run_reports_but_writes_nothing(vault: Path):
    p = _note(vault, "Journal/legacy.md")
    before = p.read_text(encoding="utf-8")
    dedup._save_dedup_index(vault, {"deadbeef": str(Path("Journal") / "legacy.md")})

    plan = dedup.backfill_capture_keys(vault, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["changed"] == [(str(Path("Journal") / "legacy.md"), ["deadbeef"])]
    assert p.read_text(encoding="utf-8") == before, "dry run must not touch the vault"


def test_backfill_writes_keys_and_makes_legacy_notes_rebuildable(vault: Path):
    p = _note(vault, "Journal/legacy.md")
    body_before = _body_of(p)
    dedup._save_dedup_index(vault, {"deadbeef": str(Path("Journal") / "legacy.md")})

    dedup.backfill_capture_keys(vault, dry_run=False)
    assert dedup.parse_capture_keys(p.read_text(encoding="utf-8")) == ["deadbeef"]
    assert _body_of(p) == body_before, "BODY-SACRED LOCK: backfill is frontmatter-only"

    dedup._dedup_index_path(vault).unlink()
    assert dedup.rebuild_dedup_index(vault) == 1
    assert dedup._load_dedup_index(vault) == {"deadbeef": str(Path("Journal") / "legacy.md")}


def test_backfill_is_idempotent(vault: Path):
    p = _note(vault, "Journal/legacy.md")
    dedup._save_dedup_index(vault, {"deadbeef": str(Path("Journal") / "legacy.md")})
    dedup.backfill_capture_keys(vault, dry_run=False)
    once = p.read_text(encoding="utf-8")
    second = dedup.backfill_capture_keys(vault, dry_run=False)
    assert second["changed"] == [], "second run must be a no-op"
    assert p.read_text(encoding="utf-8") == once


def test_backfill_groups_all_keys_of_a_merged_ledger_file(vault: Path):
    p = _note(vault, "Finance/Expenses.md", fm="created: 2026-07-15\ncategory: Finance")
    rel = str(Path("Finance") / "Expenses.md")
    dedup._save_dedup_index(vault, {"k1": rel, "k2": rel})
    dedup.backfill_capture_keys(vault, dry_run=False)
    assert dedup.parse_capture_keys(p.read_text(encoding="utf-8")) == ["k1", "k2"]


def test_backfill_reports_missing_files_instead_of_crashing(vault: Path):
    dedup._save_dedup_index(vault, {"k1": str(Path("Gone") / "nope.md")})
    plan = dedup.backfill_capture_keys(vault, dry_run=False)
    assert plan["changed"] == []
    assert plan["skipped"] == [(str(Path("Gone") / "nope.md"), "missing from vault")]
