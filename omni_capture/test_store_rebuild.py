"""
test_store_rebuild.py
---------------------
S3.8 depth-QA: data-store integrity & rebuild.

Doctrine under test (CLAUDE.md hard rule, both repos + workspace):

    "Files are the source of truth, captures.db/vectors.db/dedup_index.json are
     derived indexes."
    "Every SQLite table, index, vector store, manifest and dedup ledger is a
     derived, rebuildable cache."

This suite PROVES that claim per store, on a synthetic tmp_path vault (never
~/second-thought-storage):

  1. delete-and-rebuild  — nuke the store while "the app is stopped", run the
     rebuild path (vault_sync.sync_vault_indexes — the full diff-sync, reached
     via POST /vault/sync-index; server.py's @startup _startup_db_tasks is a
     narrower sibling that heals + purges + backfills but never re-embeds), and
     compare the result against an ORACLE computed by re-scanning the .md files
     directly. The oracle never reads a DB — files are truth, so truth is what
     we diff against. `_rebuild()` below is sync_vault_indexes; the tests that
     cover the boot path proper call server._startup_db_tasks and say so.
  2. corrupt-and-recover — per store, two corruptions (truncate-to-a-few-bytes,
     mid-file byte flip). Assert: no crash escapes the rebuild path, the vault
     is byte-identical afterwards (BODY-SACRED), and no .md is written at all.
  3. idempotence — rebuilding twice yields the same state.

`@pytest.mark.xfail(strict=True)` marks a case that asserts the CORRECT
(doctrine-mandated) behavior and is expected to fail against today's code —
same convention as the phone repo's fableS23Sync.test.ts `it.fails` cases. The
suite stays green; flip the marker off when the defect is fixed. Every xfail
here is a reported finding, not a rubber stamp.

Run:
    python -m pytest test_store_rebuild.py -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import dedup
import index_writer
import mobile_sync_agent
import storage_engine as se
import vault_sync
import vector_store
from frontmatter import read_all_fields, strip_frontmatter
from models import CaptureOutput

_BASE_URL = "http://localhost:11434"
_EMBED_MODEL = "nomic-embed-text"


# ── Fakes ─────────────────────────────────────────────────────────────────────

def _fake_embed(text: str, base_url: str, model: str = _EMBED_MODEL) -> list[float]:
    """Deterministic 8-dim embedding — no Ollama. Mirrors vector_store.py's own
    __main__ smoke fake so ranking stays meaningful, not constant."""
    import hashlib
    import math

    vec = [0.0] * 8
    for word in (text or "").lower().split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        for i in range(8):
            vec[i] += ((h >> (i * 4)) & 0xF) / 15.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ── Vault + oracle ────────────────────────────────────────────────────────────

_NOTES: dict[str, dict] = {
    "Tech_Notes/asyncio-patterns.md": {
        "tags": ["python", "async"],
        "category": "Tech_Notes",
        "body": "Async IO patterns in Python. Event loops, tasks, and gather.",
    },
    "Tech_Notes/fastapi-deps.md": {
        "tags": ["python", "fastapi", "http"],
        "category": "Tech_Notes",
        "body": "FastAPI dependency injection and async HTTP route handlers.",
    },
    "Journal/2026-07-14.md": {
        "tags": ["diary"],
        "category": "Journal",
        "body": "Walked the long way home. The light was good.",
    },
    "Reading_List/dune.md": {
        "tags": ["scifi", "books"],
        "category": "Reading_List",
        "body": "Dune — Frank Herbert. Spice, sandworms, and desert power.",
    },
}


def _mk_vault(tmp_path: Path) -> Path:
    """A small synthetic vault: several notes across categories, with tags."""
    vault = tmp_path / "vault"
    for rel, spec in _NOTES.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = "---\n" + f"tags: [{', '.join(spec['tags'])}]\n" + f"category: {spec['category']}\n" + "---\n"
        p.write_text(fm + spec["body"] + "\n", encoding="utf-8")
    return vault


def _oracle(vault: Path) -> dict:
    """Fresh-scan oracle: walk the .md files and derive what a correct index
    MUST contain. Reads files only — never a database."""
    notes: dict[str, dict] = {}
    for p in sorted(vault.rglob("*.md")):
        if any(part.startswith(".") for part in p.relative_to(vault).parts):
            continue
        fields = read_all_fields(p.read_text(encoding="utf-8"))
        raw_tags = (fields.get("tags") or "").strip().strip("[]")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        notes[str(p.relative_to(vault)).replace("\\", "/")] = {
            "category": fields.get("category") or p.parent.name,
            "tags": sorted(tags),
        }
    return {
        "count": len(notes),
        "categories": sorted({n["category"] for n in notes.values()}),
        "tags": sorted({t for n in notes.values() for t in n["tags"]}),
        "notes": notes,
    }


def _index_state(vault: Path) -> dict:
    """The same shape as _oracle(), read back out of captures.db."""
    conn = index_writer.init_db(vault)
    rows = conn.execute(
        "SELECT path, category, tags FROM captures WHERE provisional = 0"
    ).fetchall()
    conn.close()
    notes: dict[str, dict] = {}
    for r in rows:
        rel = str(Path(r["path"]).relative_to(vault)).replace("\\", "/")
        notes[rel] = {
            "category": r["category"],
            "tags": sorted(json.loads(r["tags"] or "[]")),
        }
    return {
        "count": len(notes),
        "categories": sorted({n["category"] for n in notes.values()}),
        "tags": sorted({t for n in notes.values() for t in n["tags"]}),
        "notes": notes,
    }


# ── Vault snapshot (body-sacred) ──────────────────────────────────────────────

def _snapshot_vault(vault: Path) -> dict[str, bytes]:
    """Every .md file's raw bytes, keyed by vault-relative path."""
    return {
        str(p.relative_to(vault)).replace("\\", "/"): p.read_bytes()
        for p in sorted(vault.rglob("*.md"))
    }


def _assert_bodies_sacred(
    before: dict[str, bytes], vault: Path, what: str, allow_capture_keys: bool = False
) -> None:
    """BODY-SACRED: recovery touches derived state only. Assert (a) no .md
    appeared or vanished, (b) every file's bytes are identical, and (c) the
    Markdown body below the frontmatter is byte-identical (asserted separately
    so a frontmatter-only diff is reported as the weaker failure it is).

    allow_capture_keys: the caller deliberately REGISTERS a capture during the
    test. Registering stamps `capture_keys` into frontmatter by contract
    (data-model §1.1 -- it is what makes the ledger rebuildable, finding R-1), so
    (b) is relaxed to "frontmatter may differ only by capture_keys". The BODY
    assertion (c) is never relaxed. Do NOT set this to paper over an unexpected
    vault write: it is scoped to the one legitimate frontmatter writer.
    """
    after = _snapshot_vault(vault)
    assert set(after) == set(before), f"{what}: vault .md set changed"
    for rel, raw in before.items():
        if after[rel] != raw:
            assert allow_capture_keys, f"{what}: {rel} bytes changed during recovery"
            keys_before = dedup.parse_capture_keys(raw.decode("utf-8"))
            keys_after = dedup.parse_capture_keys(after[rel].decode("utf-8"))
            assert keys_after != keys_before, (
                f"{what}: {rel} frontmatter changed but NOT by capture_keys -- "
                f"something other than dedup registration wrote to the vault"
            )
            assert set(keys_before) <= set(keys_after), (
                f"{what}: {rel} LOST a capture_key -- capture_keys is append-only (§1.1)"
            )
        body_before = strip_frontmatter(raw.decode("utf-8"))
        body_after = strip_frontmatter(after[rel].decode("utf-8"))
        assert body_after == body_before, f"{what}: BODY of {rel} was altered"


# ── Store handles ─────────────────────────────────────────────────────────────

def _restart(vault: Path) -> None:
    """Simulate an app restart: index_writer memoizes "schema already applied"
    per db path in a process-global set, so a fresh process is the only thing
    that re-runs the DDL. Tests that delete a db mid-process must clear it or
    they are testing the cache, not the rebuild."""
    index_writer._INITIALIZED.discard(str(index_writer.get_db_path(vault)))


def _rebuild(vault: Path) -> dict:
    """The full diff-sync rebuild path (vault_sync.sync_vault_indexes, POST /vault/sync-index).
    NOT the boot path — see _startup(), which runs what server.py actually does at startup."""
    _restart(vault)
    with mock.patch.object(vector_store, "_embed", side_effect=_fake_embed):
        return vault_sync.sync_vault_indexes(vault, _BASE_URL, _EMBED_MODEL)


def _startup(vault: Path) -> None:
    """The real boot path: server.py's @startup _startup_db_tasks, run synchronously.
    It hands its work to a background executor, so the submit is patched to run inline."""
    import server

    _restart(vault)
    with mock.patch.object(server, "_get_vault_root", lambda: vault), \
         mock.patch.object(server.jobs._bg_executor, "submit", lambda fn: fn()):
        server._startup_db_tasks()


def _sidecar(vault: Path) -> Path:
    return vault / ".omni_capture" / "mobile_sync_state.json"


def _store_paths(vault: Path) -> dict[str, Path]:
    return {
        "captures.db": index_writer.get_db_path(vault),
        "vectors.db": vault / ".omni_capture" / vector_store._DB_NAME,
        "dedup_index.json": dedup._dedup_index_path(vault),
        "mobile_sync_state.json": _sidecar(vault),
    }


def _drop_sqlite_sidecars(db: Path) -> None:
    """WAL/SHM must go with the db — a stale -wal can resurrect pages we
    deliberately destroyed and mask the corruption we are testing."""
    for extra in db.parent.glob(db.name + "-*"):
        extra.unlink()


def _truncate(p: Path) -> None:
    p.write_bytes(b"\x00\x01\x02\x03")
    _drop_sqlite_sidecars(p)


def _flip_midfile(p: Path) -> None:
    """Overwrite a chunk in the middle with garbage, leaving the header intact
    — the realistic bad-sector / half-flushed-page shape, not a header nuke."""
    data = bytearray(p.read_bytes())
    mid = len(data) // 2
    for i in range(mid, min(mid + 512, len(data))):
        data[i] ^= 0xFF
    p.write_bytes(bytes(data))
    _drop_sqlite_sidecars(p)


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """A built vault: synthetic notes + a fully populated set of stores."""
    v = _mk_vault(tmp_path)
    # Register BEFORE indexing, mirroring the real pipeline: write_to_vault()
    # (which registers, and since data-model §1.1 stamps `capture_keys` into the
    # note's frontmatter) returns first, and main.py:459->487 / server.py:819->837
    # index the file only afterwards. Indexing first would hash pre-stamp bytes
    # and make every note look modified -- a fixture artifact, not a product bug.
    dedup.register_in_dedup_index("some captured text", None, v, v / "Journal" / "2026-07-14.md")
    _rebuild(v)
    _sidecar(v).parent.mkdir(parents=True, exist_ok=True)
    mobile_sync_agent.save_state(
        str(_sidecar(v)),
        {"n1": {"drive_file_id": "F1", "base_rev": "r1", "local_hash": "h1"}},
    )
    yield v
    _restart(v)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Delete and rebuild
# ══════════════════════════════════════════════════════════════════════════════

def test_fresh_build_matches_oracle_count_and_categories(vault: Path):
    """Sanity anchor: the first build already agrees with the file scan."""
    oracle = _oracle(vault)
    state = _index_state(vault)
    assert state["count"] == oracle["count"] == len(_NOTES)
    assert state["categories"] == oracle["categories"]


def test_delete_all_stores_then_rebuild_matches_oracle(vault: Path):
    """App stopped -> every derived store deleted -> startup rebuild -> the
    rebuilt state must match a fresh scan of the .md files."""
    before = _snapshot_vault(vault)
    oracle = _oracle(vault)

    for p in _store_paths(vault).values():
        if p.exists():
            p.unlink()
        _drop_sqlite_sidecars(p)
    assert not index_writer.get_db_path(vault).exists()

    _rebuild(vault)

    state = _index_state(vault)
    assert state["count"] == oracle["count"], "note count lost across rebuild"
    assert state["categories"] == oracle["categories"], "categories lost across rebuild"
    assert set(state["notes"]) == set(oracle["notes"]), "note set lost across rebuild"
    for rel, want in oracle["notes"].items():
        assert state["notes"][rel]["category"] == want["category"], f"category wrong for {rel}"
    assert vector_store.count(vault) == oracle["count"], "vector store not rebuilt from files"
    _assert_bodies_sacred(before, vault, "delete-and-rebuild")


def test_delete_and_rebuild_restores_tags(vault: Path):
    """FIXED: upsert_capture_from_file now reads `tags` from the note's frontmatter
    (index_writer._read_file_tags -> tag_index.parse_tags, which handles both the
    inline and block shapes). It used to INSERT only
    timestamp/category/path/hash/filename/body_excerpt, so a rebuilt captures.db had
    tags='[]' on every row while the tags sat in the .md files — decaying tag_vocab.py,
    which reads this column as the vault's tag vocabulary for LLM tag normalization."""
    oracle = _oracle(vault)
    assert oracle["tags"], "oracle must see tags in the .md frontmatter"

    p = index_writer.get_db_path(vault)
    p.unlink()
    _drop_sqlite_sidecars(p)
    _rebuild(vault)

    state = _index_state(vault)
    assert state["tags"] == oracle["tags"], (
        f"tags lost across rebuild: index={state['tags']} oracle={oracle['tags']}"
    )
    for rel, want in oracle["notes"].items():
        assert state["notes"][rel]["tags"] == want["tags"], f"tags wrong for {rel}"


def test_rebuilt_tags_survive_into_the_llm_tag_vocabulary(vault: Path):
    """Why the column matters beyond the Library view: tag_vocab.load_vocab reads
    `SELECT tags FROM captures` as the vault's vocabulary, so a blanking rebuild used
    to make the LLM re-fork tags it should have reused. (The Tags view itself resolves
    off the files via tag_index, so it never saw this.)"""
    import tag_vocab

    p = index_writer.get_db_path(vault)
    p.unlink()
    _drop_sqlite_sidecars(p)
    _rebuild(vault)

    vocab = tag_vocab.load_vocab(index_writer.get_db_path(vault))
    # "Python" normalizes onto the existing "python" instead of forking a new tag.
    assert tag_vocab.normalize_tags(["Python"], vocab) == ["python"]


def test_rebuild_is_idempotent(vault: Path):
    """Running the rebuild twice yields the same state (and re-reads nothing it
    already has: the second pass must classify every file as `skipped`)."""
    p = index_writer.get_db_path(vault)
    p.unlink()
    _drop_sqlite_sidecars(p)

    first_result = _rebuild(vault)
    first = _index_state(vault)
    first_vecs = vector_store.count(vault)

    second_result = _rebuild(vault)
    second = _index_state(vault)

    assert first == second, "rebuild is not idempotent — state differs across two runs"
    assert vector_store.count(vault) == first_vecs, "vector rows changed on second rebuild"
    assert first_result["added"] == len(_NOTES)
    assert second_result["added"] == 0 and second_result["updated"] == 0
    assert second_result["skipped"] == len(_NOTES), "second rebuild re-did work it already had"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Corrupt and recover — per store, two corruption shapes
# ══════════════════════════════════════════════════════════════════════════════

_CORRUPTORS = [pytest.param(_truncate, id="truncate"), pytest.param(_flip_midfile, id="byteflip")]


@pytest.mark.parametrize("corrupt", _CORRUPTORS)
@pytest.mark.parametrize("store", ["captures.db", "vectors.db", "dedup_index.json", "mobile_sync_state.json"])
def test_corruption_never_crashes_rebuild_and_never_writes_the_vault(
    vault: Path, store: str, corrupt
):
    """The universal invariant, for EVERY store x EVERY corruption shape:
    the startup/rebuild path must not raise, and recovery must touch derived
    state only — no vault .md written, every body byte-identical."""
    before = _snapshot_vault(vault)
    corrupt(_store_paths(vault)[store])

    _rebuild(vault)  # must not raise

    _assert_bodies_sacred(before, vault, f"{store} corrupt-recover")


@pytest.mark.parametrize("corrupt", _CORRUPTORS)
def test_corrupt_dedup_ledger_degrades_to_empty_and_refills(vault: Path, corrupt):
    """dedup_index.json: corruption IS detected (json decode fails) and the
    ledger degrades to empty rather than raising — dedup._load_dedup_index
    (dedup.py:64-71). A later capture refills it. No vault write."""
    before = _snapshot_vault(vault)
    corrupt(_store_paths(vault)["dedup_index.json"])

    assert dedup.check_duplicate("some captured text", None, vault) is None  # no raise
    dedup.register_in_dedup_index("fresh text", None, vault, vault / "Journal" / "2026-07-14.md")
    assert dedup.check_duplicate("fresh text", None, vault) == str(Path("Journal") / "2026-07-14.md")

    # This test registers a capture on purpose, so the note legitimately gains a
    # capture_keys entry (§1.1). Body stays sacred; nothing else may change.
    _assert_bodies_sacred(before, vault, "dedup corrupt-recover", allow_capture_keys=True)


def test_corrupt_sync_sidecar_degrades_to_empty(vault: Path):
    """mobile_sync_state.json truncated to garbage bytes: load_state returns {}
    (mobile_sync_agent.py:121-133) — the documented "derived cache, safe to
    rebuild from files" contract, honored for a JSON-decode failure."""
    before = _snapshot_vault(vault)
    _truncate(_store_paths(vault)["mobile_sync_state.json"])

    assert mobile_sync_agent.load_state(str(_sidecar(vault))) == {}  # no raise
    _assert_bodies_sacred(before, vault, "sidecar corrupt-recover")


def test_sync_sidecar_byteflip_degrades_to_empty(vault: Path):
    """FIXED: load_state now catches ValueError (the shared base of JSONDecodeError
    and UnicodeDecodeError) + OSError, honouring its own 'Absent/corrupt -> empty'
    docstring. A byte-flip used to raise UnicodeDecodeError out of load_state, out of
    run_once, and out of run_pass, parking sync in 'error' forever (and crashing
    note_history._sync_entry, the other caller). The vault must be untouched either
    way — the damage was availability, never user content."""
    before = _snapshot_vault(vault)
    _flip_midfile(_store_paths(vault)["mobile_sync_state.json"])

    assert mobile_sync_agent.load_state(str(_sidecar(vault))) == {}

    _assert_bodies_sacred(before, vault, "sidecar byteflip")


def test_sync_sidecar_loss_reuses_the_hub_file_instead_of_duplicating(vault: Path):
    """The sidecar's rebuildability that actually matters: with the state gone, the note's
    drive_file_id is recovered from the HUB LISTING and the existing file UPDATED — never
    re-created as a duplicate orphan.

    This is reconcile_changes' adopt path (mobile_sync_agent.py:397-410), not mirror_to_hub's:
    the hub listing yields a file id, but NOT a base revision — nothing ever observed a sync for
    this note — so the recovery has to reconcile against an unknown ancestor. mirror_to_hub used
    to do the adopt itself with `base_rev` = the CURRENT head, a revision it had never synced at,
    which defeated its own advanced-head guard and blind-uploaded over a peer's edit (F-1).
    Orphan-avoidance is preserved; the clobber it was bought with is not.
    """
    seen: list[dict | None] = []

    def _fake_upload(drive, note, dest_folder_id, existing):
        seen.append(existing)
        return {"id": "F1", "headRevisionId": "r2"}

    local = "---\nid: n1\norigin: note\n---\nlocal body"
    remote = "---\nid: n1\norigin: note\n---\nremote body"
    vault_notes = {"n1": {"id": "n1", "path": "x.md", "content": local, "body": "local body",
                          "hash": "h2", "category": None}}
    hub_files = {"n1": {"id": "F1", "headRevisionId": "r1", "name": "n1.md"}}

    with mock.patch.object(mobile_sync_agent, "_upload_note", _fake_upload), \
         mock.patch.object(mobile_sync_agent, "_download_content", lambda d, f: remote), \
         mock.patch.object(mobile_sync_agent, "_resolve_dest_folder", lambda *a, **k: "dest"):
        reconciled, conflicts, failed, new_state = mobile_sync_agent.reconcile_changes(
            vault_notes, hub_files, {}, object(), "hubfolder",
            write_file=lambda p, c: None, new_id=lambda: "cc1",
        )

    assert failed == 0 and reconciled == 1
    # `existing` was reconstructed from the hub listing despite an EMPTY sidecar, so the merged
    # note updates F1 in place instead of creating a duplicate orphan (the conflicted copy is a
    # different note with a fresh id, so it is correctly created rather than updated).
    assert seen[0] == {"drive_file_id": "F1"}
    assert conflicts == 1, "both bodies must be kept — there is no ancestor to rule either stale"
    assert new_state["n1"]["drive_file_id"] == "F1"
    assert new_state["n1"]["local_hash"], "sidecar not repopulated after rebuild"

    # ...and mirror_to_hub, which no longer has an unobserved base to lean on, uploads nothing.
    with mock.patch.object(mobile_sync_agent, "_upload_note", _fake_upload):
        uploaded, m_failed, m_state = mobile_sync_agent.mirror_to_hub(
            vault_notes, hub_files, {}, object(), "hubfolder"
        )
    assert (uploaded, m_failed, m_state) == (0, 0, {})


def test_corrupt_captures_db_is_healed_by_the_boot_path(vault: Path):
    """FIXED: the heal is wired into server.py's @startup _startup_db_tasks, so a captures.db
    that is corrupt AT BOOT is detected and discarded there. It used to live only in
    sync_vault_indexes (POST /vault/sync-index), which is NOT on the startup path — the boot
    task ran purge_orphan_index_entries + reindex_bodies, both of which assume a readable DB and
    both of which just print their own DatabaseError and continue. So a store corrupt at boot
    stayed dead until the user manually triggered a sync-index.

    Asserts the heal happened (the db is readable again) AND that the purge/reindex steps
    sequenced after it now do their work instead of choking on the corrupt file."""
    before = _snapshot_vault(vault)
    _truncate(_store_paths(vault)["captures.db"])

    _startup(vault)   # must not raise

    conn = index_writer.init_db(vault)
    try:
        # Readable again (this is the read that used to raise DatabaseError), and empty —
        # refilling from the files is the diff-sync's job, not the boot task's.
        assert conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
    finally:
        conn.close()
    assert index_writer.reindex_bodies(vault) == 0, "reindex must run on the healed db"
    assert _rebuild(vault)["added"] == _oracle(vault)["count"], "healed db does not refill"
    _assert_bodies_sacred(before, vault, "startup heal")


def test_healthy_captures_db_survives_the_boot_path(vault: Path):
    """The boot heal must be a real corruption check, not an unconditional nuke: an intact db
    keeps every row across a restart."""
    n_before = _index_state(vault)["count"]
    assert n_before == len(_NOTES)

    _startup(vault)

    assert _index_state(vault)["count"] == n_before, "boot discarded an intact captures.db"


def test_corrupt_captures_db_is_rebuilt_by_the_diff_sync(vault: Path):
    """FIXED: sync_vault_indexes now calls index_writer.heal_corrupt_db first, so an
    unreadable captures.db is discarded and re-created from the vault files. It used
    to raise sqlite3.DatabaseError into the blanket `except Exception`, which printed
    and returned a success-shaped {added: 0} while the index stayed dead until a human
    deleted the file by hand — 'derived' without the 'rebuildable' half of the doctrine."""
    before = _snapshot_vault(vault)
    oracle = _oracle(vault)
    _truncate(_store_paths(vault)["captures.db"])

    result = _rebuild(vault)

    assert _index_state(vault)["count"] == oracle["count"], "corrupt captures.db not rebuilt"
    assert result["healed"] is True, "corruption healed but not reported to the caller"
    assert result["error"] is None, "heal path must not report the pass as failed"
    assert result["added"] == oracle["count"], "rebuild must re-add every note, not report 0"
    _assert_bodies_sacred(before, vault, "corrupt captures.db heal")


def test_healthy_captures_db_is_not_reported_as_healed(vault: Path):
    """The heal must be a real corruption check, not an unconditional nuke: an intact
    db is left alone (every note `skipped`, nothing re-added) and healed stays False."""
    result = _rebuild(vault)

    assert result["healed"] is False, "an intact captures.db must never be discarded"
    assert result["skipped"] == len(_NOTES) and result["added"] == 0


def test_busy_captures_db_is_not_mistaken_for_a_corrupt_one(vault: Path):
    """A HEALTHY-but-unavailable db must never be unlinked.

    sqlite3.OperationalError (SQLITE_BUSY/SQLITE_LOCKED, a permissions fault, an
    unwritable temp dir) is a subclass of sqlite3.DatabaseError, so the corruption
    catch used to swallow it and delete a perfectly intact user index. It is not
    reachable through the live boot path today -- WAL means readers never block, and
    on Windows the open handle makes the unlink raise OSError -- but that is two
    incidental invariants standing between a busy index and deletion, not a check.
    The probe is faulted directly so the guard is pinned on its own terms rather
    than on WAL happening to hold. Contrast the sibling truncation test, which
    raises a plain DatabaseError and MUST heal.
    """
    db_path = index_writer.get_db_path(vault)
    before = db_path.read_bytes()

    with mock.patch.object(
        index_writer.sqlite3, "connect",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        healed = index_writer.heal_corrupt_db(vault)

    assert healed is False, "a busy db is not a corrupt db -- nothing was discarded"
    assert db_path.exists(), "heal_corrupt_db unlinked a HEALTHY captures.db"
    assert db_path.read_bytes() == before, "healthy captures.db was modified"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING (HIGH): a corrupt vectors.db is never healed, and the hash-diff makes it "
        "PERMANENT. vault_sync.sync_vault_indexes classifies a file as `skipped` when "
        "captures.hash still matches the file on disk (vault_sync.py:145-146) — so with an intact "
        "captures.db and a destroyed vectors.db, every note is skipped and NOTHING is ever "
        "re-embedded. Semantic search / merge-target lookup silently return nothing forever "
        "(both fail soft to []/None), with no error surfaced to the user. The re-embed decision "
        "must consult the vector store's own contents, not captures.hash. (The name says "
        "`rebuild path` — sync_vault_indexes — deliberately: the boot path proper never "
        "re-embeds at all, so it is not even a candidate to heal this.)"
    ),
)
def test_corrupt_vectors_db_is_rebuilt_by_the_rebuild_path(vault: Path):
    oracle = _oracle(vault)
    _truncate(_store_paths(vault)["vectors.db"])

    _rebuild(vault)

    assert vector_store.count(vault) == oracle["count"], "corrupt vectors.db not rebuilt"


def test_corrupt_vectors_db_leaves_semantic_search_silently_dead(vault: Path):
    """Passing counterpart to the xfail above — evidences the finding. Reads
    fail soft (no crash, correct per the fail-soft rule) but the store is never
    repaired, so 'no results' is indistinguishable from 'store destroyed'."""
    _truncate(_store_paths(vault)["vectors.db"])

    assert vector_store.count(vault) == 0
    with mock.patch.object(vector_store, "_embed", side_effect=_fake_embed):
        assert vector_store.best_match(vault, "async python", _BASE_URL, _EMBED_MODEL) is None
        assert vector_store.retrieve_related(vault, "async python", _BASE_URL, _EMBED_MODEL) == []

    result = _rebuild(vault)
    assert result["skipped"] == len(_NOTES), "expected the captures.hash diff to skip every note"
    assert vector_store.count(vault) == 0, "expected today's rebuild to leave vectors.db empty"


def test_corrupt_captures_db_reads_fail_soft(vault: Path):
    """FIXED: search()/stats() now open the db INSIDE their try and catch
    sqlite3.DatabaseError (the base of the OperationalError they already caught AND
    of the DatabaseError('file is not a database') a corrupt file raises), so
    /search and /stats degrade to empty instead of 500ing. Mirrors the write path,
    which was already fail-soft (log_capture_db)."""
    _truncate(_store_paths(vault)["captures.db"])
    _restart(vault)

    assert index_writer.search("async", vault) == []
    assert index_writer.stats(vault)["total"] == 0

    # ...and the write path stays fail-soft too (never breaks a capture).
    index_writer.log_capture_db(
        {"category": "Journal", "filepath": str(vault / "Journal" / "2026-07-14.md"),
         "filename": "2026-07-14.md", "tags": ["diary"]},
        vault,
    )


def test_deleting_captures_db_in_process_wedges_init_db(vault: Path):
    """FINDING (MEDIUM): index_writer._INITIALIZED (index_writer.py:59, 280-283)
    memoizes "schema applied" per db PATH for the process lifetime. If the file
    disappears while the server runs (user cleanup, sync tool, antivirus), every
    later init_db re-creates an EMPTY file and skips the DDL — so the tables
    never come back until a restart. Recovery is restart-only by construction;
    this test pins that ceiling."""
    p = index_writer.get_db_path(vault)
    p.unlink()
    _drop_sqlite_sidecars(p)
    # NOTE: deliberately no _restart() — this is the live-process path.

    conn = index_writer.init_db(vault)
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            conn.execute("SELECT COUNT(*) FROM captures").fetchone()
    finally:
        conn.close()

    _restart(vault)  # a process restart is what heals it
    assert _index_state(vault)["count"] == 0
    _rebuild(vault)
    assert _index_state(vault)["count"] == len(_NOTES)


# ══════════════════════════════════════════════════════════════════════════════
# 3. The dedup ledger: derived AND rebuildable (R-1 RESOLVED) -- but not
#    auto-rebuilt at startup.
#
# s24 found the ledger unrebuildable, making the workspace lock ("every ... dedup
# ledger is a derived, rebuildable cache") literally false. Resolved s25 by
# data-model §1.1: the key is PERSISTED into each note's `capture_keys`
# frontmatter at register time, because it never was recomputable from disk bytes
# and re-keying could not have fixed the N->1 ledger or the blank-uuid4 case.
# Rebuild coverage lives in the sibling test_dedup_rebuild.py; what stays here is
# the ledger's interaction with the OTHER stores and the startup path.
# ══════════════════════════════════════════════════════════════════════════════

def _finance_capture(content: str, filename: str) -> CaptureOutput:
    return CaptureOutput(
        category="Finance",
        suggested_filename=filename,
        markdown_content=content,
        key_signals=["expense"],
        confidence=0.95,
        requires_new_category=False,
    )


def test_dedup_ledger_is_auto_rebuilt_by_the_diff_sync_path(vault: Path):
    """INVERTED (was `..._is_not_auto_rebuilt_by_the_startup_path`; the gap it pinned
    is closed — user decision 2026-07-16, HANDOVER §8 Q1 answered "yes, missing/empty
    only").

    The finding was NOT that the ledger couldn't be rebuilt — rebuild_dedup_index()
    worked — but that nothing ever called it, which left the workspace lock ("every
    ledger is a derived, rebuildable cache") true on paper and false in practice.
    Both automatic callers are now wired to dedup.rebuild_dedup_index_if_missing:
    this one (the diff-sync, where captures.db already heals) and the boot task.

    NOTE the old name was a misnomer: this exercises `_rebuild` = the diff-sync
    (POST /vault/sync-index), never the boot path — `_startup()` is that one, and it
    is covered separately below.
    """
    before = _snapshot_vault(vault)
    ledger = _store_paths(vault)["dedup_index.json"]
    assert dedup.check_duplicate("some captured text", None, vault) is not None

    ledger.unlink()
    result = _rebuild(vault)

    assert ledger.exists(), "the diff-sync must rebuild a lost dedup ledger"
    assert result["dedup_rebuilt"] is True
    # The point of the rebuild: the key is recoverable from the vault files, so a
    # capture that deduped before the loss still dedupes after it.
    assert dedup.check_duplicate("some captured text", None, vault) is not None
    _assert_bodies_sacred(before, vault, "dedup ledger rebuild")


def test_dedup_ledger_is_auto_rebuilt_by_the_boot_path(vault: Path):
    """The boot half of the same wiring — the case that actually made the ledger
    'lost in practice', since a user who loses it never necessarily reindexes."""
    before = _snapshot_vault(vault)
    ledger = _store_paths(vault)["dedup_index.json"]
    assert dedup.check_duplicate("some captured text", None, vault) is not None

    ledger.unlink()
    _startup(vault)

    assert ledger.exists(), "the boot task must rebuild a lost dedup ledger"
    assert dedup.check_duplicate("some captured text", None, vault) is not None
    _assert_bodies_sacred(before, vault, "dedup ledger rebuild (boot)")


def test_a_live_dedup_ledger_is_never_rebuilt_over(vault: Path):
    """The guard that makes 'missing/empty only' a correctness rule, not just a
    cost one: a populated ledger is AUTHORITATIVE over the vault scan. Pre-§1.1
    captures carry no capture_keys, so a rebuild is partial by construction and
    would silently drop their keys. An intact ledger must survive both paths
    byte-for-byte."""
    ledger = _store_paths(vault)["dedup_index.json"]
    ledger.write_text(
        json.dumps({"legacy-key-no-file-carries-it": "Finance/Expenses.md"}),
        encoding="utf-8",
    )
    before_bytes = ledger.read_bytes()

    result = _rebuild(vault)
    assert ledger.read_bytes() == before_bytes, "diff-sync rebuilt over a live ledger"
    assert result["dedup_rebuilt"] is False

    _startup(vault)
    assert ledger.read_bytes() == before_bytes, "boot rebuilt over a live ledger"


def test_dedup_ledger_keys_are_recovered_from_the_vault_files(vault: Path):
    """THE HEADLINE, INVERTED (was: `..._cannot_be_recovered...`; R-1 resolved s25).

    The key still is NOT recomputable from disk, and never will be:

      * It is sha256 of `output.markdown_content` — the LLM's raw pre-write text
        (storage_engine.py:944/980/1006/1052) — NOT the bytes that land in the
        .md. The written body goes through _try_inject_wikilinks +
        _postprocess_content first, and frontmatter is added on top.
      * Ledger categories (storage_engine.py:515 _LEDGER_FILES = {"Finance":
        "Expenses.md"}) and smart-merge append MANY captures into ONE file, so the
        mapping is N hashes -> 1 path. A file scan sees 1 file and can never
        recover the N distinct source texts that produced it.

    So the fix is not to re-key but to PERSIST the key into the note's
    `capture_keys` frontmatter (data-model §1.1) at register time. This test pins
    BOTH halves: the key remains unrecomputable (why persistence is required), AND
    the vault alone now regenerates the ledger — including the N->1 case that no
    re-keying scheme could have satisfied.
    """
    (vault / "Finance").mkdir(parents=True, exist_ok=True)

    p1 = se.write_to_vault(_finance_capture("Coffee 4.50 at the corner place", "coffee"),
                           vault_root=vault)
    p2 = se.write_to_vault(_finance_capture("Train ticket 12.00 to the coast", "train"),
                           vault_root=vault)

    # N captures -> 1 ledger file.
    assert p1 == p2 == vault / "Finance" / "Expenses.md"

    ledger = json.loads(_store_paths(vault)["dedup_index.json"].read_text(encoding="utf-8"))
    finance_keys = [k for k, v in ledger.items() if v.endswith("Expenses.md")]
    assert len(finance_keys) == 2, "two captures must hold two distinct dedup keys"

    # Half 1: the key is still NOT recomputable from the file's bytes. This is the
    # reason persistence is necessary — if it ever becomes recomputable, revisit §1.1.
    file_body = strip_frontmatter(p1.read_text(encoding="utf-8"))
    assert dedup.content_hash(file_body, None) not in finance_keys, (
        "the ledger key became recomputable from the file — re-evaluate §1.1"
    )
    for key in finance_keys:
        assert key not in file_body, "the key must live in frontmatter, never in the sacred body"

    # Half 2: ...but the vault still regenerates the ledger, because the keys are
    # persisted in frontmatter. Both of this merged file's keys must survive.
    assert sorted(dedup.parse_capture_keys(p1.read_text(encoding="utf-8"))) == sorted(finance_keys), (
        "the N->1 ledger file must carry ALL N of its captures' keys"
    )

    _store_paths(vault)["dedup_index.json"].unlink()
    assert dedup.rebuild_dedup_index(vault) >= 2
    assert dedup.check_duplicate("Coffee 4.50 at the corner place", None, vault) == str(
        Path("Finance") / "Expenses.md"
    )
    assert dedup.check_duplicate("Train ticket 12.00 to the coast", None, vault) == str(
        Path("Finance") / "Expenses.md"
    )


def test_dedup_ledger_loss_is_non_destructive_to_the_vault(vault: Path):
    """The saving grace, asserted: losing the ledger costs dedup RECOGNITION,
    never a byte of user content. storage_engine also re-validates a dedup hit
    against the file's real current category before trusting it (dedup.py:9-12),
    so the ledger is correctly non-authoritative."""
    (vault / "Finance").mkdir(parents=True, exist_ok=True)
    se.write_to_vault(_finance_capture("Coffee 4.50", "coffee"), vault_root=vault)
    before = _snapshot_vault(vault)

    _store_paths(vault)["dedup_index.json"].unlink()
    _rebuild(vault)

    _assert_bodies_sacred(before, vault, "dedup ledger loss")
    assert _index_state(vault)["count"] == _oracle(vault)["count"]
