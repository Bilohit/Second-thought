from pathlib import Path

import pytest

import project_registry as pr


def _write(vault: Path, text: str) -> None:
    (vault / pr.REGISTRY_FILENAME).write_text(text, encoding="utf-8")


def test_registry_lock_path_is_a_vault_root_sidecar(tmp_path):
    assert pr._registry_lock_path(tmp_path) == tmp_path / ".projects.lock"


def test_missing_file_loads_as_empty_never_raises(tmp_path):
    reg = pr.load(tmp_path)
    assert reg == {"schema": pr.SCHEMA, "projects": {}}


def test_loads_entries(tmp_path):
    _write(
        tmp_path,
        'schema = 1\n\n'
        '[projects."research"]\n'
        'description = "Cancer imaging leads."\n'
        'created = "2026-08-01T10:00:00Z"\n'
        'modified = "2026-08-01T10:12:00Z"\n'
        'device = "desktop-a1b2"\n',
    )
    reg = pr.load(tmp_path)
    assert reg["projects"]["research"]["description"] == "Cancer imaging leads."
    assert reg["projects"]["research"]["created"] == "2026-08-01T10:00:00Z"


def test_a_name_with_a_dot_would_nest_a_toml_table_and_is_dropped_on_load(tmp_path):
    # Quoted keys mean a dotted name cannot silently nest, but a hand-edited file can still
    # carry an ineligible name. It is not registered, so its notes read as loose (contract §13.1).
    _write(tmp_path, 'schema = 1\n\n[projects."a.b"]\ndescription = ""\n')
    assert pr.load(tmp_path)["projects"] == {}


def test_unknown_keys_round_trip(tmp_path):
    _write(
        tmp_path,
        'schema = 1\n\n[projects."research"]\n'
        'description = "d"\ncreated = "c"\nmodified = "m"\ndevice = "dev"\n'
        'future_field = "written by a newer phone"\n',
    )
    reg = pr.load(tmp_path)
    pr.save(tmp_path, reg)
    text = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    assert "future_field" in text
    assert "written by a newer phone" in text


def test_keys_are_always_quoted_on_write(tmp_path):
    reg = pr.empty_registry()
    reg["projects"]["research"] = {
        "description": "d", "created": "c", "modified": "m", "device": "dev",
    }
    pr.save(tmp_path, reg)
    text = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    assert '[projects."research"]' in text


def test_save_rejects_an_invalid_name(tmp_path):
    reg = pr.empty_registry()
    reg["projects"]["a/b"] = {"description": "", "created": "c", "modified": "m", "device": "d"}
    with pytest.raises(ValueError):
        pr.save(tmp_path, reg)


def test_an_unreadable_schema_is_surfaced_and_the_file_is_never_rewritten(tmp_path):
    # Contract §13.2: a peer reading a schema it does not understand must leave the file alone,
    # never rewrite it with fields it would drop.
    _write(tmp_path, 'schema = 99\n\n[projects."research"]\ndescription = "keep me"\n')
    reg = pr.load(tmp_path)
    assert reg["schema"] == 99
    with pytest.raises(pr.UnknownSchemaError):
        pr.save(tmp_path, reg)
    assert "keep me" in (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")


def test_malformed_toml_loads_as_empty_rather_than_crashing_the_app(tmp_path):
    _write(tmp_path, "this is not { valid toml")
    assert pr.load(tmp_path) == {"schema": pr.SCHEMA, "projects": {}}


def _entry(desc="", created="2026-08-01T10:00:00Z", modified="2026-08-01T10:00:00Z", device="d"):
    return {"description": desc, "created": created, "modified": modified, "device": device}


def _reg(**projects):
    return {"schema": pr.SCHEMA, "projects": dict(projects)}


# Contract §13.2, row by row. Each test quotes its row.

def test_row1_absent_present_absent_added_locally_keep():
    out = pr.merge(_reg(), _reg(a=_entry("mine")), _reg())
    assert out["projects"]["a"]["description"] == "mine"


def test_row2_absent_absent_present_added_remotely_keep():
    out = pr.merge(_reg(), _reg(), _reg(a=_entry("theirs")))
    assert out["projects"]["a"]["description"] == "theirs"


def test_row3_absent_present_present_both_added_same_name_merge_per_field():
    local = _reg(a=_entry("mine", modified="2026-08-01T10:00:00Z"))
    remote = _reg(a=_entry("theirs", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(_reg(), local, remote)
    assert out["projects"]["a"]["description"] == "theirs"   # newest modified wins


def test_row4_present_absent_unchanged_deleted_locally_delete_applies():
    base = _reg(a=_entry("d"))
    out = pr.merge(base, _reg(), _reg(a=_entry("d")))
    assert "a" not in out["projects"]


def test_row5_present_present_differing_newest_modified_wins():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    local = _reg(a=_entry("local edit", modified="2026-08-01T12:00:00Z"))
    remote = _reg(a=_entry("remote edit", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(base, local, remote)
    assert out["projects"]["a"]["description"] == "local edit"


def test_row5_exact_tie_goes_to_remote():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    same = "2026-08-01T12:00:00Z"
    out = pr.merge(base, _reg(a=_entry("local", modified=same)),
                   _reg(a=_entry("remote", modified=same)))
    assert out["projects"]["a"]["description"] == "remote"


def test_row6_edit_beats_delete_entry_is_resurrected():
    # The row that needs stating out loud (contract §13.2). Resurrecting costs the user one
    # redundant delete; honouring the delete would destroy a description they just wrote.
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    remote = _reg(a=_entry("just written", modified="2026-08-01T12:00:00Z"))
    out = pr.merge(base, _reg(), remote)
    assert out["projects"]["a"]["description"] == "just written"


def test_row6_mirrored_local_edit_beats_remote_delete():
    base = _reg(a=_entry("old", modified="2026-08-01T09:00:00Z"))
    local = _reg(a=_entry("just written", modified="2026-08-01T12:00:00Z"))
    out = pr.merge(base, local, _reg())
    assert out["projects"]["a"]["description"] == "just written"


def test_deleted_on_both_sides_stays_deleted():
    assert pr.merge(_reg(a=_entry()), _reg(), _reg())["projects"] == {}


def test_created_is_immutable_and_takes_the_earlier_value():
    base = _reg(a=_entry(created="2026-08-01T10:00:00Z"))
    local = _reg(a=_entry(created="2026-08-01T10:00:00Z", modified="2026-08-01T12:00:00Z"))
    remote = _reg(a=_entry(created="2026-07-30T08:00:00Z", modified="2026-08-01T11:00:00Z"))
    out = pr.merge(base, local, remote)
    assert out["projects"]["a"]["created"] == "2026-07-30T08:00:00Z"


def test_merge_raises_on_an_unreadable_remote_schema():
    # Contract §13.2: `schema` is not merged — an unreadable remote schema must not be silently
    # stamped over with SCHEMA, which would drop fields this build cannot see.
    remote = {"schema": 99, "projects": {}}
    with pytest.raises(pr.UnknownSchemaError):
        pr.merge(_reg(), _reg(), remote)


def test_merge_raises_on_an_unreadable_local_schema():
    # Same contract row, other side: a local registry carrying an unreadable schema must also
    # be refused rather than merged.
    local = {"schema": 99, "projects": {}}
    with pytest.raises(pr.UnknownSchemaError):
        pr.merge(_reg(), local, _reg())


def test_merge_succeeds_when_all_three_registries_are_schema_1():
    # The guard must not over-fire on the ordinary all-schema-1 case.
    out = pr.merge(_reg(), _reg(a=_entry("mine")), _reg())
    assert out["schema"] == pr.SCHEMA
    assert out["projects"]["a"]["description"] == "mine"


def test_unrelated_entries_on_each_side_both_survive():
    # The whole reason this is not last-writer-wins: two devices editing DIFFERENT projects in
    # one batch window write the same file.
    base = _reg()
    out = pr.merge(base, _reg(mine=_entry("m")), _reg(theirs=_entry("t")))
    assert set(out["projects"]) == {"mine", "theirs"}


def test_unknown_keys_survive_a_merge():
    base = _reg()
    local = _reg(a={**_entry("m"), "future_field": "keep"})
    out = pr.merge(base, local, _reg())
    assert out["projects"]["a"]["future_field"] == "keep"


def test_renamed_from_is_carried_through_a_merge():
    out = pr.merge(_reg(), _reg(new={**_entry("d"), "renamed_from": "old"}), _reg())
    assert out["projects"]["new"]["renamed_from"] == "old"


def test_resolve_returns_the_project_when_registered():
    reg = _reg(research=_entry())
    assert pr.resolve_project("body #project@research", reg) == "research"


def test_no_tag_is_loose():
    assert pr.resolve_project("plain body", _reg(research=_entry())) is None


def test_an_unregistered_name_is_loose_this_one_rule_absorbs_deletion_and_sync_lag():
    assert pr.resolve_project("#project@deleted", _reg()) is None


def test_an_ineligible_name_is_loose_and_never_registered():
    assert pr.resolve_project("#project@a/b", _reg()) is None


def test_renamed_from_resolves_the_old_name_to_the_new_project():
    # Required for CORRECTNESS, not convenience: a note on an offline phone still carries the old
    # tag, and without this a rename silently empties its own project (contract §1.3).
    reg = _reg(**{"research-cancer": {**_entry(), "renamed_from": "cancer"}})
    assert pr.resolve_project("#project@cancer", reg) == "research-cancer"
    assert pr.resolve_project("#project@research-cancer", reg) == "research-cancer"


def test_a_current_key_beats_another_entrys_renamed_from():
    reg = {"schema": pr.SCHEMA, "projects": {
        "cancer": _entry(),
        "research-cancer": {**_entry(), "renamed_from": "cancer"},
    }}
    assert pr.resolve_project("#project@cancer", reg) == "cancer"


def test_rebuild_from_vault_finds_every_project_with_an_empty_description(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "a.md").write_text("---\nid: 1\n---\n\nbody #project@research\n", encoding="utf-8")
    (tmp_path / "_loose").mkdir()
    (tmp_path / "_loose" / "b.md").write_text("---\nid: 2\n---\n\nno tag here\n", encoding="utf-8")
    reg = pr.rebuild_from_vault(tmp_path)
    assert set(reg["projects"]) == {"research"}
    assert reg["projects"]["research"]["description"] == ""


def test_rebuild_skips_ineligible_names(tmp_path):
    (tmp_path / "a.md").write_text("---\nid: 1\n---\n\n#project@a/b\n", encoding="utf-8")
    assert pr.rebuild_from_vault(tmp_path)["projects"] == {}


def test_clear_stale_renamed_from_clears_when_no_note_carries_the_old_name():
    reg = _reg(new={**_entry(), "renamed_from": "old"})
    out = pr.clear_stale_renamed_from(reg, live_names=set())
    assert "renamed_from" not in out["projects"]["new"]


def test_clear_stale_renamed_from_keeps_it_while_a_note_still_carries_the_old_name():
    reg = _reg(new={**_entry(), "renamed_from": "old"})
    out = pr.clear_stale_renamed_from(reg, live_names={"old"})
    assert out["projects"]["new"]["renamed_from"] == "old"


def test_save_writes_atomically_via_a_temp_sibling(tmp_path, monkeypatch):
    # save() must go through atomic_io's temp-sibling + os.replace idiom, not a bare
    # write_text -- a crash mid-write must never leave a truncated/empty registry (P2).
    # Proven by making the temp write blow up and asserting the ORIGINAL file survives
    # untouched and no `.tmp` litter is left behind -- exactly atomic_io.py's own smoke test.
    pr.save(tmp_path, _reg(a=_entry("original")))
    original = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")

    import atomic_io

    def _boom(tmp, text, encoding, newline):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(atomic_io.Path, "write_text", _boom)
    with pytest.raises(OSError):
        pr.save(tmp_path, _reg(a=_entry("corrupted")))

    assert (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8") == original
    assert not (tmp_path / (pr.REGISTRY_FILENAME + ".tmp")).exists()


def test_delete_through_update_leaves_every_other_project_byte_for_byte(tmp_path):
    # Pins the gap this task exists to close: a one-project delete, through the REAL public
    # path (project_registry.update -- locked load/mutate/save, the same cycle
    # vault_admin.delete_project's `r["projects"].pop(name, None)` lambda drives), must never
    # clobber an untouched sibling's bytes.
    pr.update(tmp_path, lambda r: r["projects"].update({
        "alpha": _entry("Alpha description."),
        "beta": _entry("Beta description."),
        "gamma": _entry("Gamma description."),
    }))
    before = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    beta_block = before[before.index('[projects."beta"]'):before.index('[projects."gamma"]')]

    pr.update(tmp_path, lambda r: r["projects"].pop("alpha", None))

    after = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    reg = pr.load(tmp_path)
    assert set(reg["projects"]) == {"beta", "gamma"}
    assert reg["projects"]["beta"]["description"] == "Beta description."
    assert reg["projects"]["gamma"]["description"] == "Gamma description."
    # The untouched sibling's serialized block is byte-for-byte identical, not just
    # semantically equal -- a rewrite that reordered or reformatted it would still pass a
    # looser check but would still be evidence of a whole-file clobber.
    assert beta_block in after


def test_rename_through_update_leaves_every_other_project_byte_for_byte(tmp_path):
    # Same gap, the rename half: vault_admin.rename_project's `_rename` mutate (pop old key,
    # re-key with renamed_from set) must not disturb an untouched sibling either.
    pr.update(tmp_path, lambda r: r["projects"].update({
        "alpha": _entry("Alpha description."),
        "beta": _entry("Beta description."),
        "gamma": _entry("Gamma description."),
    }))
    before = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    gamma_block = before[before.index('[projects."gamma"]'):]

    def _rename(r):
        entry = dict(r["projects"].pop("alpha"))
        entry["renamed_from"] = "alpha"
        r["projects"]["alpha-2"] = entry

    pr.update(tmp_path, _rename)

    after = (tmp_path / pr.REGISTRY_FILENAME).read_text(encoding="utf-8")
    reg = pr.load(tmp_path)
    assert set(reg["projects"]) == {"alpha-2", "beta", "gamma"}
    assert reg["projects"]["alpha-2"]["renamed_from"] == "alpha"
    assert reg["projects"]["beta"]["description"] == "Beta description."
    assert reg["projects"]["gamma"]["description"] == "Gamma description."
    assert gamma_block in after
