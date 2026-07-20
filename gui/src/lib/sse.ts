// SSE frame parser for the Python server's event stream (localhost:7070). Pure — extracted from
// api.ts (OF-11) so it carries a sibling test without dragging api.ts's Tauri/opener imports into the
// vitest node suite. The browser extension (background.js) mirrors this same wire protocol by hand.
//
// A frame is the text between two blank lines in an `text/event-stream`. We read the last `event:` and
// `data:` line in the frame; a frame with no `data:` (e.g. a bare comment/keep-alive) yields null.
export function parseSseFrame(frame: string): { ev: string; data: string } | null {
  let ev = "message", data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) ev = line.slice(7).trim();
    if (line.startsWith("data: ")) data = line.slice(6).trim();
  }
  return data ? { ev, data } : null;
}
