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
