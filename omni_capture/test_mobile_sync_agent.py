"""
test_mobile_sync_agent.py — offline tests for the desktop note-only enrichment.

Runs FULLY offline: the LLM (`_suggest_via_llm`), the embedding
(`_index_embedding`), and Drive are monkeypatched at their boundaries; the
capture pipeline entry points are injected as fakes that raise if ever called.
Nothing here reaches Ollama, the network, or live Drive.

Asserts the data-model §7 desktop enrichment contract:
  1. an `origin: note`, `enriched: false` note gains a unioned `tags` set (user
     tags kept), a `category` from the LIVE folder enum, `enriched: true`, and
     `enrich_source: "desktop-llm"`;
  2. the Markdown body is byte-identical before/after (the mandatory
     body-sacred assertion);
  3. no dedup/merge/scratchpad/`run_pipeline` path is taken.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Match the repo convention: make sibling pipeline modules importable when
# pytest is invoked from anywhere (no conftest / package in this tree).
sys.path.insert(0, str(Path(__file__).parent))

import mobile_sync_agent as msa
from config import Config, VaultConfig
from frontmatter import strip_frontmatter


# --- fixtures --------------------------------------------------------------

_NOTE = (
    "---\n"
    "id: 01J8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8\n"
    "title: Call mom re taxes\n"
    "origin: note\n"
    "created: 2026-07-07T10:00:00Z\n"
    "modified: 2026-07-07T10:05:00Z\n"
    "device: phone-a1b2\n"
    "tags:\n"
    "  - family\n"
    "aliases: []\n"
    "remind_at: 2026-07-08T09:00:00Z\n"
    "custom_future_key: preserve-me\n"
    "enriched: false\n"
    "enrich_source: phone-heuristic\n"
    "---\n"
    "# Call mom\n"
    "\n"
    "- [ ] ask about the 2025 return\n"
    "- [ ] send her the [[Tax Docs]]\n"
    "\n"
    "A stray --- fence inside the body must not confuse the parser.\n"
)


def _make_vault(tmp_path: Path) -> tuple[Config, Path]:
    """A vault with two live category folders and one un-enriched note."""
    (tmp_path / "personal").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "_scratchpad").mkdir()  # system folder — must NOT be a category
    note_path = tmp_path / "personal" / "call-mom.md"
    note_path.write_bytes(_NOTE.encode("utf-8"))
    cfg = Config(vault=VaultConfig(root=tmp_path, scratchpad_folder="_scratchpad"))
    return cfg, note_path


def _install_pipeline_landmines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake `main`/`server` whose pipeline entry points explode if called.

    The note-only path must never route through the capture pipeline, so any
    call here is a hard failure.
    """
    def _boom(*_a, **_k):
        raise AssertionError("capture pipeline was invoked from the note-only path")

    fake_main = types.ModuleType("main")
    fake_main.run_pipeline = _boom  # type: ignore[attr-defined]
    fake_server = types.ModuleType("server")
    fake_server._run_pipeline_blocking = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.setitem(sys.modules, "server", fake_server)


# --- tests -----------------------------------------------------------------

def test_enrich_note_writes_patch_and_keeps_body_sacred(monkeypatch, tmp_path):
    cfg, note_path = _make_vault(tmp_path)
    _install_pipeline_landmines(monkeypatch)

    body_before = strip_frontmatter(note_path.read_bytes().decode("utf-8"))

    # Boundary mocks: no Ollama, no network.
    monkeypatch.setattr(
        msa, "_suggest_via_llm",
        lambda body, cfg: (["planning", "roadmap-q3"], "work"),
    )
    embed_calls: list[tuple] = []
    monkeypatch.setattr(
        msa, "_index_embedding",
        lambda vault_root, np, content, cfg: embed_calls.append((np, content)),
    )

    patch = msa.enrich_note_file(note_path, cfg=cfg)

    # (1) patch fields
    assert patch["enriched"] is True
    assert patch["enrich_source"] == "desktop-llm"
    assert patch["category"] == "work"
    # tags: union, user-typed "family" kept, LLM tags added
    assert "family" in patch["tags"]
    assert "planning" in patch["tags"] and "roadmap-q3" in patch["tags"]

    # category comes from the LIVE folder enum (personal/work), not scratchpad/system
    live = msa._live_categories(cfg)
    assert live == ["personal", "work"]
    assert patch["category"] in live

    # persisted frontmatter reflects the patch
    after = note_path.read_bytes().decode("utf-8")
    entries = msa._parse_block(msa._FM_RE.match(after).group(1))
    assert msa._read_scalar(entries, "enriched") == "true"
    assert msa._read_scalar(entries, "enrich_source") == "desktop-llm"
    assert msa._read_scalar(entries, "category") == "work"
    assert "family" in (msa._read_list(entries, "tags") or [])

    # immutable / unknown fields round-tripped, never stripped (contract §12)
    assert msa._read_scalar(entries, "id") == "01J8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8ZQ8"
    assert msa._read_scalar(entries, "origin") == "note"
    assert msa._read_scalar(entries, "created") == "2026-07-07T10:00:00Z"
    assert msa._read_scalar(entries, "custom_future_key") == "preserve-me"
    assert msa._read_scalar(entries, "remind_at") == "2026-07-08T09:00:00Z"

    # (2) BODY BYTE-IDENTICAL (the mandatory body-sacred assertion)
    body_after = strip_frontmatter(after)
    assert body_after == body_before
    assert note_path.read_bytes().endswith(body_before.encode("utf-8"))

    # embedding was computed once (into the desktop-local vectors.db)
    assert len(embed_calls) == 1

    # (3) no pipeline path taken — landmines never fired (else AssertionError above)


def test_capture_note_is_skipped_untouched(monkeypatch, tmp_path):
    """`origin: capture` must never be grabbed by the note-only path."""
    cfg, _ = _make_vault(tmp_path)
    _install_pipeline_landmines(monkeypatch)

    cap = (tmp_path / "personal" / "clip.md")
    original = _NOTE.replace("origin: note", "origin: capture").encode("utf-8")
    cap.write_bytes(original)

    def _fail(*_a, **_k):
        raise AssertionError("enrichment must not run on a capture note")

    monkeypatch.setattr(msa, "_suggest_via_llm", _fail)
    monkeypatch.setattr(msa, "_index_embedding", _fail)

    patch = msa.enrich_note_file(cap, cfg=cfg)
    assert patch == {}
    assert cap.read_bytes() == original  # completely untouched


def test_already_enriched_note_is_skipped(monkeypatch, tmp_path):
    cfg, note_path = _make_vault(tmp_path)
    note_path.write_bytes(_NOTE.replace("enriched: false", "enriched: true").encode("utf-8"))

    def _fail(*_a, **_k):
        raise AssertionError("must not re-enrich an already enriched note")

    monkeypatch.setattr(msa, "_suggest_via_llm", _fail)
    monkeypatch.setattr(msa, "_index_embedding", _fail)

    assert msa.enrich_note_file(note_path, cfg=cfg) == {}


def test_mirror_honors_exclusions(tmp_path):
    """Vault->hub enumeration mirrors notes and drops derived/system files."""
    (tmp_path / "personal").mkdir()
    (tmp_path / ".omni_capture").mkdir()
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "personal" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / ".omni_capture" / "captures.db").write_text("db", encoding="utf-8")
    (tmp_path / ".omni_capture" / "notes.md").write_text("derived", encoding="utf-8")
    (tmp_path / ".obsidian" / "workspace.md").write_text("cfg", encoding="utf-8")
    (tmp_path / "personal" / ".category.toml").write_text("d", encoding="utf-8")

    pushed: list[tuple[str, bytes]] = []
    cfg = Config(vault=VaultConfig(root=tmp_path))
    mirrored = msa.mirror_vault_to_hub(
        tmp_path, lambda rel, content: pushed.append((rel, content)), cfg=cfg
    )

    assert mirrored == ["SecondThoughtVault/personal/a.md"]
    assert [p[0] for p in pushed] == ["SecondThoughtVault/personal/a.md"]
    assert pushed[0][1] == b"x"


def test_write_back_and_reconcile_are_v0_1_stubs(tmp_path):
    """Bidirectional paths are deliberate v0.1 stubs, not silent no-ops."""
    with pytest.raises(NotImplementedError):
        msa.pull_and_reconcile(tmp_path)
    with pytest.raises(NotImplementedError):
        msa.push_enriched_frontmatter(tmp_path / "x.md")
