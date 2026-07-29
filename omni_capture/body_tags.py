"""ISS-051 (§1.1): desktop mirror of the phone's `bodyTags.ts` inline `#tag` extractor.

Pure, read-only scan over note BODY text (never writes it back — body-sacred, data-model §1).
Grammar (kept identical to the phone parser — do not drift the two):
 - a tag starts at `#` immediately followed by a token char, preceded by start-of-string or
   whitespace (so a markdown heading `## Notes` never matches, and a mid-word `#` — e.g. a URL
   fragment `page#section` — never matches either, since nothing precedes it but a non-space char).
 - token = `[A-Za-z0-9_@]` for the first char (so `@work`, `project:work`, `area/health` all start
   valid tokens) then `[A-Za-z0-9_/@:-]*` for the rest — letters/digits/underscore plus `/` `@` `:`
   `-` so nested (`work/planning`), GTD context (`@work`), and key:value (`project:work`) tags all
   fall out of one token shape.
 - fenced code blocks (``` ... ```) and inline code spans (`...`) are stripped before scanning.
 - a token that is EXACTLY 3 or 6 hex digits (`fff`, `a1b2c3`) is dropped — a bare hex color, not a
   tag.
 - no case normalization — the phone parser does not lowercase, so neither does this one.
# ponytail: no escaping for a literal `#` inside a fence whose language tag itself contains
# backticks (vanishingly rare); no attempt to parse full CommonMark — this is a scanner, not a
# parser. The 3/6-hex-digit exclusion is a token-shape heuristic, not a color-syntax parser: a
# literal tag that happens to be exactly 3 or 6 hex digits (`#abc`, `#a1b2c3`) is a rare false
# negative; upgrade to a real Markdown AST only if it ever bites.
"""
import re

_FENCED_CODE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_TAG_TOKEN = re.compile(r"(^|\s)#([A-Za-z0-9_@][A-Za-z0-9_/@:-]*)")
_HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{3}$|^[0-9A-Fa-f]{6}$")


# v2.2 (data-model §1.2): attachments are body-authoritative, referenced inline as standard Markdown
# `![alt](../_attachments/<note-id>/<filename>)`. Desktop mirror of the phone's parseBodyAttachmentRefs
# (keep the two identical). Pure, read-only — extracts each ref's filename (deduped, first-seen order)
# so the save/enrichment path can recompute the derived `attachments:` cache. Only refs under
# `../_attachments/<id>/` count; external and other-directory images are ignored.
# ponytail: a plain regex scan like the phone's, not a Markdown AST — a ref inside a code fence is
# still matched (rare false positive); upgrade only if it bites.
_ATTACHMENT_REF = re.compile(r"!\[[^\]]*\]\(\.\./_attachments/[^/)]+/([^/)]+)\)")


def parse_body_attachment_refs(body: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in _ATTACHMENT_REF.finditer(body):
        filename = m.group(1).strip()
        if filename and filename not in seen:
            seen.add(filename)
            out.append(filename)
    return out


# Legacy pre-v2.2 attachment line, e.g. `[attachment: memo-0712.m4a]`, as its own whole (trimmed)
# line. Desktop mirror of the phone's ATTACHMENT_LINE (attachments.ts:9-10).
_LEGACY_ATTACHMENT_LINE = re.compile(r"^\[attachment:\s*([^\]]+?)\s*\]$")

# Audio extensions for the default alt-text rule in attachment_ref_text, mirroring the phone's
# AUDIO_EXTS (attachments.ts:85). Module-private: no other module needs the set, only the
# default-alt decision below (the phone's classifyAttachment also distinguishes IMAGE_EXTS, but
# attachmentRefText's default-alt rule never branches on it — anything non-audio defaults to
# "photo" — so there is nothing here for an image-extension set to do).
_AUDIO_EXTS = {"m4a", "mp3", "wav", "aac", "ogg", "caf"}


def _ext_of(filename: str) -> str:
    m = re.search(r"\.([a-zA-Z0-9]+)$", filename)
    return m.group(1).lower() if m else ""


def derive_body_attachments(body: str) -> list[str]:
    """The recompute-on-save cache for `attachments:` frontmatter (data-model §1.2): every filename
    the sacred body references, by EITHER the v2.2 inline ref `![](../_attachments/id/file)` OR the
    legacy pre-v2.2 `[attachment: file]` line — so a note authored before the inline-ref editor
    lands never loses its attachments on the first recompute. First-seen order, deduped. Desktop
    mirror of the phone's deriveBodyAttachments (attachments.ts:68)."""
    seen: set[str] = set()
    out: list[str] = []

    def add(filename: str) -> None:
        if filename and filename not in seen:
            seen.add(filename)
            out.append(filename)

    for filename in parse_body_attachment_refs(body):
        add(filename)
    for line in body.split("\n"):
        m = _LEGACY_ATTACHMENT_LINE.match(line.strip())
        if m:
            add(m.group(1).strip())
    return out


def attachment_ref_text(note_id: str, filename: str, alt: str | None = None) -> str:
    """Build the exact Markdown the editor inserts at the cursor when the user attaches from edit
    mode (data-model §1.2). `alt` defaults to a kind-appropriate label so a bare tap (no rename)
    still reads sensibly as a view-mode caption. Desktop mirror of the phone's attachmentRefText
    (attachments.ts:46)."""
    if alt and alt.strip():
        label = alt.strip()
    else:
        label = "voice memo" if _ext_of(filename) in _AUDIO_EXTS else "photo"
    return f"![{label}](../_attachments/{note_id}/{filename})"


def extract_body_tags(body: str) -> list[str]:
    """Extract literal `#tag` tokens from a note body. Returns tags in first-seen order, deduped,
    with the leading `#` stripped."""
    scanned = _FENCED_CODE.sub(" ", body)
    scanned = _INLINE_CODE.sub(" ", scanned)
    seen: set[str] = set()
    out: list[str] = []
    for m in _TAG_TOKEN.finditer(scanned):
        tag = m.group(2)
        if _HEX_COLOR.match(tag):
            continue
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
