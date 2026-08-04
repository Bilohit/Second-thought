# omni_capture/test_folder_import.py
import folder_import


def test_sanitise_replaces_illegal_runs_with_single_dash():
    assert folder_import.sanitise_name("My Notes") == "My-Notes"
    assert folder_import.sanitise_name("r&d") == "r-d"
    assert folder_import.sanitise_name("2026 ideas") == "2026-ideas"


def test_sanitise_strips_leading_and_trailing_dashes_and_may_return_empty():
    # A leading char must be alphanumeric; a name of only illegal chars has no suggestion.
    assert folder_import.sanitise_name("_hidden") == "hidden"
    assert folder_import.sanitise_name("!!!") == ""


def test_tag_line_goes_under_the_first_heading():
    body = "# Q3 planning\n\nKickoff is the 14th.\n"
    assert folder_import.tag_line_insert(body, "Work") == (
        "# Q3 planning\n#project@Work\n\nKickoff is the 14th.\n"
    )


def test_tag_line_goes_first_when_there_is_no_heading():
    body = "Kickoff is the 14th.\n"
    assert folder_import.tag_line_insert(body, "Work") == "#project@Work\nKickoff is the 14th.\n"


def test_tag_line_goes_under_a_heading_that_carries_a_utf8_bom():
    """FR-35. Notepad -- the default editor for a Windows user hand-writing a vault -- saves
    UTF-8 WITH a BOM, the apply route reads with plain `utf-8` (not `utf-8-sig`), and
    `note_model.parse_note` captures the body verbatim, so the BOM reaches this function.
    Before the fix `startswith("# ")` missed, the loop fell through, and the tag was prepended
    ABOVE the heading -- breaking placement pick P1 on exactly the vaults the import adopts.
    The BOM byte itself must SURVIVE (body-sacred): it is stepped over, never stripped."""
    body = "\ufeff# Q3 planning\n\nKickoff is the 14th.\n"
    assert folder_import.tag_line_insert(body, "Work") == (
        "\ufeff# Q3 planning\n#project@Work\n\nKickoff is the 14th.\n"
    )


def test_plan_skips_exempt_loose_dot_dirs_and_already_tagged_notes(tmp_path):
    (tmp_path / "Work").mkdir()
    (tmp_path / "Work" / "a.md").write_text("---\nid: 1\n---\n# A\n", encoding="utf-8")
    (tmp_path / "Work" / "b.md").write_text("---\nid: 2\n---\n# B\n#project@Work\n", encoding="utf-8")
    (tmp_path / "_loose").mkdir()
    (tmp_path / "_loose" / "c.md").write_text("---\nid: 3\n---\n# C\n", encoding="utf-8")
    (tmp_path / "_trash").mkdir()
    (tmp_path / "_trash" / "d.md").write_text("---\nid: 4\n---\n# D\n", encoding="utf-8")
    (tmp_path / ".omni_capture").mkdir()

    plan = folder_import.plan_import(tmp_path, {"schema": 1, "projects": {}})

    assert [c.folder for c in plan] == ["Work"]
    assert [p.name for p in plan[0].note_paths] == ["a.md"]


def test_frontmatter_holding_a_project_shaped_string_is_not_read_as_tagged(tmp_path):
    """note_model preserves unknown frontmatter keys verbatim, so a frontmatter VALUE can contain
    a whitespace-preceded `#project@` token. Scanning raw file text would read this note as
    ALREADY TAGGED and silently drop it from every import.

    Note the shape that matters: `_PROJECT_TAG` is whitespace-anchored (projects.py:27), so a URL
    fragment like `page#project@X` does NOT match -- that tightening already defends the URL case.
    The live exposure is a SPACE-PRECEDED token, which is what this fixture uses."""
    (tmp_path / "Work").mkdir()
    (tmp_path / "Work" / "a.md").write_text(
        "---\nid: 9\nsummary: moved from #project@Legacy\n---\n# A\n",
        encoding="utf-8",
    )

    plan = folder_import.plan_import(tmp_path, {"schema": 1, "projects": {}})

    assert [p.name for p in plan[0].note_paths] == ["a.md"]


def test_plan_counts_phone_authored_notes_for_disclosure_without_excluding_them(tmp_path):
    """s140: phone-origin notes ARE imported (user-affirmed); the row only DISCLOSES how many.
    The effective-origin rule is the enrichment pass's own (mobile_sync_agent.py:1462-1464):
    a legacy note with no `origin_device` is phone-origin only if it carries the phone
    authorship marker `enrich_source: phone-heuristic`."""
    (tmp_path / "Work").mkdir()
    (tmp_path / "Work" / "a.md").write_text(
        "---\nid: 1\norigin_device: phone\n---\n# A\n", encoding="utf-8")
    (tmp_path / "Work" / "b.md").write_text(
        "---\nid: 2\nenrich_source: phone-heuristic\n---\n# B\n", encoding="utf-8")
    (tmp_path / "Work" / "c.md").write_text(
        "---\nid: 3\norigin_device: desktop\n---\n# C\n", encoding="utf-8")
    # No origin_device and no phone marker -> desktop, never counted as phone.
    (tmp_path / "Work" / "d.md").write_text("---\nid: 4\n---\n# D\n", encoding="utf-8")

    plan = folder_import.plan_import(tmp_path, {"schema": 1, "projects": {}})

    assert plan[0].phone_count == 2
    # Disclosure only: every note is still a candidate, phone-authored or not.
    assert [p.name for p in plan[0].note_paths] == ["a.md", "b.md", "c.md", "d.md"]


def test_plan_reports_validity_suggestion_and_existing_project(tmp_path):
    for folder in ("My Notes", "Recipes"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "n.md").write_text("---\nid: x\n---\n# N\n", encoding="utf-8")

    plan = {c.folder: c for c in folder_import.plan_import(
        tmp_path, {"schema": 1, "projects": {"Recipes": {"created": "2026-01-01"}}})}

    assert plan["My Notes"].valid is False
    assert plan["My Notes"].suggested == "My-Notes"
    assert plan["Recipes"].valid is True
    assert plan["Recipes"].existing is True
