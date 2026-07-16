"""
test_note_editor_newlines.py — A2: the in-app editor preserves a note's
existing newline convention byte-exactly.

The editor is the sanctioned body writer (body-sacred allows the user's editor
to change the body), but it must only rewrite bytes the user actually typed.
Default (translated) text I/O rewrote every `\n` as `\r\n` on Windows, silently
flipping an LF note to CRLF on the first save. Fix mirrors the verbatim
newline="" pattern already proven on the hub sync paths (mobile_sync_agent.py).
"""
import tempfile
from pathlib import Path

import pytest

from note_editor import add_attachment, read_note, write_note_body


def _vault_with(note_bytes: bytes, name: str = "note.md"):
    tmp = tempfile.mkdtemp()
    vault = Path(tmp)
    cat = vault / "Tech_Notes"
    cat.mkdir()
    note = cat / name
    note.write_bytes(note_bytes)
    return vault, note


_LF = (
    b"---\ntitle: LF note\ncategory: Tech_Notes\ntags: [work]\n---\n"
    b"# LF note\n\nFirst line.\nSecond line.\n"
)
_CRLF = (
    b"---\r\ntitle: CRLF note\r\ncategory: Tech_Notes\r\ntags: [work]\r\n---\r\n"
    b"# CRLF note\r\n\r\nFirst line.\r\nSecond line.\r\n"
)


@pytest.mark.parametrize("original", [_LF, _CRLF], ids=["lf", "crlf"])
def test_read_write_roundtrip_is_byte_exact(original):
    """A read -> write of the same body must not change a single byte."""
    vault, note = _vault_with(original)
    data = read_note(vault, str(note))
    write_note_body(vault, str(note), data["body"], data["mtime"])
    assert note.read_bytes() == original


@pytest.mark.parametrize(
    "original,newline", [(_LF, b"\n"), (_CRLF, b"\r\n")], ids=["lf", "crlf"]
)
def test_edited_body_keeps_the_files_newline_convention(original, newline):
    """A real edit rewrites the body -- in the file's own convention, not the
    platform's. The GUI's textarea hands the body back LF-normalized, so the
    file's bytes (not the client's) must decide."""
    vault, note = _vault_with(original)
    data = read_note(vault, str(note))
    write_note_body(vault, str(note), "# Edited\n\nAlpha.\nBeta.\n", data["mtime"])

    after = note.read_bytes()
    assert b"Alpha." in after and b"Beta." in after
    assert b"Second line." not in after          # body really was replaced
    # every line break is the file's own -- none of the other kind leaked in
    assert after.count(newline) == after.count(b"\n")
    if newline == b"\n":
        assert b"\r" not in after
    # frontmatter block carried through untouched, in the file's convention
    assert after.startswith(b"---" + newline + b"title: ")
    assert b"tags: [work]" + newline + b"---" + newline in after


def test_lf_note_never_gains_a_carriage_return():
    """The reported bug, pinned directly: on Windows the default write
    translation turned an LF note into a CRLF note on the first save."""
    vault, note = _vault_with(_LF)
    data = read_note(vault, str(note))
    write_note_body(vault, str(note), "# LF note\n\nEdited body.\n", data["mtime"])
    assert b"\r" not in note.read_bytes()


def test_crlf_note_never_loses_its_carriage_returns():
    """The mirror case: a client that normalizes CRLF away (every HTML
    textarea does) must not flatten the file to LF."""
    vault, note = _vault_with(_CRLF)
    data = read_note(vault, str(note))
    write_note_body(vault, str(note), "# CRLF note\n\nEdited body.\n", data["mtime"])
    after = note.read_bytes()
    assert b"\n" in after
    assert after.count(b"\r\n") == after.count(b"\n")  # no bare LF anywhere


@pytest.mark.parametrize(
    "original,newline", [(_LF, b"\n"), (_CRLF, b"\r\n")], ids=["lf", "crlf"]
)
def test_read_note_body_is_lf_normalized_for_clients(original, newline):
    """read_note's API contract is unchanged by the verbatim read: clients
    always see LF, the convention lives on disk."""
    vault, note = _vault_with(original)
    data = read_note(vault, str(note))
    assert "\r" not in data["body"]
    assert "First line.\nSecond line." in data["body"]


@pytest.mark.parametrize(
    "fm,newline",
    [
        (b"---\nid: n1\ntitle: LF\ncategory: Tech_Notes\n---\n# LF\n\nBody.\n", b"\n"),
        (b"---\r\nid: n1\r\ntitle: CRLF\r\ncategory: Tech_Notes\r\n---\r\n# CRLF\r\n\r\nBody.\r\n", b"\r\n"),
    ],
    ids=["lf", "crlf"],
)
def test_add_attachment_appends_in_the_files_newline_convention(fm, newline):
    """add_attachment appends a link line + an `attachments:` frontmatter key --
    both must use the file's convention, never mix the two."""
    vault, note = _vault_with(fm, name="with_id.md")
    data = read_note(vault, str(note))
    add_attachment(vault, str(note), "memo.m4a", b"fakeaudio", data["mtime"])

    after = note.read_bytes()
    assert b"[attachment: memo.m4a]" in after
    assert b"attachments: [memo.m4a]" in after
    assert b"Body." in after                      # original body preserved
    assert after.count(newline) == after.count(b"\n")
    if newline == b"\n":
        assert b"\r" not in after
