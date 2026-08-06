"""test_hand_made_folders.py -- FR-34 (s146 ruling; contract §2.1)."""
import json

import project_registry
from hand_made_folders import build_census, write_census


def _mk(vault, *parts, note=False):
    d = vault
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    if note:
        (d / f"{parts[-1]}.md").write_text("x", encoding="utf-8")
    return d


def test_reserved_folders_are_excluded(tmp_path):
    for name in ("_loose", "_scratchpad", "_trash", "_attachments", "_mobile_inbox", "_templates"):
        (tmp_path / name).mkdir()
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_reserved_folders_are_pruned_not_merely_skipped(tmp_path):
    """A reserved folder that only skipped its own row would still let os.walk descend and
    report `_trash/Foo` at depth 2 -- and `_loose` may never be rendered at all."""
    for name in ("_loose", "_scratchpad", "_trash", "_attachments", "_mobile_inbox", "_templates"):
        _mk(tmp_path, name, "Sub", note=True)
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_hand_made_folder_inside_a_registry_project_is_reported(tmp_path):
    """Contract §2.1's own example: `Work/Clients` where `Work` is a registry project. The
    project folder is pruned from the rows but MUST still be descended into."""
    _mk(tmp_path, "Work", "Clients", note=True)
    (tmp_path / ".projects.toml").write_text(
        'schema = 1\n[projects.Work]\ndescription = "d"\n', encoding="utf-8"
    )
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == [{"path": "Work/Clients", "depth": 2, "note_count": 1}]


def test_registry_project_folder_excluded_at_depth1(tmp_path):
    (tmp_path / "Work").mkdir()
    (tmp_path / ".projects.toml").write_text(
        'schema = 1\n[projects.Work]\ndescription = "d"\n', encoding="utf-8"
    )
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_registry_project_with_custom_dir_excluded_by_dir_not_name(tmp_path):
    # A project's HOME can differ from its name (contract §13.1, v3.2) -- exclusion 1 must
    # test the resolved directory, not the registry key.
    (tmp_path / "My Notes").mkdir()
    (tmp_path / ".projects.toml").write_text(
        'schema = 1\n[projects.MyNotes]\ndescription = "d"\ndir = "My Notes"\n', encoding="utf-8"
    )
    reg = project_registry.load(tmp_path)
    assert reg["projects"]["MyNotes"]["dir"] == "My Notes"  # sanity: registry actually parsed it
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_attachments_descendants_excluded_regardless_of_depth(tmp_path):
    _mk(tmp_path, "_attachments", "note-id-1")
    _mk(tmp_path, "_attachments", "note-id-1", "deep")
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_dot_prefixed_excluded(tmp_path):
    (tmp_path / ".sync").mkdir()
    (tmp_path / ".omni_capture").mkdir()
    census = build_census(tmp_path, "desktop-t")
    assert census["folders"] == []


def test_hand_made_folder_at_depth3_reports_correct_depth(tmp_path):
    _mk(tmp_path, "Work", "Clients", "Acme")
    census = build_census(tmp_path, "desktop-t")
    by_path = {f["path"]: f for f in census["folders"]}
    assert by_path.keys() == {"Work", "Work/Clients", "Work/Clients/Acme"}
    assert by_path["Work/Clients/Acme"]["depth"] == 3


def test_note_count_is_direct_children_only(tmp_path):
    nested = _mk(tmp_path, "Work", "Clients")
    (tmp_path / "Work" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "Work" / "b.md").write_text("x", encoding="utf-8")
    (nested / "c.md").write_text("x", encoding="utf-8")
    census = build_census(tmp_path, "desktop-t")
    by_path = {f["path"]: f for f in census["folders"]}
    assert by_path["Work"]["note_count"] == 2
    assert by_path["Work/Clients"]["note_count"] == 1


def test_folders_sorted_by_path(tmp_path):
    for name in ("Zebra", "Apple", "Mango"):
        (tmp_path / name).mkdir()
    census = build_census(tmp_path, "desktop-t")
    paths = [f["path"] for f in census["folders"]]
    assert paths == sorted(paths) == ["Apple", "Mango", "Zebra"]


def test_path_never_contains_vault_root(tmp_path):
    _mk(tmp_path, "Work", "Clients")
    census = build_census(tmp_path, "desktop-t")
    root_str = str(tmp_path)
    for f in census["folders"]:
        assert root_str not in f["path"]
        assert "\\" not in f["path"]  # '/'-separated, contract §2.1
        assert not f["path"].startswith("/")


def test_missing_vault_root_yields_zero_folders_not_an_error(tmp_path):
    missing = tmp_path / "does-not-exist"
    census = build_census(missing, "desktop-t")
    assert census["folders"] == []
    assert census["version"] == 1
    assert census["device"] == "desktop-t"


def test_census_shape(tmp_path):
    census = build_census(tmp_path, "desktop-t")
    assert set(census.keys()) == {"version", "generated_at", "device", "folders"}
    assert census["generated_at"].endswith("Z")


def test_write_census_creates_file_and_skips_when_unchanged(tmp_path):
    _mk(tmp_path, "Work")
    path1, changed1 = write_census(tmp_path, "desktop-t")
    assert changed1 is True
    on_disk = json.loads((tmp_path / ".sync" / "hand_made_folders.json").read_text(encoding="utf-8"))
    assert on_disk["folders"] == [{"path": "Work", "depth": 1, "note_count": 0}]

    path2, changed2 = write_census(tmp_path, "desktop-t")
    assert changed2 is False
    assert path1 == path2
    # Unchanged means the file was left alone -- generated_at must NOT have moved.
    still_on_disk = json.loads((tmp_path / ".sync" / "hand_made_folders.json").read_text(encoding="utf-8"))
    assert still_on_disk["generated_at"] == on_disk["generated_at"]


def test_write_census_rewrites_when_folders_change(tmp_path):
    write_census(tmp_path, "desktop-t")
    _mk(tmp_path, "NewFolder")
    _, changed = write_census(tmp_path, "desktop-t")
    assert changed is True
    on_disk = json.loads((tmp_path / ".sync" / "hand_made_folders.json").read_text(encoding="utf-8"))
    assert {f["path"] for f in on_disk["folders"]} == {"NewFolder"}


def test_write_census_never_writes_inside_a_hand_made_folder(tmp_path):
    # READ-ONLY IS THE WHOLE POINT (s146). The only file this module ever creates is the
    # one census file under .sync/.
    hand_made = _mk(tmp_path, "Work")
    before = set(hand_made.iterdir())
    write_census(tmp_path, "desktop-t")
    after = set(hand_made.iterdir())
    assert before == after == set()
