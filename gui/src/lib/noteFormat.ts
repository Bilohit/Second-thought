/**
 * noteFormat.ts — pure markdown-editing helpers for the full-window note
 * editor (F-7). No DOM/React here; NoteEditor.tsx applies the returned
 * caret range to the live <textarea> selection.
 */

export type FormatKind = "bold" | "italic" | "heading" | "list" | "link" | "code";

interface Wrap {
  pre: string;
  post: string;
  /** true = prefix is inserted at the start of the selection's line rather than wrapping the selection itself. */
  line?: boolean;
}

const WRAPS: Record<FormatKind, Wrap> = {
  bold: { pre: "**", post: "**" },
  italic: { pre: "_", post: "_" },
  link: { pre: "[", post: "](url)" },
  heading: { pre: "## ", post: "", line: true },
  list: { pre: "- ", post: "", line: true },
  code: { pre: "```\n", post: "\n```" },
};

export interface FormatResult {
  value: string;
  selStart: number;
  selEnd: number;
}

/** Apply a formatting action to `value` given the current selection
 *  [selStart, selEnd). Mirrors the mock's `applyFmt` exactly (05-desktop-
 *  viewer-refined-v2.html) so the radial spokes match the approved mock. */
export function applyMarkdownFormat(value: string, selStart: number, selEnd: number, kind: FormatKind): FormatResult {
  const w = WRAPS[kind];
  if (w.line) {
    const lineStart = value.lastIndexOf("\n", selStart - 1) + 1;
    const next = value.slice(0, lineStart) + w.pre + value.slice(lineStart);
    const caret = selEnd + w.pre.length;
    return { value: next, selStart: caret, selEnd: caret };
  }
  const sel = value.slice(selStart, selEnd);
  const next = value.slice(0, selStart) + w.pre + sel + w.post + value.slice(selEnd);
  const caret = selStart + w.pre.length + sel.length;
  return { value: next, selStart: caret, selEnd: caret };
}

export interface OutlineEntry {
  level: number;
  text: string;
  /** 0-based line index within the body, for scroll-to-heading. */
  line: number;
}

/** Parse ATX headings (`#`..`######`) out of a note body, in document order. */
export function parseOutline(body: string): OutlineEntry[] {
  const lines = body.split("\n");
  const out: OutlineEntry[] = [];
  lines.forEach((line, i) => {
    const m = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    if (m) out.push({ level: m[1].length, text: m[2], line: i });
  });
  return out;
}

/** Parse `[[wikilink]]` / `[[wikilink|alias]]` targets out of a note body,
 *  in first-seen order, de-duplicated. */
export function parseWikilinks(body: string): string[] {
  const seen = new Set<string>();
  const re = /\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body))) {
    const target = m[1].trim();
    if (target) seen.add(target);
  }
  return [...seen];
}
