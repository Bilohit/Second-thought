// Minimal Markdown block+inline parser for the desktop note viewer's view mode. Pure + tested so
// the React <Markdown> component stays a thin mapper over these blocks. Ported from the phone
// app's src/lib/markdown.ts (same Block/Span shape, same subset). Recognizes BOTH the legacy
// `[attachment: filename]` whole line AND the phone's inline-ref whole line
// `![alt](../_attachments/<note-id>/<filename>)` — no migration, legacy stays supported forever
// (workspace CLAUDE.md cross-peer parity rule); an inline ref that is not alone on its own line
// stays ordinary markdown text, same as any other image reference.
//
// ponytail: subset renderer — headings, checklists, bullets, paragraphs, attachment lines; inline
// [[wikilink]] + **bold**. No italic/links/code/tables/nesting. Extend only if a real note needs it.

import { kindOf } from "./attachments";

export type Span =
  | { kind: "text"; value: string }
  | { kind: "bold"; value: string }
  | { kind: "wikilink"; target: string };

export type Block =
  | { kind: "heading"; level: number; spans: Span[] }
  | { kind: "check"; checked: boolean; spans: Span[] }
  | { kind: "bullet"; spans: Span[] }
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "attachment"; filename: string; alt?: string };

const WIKILINK = /\[\[([^\]]+)\]\]/;
const BOLD = /\*\*([^*]+)\*\*/;
const HEADING_LINE = /^(#{1,6})\s+(.*)$/;
const CHECK_LINE = /^[-*]\s+\[([ xX])\]\s+(.*)$/;
const BULLET_LINE = /^[-*]\s+(.*)$/;
const ATTACHMENT_WHOLE_LINE = /^\[attachment:\s*([^\]]+?)\s*\]$/;
// The phone's inline-ref form (attachments.ts's INLINE_ATTACHMENT_REF_RE), anchored to a whole
// line — same path shape restriction (`../_attachments/<id>/`) so an ordinary image reference
// elsewhere is never mistaken for an attachment.
const INLINE_ATTACHMENT_WHOLE_LINE = /^!\[([^\]]*)\]\(\.\.\/_attachments\/[^/)]+\/([^/)]+)\)$/;

export function parseInline(text: string): Span[] {
  const spans: Span[] = [];
  let rest = text;
  while (rest.length > 0) {
    const wl = rest.match(WIKILINK);
    const bd = rest.match(BOLD);
    const wlIdx = wl ? (wl.index ?? 0) : Infinity;
    const bdIdx = bd ? (bd.index ?? 0) : Infinity;
    if (wlIdx === Infinity && bdIdx === Infinity) {
      spans.push({ kind: "text", value: rest });
      break;
    }
    if (wlIdx <= bdIdx && wl) {
      if (wlIdx > 0) spans.push({ kind: "text", value: rest.slice(0, wlIdx) });
      spans.push({ kind: "wikilink", target: wl[1].trim() });
      rest = rest.slice(wlIdx + wl[0].length);
    } else if (bd) {
      if (bdIdx > 0) spans.push({ kind: "text", value: rest.slice(0, bdIdx) });
      spans.push({ kind: "bold", value: bd[1] });
      rest = rest.slice(bdIdx + bd[0].length);
    }
  }
  return spans;
}

// Read-only: never mutates or re-serializes `body` (body-sacred) — the viewer renders from these
// blocks, the file bytes are untouched.
export function parseBlocks(body: string): Block[] {
  const blocks: Block[] = [];
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  let para: string[] = [];
  const flush = () => {
    if (para.length) {
      blocks.push({ kind: "paragraph", spans: parseInline(para.join(" ")) });
      para = [];
    }
  };
  for (const line of lines) {
    const t = line.trim();
    if (t === "") { flush(); continue; }
    const heading = t.match(HEADING_LINE);
    if (heading) { flush(); blocks.push({ kind: "heading", level: heading[1].length, spans: parseInline(heading[2]) }); continue; }
    const check = t.match(CHECK_LINE);
    if (check) { flush(); blocks.push({ kind: "check", checked: check[1].toLowerCase() === "x", spans: parseInline(check[2]) }); continue; }
    const bullet = t.match(BULLET_LINE);
    if (bullet) { flush(); blocks.push({ kind: "bullet", spans: parseInline(bullet[1]) }); continue; }
    const attachment = t.match(ATTACHMENT_WHOLE_LINE);
    if (attachment) { flush(); blocks.push({ kind: "attachment", filename: attachment[1].trim() }); continue; }
    const inlineAttachment = t.match(INLINE_ATTACHMENT_WHOLE_LINE);
    if (inlineAttachment) {
      flush();
      const alt = inlineAttachment[1].trim();
      const block: Block = { kind: "attachment", filename: inlineAttachment[2].trim() };
      if (alt) block.alt = alt;
      blocks.push(block);
      continue;
    }
    para.push(t);
  }
  flush();
  return blocks;
}

// -- stable React keys for rendered blocks ------------------------------------
// Array index alone breaks when blocks are inserted/removed above an existing
// block: React then reuses that array slot's component instance for a
// different block, losing transient state (e.g. a checkbox's in-flight
// toggle, an attachment mid-fetch). Derive the key from the block's own text
// instead of its position, so it survives edits made elsewhere in the note.
function blockText(b: Block): string {
  if (b.kind === "attachment") return b.filename;
  return b.spans.map((s) => (s.kind === "wikilink" ? s.target : s.value)).join("");
}

function hashText(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

// Duplicate-content blocks (e.g. two identical checklist items) hash equal;
// callers disambiguate with a running occurrence count -- see Markdown.tsx.
export function blockKey(b: Block): string {
  return `${b.kind}:${hashText(blockText(b))}`;
}

// Re-export so Markdown.tsx doesn't need a second import for attachment-kind lookup.
export { kindOf };
