/**
 * starsSim.ts — the STARS view's force model (DECISIONS §5 s146; user's own words: "movement · wire
 * connections · drag-around physics · quick peek at the dots"). Ported VERBATIM from
 * `SecondThoughtV2.html`'s `class Sky` (:1772-1884, instantiated as `skyD`/`skyP` :1885-1886) — that
 * class was written for the desktop; `skyD` is directly portable. Every constant below is copied, not
 * tuned, not re-derived. If a number here ever disagrees with the mock, the mock wins.
 *
 * Mirrors the already-shipped RN port's decomposition 1:1 (`Second Thought - Android App/phone/src/
 * lib/starsSim.ts`) — NOT imported (different repo, RN-specific types) but followed line-for-line so
 * the two force models can never silently drift. Differences from that file, and why:
 *   - `initNodes`/`stepSimulation`/`releaseMomentum`/`isTap`/`coreVisual` are untouched — same formulas.
 *   - Twinkle phase: the phone offsets its Animated-driven pulse to a POSITIVE delay
 *     (`Math.abs(Math.sin(index*7.13))*1700`) because RN `Animated` has no negative
 *     `animation-delay`. The DOM has no such limit — the CALLER (BrowseStarsView.tsx) uses the mock's
 *     own signed phase directly (`Math.sin(i*7.13)*1.7+1.7`, SecondThoughtV2.html:1786) via a CSS
 *     custom property, not this module (twinkle is pure CSS animation-delay, not physics).
 *   - `selectRecentIds` takes a NUMBER `modified` (epoch seconds, `SearchResult.modified` from
 *     `lib/api.ts` — a filesystem `stat().st_mtime`), not an ISO string. Desktop has no ISO
 *     `note.modified` field to parse; sorting numbers directly is both simpler and avoids a
 *     needless `Date.parse` round-trip.
 *   - `buildStarEdges`/`computeDegrees` take a minimal local `StarSourceNote` shape (id + tags) —
 *     desktop has no `Note`/`LinkIndex` types (those are RN-only modules) and, per the ceiling noted
 *     below, no wikilink edges are ever produced here, so the wikilink half of the phone's
 *     `buildStarEdges` (which reads a real `LinkIndex`) has nothing to port.
 *
 * ★ s152: the edge model is now weighted (tags · project · opt-in semantic · wikilink) and budgeted
 * per node. That block is marked in the file and is kept IDENTICAL in the phone's copy. The ceiling
 * below is unchanged and still real — desktop supplies no `links`, so the wikilink signal simply
 * never bids here; the other three carry the sky.
 *
 * ponytail: NO WIKILINK EDGES. The phone's `buildStarEdges` reads a durable on-device `linkIndex`
 * (SQLite `links` table, built by `db/index.ts`'s writers) — the desktop has no equivalent. The
 * capture pipeline's `link_resolver.py` builds a link index too, but only in-process at capture-write
 * time to inject `[[wikilinks]]` into a note's body; it is never persisted or exposed over the FastAPI
 * server (grepped `omni_capture/server.py` for every `@app.get`/`@app.post` route — no `/links`,
 * `/backlinks`, or `/graph` endpoint exists). Reconstructing one client-side would mean fetching every
 * candidate note's full body (one `GET /note` round trip per node, up to `NODE_CAP`) just to regex it
 * for `[[...]]` targets and resolve them back to paths — that's inventing a link source out of N
 * network calls, not using one that exists; the brief is explicit that this is not allowed. So this
 * module only ever builds `"tag"`-kind edges (real data — `SearchResult.tags`, a JSON array column
 * populated for every indexed vault file, including every `origin: note` file — see `index_writer.py`'s
 * `_read_file_tags`/`upsert_capture_from_file`). Upgrade path: expose a `/links` (or similar) endpoint
 * off `link_resolver.build_link_index`, then wire a real `"wikilink"` pass here the same shape as the
 * phone's. Until then every star's wikilink DEGREE is 0 (see `computeDegrees` below), so `coreVisual`
 * never selects the 8px/10px buckets on desktop — a real, honest consequence of the missing source,
 * not a bug in this file.
 */

export interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  ph: number; // per-node phase for idle drift + twinkle: i * 1.7
  drag: boolean; // ★ every force below is gated on !drag — that anchoring IS the drag physics
  fvx?: number; // last drag-frame delta, feeds release momentum (v = fv * 1.6)
  fvy?: number;
}

export type SimEdgeKind = "wikilink" | "tag" | "project" | "semantic";
export interface SimEdge {
  a: string;
  b: string;
  /** The signal that WON this pair (strongest bid), for colour + explanation. */
  kind: SimEdgeKind;
  /** 0..1 strength. Drives spring stiffness, rest length and line opacity — a strong pair settles
   *  closer and steadier, a weak one sits further out and sways more (DECISIONS §5 s152). */
  weight: number;
}

export interface StepOptions {
  // ★ reduced motion kills the idle-drift term ONLY — springs, repulsion, centering, drag and clamp
  // all keep running (DECISIONS §5 s146 pt.4). Default false.
  reducedMotion?: boolean;
  // FR-44 fix, mirrored from the phone port (same rationale, same field name): the drift term
  // (Math.sin(...)*DRIFT_VX etc.) is an undecaying forcing function — with reducedMotion:false (the
  // shipping default) the sky never settles, even though every other force does. This is the
  // multiplier the caller (BrowseStarsView.tsx) computes from elapsed-time-since-armed via
  // `driftEnvelope()` below and passes in; it decays 1 -> 0 over SETTLE_SEC so the drift itself
  // eventually stops without touching DRIFT_VX/DRIFT_VY (both regex-checked across repos by
  // tools/parity_edge_model.py). Default 1 — every existing caller and test is behaviour-identical
  // without passing it.
  driftEnvelope?: number;
}

// ── deterministic init (never Math.random — same hash the mock/phone both use) ──────────────────
export function hashPosition(i: number, w: number, h: number): { x: number; y: number } {
  const fx = (((Math.sin(i * 12.9898) * 43758.5453) % 1) + 1) % 1;
  const fy = (((Math.sin(i * 78.233) * 12543.123) % 1) + 1) % 1;
  return { x: w * (0.14 + 0.72 * fx), y: h * (0.12 + 0.7 * fy) };
}

export function initNodes(ids: readonly string[], w: number, h: number): SimNode[] {
  return ids.map((id, i) => {
    const { x, y } = hashPosition(i, w, h);
    return { id, x, y, vx: 0, vy: 0, ph: i * 1.7, drag: false };
  });
}

// ── the step, verbatim from Sky.step(t) (SecondThoughtV2.html:1841-1879) ─────────────────────────
const REPEL_NUM = 2600; // :1848
const REPEL_D2_FLOOR = 40; // :1847
const SPRING_WIKILINK = { k: 0.015, rest: 105 }; // :1861
const SPRING_TAG = { k: 0.003, rest: 170 }; // :1862
const CENTER_PULL = 0.0016; // :1865
const DRIFT_VX = 0.012; // sin(t/1700 + ph), :1866
const DRIFT_VY = 0.012; // cos(t/2100 + ph), :1866
const DAMPING = 0.9; // :1867
// ★ s154 (FR-40, user-ruled): 26 → 66, and DELIBERATELY NOT the mock's :1870 literal any more.
// The clamp bounds the node CENTRE, but `.bs-lbl` is an 80px-wide centred label, so at 26 a
// right-edge label's box ended at W+14 and was clipped by skyStyle's `overflow:hidden`. Measured
// live over CDP: right edge 749 against a 736px viewport — +13px, matching the arithmetic.
// 66 = 26 + half the label width. Kept EQUAL to the phone sibling's constant: this pair sits
// OUTSIDE the shared-block markers, so `parity:edge-model` would not catch a one-sided edit.
const CLAMP_X = [66, 66] as const; // [left margin, right margin] — x in [66, W-66]
const CLAMP_Y = [20, 34] as const; // y in [20, H-34], :1871

// ── FR-44 settle envelope, mirrored from the phone port — NOT part of the shared edge model, a
// purely local addition (identical formula on both platforms by hand, not by the marker check).
// Multiplies the drift term only; every other force (repulsion/springs/centering/damping/clamp) is
// untouched. `elapsedSec` is time since the caller last "armed" the sky (mount, or any re-arm trigger
// below) — the caller owns the clock, this stays a pure function of one number.
export const SETTLE_SEC = 7;
export function driftEnvelope(elapsedSec: number): number {
  return Math.max(0, 1 - elapsedSec / SETTLE_SEC);
}

// ── weight → motion (s152) ───────────────────────────────────────────────────────────────────────
// The mock shipped two discrete springs; the weighted model interpolates BETWEEN them, so a 1.0
// edge is bit-for-bit the old wikilink spring and a 0.0 edge is bit-for-bit the old tag spring.
// Nothing outside these two helpers changed: repulsion, centering, damping, drift and the clamp are
// untouched, which is what keeps the felt motion of the sky the same.
function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}
export function springK(weight: number): number {
  return SPRING_TAG.k + (SPRING_WIKILINK.k - SPRING_TAG.k) * clamp01(weight);
}
export function springRest(weight: number): number {
  return SPRING_TAG.rest + (SPRING_WIKILINK.rest - SPRING_TAG.rest) * clamp01(weight);
}
/** Line opacity for a drawn edge — the visual half of the same continuum. */
export function edgeOpacity(weight: number): number {
  return 0.1 + 0.38 * clamp01(weight);
}

export function stepSimulation(
  nodes: readonly SimNode[],
  edges: readonly SimEdge[],
  t: number,
  w: number,
  h: number,
  opts: StepOptions = {}
): SimNode[] {
  const reducedMotion = opts.reducedMotion ?? false;
  const byId = new Map<string, SimNode>();
  for (const n of nodes) byId.set(n.id, { ...n });
  const arr = [...byId.values()]; // same objects as byId's values — mutations below are shared

  // Pairwise repulsion — O(n²), NODE_CAP below is what keeps this cheap.
  for (let i = 0; i < arr.length; i++) {
    for (let j = i + 1; j < arr.length; j++) {
      const a = arr[i];
      const b = arr[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < REPEL_D2_FLOOR) d2 = REPEL_D2_FLOOR;
      const f = REPEL_NUM / d2;
      const d = Math.sqrt(d2);
      dx /= d;
      dy /= d;
      if (!a.drag) {
        a.vx -= dx * f;
        a.vy -= dy * f;
      }
      if (!b.drag) {
        b.vx += dx * f;
        b.vy += dy * f;
      }
    }
  }

  // ONE spring pass, interpolated by weight (s152). The two named constants below are now the ENDS
  // of a continuum rather than two discrete cases: weight 0 is exactly the old tag spring, weight 1
  // exactly the old wikilink spring, so the mock's numbers are still the only numbers here.
  for (const e of edges) {
    const a = byId.get(e.a);
    const b = byId.get(e.b);
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
    const f = springK(e.weight) * (d - springRest(e.weight));
    if (!a.drag) {
      a.vx += (dx / d) * f;
      a.vy += (dy / d) * f;
    }
    if (!b.drag) {
      b.vx -= (dx / d) * f;
      b.vy -= (dy / d) * f;
    }
  }

  for (const n of arr) {
    if (!n.drag) {
      n.vx += (w / 2 - n.x) * CENTER_PULL;
      n.vy += (h / 2 - n.y) * CENTER_PULL;
      if (!reducedMotion) {
        const envelope = opts.driftEnvelope ?? 1;
        n.vx += Math.sin(t / 1700 + n.ph) * DRIFT_VX * envelope;
        n.vy += Math.cos(t / 2100 + n.ph) * DRIFT_VY * envelope;
      }
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x += n.vx;
      n.y += n.vy;
    }
    // Clamp runs unconditionally, dragged or not — a dragged node still can't leave the sky.
    n.x = Math.min(Math.max(n.x, CLAMP_X[0]), w - CLAMP_X[1]);
    n.y = Math.min(Math.max(n.y, CLAMP_Y[0]), h - CLAMP_Y[1]);
  }

  const out = nodes.map((orig) => byId.get(orig.id) as SimNode);
  // FR-44 quiescence guard, mirrored from the phone port: the max per-node displacement this step,
  // for the caller's consecutive-quiet-frames counter (quiescenceStep, below). Least-invasive
  // extension of the existing return shape (SimNode[]) — an attached property, not a new return type,
  // so every existing caller/test that reads `stepSimulation(...)` as a plain node array is unaffected.
  let maxDelta = 0;
  for (const orig of nodes) {
    const next = byId.get(orig.id);
    if (!next) continue;
    const d = Math.hypot(next.x - orig.x, next.y - orig.y);
    if (d > maxDelta) maxDelta = d;
  }
  (out as SimNode[] & { maxDelta: number }).maxDelta = maxDelta;
  return out;
}

// ── FR-44 quiescence guard, mirrored from the phone port: after QUIESCENCE_FRAMES consecutive frames
// whose maxDelta (above) stays under QUIESCENCE_DELTA_PX, the caller stops scheduling
// requestAnimationFrame — this is what makes the settle envelope's decay-to-zero actually STOP the
// loop rather than just slow it asymptotically forever. Pure: the caller (BrowseStarsView.tsx) owns
// the running counter, this just advances it one frame.
export const QUIESCENCE_DELTA_PX = 0.01;
export const QUIESCENCE_FRAMES = 30;
export function quiescenceStep(maxDelta: number, consecutive: number): { consecutive: number; settled: boolean } {
  const next = maxDelta < QUIESCENCE_DELTA_PX ? consecutive + 1 : 0;
  return { consecutive: next, settled: next >= QUIESCENCE_FRAMES };
}

// ── release momentum (Sky.wireDrag's pointerup, :1823) ───────────────────────────────────────────
export function releaseMomentum(fvx: number, fvy: number): { vx: number; vy: number } {
  return { vx: fvx * 1.6, vy: fvy * 1.6 };
}

// ── tap vs. drag (Sky.wireDrag, :1819: total movement <= 6px counts as a tap) ───────────────────
export const TAP_THRESHOLD_PX = 6;
export function isTap(totalDx: number, totalDy: number): boolean {
  return Math.abs(totalDx) + Math.abs(totalDy) <= TAP_THRESHOLD_PX;
}

// ── core size encodes wikilink degree (0 / 1 / 2+) — SecondThoughtV2.html :200-203 ───────────────
export interface CoreVisual {
  size: number;
  opacity: number;
}
export function coreVisual(degree: number): CoreVisual {
  if (degree === 0) return { size: 5, opacity: 0.75 };
  if (degree === 1) return { size: 8, opacity: 1 };
  return { size: 10, opacity: 1 };
}

// ── node selection: cap the O(n²) sim to the most-recently-modified N notes ──────────────────────
// ponytail: hard cap at NODE_CAP, most-recently-modified wins, ties are stable (Array.sort is stable
// in V8). The real ceiling is the repulsion pass above: it's O(n²), so NODE_CAP=100 is ~4,950
// pairs/frame — measured fine on the mock's own numbers (DECISIONS §5 s146 pt.6), several hundred
// nodes would not be. Upgrade path IF a device/vault measurement ever shows this dropping frames:
// spatial partitioning (grid/quadtree) for the repulsion pass. Do not raise the cap on a hunch, only
// on that measurement — same rule the phone port already applies.
export const NODE_CAP = 100;

export interface RecencyItem {
  id: string;
  /** Epoch SECONDS (`SearchResult.modified` — a `stat().st_mtime`), or null when the file couldn't be
   *  stat'd (index lagging a vault delete). Null sorts last, same as an absent phone `note.modified`
   *  would via `Date.parse(undefined) === NaN` sorting last in a descending compare. */
  modified: number | null;
}

export function selectRecentIds(items: readonly RecencyItem[], cap: number = NODE_CAP): string[] {
  return [...items]
    .sort((a, b) => (b.modified ?? -Infinity) - (a.modified ?? -Infinity))
    .slice(0, cap)
    .map((n) => n.id);
}

// ══ THE EDGE MODEL (s152) — THIS BLOCK IS KEPT IDENTICAL IN `phone/src/lib/starsSim.ts`. ═════════
// Change one, change the other in the same commit, or the two skies stop agreeing about what a
// connection IS. Everything it needs arrives on `StarSourceNote`, so neither platform's own types
// (desktop `SearchResult`, phone `Note`/`LinkIndex`) leak in here.
//
// Why weighted-and-budgeted rather than the old boolean "shares a tag": both boolean rules are
// degenerate on a real vault, in OPPOSITE directions (measured s151 on the user's own 29 notes —
// `shares ≥1 tag` drew ZERO edges because every tag occurred exactly once, `same project` drew ALL
// 406 pairs because every note sat in `_loose`). A score plus a per-node budget is what makes the
// drawn set both non-empty and bounded, whatever shape the vault happens to be in.
export interface StarSourceNote {
  id: string;
  tags: readonly string[];
  /** Owning project. `_loose`/`uncategorized`/empty are the ABSENCE of a grouping, not a grouping —
   *  they can never source an edge (and `_loose` must never be rendered at all). */
  project?: string | null;
  /** Ids this note wikilinks TO, already resolved. Desktop supplies none — see the ponytail above. */
  links?: readonly string[];
  /** The note's embedding, supplied ONLY when smart connections are on. Absent = no semantic bid. */
  vec?: readonly number[] | null;
}

export interface EdgeOptions {
  /** The opt-in semantic pass (DECISIONS §5 s152). Default OFF — the user's own call. */
  semantic?: boolean;
  /** Index into DENSITY_STEPS. Omitted = the shipped default (s156). */
  densityIndex?: number;
}

/** Max edges any one star may SOURCE. Drawn degree can still exceed it via inbound picks — the kept
 *  set is a union, not a partition, so a genuinely central note stays central. */
export const EDGE_TOP_K = 3;
/** The ABSOLUTE floor: a cosine below this is not a relationship, it is two notes written in the
 *  same language. Since s156 it is a floor and never a ceiling — see `adaptiveSemanticFloor`. */
export const SEMANTIC_FLOOR = 0.62;

/** ★ s156 (D1, user-ruled): CONNECTION DENSITY. One index moves two knobs at once — the percentile
 *  the semantic floor tracks, and the per-node edge budget. Both are needed, and for different
 *  reasons. The percentile is what makes the floor adapt to a vault's own similarity distribution.
 *  The budget is what makes the control do anything at all on a vault whose distribution the
 *  absolute floor already dominates: on the user's real vault 74 of 435 pairs clear 0.62 but only 39
 *  edges are drawn, so 35 REAL pairs are pruned by the budget alone. Raising density un-prunes those;
 *  it can never invent one, because the floor below is a max(), not a replacement. */
export interface DensityStep {
  readonly name: string;
  /** Percentile of the observed cosine distribution the semantic floor tracks. */
  readonly percentile: number;
  /** Max edges any one star may SOURCE at this step (see EDGE_TOP_K). */
  readonly topK: number;
}
export const DENSITY_STEPS: readonly DensityStep[] = [
  { name: "Minimal", percentile: 92, topK: 1 },
  { name: "Sparse", percentile: 88, topK: 2 },
  { name: "Balanced", percentile: 83, topK: 3 },
  { name: "Dense", percentile: 78, topK: 4 },
  { name: "Maximal", percentile: 70, topK: 5 },
];
/** Index of the shipped default. Measured s155 on the real vault: the fixed 0.62 floor sits at ~p83,
 *  so this step reproduces the pre-s156 sky to within one edge. Adaptivity cannot regress the one
 *  case anybody can actually see — that is why p83 is the default and not a rounder number. */
export const DENSITY_DEFAULT_INDEX = 2;

/** Clamped lookup. A persisted preference can be anything — an out-of-range index must resolve to a
 *  real step, never to `undefined` that then reads as a missing topK deep inside the budget loop. */
export function densityStep(i: number): DensityStep {
  if (!Number.isFinite(i)) return DENSITY_STEPS[DENSITY_DEFAULT_INDEX];
  const k = Math.min(Math.max(Math.round(i), 0), DENSITY_STEPS.length - 1);
  return DENSITY_STEPS[k];
}

/** Nearest-rank percentile over an array sorted ASCENDING. `p` is 0..100. An empty distribution
 *  scores 0, which makes the max() below fall back to the absolute floor — the safe direction. */
export function percentileOf(sortedAsc: readonly number[], p: number): number {
  if (sortedAsc.length === 0) return 0;
  const q = Math.min(Math.max(p, 0), 100) / 100;
  const idx = Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1));
  return sortedAsc[idx];
}

/** THE HYBRID RULE (D1-C). `SEMANTIC_FLOOR` is the FLOOR, never a ceiling: the percentile may raise
 *  the bar on a vault whose notes are all alike, and may never lower it on a vault whose notes are
 *  all unrelated. Measured across three vault shapes — real / one-topic / unrelated — this is the
 *  only rule that stays honest in all three: a pure percentile keeps the top 17% of an unrelated
 *  vault at cosines around 0.18 and draws a constellation over nothing. */
export function adaptiveSemanticFloor(sortedAsc: readonly number[], p: number): number {
  return Math.max(SEMANTIC_FLOOR, percentileOf(sortedAsc, p));
}

const W_WIKILINK = 1;
const W_TAG_BASE = 0.35;
const W_TAG_SPAN = 0.4;
const W_PROJECT = 0.3;
const W_SEMANTIC_BASE = 0.5;
const W_SEMANTIC_SPAN = 0.5;

function isRealProject(p: string | null | undefined): boolean {
  return !!p && p !== "_loose" && p !== "uncategorized";
}

/** Cosine similarity. A zero-length vector scores 0 rather than NaN — an unembedded note must read
 *  as "no evidence", never as a NaN that then propagates silently through every comparison. */
export function cosine(a: readonly number[], b: readonly number[]): number {
  const n = Math.min(a.length, b.length);
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / Math.sqrt(na * nb);
}

/** The strongest signal connecting two notes, or null when nothing does. Signals BID; the highest
 *  bid wins outright — a pair is drawn once, coloured by whatever justified it best. */
export function pairWeight(
  a: StarSourceNote,
  b: StarSourceNote,
  semantic: boolean,
  floor: number = SEMANTIC_FLOOR
): { weight: number; kind: SimEdgeKind } | null {
  let best: { weight: number; kind: SimEdgeKind } | null = null;
  const bid = (weight: number, kind: SimEdgeKind): void => {
    if (!best || weight > best.weight) best = { weight, kind };
  };

  // An explicit [[link]] is the user's own assertion of a relationship — nothing outranks it.
  if (a.links?.includes(b.id) || b.links?.includes(a.id)) bid(W_WIKILINK, "wikilink");

  // Tags: Jaccard, not "shares at least one" — three tags in common must beat one.
  const union = new Set<string>([...a.tags, ...b.tags]);
  if (union.size > 0) {
    let inter = 0;
    for (const t of new Set(a.tags)) if (b.tags.includes(t)) inter++;
    if (inter > 0) bid(W_TAG_BASE + W_TAG_SPAN * (inter / union.size), "tag");
  }

  if (isRealProject(a.project) && a.project === b.project) bid(W_PROJECT, "project");

  // Semantic: opt-in, and a pass over vectors that ALREADY EXIST on disk — no inference at render
  // time, nothing leaves the device, no model loaded just to draw a sky.
  if (semantic && a.vec && b.vec) {
    const s = cosine(a.vec, b.vec);
    if (s >= floor) {
      // Normalised against the EFFECTIVE floor, so a just-passing edge is weight 0.5 at every
      // density rather than drifting as the floor moves. `span` guards a degenerate floor of 1.
      const span = Math.max(1 - floor, 1e-6);
      bid(W_SEMANTIC_BASE + W_SEMANTIC_SPAN * ((s - floor) / span), "semantic");
    }
  }
  return best;
}

const EDGE_SEP = "\u0000"; // cannot occur in a vault-relative path

function edgeKey(a: string, b: string): string {
  return a < b ? a + EDGE_SEP + b : b + EDGE_SEP + a;
}

/**
 * Score every in-cap pair, then keep each star's own top `EDGE_TOP_K` and union the picks.
 * Deduped, unordered pairs restricted to `allowedIds` (the capped node set) — a pair with either end
 * outside the cap is simply dropped, same as the mock only ever wiring pairs both present in `NOTES`.
 * Output is sorted by edge key, so the same vault redraws the same sky rather than a reshuffled one.
 */
export function buildStarEdges(
  notes: readonly StarSourceNote[],
  allowedIds: ReadonlySet<string>,
  opts: EdgeOptions = {}
): SimEdge[] {
  const semantic = opts.semantic ?? false;
  const step = densityStep(opts.densityIndex ?? DENSITY_DEFAULT_INDEX);
  const included = notes.filter((n) => allowedIds.has(n.id));

  // Pass 1: the observed cosine distribution, needed before ANY pair can be judged — the floor is a
  // property of the whole vault, not of a pair. Only runs when the semantic bid is on.
  // ponytail: cosine is computed twice per pair (here, then again in pairWeight). At NODE_CAP=100
  // that is 2 x 4,950 x 384 multiplies, run once per data change behind a useMemo, not per frame —
  // measured negligible. Cache pass 1 into a Map keyed by edgeKey if a profile ever shows it.
  let floor = SEMANTIC_FLOOR;
  if (semantic) {
    const cosines: number[] = [];
    for (let i = 0; i < included.length; i++) {
      for (let j = i + 1; j < included.length; j++) {
        const a = included[i];
        const b = included[j];
        if (a.vec && b.vec) cosines.push(cosine(a.vec, b.vec));
      }
    }
    cosines.sort((x, y) => x - y);
    floor = adaptiveSemanticFloor(cosines, step.percentile);
  }

  const scored = new Map<string, SimEdge>();
  const candidates = new Map<string, string[]>();

  const remember = (id: string, key: string): void => {
    const list = candidates.get(id);
    if (list) list.push(key);
    else candidates.set(id, [key]);
  };

  for (let i = 0; i < included.length; i++) {
    for (let j = i + 1; j < included.length; j++) {
      const a = included[i];
      const b = included[j];
      const w = pairWeight(a, b, semantic, floor);
      if (!w) continue;
      const key = edgeKey(a.id, b.id);
      if (scored.has(key)) continue;
      const [lo, hi] = a.id < b.id ? [a.id, b.id] : [b.id, a.id];
      scored.set(key, { a: lo, b: hi, kind: w.kind, weight: w.weight });
      remember(a.id, key);
      remember(b.id, key);
    }
  }

  const keep = new Set<string>();
  for (const keys of candidates.values()) {
    // Ties break on the key, never on insertion order — two equal-weight candidates must resolve the
    // same way on every machine, or the same vault draws a different sky on desktop than on phone.
    keys.sort((x, y) => (scored.get(y) as SimEdge).weight - (scored.get(x) as SimEdge).weight || (x < y ? -1 : 1));
    for (const k of keys.slice(0, step.topK)) keep.add(k);
  }
  return [...keep].sort().map((k) => scored.get(k) as SimEdge);
}
/**
 * Why an empty sky is empty (DECISIONS §5 s152). The whole point of shipping smart connections OFF
 * by default was to avoid a state the user cannot tell apart from a broken feature — so every way a
 * sky can end up with zero edges has to name ITSELF, and the two that have a fix have to offer it.
 *
 * `sparse` and `needsEmbeddings` are deliberately NOT collapsed into one message: one of them the
 * user can act on, the other one they cannot, and telling someone to turn on a setting that is
 * already on is worse than saying nothing.
 */
export type StarsEmptyState = "offer-smart" | "needs-embeddings" | "sparse" | null;

export interface StarsEmptyInput {
  starCount: number;
  edgeCount: number;
  smartOn: boolean;
  /** Whether embeddings actually exist to score against — NOT whether the setting is on. */
  embeddingsAvailable: boolean;
}

export function starsEmptyState(s: StarsEmptyInput): StarsEmptyState {
  // No stars at all is the view's own pre-existing empty state, not this one.
  if (s.starCount === 0 || s.edgeCount > 0) return null;
  if (!s.smartOn) return "offer-smart";
  return s.embeddingsAvailable ? "sparse" : "needs-embeddings";
}
// ══ END OF THE SHARED EDGE MODEL ═════════════════════════════════════════════════════════════════

// ── degree = wikilink-edge count only (mirrors the mock: `n.links.length`, :1784) ────────────────
export function computeDegrees(ids: readonly string[], edges: readonly SimEdge[]): Map<string, number> {
  const m = new Map<string, number>(ids.map((id) => [id, 0]));
  for (const e of edges) {
    if (e.kind !== "wikilink") continue;
    if (m.has(e.a)) m.set(e.a, (m.get(e.a) ?? 0) + 1);
    if (m.has(e.b)) m.set(e.b, (m.get(e.b) ?? 0) + 1);
  }
  return m;
}

// ── SearchResult.tags is a JSON-array-of-strings column (index_writer.py: `tags TEXT DEFAULT '[]'`),
// possibly null/malformed (index lag, a row from before the column existed). Never throws.
export function parseTagsField(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((t): t is string => typeof t === "string") : [];
  } catch {
    return [];
  }
}

// ── FR-44 pt.4: semantic motion at rest — brightness (+ conflict radius) only, only on notes that
// need attention (queued/conflict), everything else stays completely static once settled. Mirrored
// byte-for-byte from the phone port (starsSim.ts) — these are the SPEC for the curve (bounds +
// period), asserted directly in the sibling test. ★ Kept here even though BrowseStarsView.tsx does
// not yet drive a per-star pulse from them: the desktop sky has no per-node sync (queued/conflict)
// state wired into it today (StarNote carries no such field — see the caller's own report), so there
// is nothing on this side to attach the visual to without inventing a data path the brief explicitly
// forbids. The constants/formulas still have to match the phone's byte-for-byte per the brief, and
// living here (not invented, not duplicated) is what makes them ready the day a real per-note state
// survives the trip into this view.
export const QUEUED_PULSE_PERIOD_SEC = 5.5; // sin(t*1.15+phase): 2*PI/1.15 ~= 5.463s
export const QUEUED_PULSE_MIN = 0.4;
export const QUEUED_PULSE_MAX = 0.92;
export const CONFLICT_PULSE_PERIOD_SEC = 2.3; // sin(t*2.7+phase): 2*PI/2.7 ~= 2.327s
export const CONFLICT_OPACITY_MIN = 0.34;
export const CONFLICT_OPACITY_MAX = 0.96;
export const CONFLICT_RADIUS_MIN = 2.2;
export const CONFLICT_RADIUS_MAX = 3.3;

function pulseCurve(min: number, max: number, angularFreq: number, tSec: number, phase: number): number {
  return min + (max - min) * (0.5 + 0.5 * Math.sin(tSec * angularFreq + phase));
}
export function queuedPulseOpacity(tSec: number, phase: number): number {
  return pulseCurve(QUEUED_PULSE_MIN, QUEUED_PULSE_MAX, 1.15, tSec, phase);
}
export function conflictPulseOpacity(tSec: number, phase: number): number {
  return pulseCurve(CONFLICT_OPACITY_MIN, CONFLICT_OPACITY_MAX, 2.7, tSec, phase);
}
export function conflictPulseRadius(tSec: number, phase: number): number {
  return pulseCurve(CONFLICT_RADIUS_MIN, CONFLICT_RADIUS_MAX, 2.7, tSec, phase);
}
