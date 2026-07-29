/**
 * attachments.ts — F-13 (desktop half): pure parsing for the
 * `[attachment: <filename>]` link syntax note_editor.py's `add_attachment`
 * appends to a note body, PLUS the phone's newer inline-ref form
 * `![alt](../_attachments/<note-id>/<filename>)` (data-model §1.2). Both are
 * body-authoritative and permanent: the phone writes the inline-ref form, the
 * legacy whole-line form is never migrated away, so this parser must keep
 * recognizing both forever (workspace CLAUDE.md cross-peer parity rule).
 */

const ATTACHMENT_LINE_RE = /\[attachment:\s*([^\]]+?)\s*\]/g;

// Same ref shape as the phone's ATTACHMENT_REF (phone/src/lib/attachments.ts) — only refs under
// `../_attachments/<id>/` count; external/other-directory images are ordinary markdown, not attachments.
const INLINE_ATTACHMENT_REF_RE = /!\[([^\]]*)\]\(\.\.\/_attachments\/[^/)]+\/([^/)]+)\)/g;

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]);
const AUDIO_EXT = new Set(["m4a", "mp3", "wav", "ogg", "webm", "aac", "flac"]);

export type AttachmentKind = "image" | "audio" | "file";

export interface ParsedAttachment {
  filename: string;
  kind: AttachmentKind;
  alt?: string;
}

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i === -1 ? "" : filename.slice(i + 1).toLowerCase();
}

export function kindOf(filename: string): AttachmentKind {
  const ext = extOf(filename);
  if (IMAGE_EXT.has(ext)) return "image";
  if (AUDIO_EXT.has(ext)) return "audio";
  return "file";
}

/** Extract every attachment reference in *body* — legacy `[attachment: <filename>]` lines AND
 *  the phone's inline-ref `![alt](../_attachments/<id>/<filename>)` form — in body order,
 *  de-duplicated by filename across both forms (a note may reference the same attachment more
 *  than once in prose without that meaning two distinct files). */
export function parseAttachments(body: string): ParsedAttachment[] {
  const matches: { index: number; filename: string; alt?: string }[] = [];
  for (const m of body.matchAll(ATTACHMENT_LINE_RE)) {
    matches.push({ index: m.index ?? 0, filename: m[1].trim() });
  }
  for (const m of body.matchAll(INLINE_ATTACHMENT_REF_RE)) {
    matches.push({ index: m.index ?? 0, filename: m[2].trim(), alt: m[1].trim() || undefined });
  }
  matches.sort((a, b) => a.index - b.index);

  const seen = new Set<string>();
  const out: ParsedAttachment[] = [];
  for (const m of matches) {
    if (!m.filename || seen.has(m.filename)) continue;
    seen.add(m.filename);
    const attachment: ParsedAttachment = { filename: m.filename, kind: kindOf(m.filename) };
    if (m.alt) attachment.alt = m.alt;
    out.push(attachment);
  }
  return out;
}
