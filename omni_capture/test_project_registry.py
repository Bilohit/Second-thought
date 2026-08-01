from pathlib import Path

import pytest

import project_registry as pr


def _write(vault: Path, text: str) -> None:
    (vault / pr.REGISTRY_FILENAME).write_text(text, encoding="utf-8")


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
