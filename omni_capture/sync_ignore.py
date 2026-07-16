"""
sync_ignore.py — F-5: per-note LOCAL-ONLY sync-ignore set.

Desktop-local mirror of the phone's local-only sync-ignore behaviour (no
contract change — this never touches data-model-and-contracts.md). Persisted
at `<vault>/.omni_capture/sync_ignore.json` as a flat list of vault-relative
POSIX paths. Enforced at the two outbound sync paths — `mirror_to_hub` and
`reconcile_changes` — via `filter_ignored_notes`, so an ignored file never
leaves this machine in either direction of outbound sync (upload, and the
"local changed, push the merge" half of reconcile). Inbound pulls are also
skipped for an ignored note today, because `filter_ignored_notes` removes it
from `vault_notes` entirely before either sync function ever sees it — this
matches "LOCAL-ONLY" (the file simply never interacts with the hub while
ignored), not merely "never uploaded."

Files remain the source of truth: this JSON sidecar is a derived, disposable
preference file, never authoritative over anything but the ignore set itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def _ignore_file(vault_root: Path) -> Path:
    d = vault_root.resolve() / ".omni_capture"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sync_ignore.json"


def _to_rel(vault_root: Path, path_str: str) -> str:
    root = vault_root.resolve()
    p = Path(path_str)
    p = p.resolve() if p.is_absolute() else (root / p).resolve()
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def load_ignored(vault_root: Path) -> set[str]:
    p = _ignore_file(vault_root)
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return set(data.get("ignored", []))
    except (json.JSONDecodeError, OSError):
        return set()  # derived cache — safe to treat as empty on corruption


def save_ignored(vault_root: Path, ignored: set[str]) -> None:
    p = _ignore_file(vault_root)
    p.write_text(json.dumps({"ignored": sorted(ignored)}, indent=2), encoding="utf-8")


def is_ignored(vault_root: Path, path_str: str) -> bool:
    return _to_rel(vault_root, path_str) in load_ignored(vault_root)


def set_ignored(vault_root: Path, path_str: str, ignored: bool) -> set[str]:
    """Toggle *path_str*'s membership in the ignore set; returns the new set."""
    rel = _to_rel(vault_root, path_str)
    current = load_ignored(vault_root)
    if ignored:
        current.add(rel)
    else:
        current.discard(rel)
    save_ignored(vault_root, current)
    return current


def filter_ignored_notes(vault_notes: Dict[str, Dict], vault_root: Path) -> Dict[str, Dict]:
    """Drop entries from a `read_vault_notes()`-shaped dict whose vault-relative
    path is in the local ignore set. Used at the mirror_to_hub / reconcile_changes
    call sites (see module docstring) — never mutates the input dict."""
    ignored = load_ignored(vault_root)
    if not ignored:
        return vault_notes
    root = vault_root.resolve()
    out: Dict[str, Dict] = {}
    for note_id, note in vault_notes.items():
        try:
            rel = str(Path(note["path"]).resolve().relative_to(root)).replace("\\", "/")
        except (KeyError, ValueError):
            out[note_id] = note
            continue
        if rel in ignored:
            continue
        out[note_id] = note
    return out


# ---------------------------------------------------------------------------
# Smoke test  (python sync_ignore.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        cat = vault / "Personal"
        cat.mkdir()
        note_path = cat / "example.md"
        note_path.write_text("---\nid: n1\n---\nbody\n", encoding="utf-8")

        # T1: default is not ignored.
        assert is_ignored(vault, str(note_path)) is False
        print("[T1] default not ignored  PASS")

        # T2: set_ignored(True) persists and round-trips.
        set_ignored(vault, str(note_path), True)
        assert is_ignored(vault, str(note_path)) is True
        assert "Personal/example.md" in load_ignored(vault)
        print("[T2] set_ignored True  PASS")

        # T3: filter_ignored_notes drops the ignored note.
        notes = {"n1": {"id": "n1", "path": str(note_path)}, "n2": {"id": "n2", "path": str(vault / "Personal" / "other.md")}}
        filtered = filter_ignored_notes(notes, vault)
        assert "n1" not in filtered and "n2" in filtered
        print("[T3] filter_ignored_notes  PASS")

        # T4: set_ignored(False) clears it.
        set_ignored(vault, str(note_path), False)
        assert is_ignored(vault, str(note_path)) is False
        assert filter_ignored_notes(notes, vault) == notes
        print("[T4] set_ignored False  PASS")

    print("\nAll sync_ignore.py smoke tests passed.")
