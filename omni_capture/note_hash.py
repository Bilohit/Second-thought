"""Body-only note hash — frontmatter-independent, for LAN provisional dedup (contract §11.2)."""
import hashlib
from frontmatter import strip_frontmatter   # existing helper


def body_hash(raw_note: str) -> str:
    """sha256 of the note body BELOW the frontmatter. No normalization (byte-exact)."""
    body = strip_frontmatter(raw_note)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def dedup_key(note_id: str, raw_note: str) -> str:
    return f"{note_id}:{body_hash(raw_note)}"
