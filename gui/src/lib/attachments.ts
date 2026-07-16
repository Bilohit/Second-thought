/**
 * attachments.ts — F-13 (desktop half): pure parsing for the
 * `[attachment: <filename>]` link syntax note_editor.py's `add_attachment`
 * appends to a note body. MATCHES the phone's link syntax exactly (workspace
 * CLAUDE.md cross-peer parity rule) so either peer's viewer can render a
 * note the other peer attached to.
 */

const ATTACHMENT_LINE_RE = /\[attachment:\s*([^\]]+?)\s*\]/g;

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]);
const AUDIO_EXT = new Set(["m4a", "mp3", "wav", "ogg", "webm", "aac", "flac"]);

export type AttachmentKind = "image" | "audio" | "file";

export interface ParsedAttachment {
  filename: string;
  kind: AttachmentKind;
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

/** Extract every `[attachment: <filename>]` link in *body*, in order,
 *  de-duplicated by filename (a note may reference the same attachment more
 *  than once in prose without that meaning two distinct files). */
export function parseAttachments(body: string): ParsedAttachment[] {
  const seen = new Set<string>();
  const out: ParsedAttachment[] = [];
  for (const m of body.matchAll(ATTACHMENT_LINE_RE)) {
    const filename = m[1].trim();
    if (!filename || seen.has(filename)) continue;
    seen.add(filename);
    out.push({ filename, kind: kindOf(filename) });
  }
  return out;
}
