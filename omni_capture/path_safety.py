"""
path_safety.py - one neutral resolve-and-compare guard for vault subdirectories.

Extracted from vault_admin._safe_category_dir so that non-server modules
(trash.py, mobile_sync_agent.py) can reuse the strongest guard in the repo
without importing a server-adjacent admin module and without inheriting its
FastAPI coupling. `vault_admin._safe_category_dir` is now a thin HTTP-wrapping
call into this; it remains the entry point for route handlers.

This is deliberately NOT a replacement for the two narrower guards:
  - provisional_store._validate_op_id     allowlist ^[A-Za-z0-9_-]+$ (op ids only;
                                          rejects the dots/spaces every real filename has)
  - mobile_sync_agent._safe_path_component  blocklist for a single hub-supplied
                                          path component, no filesystem access

Use this one when the value names a DIRECTORY that must sit directly inside the
vault root. Raises ValueError so callers pick their own failure mode.
"""
from __future__ import annotations
import re
from pathlib import Path


def safe_name(name: str) -> str:
    """Replace every character that is not word/dash/dot/space with an underscore."""
    return re.sub(r"[^\w\-. ]", "_", name).strip()


def safe_subdir(root: Path, name: str) -> Path:
    """
    Resolve `name` as a directory that is guaranteed to live DIRECTLY inside
    `root`.

    Note the two-stage contract, preserved verbatim from vault_admin so that
    category CRUD behaviour does not change: separators and traversal segments
    are first NEUTRALIZED by `safe_name` (`../evil` -> `.._evil`, a harmless
    literal directory name), and the resolve-and-compare below is the backstop
    that guarantees the result never escapes or nests below the root. Only a
    name that is empty or dot-only after cleaning raises.

    Raises ValueError on any invalid / unsafe name.
    """
    cleaned = safe_name(name)
    cleaned = re.sub(r"[. ]+$", "", cleaned)  # Windows silently strips trailing dots/spaces
    if not cleaned or cleaned in (".", ".."):
        raise ValueError(f"invalid vault subdirectory name: {name!r}")

    root_resolved = root.resolve()
    target = (root_resolved / cleaned).resolve()
    if target.parent != root_resolved:
        raise ValueError(f"vault subdirectory must not traverse or nest: {name!r}")
    return target


# ---------------------------------------------------------------------------
# Smoke test  (python path_safety.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Ordinary names survive, including the dots/spaces an allowlist would eat.
        assert safe_subdir(root, "Ideas").name == "Ideas"
        assert safe_subdir(root, "Work Notes").name == "Work Notes"
        assert safe_subdir(root, "v1.2 drafts").name == "v1.2 drafts"
        assert safe_subdir(root, "Ideas").parent == root.resolve()

        # Empty / dot-only names are refused outright.
        for bad in ("", "   ", ".", "..", "...", ". . .", "..  "):
            try:
                safe_subdir(root, bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError for {bad!r}")

        # Traversal and separators are NEUTRALIZED, not refused -- but the
        # resolve-and-compare backstop guarantees the result stays in the vault.
        # This is the property that actually matters at every call site.
        for hostile in ("../evil", "..\\evil", "../../etc/passwd", "a/b", "a\\b",
                        "C:evil", "\\\\server\\share", "Ideas/../../out", "./", "../"):
            got = safe_subdir(root, hostile)
            assert got.parent == root.resolve(), f"{hostile!r} escaped to {got}"

        # Windows trailing-dot/space stripping must not open an escape.
        assert safe_subdir(root, "Ideas.").name == "Ideas"
        assert safe_subdir(root, "Ideas  ").name == "Ideas"

        print("path_safety smoke OK")
