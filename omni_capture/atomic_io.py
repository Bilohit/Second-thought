"""
atomic_io.py - the two atomic write shapes this codebase already uses, in one place.

The repo demonstrably knows the correct idiom (temp sibling + os.replace) and uses it in
three places: `mobile_sync_agent._atomic_write_note`, `mobile_sync_agent.save_state`, and
`provisional_store._save_state`. Several other modules did a bare `write_text`, which
truncates the target and streams -- a crash mid-write leaves a TORN file that parses fine
and is therefore indistinguishable from a real edit.

There are deliberately TWO functions here, not one. Conflating them breaks things:

  atomic_write_verbatim  -- newline="" -- for anything whose bytes belong to the user.
                            `newline=""` is load-bearing, not cosmetic: it disables newline
                            translation on write, which is what stops an LF note being
                            silently rewritten CRLF-wide on Windows (body-sacred).
  atomic_write_text      -- default newline handling -- for machine-owned sidecars
                            (JSON indexes, TOML config). These are not note bodies and
                            os.linesep is fine.

`mobile_sync_agent._atomic_write_note` is deliberately NOT rerouted through this module:
its `.md.tmp` sibling naming is load-bearing for `_reap_tmp_orphans`, and its docstring
carries the S4-1 history. It is the same idiom, kept where its context lives.
"""
from __future__ import annotations

import os
from pathlib import Path


def _atomic(path: Path, text: str, newline: str | None) -> None:
    """Write `text` to `path` via a temp SIBLING + os.replace.

    The temp must be a sibling: os.replace is only atomic within one filesystem, and a
    cross-device rename fails outright. On any failure the temp is reaped so a crashed
    write does not leave litter next to the real file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline=newline)
        os.replace(tmp, path)   # atomic
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_verbatim(path: Path, text: str) -> None:
    """Atomic, byte-verbatim. Use for note bodies and anything else user-owned."""
    _atomic(path, text, newline="")


def atomic_write_text(path: Path, text: str) -> None:
    """Atomic, default newline handling. Use for machine-owned sidecars only."""
    _atomic(path, text, newline=None)


# ---------------------------------------------------------------------------
# Smoke test  (python atomic_io.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)

        # T1: verbatim write does not translate newlines.
        lf = d / "lf.md"
        atomic_write_verbatim(lf, "a\nb\n")
        assert lf.read_bytes() == b"a\nb\n", lf.read_bytes()

        # T2: verbatim write preserves CRLF too -- the convention is the file's.
        crlf = d / "crlf.md"
        atomic_write_verbatim(crlf, "a\r\nb\r\n")
        assert crlf.read_bytes() == b"a\r\nb\r\n", crlf.read_bytes()

        # T3: overwrite leaves no .tmp behind.
        atomic_write_verbatim(lf, "c\nd\n")
        assert lf.read_bytes() == b"c\nd\n"
        assert not (d / "lf.md.tmp").exists()

        # T4: a failed write leaves the ORIGINAL intact and reaps the temp.
        #     This is the whole point of the batch: a torn write must be impossible.
        original = lf.read_bytes()
        boom = d / "lf.md.tmp"

        class _Exploding(str):
            def __str__(self):  # pragma: no cover - defensive
                return self

        try:
            _atomic(lf, "x" * 10, newline=_Exploding("not-a-valid-newline"))
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("expected the bad newline arg to raise")
        assert lf.read_bytes() == original, "original was damaged by a failed write"
        assert not boom.exists(), "temp file was not reaped after a failed write"

        # T5: sidecar shape creates missing parents.
        nested = d / "sub" / "dir" / "state.json"
        atomic_write_text(nested, '{"k": 1}')
        assert nested.read_text(encoding="utf-8") == '{"k": 1}'

        print("atomic_io smoke OK")
