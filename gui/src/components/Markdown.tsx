// Second Thought/gui/src/components/Markdown.tsx
//
// Renders parseBlocks() output for the desktop note viewer's view mode. Attachment blocks render
// in place (at their line position), replacing NoteEditor's old bottom-collected attachment list.
import type { CSSProperties } from "react";
import type { Block, Span } from "../lib/markdown";
import { kindOf, blockKey } from "../lib/markdown";
import { AudioPlayer } from "./AudioPlayer";

function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((s, i) => {
        if (s.kind === "bold") return <strong key={i}>{s.value}</strong>;
        if (s.kind === "wikilink") return <span key={i} style={{ textDecoration: "underline", textUnderlineOffset: 2, color: "var(--text-1)" }}>{s.target}</span>;
        return <span key={i}>{s.value}</span>;
      })}
    </>
  );
}

const HEADING_SIZE: Record<number, number> = { 1: 20, 2: 17, 3: 15 };

function AttachmentBlock({ filename, alt, url }: { filename: string; alt: string | undefined; url: string | undefined }) {
  const kind = kindOf(filename);
  const frameStyle: CSSProperties = { border: "1px solid var(--border)", margin: "10px 0" };
  const labelStyle: CSSProperties = {
    display: "flex", alignItems: "center", gap: 6, fontSize: 10, letterSpacing: "0.08em",
    color: "var(--text-3)", padding: "6px 10px", borderBottom: "1px solid var(--border-2)",
    textTransform: "uppercase",
  };
  // Bytes absent locally (not yet synced down, or a hand-typed ref) -- url is undefined because
  // attachmentUrls has no entry for this filename. Contract §1.2 / parity with the phone's
  // MissingAttachment: a bordered (dashed) placeholder naming the file, never a broken <img> and
  // never an <AudioPlayer> stuck at 0:00.
  if (!url) {
    return (
      <div style={{ ...frameStyle, borderStyle: "dashed" }}>
        <div style={labelStyle}>NOT SYNCED · {alt ?? filename}</div>
      </div>
    );
  }
  return (
    <div style={frameStyle}>
      <div style={labelStyle}>{kind === "audio" ? "VOICE MEMO" : kind === "image" ? "IMAGE" : "FILE"} · {filename}</div>
      {kind === "image" && (
        <>
          <img src={url} alt={alt ?? filename} style={{ display: "block", width: "100%", maxHeight: 320, objectFit: "contain", background: "var(--surface)" }} />
          {alt && <div style={{ padding: "6px 10px", fontSize: 11, color: "var(--text-3)", borderTop: "1px solid var(--border-2)" }}>{alt}</div>}
        </>
      )}
      {kind === "audio" && (
        <div style={{ padding: 10 }}>
          <AudioPlayer src={url} />
          {alt && <div style={{ paddingTop: 6, fontSize: 11, color: "var(--text-3)" }}>{alt}</div>}
        </div>
      )}
      {kind === "file" && (
        <a href={url} download={filename} target="_blank" rel="noreferrer" style={{ display: "block", padding: "10px 12px", fontSize: 12, color: "var(--text-2)" }}>
          Open {filename}
        </a>
      )}
    </div>
  );
}

export function Markdown({ blocks, attachmentUrls }: { blocks: Block[]; attachmentUrls: Record<string, string> }) {
  // blockKey is content-derived (not positional), so inserting/removing a block
  // elsewhere doesn't reshuffle which component instance a given block keeps.
  // Duplicate-content blocks hash equal -- disambiguate with an occurrence count.
  const seen = new Map<string, number>();
  const keyFor = (b: Block) => {
    const base = blockKey(b);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? base : `${base}:${n}`;
  };
  return (
    <div style={{ fontSize: 13.5, lineHeight: 1.75, color: "var(--text-1)" }}>
      {blocks.map((b) => {
        const key = keyFor(b);
        if (b.kind === "heading") {
          return <div key={key} style={{ fontSize: HEADING_SIZE[Math.min(b.level, 3)] ?? 15, fontWeight: 600, margin: "18px 0 8px" }}><Spans spans={b.spans} /></div>;
        }
        if (b.kind === "check") {
          return (
            <div key={key} style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "2px 0" }}>
              <span style={{ color: b.checked ? "var(--text-2)" : "var(--text-3)" }}>{b.checked ? "[x]" : "[ ]"}</span>
              <span style={{ textDecoration: b.checked ? "line-through" : "none", color: b.checked ? "var(--text-3)" : "var(--text-1)" }}><Spans spans={b.spans} /></span>
            </div>
          );
        }
        if (b.kind === "bullet") {
          return (
            <div key={key} style={{ display: "flex", gap: 8, margin: "2px 0" }}>
              <span style={{ color: "var(--text-3)" }}>{"•"}</span>
              <span><Spans spans={b.spans} /></span>
            </div>
          );
        }
        if (b.kind === "attachment") {
          return <AttachmentBlock key={key} filename={b.filename} alt={b.alt} url={attachmentUrls[b.filename]} />;
        }
        return <p key={key} style={{ margin: "0 0 12px" }}><Spans spans={b.spans} /></p>;
      })}
    </div>
  );
}
