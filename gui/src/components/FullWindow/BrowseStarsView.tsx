/**
 * BrowseStarsView.tsx — P3-C2: the real STARS constellation (BUILD-STATE/PROGRESS/DECISIONS.md §5
 * s146; the user's own words: "movement · wire connection[s] based dragging around physics, with the
 * functionality of quick peeking at the dots"). Replaces the P3-C1 placeholder — mounted by
 * BrowseView.tsx when its `mode` prop is "stars" (itself owned by FullWindow.tsx's titlebar
 * LIST/STARS toggle). Board: SecondThoughtV2.html's `#d-br-stars`/`.sky`/`.star`/`.star-card`
 * markup+CSS (:193-220, :998-1005) and its `class Sky` behavior (:1772-1884).
 *
 * Force model lives in ../../lib/starsSim.ts (pure, tested, ported verbatim from the mock). This file
 * is the DOM-facing half — the requestAnimationFrame loop, the per-node pointer drag, the SVG wires,
 * the peek card — mirroring the shape of the already-shipped RN sibling port
 * (`Second Thought - Android App/phone/src/components/StarsSky.tsx`), NOT imported (different repo,
 * RN-specific), but followed closely so the two behaviors can't silently diverge.
 *
 * No React re-render per animation frame: every star's on-screen position is written straight to its
 * DOM node's `style.transform` (and every wire's SVG endpoints via `setAttribute`) from the RAF loop
 * — exactly what the mock's own `Sky.step()` does. React only re-renders on data fetch, a resize, or
 * a peek-card open/close. The RAF effect's deps are `[visible, size.w, size.h]` ONLY — never `notes`/
 * `edges` — because those are fresh array identities on every unrelated note-store tick; depending on
 * them would restart the loop (and dismiss an open peek card) on every such tick, not just a real
 * STARS entry. This is the exact regression the phone port's own header comment documents having
 * fixed; node/edge state is read through refs instead.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { searchCaptures } from "../../lib/api";
import { formatAgo } from "../../lib/projectsView";
import { StarIcon } from "../PillMenu/icons";
import { BTN_PRIMARY, BTN_SECONDARY } from "../ui/styles";
import { micro, label as fsLabel, read as fsRead } from "../../lib/type";
import {
  buildStarEdges,
  computeDegrees,
  coreVisual,
  initNodes,
  isTap,
  parseTagsField,
  releaseMomentum,
  selectRecentIds,
  stepSimulation,
  type SimEdge,
  type SimNode,
} from "../../lib/starsSim";

interface Props {
  visible: boolean;
  onOpenNote?: (path: string) => void;
}

interface StarNote {
  id: string; // vault-relative path — the same stable unique key BrowseView's own rows key on
  title: string;
  project: string;
  tags: string[];
  modified: number | null; // epoch seconds (SearchResult.modified), or null if unstat-able
}

// SecondThoughtV2.html :215 (.star-card{width:230px}) and :1834-1835 (the clamp margins — 240/150,
// NOT card-size-derived; ported as the mock's own literals, not re-derived).
const CARD_W = 230;
const CARD_LEFT_CLAMP = 240;
const CARD_TOP_CLAMP = 150;

export default function BrowseStarsView({ visible, onOpenNote }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const elemsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const lineElemsRef = useRef<({ a: string; b: string; el: SVGLineElement } | undefined)[]>([]);
  const nodesRef = useRef<SimNode[]>([]);
  const edgesRef = useRef<SimEdge[]>([]);
  const idsKeyRef = useRef<string>("");
  const dragMetaRef = useRef<Map<string, { sx: number; sy: number; px: number; py: number }>>(new Map());

  const [notes, setNotes] = useState<StarNote[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [peekId, setPeekId] = useState<string | null>(null);
  const [peekPos, setPeekPos] = useState({ x: 0, y: 0 });

  // ── data: refetched on every `visible` transition to true, same convention as BrowseView.tsx's own
  // project/tag fetch. searchCaptures("", ...) is the server's documented "browse everything" blank
  // query (vault_admin.py's search_captures docstring) — the same source BrowseView's own NOTES
  // section and notesForProject/notesForTag already trust for "the vault's notes", not a new one. ──
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    searchCaptures("", { limit: 200 })
      .then(({ results }) => {
        if (cancelled) return;
        const shaped: StarNote[] = results.map((r) => ({
          id: r.path,
          title: r.filename ?? r.path.split(/[\\/]/).pop() ?? r.path,
          project: r.project ?? "uncategorized",
          tags: parseTagsField(r.tags),
          modified: r.modified ?? null,
        }));
        setNotes(shaped);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          setNotes([]);
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const recentIds = useMemo(
    () => selectRecentIds(notes.map((n) => ({ id: n.id, modified: n.modified }))),
    [notes]
  );
  const idSet = useMemo(() => new Set(recentIds), [recentIds]);
  const byId = useMemo(() => new Map(notes.map((n) => [n.id, n])), [notes]);
  // ponytail: shared-tag edges only — no wikilink source is reachable client-side. See starsSim.ts's
  // header comment for the full ceiling (no /links endpoint on the FastAPI server) and upgrade path.
  const edges = useMemo(
    () => buildStarEdges(notes.map((n) => ({ id: n.id, tags: n.tags })), idSet),
    [notes, idSet]
  );
  const degrees = useMemo(() => computeDegrees(recentIds, edges), [recentIds, edges]);
  edgesRef.current = edges;

  const getNode = useCallback((id: string): SimNode | undefined => nodesRef.current.find((n) => n.id === id), []);

  // ── host size (ResizeObserver) — the only thing the physics loop below depends on. ──
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const ro = new ResizeObserver(() => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    });
    ro.observe(host);
    setSize({ w: host.clientWidth, h: host.clientHeight });
    return () => ro.disconnect();
  }, [visible]);

  // ── (re)seed node positions only when the ID SET actually changes (new/removed notes), never on a
  // pure resize or an unrelated data refetch that returns the same ids — a resize must not teleport
  // stars back to their hashed starting positions mid-interaction. ──
  const idsKey = recentIds.join(",");
  useEffect(() => {
    if (size.w === 0 || size.h === 0) return;
    if (idsKey === idsKeyRef.current) return;
    idsKeyRef.current = idsKey;
    nodesRef.current = initNodes(recentIds, size.w, size.h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, size.w, size.h]);

  // ── the RAF loop. Deps limited to visibility + host size — see the file header comment. ──
  useEffect(() => {
    if (!visible || size.w === 0 || size.h === 0) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const loop = (t: number) => {
      nodesRef.current = stepSimulation(nodesRef.current, edgesRef.current, t, size.w, size.h, { reducedMotion });
      const byIdThisFrame = new Map(nodesRef.current.map((n) => [n.id, n]));
      for (const n of nodesRef.current) {
        const el = elemsRef.current.get(n.id);
        if (el) el.style.transform = `translate(${n.x}px, ${n.y}px) translate(-50%, -50%)`;
      }
      for (const entry of lineElemsRef.current) {
        if (!entry) continue;
        const { a, b, el } = entry;
        const na = byIdThisFrame.get(a);
        const nb = byIdThisFrame.get(b);
        if (!na || !nb) continue;
        el.setAttribute("x1", String(na.x));
        el.setAttribute("y1", String(na.y));
        el.setAttribute("x2", String(nb.x));
        el.setAttribute("y2", String(nb.y));
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      setPeekId(null); // Sky.stop() also dismisses the card (:1883)
    };
  }, [visible, size.w, size.h]);

  const openPeek = useCallback((id: string, x: number, y: number) => {
    setPeekId(id);
    setPeekPos({ x, y });
  }, []);
  const closePeek = useCallback(() => setPeekId(null), []);

  // ── drag (Sky.wireDrag, :1806-1825, ported to React pointer-capture handlers) ──
  const onPointerDown = useCallback(
    (id: string) => (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      const node = getNode(id);
      if (!node) return;
      node.drag = true;
      node.vx = 0;
      node.vy = 0;
      node.fvx = 0;
      node.fvy = 0;
      dragMetaRef.current.set(id, { sx: e.clientX, sy: e.clientY, px: e.clientX, py: e.clientY });
    },
    [getNode]
  );
  const onPointerMove = useCallback(
    (id: string) => (e: ReactPointerEvent<HTMLDivElement>) => {
      const node = getNode(id);
      const meta = dragMetaRef.current.get(id);
      if (!node || !node.drag || !meta) return;
      const dx = e.clientX - meta.px;
      const dy = e.clientY - meta.py;
      meta.px = e.clientX;
      meta.py = e.clientY;
      node.x += dx;
      node.y += dy;
      node.fvx = dx;
      node.fvy = dy;
      // pins the star to the pointer between RAF ticks, same as the mock's own synchronous write.
      const el = elemsRef.current.get(id);
      if (el) el.style.transform = `translate(${node.x}px, ${node.y}px) translate(-50%, -50%)`;
    },
    [getNode]
  );
  const onPointerUp = useCallback(
    (id: string) => (e: ReactPointerEvent<HTMLDivElement>) => {
      const node = getNode(id);
      const meta = dragMetaRef.current.get(id);
      dragMetaRef.current.delete(id);
      if (!node) return;
      node.drag = false;
      const momentum = releaseMomentum(node.fvx ?? 0, node.fvy ?? 0);
      node.vx = momentum.vx;
      node.vy = momentum.vy;
      const totalDx = meta ? e.clientX - meta.sx : 0;
      const totalDy = meta ? e.clientY - meta.sy : 0;
      // ★ a tap PEEKS; it never navigates. Only the peek card's OPEN NOTE button calls onOpenNote.
      if (isTap(totalDx, totalDy)) openPeek(id, node.x, node.y);
    },
    [getNode, openPeek]
  );
  const onKeyDown = useCallback(
    (id: string) => (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      const node = getNode(id);
      if (node) openPeek(id, node.x, node.y);
    },
    [getNode, openPeek]
  );

  if (!visible) return null;

  const empty = loaded && notes.length === 0;
  const peekNote = peekId ? byId.get(peekId) : undefined;

  // hostRef stays mounted on every branch (empty or populated) so the ResizeObserver effect above —
  // deps [visible] only — never misses attaching just because the FIRST visible render happened to
  // be the empty state (loaded flips true asynchronously, after the initial fetch resolves).
  return (
    <div ref={hostRef} className="bs-sky" style={skyStyle}>
      {empty && (
        <div style={emptyWrapStyle}>
          <StarIcon size={22} />
          <span style={emptyTitleStyle}>Nothing to show</span>
          <span style={emptyBodyStyle}>Notes appear here as stars once you've written a few.</span>
        </div>
      )}

      {!empty && size.w > 0 && size.h > 0 && (
        <>
          <svg style={svgStyle} width={size.w} height={size.h}>
            {edges.map((e, i) => (
              <line
                key={i}
                ref={(el) => {
                  lineElemsRef.current[i] = el ? { a: e.a, b: e.b, el } : undefined;
                }}
                stroke="var(--text-1)"
                strokeWidth={1}
                strokeOpacity={e.kind === "wikilink" ? 0.3 : 0.1}
                strokeDasharray={e.kind === "tag" ? "3 5" : undefined}
              />
            ))}
          </svg>

          {recentIds.map((id) => {
            const note = byId.get(id);
            if (!note) return null;
            const { size: coreSize, opacity: coreOpacity } = coreVisual(degrees.get(id) ?? 0);
            return (
              <div
                key={id}
                ref={(el) => {
                  if (el) elemsRef.current.set(id, el);
                  else elemsRef.current.delete(id);
                }}
                className="bs-star"
                style={starStyle}
                role="button"
                tabIndex={0}
                aria-label={`${note.title}, peek`}
                onPointerDown={onPointerDown(id)}
                onPointerMove={onPointerMove(id)}
                onPointerUp={onPointerUp(id)}
                onPointerCancel={onPointerUp(id)}
                onKeyDown={onKeyDown(id)}
              >
                <div
                  className="bs-core"
                  style={{
                    ...coreBaseStyle,
                    width: coreSize,
                    height: coreSize,
                    opacity: coreOpacity,
                    // per-node twinkle phase, mock's own literal (SecondThoughtV2.html:1786) — the
                    // DOM has no negative-animation-delay limit, so this is used unmodified (the RN
                    // sibling port had to offset it positive; see starsSim.ts's header comment).
                    ["--twd" as string]: `${(Math.sin(recentIds.indexOf(id) * 7.13) * 1.7 + 1.7).toFixed(2)}s`,
                  }}
                />
                <div className="bs-lbl" style={lblStyle}>{note.title}</div>
              </div>
            );
          })}

          <div style={legendStyle} aria-hidden="true">
            <div style={legendRowStyle}><span style={legendWikStyle} />wikilink · spring</div>
            <div style={legendRowStyle}><span style={legendTagStyle} />shared tag · thread</div>
          </div>
        </>
      )}

      {peekNote && (
        <>
          {/* Backdrop dismiss — click anywhere outside the card closes it, never navigates. */}
          <div style={backdropStyle} onClick={closePeek} />
          <PeekCard
            note={peekNote}
            x={peekPos.x}
            y={peekPos.y}
            hostW={size.w}
            hostH={size.h}
            onOpen={() => {
              closePeek();
              onOpenNote?.(peekNote.id);
            }}
            onClose={closePeek}
          />
        </>
      )}
    </div>
  );
}

function PeekCard({
  note,
  x,
  y,
  hostW,
  hostH,
  onOpen,
  onClose,
}: {
  note: StarNote;
  x: number;
  y: number;
  hostW: number;
  hostH: number;
  onOpen: () => void;
  onClose: () => void;
}) {
  // SecondThoughtV2.html :1833-1835 — the mock's own literal clamp margins, not card-size-derived.
  const left = Math.min(Math.max(x + 14, 6), hostW - CARD_LEFT_CLAMP);
  const top = Math.min(Math.max(y - 20, 6), hostH - CARD_TOP_CLAMP);
  const age = note.modified != null ? formatAgo(note.modified * 1000) : "unknown";
  const tagsLine = note.tags.length > 0 ? note.tags.map((t) => `#${t}`).join(" ") : "";

  return (
    <div className="bs-card" style={{ ...cardStyle, left, top }}>
      <div style={cardTitleStyle}>{note.title}</div>
      {/* No "status" segment (mock's STL[n.st]) — desktop notes carry no analogous per-note state;
          omitted rather than fabricated. */}
      <div style={cardMetaStyle}>{note.project} · {age}</div>
      {/* Always "no wikilinks" — see the ponytail in starsSim.ts on why. */}
      <div style={cardLinksStyle}>no wikilinks</div>
      {tagsLine && <div style={cardLinksStyle}>{tagsLine}</div>}
      <div style={cardActionsStyle}>
        <button className="btn-hover" style={{ ...BTN_PRIMARY, flex: 1 }} onClick={onOpen}>OPEN NOTE</button>
        <button className="btn-hover" style={BTN_SECONDARY} onClick={onClose}>CLOSE</button>
      </div>
    </div>
  );
}

// ── styles ───────────────────────────────────────────────────────────────────────────────────────
// .sky background: SecondThoughtV2.html :193-196's radial-gradient overlay, transcribed with the
// token this app's --surface already equals (#262626 === rgb(38,38,38), the mock's literal), via
// color-mix instead of an invented rgba (DESIGN.md Token-Only Rule).
const skyStyle: CSSProperties = {
  flex: 1, minHeight: 0, position: "relative", overflow: "hidden",
  background:
    "radial-gradient(500px 320px at 30% 20%, color-mix(in srgb, var(--surface) 35%, transparent), transparent 70%), " +
    "radial-gradient(600px 400px at 75% 80%, color-mix(in srgb, var(--surface) 28%, transparent), transparent 70%), " +
    "var(--bg)",
  touchAction: "none",
};
const svgStyle: CSSProperties = { position: "absolute", inset: 0, pointerEvents: "none" };
const starStyle: CSSProperties = {
  position: "absolute", left: 0, top: 0, transform: "translate(-50%,-50%)",
  display: "flex", flexDirection: "column", alignItems: "center", cursor: "grab",
  userSelect: "none", touchAction: "none", outline: "none",
};
const coreBaseStyle: CSSProperties = {
  borderRadius: "50%", // a star's core earns round — CLAUDE.md's identity carve-out
  background: "var(--text-1)",
  boxShadow: "0 0 6px color-mix(in srgb, var(--text-1) 70%, transparent), 0 0 14px color-mix(in srgb, var(--text-1) 25%, transparent)",
  animationName: "bsTwinkle", animationDuration: "3.4s", animationTimingFunction: "ease-in-out",
  animationIterationCount: "infinite", animationDelay: "var(--twd, 0s)",
};
const lblStyle: CSSProperties = {
  fontSize: micro, color: "var(--text-3)", marginTop: 6, whiteSpace: "nowrap",
  maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis",
};
const legendStyle: CSSProperties = { position: "absolute", left: 14, bottom: 12, fontSize: micro, color: "var(--text-3)", lineHeight: 1.9, pointerEvents: "none" };
const legendRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 6 };
const legendWikStyle: CSSProperties = { display: "inline-block", width: 22, height: 1, background: "color-mix(in srgb, var(--text-1) 40%, transparent)" };
const legendTagStyle: CSSProperties = { display: "inline-block", width: 22, borderTop: "1px dashed color-mix(in srgb, var(--text-1) 22%, transparent)" };
const backdropStyle: CSSProperties = { position: "absolute", inset: 0, zIndex: 4 };
const cardStyle: CSSProperties = {
  position: "absolute", width: CARD_W, background: "var(--glass-bg)", border: "1px solid var(--border)",
  padding: "12px 14px", zIndex: 5, display: "flex", flexDirection: "column", gap: 4,
};
// SecondThoughtV2.html :218 (.star-card h5{font-size:12px}) — the "read" step, not "title".
const cardTitleStyle: CSSProperties = { fontSize: fsRead, fontWeight: 600, color: "var(--text-1)" };
const cardMetaStyle: CSSProperties = { fontSize: fsLabel, color: "var(--text-3)", marginBottom: 4 };
const cardLinksStyle: CSSProperties = { fontSize: fsLabel, color: "var(--text-2)", lineHeight: 1.8 };
const cardActionsStyle: CSSProperties = { display: "flex", gap: 8, marginTop: 8 };
const emptyWrapStyle: CSSProperties = {
  position: "absolute", inset: 0, display: "flex", flexDirection: "column" as const,
  alignItems: "center", justifyContent: "center", gap: 10,
  color: "var(--text-3)", textAlign: "center" as const, padding: 24,
};
const emptyTitleStyle: CSSProperties = { fontSize: fsRead, fontWeight: 600, color: "var(--text-2)" };
const emptyBodyStyle: CSSProperties = { fontSize: fsLabel, maxWidth: 280, lineHeight: 1.6 };
