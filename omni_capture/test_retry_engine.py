"""
test_retry_engine.py
---------------------
P2a: the enrichment retry engine that needs_llm_retry has always promised but
never performed. No fixtures/conftest -- plain functions, pytest's tmp_path only.

The safety gate is the point of this file. A placeholder is repaired only while it
is provably untouched; every negative case below must leave the file byte-identical.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from frontmatter import strip_frontmatter
from storage_engine import route_failed_llm
from retry_engine import (
    LEGACY_EDIT_SLACK_S,
    body_signature,
    is_retryable,
    placeholder_matches,
    retry_pending,
    _extract_original_text,
)
from models import CaptureOutput
from config import Config


def _place(tmp_path: Path, text: str = "raw text that must not be lost") -> Path:
    return route_failed_llm(
        text, "Ollama connection refused",
        vault_root=tmp_path, scratchpad_folder="_scratchpad",
    )


def _strip_sig(path: Path) -> str:
    """Rewrite a placeholder as a pre-retry_sig (legacy) one, preserving mtime so it
    still reads as untouched."""
    text = path.read_text(encoding="utf-8")
    legacy = "\n".join(l for l in text.split("\n") if not l.startswith("retry_sig:"))
    st = path.stat()
    path.write_text(legacy, encoding="utf-8")
    os.utime(path, (st.st_atime, st.st_mtime))
    return legacy


def _make_cfg(vault_root: Path) -> Config:
    cfg = Config()
    cfg.vault.root = vault_root
    cfg.vault.scratchpad_folder = "_scratchpad"
    cfg.vector.enabled = False
    return cfg


def _good_output(filename: str = "recovered-note", project: str | None = "Tech_Notes") -> CaptureOutput:
    out = CaptureOutput(
        suggested_filename=filename,
        markdown_content="# Recovered\n\nrepaired body", rationale="ok",
        key_signals=["k"], confidence=0.9, requires_new_category=False,
    )
    out.project = project
    return out


def _register(vault: Path, name: str = "Tech_Notes") -> None:
    """A project exists in `.projects.toml`, not on disk -- its folder appears the
    first time a note is filed into it."""
    import project_registry
    project_registry.save(vault, {"schema": 1, "projects": {name: {"description": ""}}})


# --------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------

def test_is_retryable_true_for_flagged_placeholder(tmp_path: Path):
    assert is_retryable(_place(tmp_path).read_text(encoding="utf-8")) is True


def test_is_retryable_false_without_the_flag():
    text = "---\ncreated: 2026-07-31T00:00:00\ntags: []\n---\n\nordinary note body\n"
    assert is_retryable(text) is False


def test_placeholder_matches_true_for_untouched_placeholder(tmp_path: Path):
    path = _place(tmp_path)
    assert placeholder_matches(path.read_text(encoding="utf-8"), path) is True


def test_route_failed_llm_stamps_a_retry_sig_over_the_body(tmp_path: Path):
    """The signature must be computed over exactly the bytes strip_frontmatter
    returns -- otherwise every repair is gated on a hash that can never match."""
    text = _place(tmp_path).read_text(encoding="utf-8")
    sig = [l for l in text.split("\n") if l.startswith("retry_sig:")][0].split(": ", 1)[1]
    assert sig == body_signature(strip_frontmatter(text))


def test_placeholder_matches_false_for_appended_edit(tmp_path: Path):
    """SAFETY GATE: an appended edit leaves the warning banner intact, so the banner
    prefix alone cannot catch it -- only the signature can."""
    path = _place(tmp_path)
    text = path.read_text(encoding="utf-8")
    edited = text + "Actually let me add my own note here.\n"
    assert is_retryable(edited) is True           # flag still set...
    assert placeholder_matches(edited, path) is False  # ...but the body no longer hashes


def test_placeholder_matches_false_when_the_banner_is_removed(tmp_path: Path):
    path = _place(tmp_path)
    text = path.read_text(encoding="utf-8")
    gutted = text.replace("> [!warning] LLM enrichment failed\n", "")
    assert placeholder_matches(gutted, path) is False


def test_legacy_placeholder_without_sig_passes_only_while_unmodified(tmp_path: Path):
    """Pre-retry_sig placeholders fall back to mtime-vs-created."""
    path = _place(tmp_path)
    legacy = _strip_sig(path)
    assert "retry_sig" not in legacy
    assert placeholder_matches(legacy, path) is True

    # Touching the file past the slack window reads as edited.
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + LEGACY_EDIT_SLACK_S + 60))
    assert placeholder_matches(path.read_text(encoding="utf-8"), path) is False


def test_legacy_placeholder_cannot_be_proven_untouched_without_a_path(tmp_path: Path):
    """No path -> no mtime -> a legacy placeholder is unverifiable, so it is skipped."""
    path = _place(tmp_path)
    legacy = _strip_sig(path)
    assert placeholder_matches(legacy) is False


def test_extract_original_text_returns_the_raw_capture(tmp_path: Path):
    path = _place(tmp_path, "the raw captured text that must not be lost")
    body = strip_frontmatter(path.read_text(encoding="utf-8"))
    assert _extract_original_text(body) == "the raw captured text that must not be lost"


# --------------------------------------------------------------------------
# retry_pending -- preconditions
# --------------------------------------------------------------------------

def test_retry_pending_noop_when_scratchpad_missing(tmp_path: Path):
    summary = retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: True})
    assert summary == {"attempted": 0, "recovered": 0, "skipped": 0, "failed": 0}


def test_retry_pending_runs_with_no_projects_at_all(tmp_path: Path):
    """Projects S1 (Task 13): the old ">=1 category folder" precondition is DELETED.
    A retry can always succeed now -- worst case the repaired note lands in `_loose/`
    -- so an empty registry must no longer disable the pass. The old test asserted the
    opposite; keeping it would have permanently disabled retries on a fresh vault."""
    _place(tmp_path, "the raw captured text that must not be lost")

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(return_value=_good_output(project=None)),
            },
        )

    assert summary == {"attempted": 1, "recovered": 1, "skipped": 0, "failed": 0}
    written = list((tmp_path / "_loose").glob("*.md"))
    assert len(written) == 1, f"expected one recovered note in _loose, got {written}"


def test_retry_pending_skips_pass_when_ollama_unreachable(tmp_path: Path):
    _register(tmp_path)
    _place(tmp_path)
    summary = retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: False})
    assert summary["attempted"] == 0


# --------------------------------------------------------------------------
# retry_pending -- repair path
# --------------------------------------------------------------------------

def test_retry_pending_repairs_a_matching_placeholder(tmp_path: Path):
    _register(tmp_path)
    placeholder_path = _place(tmp_path, "the raw captured text that must not be lost")

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(return_value=_good_output()),
            },
        )

    assert summary == {"attempted": 1, "recovered": 1, "skipped": 0, "failed": 0}
    assert not placeholder_path.exists(), "the old placeholder must be removed after repair"
    # write_to_vault derives the filename from the note's title (s55), so the
    # suggested_filename is a hint, not the path -- assert on the project folder.
    written = list((tmp_path / "Tech_Notes").glob("*.md"))
    assert len(written) == 1, f"expected one recovered note, got {written}"
    text = written[0].read_text(encoding="utf-8")
    assert "needs_llm_retry" not in text
    assert "repaired body" in text


def test_retry_pending_feeds_the_raw_text_back_to_the_llm(tmp_path: Path):
    """The banner must not reach the model -- it would be classified as content."""
    _register(tmp_path)
    _place(tmp_path, "kubernetes ingress notes")
    llm = mock.Mock(return_value=_good_output())

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        retry_pending(tmp_path, deps={"is_ollama_reachable": lambda: True, "run_llm_engine": llm})

    enriched = llm.call_args[0][0]
    assert enriched.enriched_text == "kubernetes ingress notes"
    assert "[!warning]" not in enriched.enriched_text


def test_retry_pending_never_touches_a_hand_edited_placeholder(tmp_path: Path):
    """SAFETY GATE end-to-end: a hand-edited body is skipped and left byte-identical,
    even though needs_llm_retry: true is still set."""
    _register(tmp_path)
    placeholder_path = _place(tmp_path)
    edited = placeholder_path.read_text(encoding="utf-8") + "\nmy own edit\n"
    placeholder_path.write_text(edited, encoding="utf-8")

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(side_effect=AssertionError("must not be called")),
            },
        )

    assert summary == {"attempted": 0, "recovered": 0, "skipped": 1, "failed": 0}
    assert placeholder_path.exists()
    assert placeholder_path.read_text(encoding="utf-8") == edited, "hand-edited body must be byte-identical"


# --------------------------------------------------------------------------
# retry_pending -- boundedness and failure containment
# --------------------------------------------------------------------------

def test_retry_pending_is_bounded_per_run(tmp_path: Path):
    _register(tmp_path)
    for i in range(3):
        _place(tmp_path, f"raw text {i}")

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={
                "is_ollama_reachable": lambda: True,
                "run_llm_engine": mock.Mock(side_effect=lambda e, **kw: _good_output(
                    "recovered-" + e.enriched_text.split()[-1])),
            },
            max_items=2,
        )

    assert summary["attempted"] == 2, "must stop at max_items even with 3 eligible placeholders"
    remaining = list((tmp_path / "_scratchpad").glob("*.md"))
    assert len(remaining) == 1, "the un-attempted placeholder must be left for the next pass"


def test_retry_pending_contains_a_per_item_failure(tmp_path: Path):
    """One bad capture must not abort the pass -- the other eligible item in the
    same run still gets repaired."""
    _register(tmp_path)
    _place(tmp_path, "bad raw text")
    _place(tmp_path, "good raw text")

    def _flaky_llm(enriched, **kwargs):
        if "bad" in enriched.enriched_text:
            raise RuntimeError("model still unavailable")
        return _good_output()

    import config as config_module
    with mock.patch.object(config_module, "get_config", lambda: _make_cfg(tmp_path)):
        summary = retry_pending(
            tmp_path,
            deps={"is_ollama_reachable": lambda: True, "run_llm_engine": _flaky_llm},
        )

    assert summary == {"attempted": 2, "recovered": 1, "skipped": 0, "failed": 1}
    remaining = list((tmp_path / "_scratchpad").glob("*.md"))
    assert len(remaining) == 1, "the failed item stays in place, still needs_llm_retry: true"
    assert is_retryable(remaining[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
