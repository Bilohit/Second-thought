"""ISS-051 §3: the machine-managed trailing `tags:` body line.

Desktop enrichment writes its tags into the BODY (not just frontmatter), as a single visible line at
the very end: `tags: #a #b #c`. This is the ONLY body region a machine may write, and only on notes
the device originated (`origin_device` match) — see `enrich_notes` for the gate.

Body-sacred is preserved by construction: everything ABOVE the trailing line is byte-identical
across an apply, because `apply` never rewrites the recovered user body — it only re-appends the
machine line. `strip_trailing_tags_line` is the exact inverse used by the amended body-sacred assert.

ponytail: the tags line is detected only when preceded by a newline (the machine always writes one),
so a user body that legitimately BEGINS with `tags:` is never mistaken for the machine line. A user
who hand-types a `tags: #x` line at the very end is treated as the machine line (same unified tag
set — extract_body_tags reads it either way), which is the intended, documented collision.
"""
import re

# The token shape mirrors body_tags._TAG_TOKEN's rest-of-token charset (letters/digits/_ plus / @ : -).
_TRAILING_TAGS = re.compile(r"\ntags:(?: #[\w/@:-]+)+\n?\Z")


def strip_trailing_tags_line(body: str) -> str:
    """Return the user body with the machine trailing `tags:` line removed (byte-exact inverse of
    apply). A no-op when there is no such line."""
    return _TRAILING_TAGS.sub("", body)


def apply_trailing_tags_line(body: str, tags: list[str]) -> str:
    """Replace (idempotently) the machine trailing `tags:` line with one carrying `tags`. Empty
    `tags` removes the line. The recovered user body is never rewritten — only the final line is."""
    base = strip_trailing_tags_line(body)
    if not tags:
        return base
    line = "tags: " + " ".join("#" + t for t in tags)
    return base + "\n" + line + "\n"
