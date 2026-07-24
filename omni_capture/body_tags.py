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
