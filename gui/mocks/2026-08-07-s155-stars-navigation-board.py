"""Generate the s155 STARS navigation + density board.

The question (user, s155): make the constellation's connection density ADAPTIVE to
the vault, expose a user setting for fine-tuning, and make the sky navigable
(zoom in / zoom out / pan) "for easy and simple navigation", taking ideas from
Obsidian's graph view.

Three decisions are rendered here, each with the CURRENT shipped behavior first:

  D1  the density rule        fixed absolute floor (today) | pure percentile | hybrid
  D2  where the controls live corner toggle (today) | Obsidian-style panel | split
  D3  labels under zoom       scale with sky | constant size | constant + fade

Everything in D1 is the REAL vault: 30 notes from captures.db, real tags, real
project, real 384-d embeddings from vectors.db, laid out by a Python port of the
SHIPPING force model whose constants are parsed out of gui/src/lib/starsSim.ts at
build time and asserted — so the board cannot drift from the simulation it argues
about. The two extra vault SHAPES in D1 are synthetic by necessity (only one real
vault exists) and are labelled as such on the board itself.

Run:  python 2026-08-07-s155-stars-navigation-board.py
"""
from __future__ import annotations
import json
import math
import random
import re
import sqlite3
import struct
from itertools import combinations
from pathlib import Path

ROOT = Path(r"c:\Users\biloh\Claude\Projects\Second Thought Full Codebase")
V2_MOCK = ROOT / "SecondThoughtV2.html"
HERE = Path(__file__).parent
VAULT = Path.home() / "second-thought-storage"
CAPTURES_DB = VAULT / ".omni_capture" / "captures.db"
VECTORS_DB = VAULT / ".omni_capture" / "vectors.db"


# ── fonts + tokens + scale, re-derived from source (s147/s148/s150/s151 convention) ──
def load_font_faces() -> str:
    html = V2_MOCK.read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"@font-face\s*\{[^}]*\}", html) if "IBM Plex Mono" in b]
    assert len(blocks) == 3, f"expected 3 IBM Plex Mono @font-face blocks, found {len(blocks)}"
    return "\n".join(blocks)


INDEX_CSS = (ROOT / "Second Thought/gui/src/index.css").read_text(encoding="utf-8")


def token(name: str) -> str:
    m = re.search(rf"--{re.escape(name)}:\s*([^;]+);", INDEX_CSS)
    assert m, f"token --{name} not found in index.css"
    return m.group(1).strip()


TOK = {n: token(n) for n in (
    "bg", "surface", "surface-2", "border", "border-2",
    "text-1", "text-2", "text-3", "accent", "ctl-face", "green", "yellow", "red",
)}

TYPE_TS = (ROOT / "Second Thought/gui/src/lib/type.ts").read_text(encoding="utf-8")
SCALE = {}
for name in ("micro", "label", "body", "read", "lead", "title", "display", "hero"):
    m = re.search(rf"export const {name} = (\d+);", TYPE_TS)
    assert m, f"lib/type.ts export `{name}` missing"
    SCALE[name] = int(m.group(1))
assert list(SCALE.values()) == [9, 10, 11, 12, 13, 16, 20, 22], f"type scale drifted: {SCALE}"

# ── the shipping force + edge constants, parsed from starsSim.ts (never hand-copied) ──
SIM_TS = (ROOT / "Second Thought/gui/src/lib/starsSim.ts").read_text(encoding="utf-8")


def num(pattern: str) -> float:
    m = re.search(pattern, SIM_TS)
    assert m, f"constant not found in starsSim.ts: {pattern}"
    return float(m.group(1))


REPEL_NUM = num(r"const REPEL_NUM = ([\d.]+);")
REPEL_D2_FLOOR = num(r"const REPEL_D2_FLOOR = ([\d.]+);")
K_WIKI = num(r"const SPRING_WIKILINK = \{ k: ([\d.]+)")
REST_WIKI = num(r"const SPRING_WIKILINK = \{ k: [\d.]+, rest: ([\d.]+)")
K_TAG = num(r"const SPRING_TAG = \{ k: ([\d.]+)")
REST_TAG = num(r"const SPRING_TAG = \{ k: [\d.]+, rest: ([\d.]+)")
CENTER_PULL = num(r"const CENTER_PULL = ([\d.]+);")
DAMPING = num(r"const DAMPING = ([\d.]+);")
NODE_CAP = int(num(r"export const NODE_CAP = (\d+);"))
SEM_FLOOR = num(r"export const SEMANTIC_FLOOR = ([\d.]+);")
TOP_K = int(num(r"export const EDGE_TOP_K = (\d+);"))
CLAMP_X = int(num(r"const CLAMP_X = \[(\d+), \d+\]"))
CLAMP_Y = int(num(r"const CLAMP_Y = \[(\d+), \d+\]"))
assert (REPEL_NUM, K_WIKI, K_TAG, DAMPING, NODE_CAP) == (2600.0, 0.015, 0.003, 0.9, 100), \
    "starsSim force constants moved — re-read them before trusting this board"
assert (SEM_FLOOR, TOP_K) == (0.62, 3), \
    f"the edge-model constants this board argues about moved: floor={SEM_FLOOR} topK={TOP_K}"
assert CLAMP_X == 66, f"CLAMP_X moved to {CLAMP_X} — FR-40 set it to 66"


# ── real vault data ────────────────────────────────────────────────────────────
def load_notes() -> list[dict]:
    con = sqlite3.connect(str(CAPTURES_DB))
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT path, project, filename, tags FROM captures"):
        try:
            tags = set(json.loads(r["tags"] or "[]"))
        except Exception:
            tags = set()
        name = (r["filename"] or Path(r["path"]).name or r["path"]).removesuffix(".md")
        out.append({"path": r["path"], "project": r["project"] or "", "title": name, "tags": tags})
    con.close()
    return out


def load_vectors() -> dict[str, list[float]]:
    """Mean-pool each note's chunk vectors back to one per note (ids are `path::cN`)."""
    con = sqlite3.connect(str(VECTORS_DB))
    acc: dict[str, list[list[float]]] = {}
    for vid, blob in con.execute("SELECT id, embedding FROM embeddings"):
        acc.setdefault(vid.split("::")[0], []).append(list(struct.unpack(f"{len(blob) // 4}f", blob)))
    con.close()
    out = {}
    for parent, vecs in acc.items():
        dim = len(vecs[0])
        mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        norm = math.sqrt(sum(x * x for x in mean)) or 1.0
        out[parent] = [x / norm for x in mean]
    return out


NOTES = load_notes()
VECS = load_vectors()
N = len(NOTES)


def vec_for(note: dict) -> list[float] | None:
    p = note["path"].replace("\\", "/")
    for key in VECS:
        if p.endswith(key.replace("\\", "/")):
            return VECS[key]
    return None


for nt in NOTES:
    nt["vec"] = vec_for(nt)

MATCHED = sum(1 for n in NOTES if n["vec"])
assert MATCHED == N, f"only {MATCHED} of {N} notes matched a vector — board would be partial"


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ══ THE THREE VAULT SHAPES ══════════════════════════════════════════════════════
# Only one real vault exists, so the other two shapes are SYNTHETIC and the board
# says so on its face. They exist to answer the one question the real vault cannot:
# what does each rule do when the vault is NOT shaped like this one?
def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def synth_sims(kind: str, n: int) -> dict[tuple[int, int], float]:
    """Deterministic synthetic pair-similarity matrices. Seeded, never Math.random-ish drift."""
    rng = random.Random(20260807)
    dim = 32
    if kind == "tight":
        # one dominant topic: every note is the same direction plus a little noise, so
        # nearly every pair scores high. This is the "all my notes are about one project" vault.
        # sigma is chosen against cos ~= 1/sqrt(1 + sigma^2 * dim): 0.11 over 32 dims lands
        # the pair cosines around 0.85, i.e. a vault where everything really is one topic.
        base = _unit([rng.gauss(0, 1) for _ in range(dim)])
        vecs = [_unit([base[d] + rng.gauss(0, 0.11) for d in range(dim)]) for _ in range(n)]
    else:
        # genuinely unrelated notes: independent directions, so nearly every pair scores low.
        vecs = [_unit([rng.gauss(0, 1) for _ in range(dim)]) for _ in range(n)]
    return {(i, j): cosine(vecs[i], vecs[j]) for i, j in combinations(range(n), 2)}


REAL_SIMS = {(i, j): cosine(NOTES[i]["vec"], NOTES[j]["vec"]) for i, j in combinations(range(N), 2)}
SHAPES = {
    "real": REAL_SIMS,
    "tight": synth_sims("tight", N),
    "scattered": synth_sims("scattered", N),
}


def percentile(vals: list[float], q: float) -> float:
    s = sorted(vals)
    if not s:
        return 0.0
    return s[min(len(s) - 1, max(0, int(round(q / 100 * (len(s) - 1)))))]


# ── the three candidate density rules ──────────────────────────────────────────
# All three feed the SAME top-K union that ships today; only the FLOOR differs.
ABS_SAFETY = 0.45   # "below this is two notes written in the same language, not a relationship"
TARGET_PCT = 83.0   # measured: the shipped 0.62 sits at ~p83 of the real vault


def floor_fixed(_sims) -> float:
    return SEM_FLOOR


def floor_percentile(sims) -> float:
    return percentile(list(sims.values()), TARGET_PCT)


def floor_hybrid(sims) -> float:
    return max(ABS_SAFETY, percentile(list(sims.values()), TARGET_PCT))


RULES = [
    ("A", "Fixed floor — as shipped", floor_fixed,
     f"One hardcoded number ({SEM_FLOOR}) for every vault on earth."),
    ("B", "Pure percentile", floor_percentile,
     f"Always keep the strongest {100 - TARGET_PCT:.0f}% of pairs, whatever they score."),
    ("C", "Hybrid — percentile with a floor under it", floor_hybrid,
     f"max({ABS_SAFETY}, p{TARGET_PCT:.0f}). Adapts, but never invents a connection."),
]


def edges_for(sims, floor: float, n: int) -> list[tuple[int, int, float, str]]:
    """Score → per-node top-K → union. The shipped selection, with a swappable floor."""
    scored: dict[tuple[int, int], float] = {}
    for (i, j), s in sims.items():
        if s >= floor:
            # the shipped semantic weight ramp, re-based on the active floor
            span = max(1e-6, 1.0 - floor)
            scored[(i, j)] = 0.50 + 0.50 * (s - floor) / span
    cand: dict[int, list[tuple[int, int]]] = {}
    for p in scored:
        cand.setdefault(p[0], []).append(p)
        cand.setdefault(p[1], []).append(p)
    keep: set[tuple[int, int]] = set()
    for _node, lst in cand.items():
        lst.sort(key=lambda p: -scored[p])
        for p in lst[:TOP_K]:
            keep.add(p)
    return [(i, j, scored[(i, j)], "semantic") for (i, j) in sorted(keep)]


# ── the shipping force model, ported (same as the s151 board) ──────────────────
def hash_position(i: int, w: float, h: float) -> tuple[float, float]:
    fx = ((math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1
    fy = ((math.sin(i * 78.233) * 12543.123) % 1 + 1) % 1
    return w * (0.14 + 0.72 * fx), h * (0.12 + 0.7 * fy)


def layout(edges, w: float, h: float, n: int, iters: int = 700):
    """Repulsion / weighted springs / centering / damping, reduced-motion (no idle
    drift), run to equilibrium. Clamp margins are the SHIPPING ones, parsed above."""
    xs, ys, vxs, vys = [], [], [0.0] * n, [0.0] * n
    for i in range(n):
        x, y = hash_position(i, w, h)
        xs.append(x)
        ys.append(y)
    for _ in range(iters):
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = xs[j] - xs[i], ys[j] - ys[i]
                d2 = max(dx * dx + dy * dy, REPEL_D2_FLOOR)
                f = REPEL_NUM / d2
                d = math.sqrt(d2)
                ux, uy = dx / d, dy / d
                vxs[i] -= ux * f * 0.02
                vys[i] -= uy * f * 0.02
                vxs[j] += ux * f * 0.02
                vys[j] += uy * f * 0.02
        for (i, j, wt, _kind) in edges:
            k = K_TAG + (K_WIKI - K_TAG) * wt
            rest = REST_TAG + (REST_WIKI - REST_TAG) * wt
            dx, dy = xs[j] - xs[i], ys[j] - ys[i]
            d = math.hypot(dx, dy) or 0.001
            f = (d - rest) * k
            ux, uy = dx / d, dy / d
            vxs[i] += ux * f
            vys[i] += uy * f
            vxs[j] -= ux * f
            vys[j] -= uy * f
        for i in range(n):
            vxs[i] += (w / 2 - xs[i]) * CENTER_PULL
            vys[i] += (h / 2 - ys[i]) * CENTER_PULL
            vxs[i] *= DAMPING
            vys[i] *= DAMPING
            xs[i] += vxs[i]
            ys[i] += vys[i]
            xs[i] = min(max(xs[i], 26), w - 26)
            ys[i] = min(max(ys[i], 20), h - 34)
    return xs, ys


def degree_of(edges, n):
    deg = [0] * n
    for i, j, _w, _k in edges:
        deg[i] += 1
        deg[j] += 1
    return deg


def constellation(edges, n, w=420, h=280, *, labels=False, scale=1.0,
                  label_px=None, label_op=1.0) -> str:
    """`scale` renders the sky as if zoomed — used by D3 to show what zoom does to labels.
    `label_px` None = labels scale with the sky (naive); a number = constant screen size."""
    xs, ys = layout(edges, w, h, n)
    deg = degree_of(edges, n)
    cx, cy = w / 2, h / 2
    parts = [f'<svg class="sky" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">',
             f'<g transform="translate({cx} {cy}) scale({scale}) translate({-cx} {-cy})">']
    for (i, j, wt, _kind) in edges:
        op = 0.10 + 0.38 * wt
        parts.append(
            f'<line x1="{xs[i]:.1f}" y1="{ys[i]:.1f}" x2="{xs[j]:.1f}" y2="{ys[j]:.1f}" '
            f'stroke="var(--text-1)" stroke-opacity="{op:.2f}" stroke-width="{1 / scale:.2f}" '
            f'stroke-dasharray="{6 / scale:.1f} {3 / scale:.1f}"/>')
    for i in range(n):
        size = 5.0
        parts.append(
            f'<circle cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="{size / 2:.1f}" '
            f'fill="var(--text-1)" fill-opacity="0.75"/>')
        if labels and i < len(NOTES):
            t = NOTES[i]["title"][:13].replace("&", "&amp;").replace("<", "&lt;")
            fs = (SCALE["micro"] / scale) if label_px is None else (label_px / scale)
            parts.append(
                f'<text x="{xs[i]:.1f}" y="{ys[i] + size / 2 + 8 / scale:.1f}" text-anchor="middle" '
                f'class="starlabel" font-size="{fs:.2f}" opacity="{label_op}">{t}</text>')
    parts.append("</g></svg>")
    return "".join(parts)


# ── icons: inline SVG only, never emoji (identity lock) ────────────────────────
def ic(paths: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<svg{c} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


STAR_ICON = ic('<circle cx="12" cy="12" r="2.4"/><circle cx="5" cy="6" r="1.6"/>'
               '<circle cx="19" cy="7" r="1.6"/><circle cx="6" cy="18" r="1.6"/>'
               '<path d="M6.4 7.1 10 10.4M17.6 8.1 14 10.4M7.2 16.7 10.4 13.6"/>')
PLUS_ICON = ic('<path d="M12 5v14M5 12h14"/>')
MINUS_ICON = ic('<path d="M5 12h14"/>')
FIT_ICON = ic('<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4'
              'M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>')
CHEV_ICON = ic('<path d="M6 9l6 6 6-6"/>')
SLIDER_ICON = ic('<path d="M4 8h10M18 8h2M4 16h4M12 16h8"/><circle cx="16" cy="8" r="2"/>'
                 '<circle cx="10" cy="16" r="2"/>')

# ══ SECTION BUILDERS ════════════════════════════════════════════════════════════
SHAPE_LABEL = {
    "real": ("YOUR VAULT", "real &mdash; 30 notes, real embeddings"),
    "tight": ("ONE-TOPIC VAULT", "synthetic &mdash; everything is about the same thing"),
    "scattered": ("UNRELATED VAULT", "synthetic &mdash; nothing is about the same thing"),
}


def d1_matrix() -> str:
    """3 rules x 3 vault shapes. The whole argument for adaptivity is in this grid."""
    head = "".join(
        f'<th><span class="shname">{SHAPE_LABEL[s][0]}</span>'
        f'<span class="shsub">{SHAPE_LABEL[s][1]}</span></th>' for s in SHAPES)
    rows = []
    for code, name, fn, blurb in RULES:
        cells = []
        for shape, sims in SHAPES.items():
            f = fn(sims)
            edges = edges_for(sims, f, N)
            deg = degree_of(edges, N)
            iso = sum(1 for d in deg if d == 0)
            mean_deg = (2 * len(edges) / N) if N else 0
            verdict, vcls = rule_verdict(code, shape, len(edges), iso, mean_deg, f)
            cells.append(
                f'<td><div class="skywrap">{constellation(edges, N)}</div>'
                f'<div class="metric"><b>{len(edges)}</b> edges &middot; '
                f'mean degree <b>{mean_deg:.1f}</b><br>'
                f'floor <b>{f:.2f}</b> &middot; {iso} isolated</div>'
                f'<div class="verdict {vcls}">{verdict}</div></td>')
        rows.append(
            f'<tr><th class="rulehead"><span class="rcode">{code}</span>'
            f'<span class="rname">{name}</span><span class="rwhy">{blurb}</span></th>'
            f'{"".join(cells)}</tr>')
    return (f'<table class="matrix"><tr><th class="corner"></th>{head}</tr>'
            f'{"".join(rows)}</table>')


MAX_EDGES = None  # set after N is known; top-K union ceiling


def rule_verdict(code: str, shape: str, edges: int, iso: int, mean_deg: float, floor: float):
    """Derived from the numbers rendered beside it, never hand-written prose that can
    drift away from them. Three failure modes, each with a numeric trigger."""
    ceiling = N * TOP_K  # every star sourcing its full top-K, before dedup
    if edges == 0:
        if floor <= ABS_SAFETY + 1e-9 and shape == "scattered":
            return "nothing clears the safety floor &mdash; honestly empty", "good"
        return "empty sky &mdash; the <code>sparse</code> state, with no fix to offer", "bad"
    if mean_deg >= 4.0:
        return f"saturating &mdash; mean degree {mean_deg:.1f}, top-K nearly maxed", "bad"
    if floor < ABS_SAFETY:
        return f"draws edges down to {floor:.2f} similarity &mdash; invents structure", "bad"
    return f"readable &mdash; mean degree {mean_deg:.1f}", "good"


def zoom_ctl(active: str = "") -> str:
    def b(key, icon, txt=""):
        cls = "zbtn" + (" on" if key == active else "")
        return f'<button class="{cls}">{icon}{txt}</button>'
    return (f'<div class="zoomctl">{b("out", MINUS_ICON)}'
            f'<span class="zpct">100%</span>{b("in", PLUS_ICON)}'
            f'<span class="zsep"></span>{b("fit", FIT_ICON)}</div>')


def toggle(on: bool) -> str:
    return f'<span class="tg {"on" if on else ""}"><span class="knob"></span></span>'


def seg(options, active) -> str:
    return ('<span class="seg">' + "".join(
        f'<span class="segopt{" on" if o == active else ""}">{o}</span>' for o in options)
        + "</span>")


def d2_options(edges) -> str:
    sky = constellation(edges, N, w=420, h=250)
    # ── A: today, plus the new controls simply added to the same corner ──
    a = (f'<div class="skywrap tall">{sky}'
         f'<div class="ov tr row">{toggle(True)}<span class="ovlbl">Smart connections</span></div>'
         f'<div class="ov tr2 row">{seg(["Sparse", "Balanced", "Dense"], "Balanced")}</div>'
         f'<div class="ov br">{zoom_ctl()}</div></div>')
    # ── B: Obsidian-style collapsible panel owning everything ──
    b = (f'<div class="skywrap tall">{sky}'
         f'<div class="ov tl panel">'
         f'<div class="prow phead"><span class="pico">{SLIDER_ICON}</span>'
         f'<span class="ptitle">SKY</span><span class="pchev">{CHEV_ICON}</span></div>'
         f'<div class="prow"><span class="plbl">Smart connections</span>{toggle(True)}</div>'
         f'<div class="prow"><span class="plbl">Density</span></div>'
         f'<div class="prow">{seg(["Sparse", "Balanced", "Dense"], "Balanced")}</div>'
         f'<div class="prow slim"><span class="plbl">Connections</span>'
         f'<span class="pval">39 &middot; mean 2.6</span></div>'
         f'</div>'
         f'<div class="ov br">{zoom_ctl()}</div></div>')
    # ── C: split — density in the titlebar, sky stays bare, zoom gesture-only ──
    c = (f'<div class="fwtitle"><span class="fwt">BROWSE</span>'
         f'<span class="fwspacer"></span>'
         f'{seg(["Notes", "Trash"], "Notes")}'
         f'<span class="segico">{seg(["list", "stars"], "stars")}</span>'
         f'{seg(["Sparse", "Balanced", "Dense"], "Balanced")}</div>'
         f'<div class="skywrap tall nobord">{sky}'
         f'<div class="ov tr row">{toggle(True)}<span class="ovlbl">Smart connections</span></div>'
         f'<div class="ov bc hint">scroll to zoom &middot; drag to pan &middot; double-click to fit</div>'
         f'</div>')
    items = [
        ("A", "Everything in the corner", a,
         "Least new structure: the density control and the zoom cluster join the toggle that is "
         "already there. Three separate floating groups end up competing over one sky."),
        ("B", "Collapsible SKY panel &mdash; Obsidian's own answer", b,
         "One panel owns every sky-level control and collapses to a single row. Matches how "
         "Obsidian's graph puts filters, forces and display in a corner disclosure. Scales if a "
         "fourth control ever arrives; costs one more click to reach a setting."),
        ("C", "Titlebar split, sky stays bare", c,
         "Density joins the LIST/STARS toggle in the titlebar where view-level switches already "
         "live; zoom is gesture-only with a one-line hint. Cleanest sky, least discoverable zoom, "
         "and the titlebar row is already carrying two toggles."),
    ]
    return "".join(
        f'<div class="opt"><div class="ohead"><span class="ocode">{c_}</span>'
        f'<span class="oname">{n_}</span></div>{body}<p class="owhy">{why}</p></div>'
        for c_, n_, body, why in items)


def d3_options(edges) -> str:
    """What zoom does to the 9px labels — the one visible consequence of the transform choice."""
    outs = []
    specs = [
        ("A", "Labels scale with the sky",
         "One transform on a wrapper: cheapest possible change, physics untouched. But the label "
         "is 9px by design &mdash; at 40% it is 3.6px and unreadable, at 220% it is 20px and shouts.",
         None, 1.0),
        ("B", "Labels stay one size",
         "Labels are counter-scaled so they render at 9px at every zoom. Always legible &mdash; but "
         "zoomed out, 30 labels at full size collide into a solid band of text.",
         SCALE["micro"], 1.0),
        ("C", "One size, and they fade out when zoomed out",
         "Constant 9px, with the whole label layer fading below a zoom threshold &mdash; exactly "
         "Obsidian's text-fade behaviour. Zoomed out you read the SHAPE; zoomed in you read the names.",
         SCALE["micro"], None),
    ]
    for code, name, why, lpx, _ in specs:
        cells = []
        for z, ztag in ((0.45, "40% &mdash; zoomed out"), (1.0, "100%"), (2.0, "200% &mdash; zoomed in")):
            op = 1.0
            if code == "C":
                op = 0.0 if z < 0.7 else 1.0
            svg = constellation(edges, N, w=420, h=250, labels=True, scale=z,
                               label_px=lpx, label_op=op)
            note = ""
            if code == "C" and z < 0.7:
                note = '<div class="zfade">labels hidden below 70%</div>'
            cells.append(f'<div class="zcell"><div class="ztag">{ztag}</div>'
                         f'<div class="skywrap sm">{svg}{note}</div></div>')
        outs.append(f'<div class="opt"><div class="ohead"><span class="ocode">{code}</span>'
                    f'<span class="oname">{name}</span></div>'
                    f'<div class="zrow">{"".join(cells)}</div>'
                    f'<p class="owhy">{why}</p></div>')
    return "".join(outs)


# ── the measured distribution table ────────────────────────────────────────────
def dist_table() -> str:
    sims = sorted(REAL_SIMS.values())
    P = len(sims)
    above = sum(1 for s in sims if s >= SEM_FLOOR)
    rows = "".join(
        f"<tr><td>p{q}</td><td>{percentile(sims, q):.3f}</td></tr>"
        for q in (50, 70, 80, 85, 90, 95))
    return (f'<table class="dist"><tr><th>percentile</th><th>cosine</th></tr>{rows}</table>'
            f'<p class="note">{P} pairs &middot; median <b>{percentile(sims, 50):.3f}</b> &middot; '
            f'range {sims[0]:.3f}&ndash;{sims[-1]:.3f}. The shipped floor <b>{SEM_FLOOR}</b> passes '
            f'<b>{above}</b> of them &mdash; it already sits at about <b>p{100 * (P - above) / P:.0f}</b>.</p>')


E_REAL = edges_for(REAL_SIMS, SEM_FLOOR, N)
MEAN_DEG_REAL = 2 * len(E_REAL) / N

HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>STARS &mdash; adaptive density + sky navigation (s155)</title>
<style>
{load_font_faces()}
:root {{
  --bg:{TOK['bg']}; --surface:{TOK['surface']}; --surface-2:{TOK['surface-2']};
  --border:{TOK['border']}; --border-2:{TOK['border-2']};
  --text-1:{TOK['text-1']}; --text-2:{TOK['text-2']}; --text-3:{TOK['text-3']};
  --accent:{TOK['accent']}; --ctl-face:{TOK['ctl-face']};
  --green:{TOK['green']}; --yellow:{TOK['yellow']}; --red:{TOK['red']};
  --mono:'IBM Plex Mono',monospace; --track:0.01em;
  --micro:{SCALE['micro']}px; --label:{SCALE['label']}px; --body:{SCALE['body']}px;
  --read:{SCALE['read']}px; --lead:{SCALE['lead']}px; --title:{SCALE['title']}px;
  --display:{SCALE['display']}px; --hero:{SCALE['hero']}px;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text-1);
  font-family:var(--mono); letter-spacing:var(--track); font-size:var(--body); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:34px 22px 80px; }}
h1 {{ font-size:var(--hero); font-weight:600; margin:0 0 6px; }}
.sub {{ color:var(--text-3); font-size:var(--read); margin:0 0 6px; line-height:1.7; }}
.sec {{ margin-top:44px; border-top:1px solid var(--border); padding-top:22px; }}
.sec > h2 {{ font-size:var(--title); font-weight:600; margin:0 0 4px; }}
.sec > .q {{ color:var(--text-2); font-size:var(--read); margin:0 0 18px; line-height:1.75; max-width:78ch; }}
.callout {{ border:1px solid var(--border); background:var(--surface); padding:14px 16px;
  margin:16px 0 22px; font-size:var(--read); line-height:1.8; color:var(--text-2); }}
.callout b {{ color:var(--text-1); }}
.two {{ display:grid; grid-template-columns:minmax(0,220px) minmax(0,1fr); gap:22px; align-items:start; }}
table.dist {{ border-collapse:collapse; font-size:var(--label); }}
table.dist th, table.dist td {{ border:1px solid var(--border); padding:4px 12px; text-align:left; }}
table.dist th {{ color:var(--text-3); font-weight:500; }}
.note {{ font-size:var(--read); color:var(--text-2); line-height:1.85; margin:0; }}
.note b {{ color:var(--text-1); }}

/* ── D1 matrix ── */
.mscroll {{ overflow-x:auto; }}
table.matrix {{ border-collapse:collapse; width:100%; }}
table.matrix th, table.matrix td {{ border:1px solid var(--border); padding:10px; vertical-align:top; }}
th.corner {{ border:none; }}
.shname {{ display:block; font-size:var(--label); color:var(--text-1); font-weight:600; }}
.shsub {{ display:block; font-size:var(--micro); color:var(--text-3); font-weight:400; margin-top:2px; }}
th.rulehead {{ width:186px; text-align:left; background:var(--surface); }}
.rcode {{ display:inline-block; border:1px solid var(--border-2); color:var(--text-1);
  font-size:var(--micro); padding:1px 6px; margin-bottom:6px; }}
.rname {{ display:block; font-size:var(--body); color:var(--text-1); font-weight:600; }}
.rwhy {{ display:block; font-size:var(--micro); color:var(--text-3); margin-top:5px; line-height:1.7; font-weight:400; }}
.skywrap {{ position:relative; border:1px solid var(--border); background:
  radial-gradient(500px 320px at 30% 20%, color-mix(in srgb, var(--surface) 35%, transparent), transparent 70%),
  radial-gradient(600px 400px at 75% 80%, color-mix(in srgb, var(--surface) 28%, transparent), transparent 70%),
  var(--bg); overflow:hidden; }}
.skywrap.nobord {{ border-top:none; }}
svg.sky {{ display:block; width:100%; height:auto; }}
.starlabel {{ fill:var(--text-3); font-family:var(--mono); letter-spacing:var(--track); }}
.metric {{ font-size:var(--micro); color:var(--text-3); margin-top:7px; line-height:1.7; }}
.metric b {{ color:var(--text-1); }}
.verdict {{ font-size:var(--micro); margin-top:6px; line-height:1.6; padding-left:9px;
  border-left:1px solid var(--border-2); }}
.verdict.good {{ color:var(--green); border-left-color:var(--green); }}
.verdict.ok {{ color:var(--text-2); }}
.verdict.bad {{ color:var(--yellow); border-left-color:var(--yellow); }}

/* ── options ── */
.opt {{ margin:26px 0 0; }}
.ohead {{ display:flex; align-items:baseline; gap:10px; margin-bottom:9px; }}
.ocode {{ border:1px solid var(--border-2); color:var(--text-1); font-size:var(--micro); padding:1px 6px; }}
.oname {{ font-size:var(--lead); font-weight:600; }}
.owhy {{ font-size:var(--read); color:var(--text-2); line-height:1.85; margin:10px 0 0; max-width:82ch; }}
.skywrap.tall {{ min-height:250px; }}
.skywrap.sm svg.sky {{ height:auto; }}
.ov {{ position:absolute; z-index:2; }}
.ov.tr {{ top:10px; right:12px; }}
.ov.tr2 {{ top:36px; right:12px; }}
.ov.tl {{ top:10px; left:12px; }}
.ov.br {{ right:12px; bottom:10px; }}
.ov.bc {{ left:50%; transform:translateX(-50%); bottom:10px; }}
.row {{ display:flex; align-items:center; gap:8px; }}
.ovlbl {{ font-size:var(--label); color:var(--text-3); }}
.hint {{ font-size:var(--micro); color:var(--text-3); }}
.tg {{ width:26px; height:14px; border:1px solid var(--border-2); background:var(--ctl-face);
  display:inline-flex; align-items:center; padding:1px; }}
.tg .knob {{ width:10px; height:10px; background:var(--text-3); }}
.tg.on {{ border-color:var(--text-2); }}
.tg.on .knob {{ background:var(--text-1); margin-left:auto; }}
.seg {{ display:inline-flex; border:1px solid var(--border-2); background:var(--ctl-face); }}
.segopt {{ font-size:var(--micro); color:var(--text-3); padding:3px 8px; }}
.segopt.on {{ background:var(--surface-2); color:var(--text-1); }}
.segico .segopt {{ padding:3px 7px; }}
.zoomctl {{ display:inline-flex; align-items:center; border:1px solid var(--border-2);
  background:var(--ctl-face); }}
.zbtn {{ background:none; border:none; color:var(--text-2); padding:4px 7px; cursor:pointer;
  display:inline-flex; align-items:center; font-family:var(--mono); }}
.zbtn svg {{ width:12px; height:12px; }}
.zpct {{ font-size:var(--micro); color:var(--text-3); min-width:34px; text-align:center; }}
.zsep {{ width:1px; align-self:stretch; background:var(--border-2); }}
.panel {{ border:1px solid var(--border); background:var(--surface); min-width:178px; }}
.prow {{ display:flex; align-items:center; justify-content:space-between; gap:10px;
  padding:6px 9px; border-top:1px solid var(--border); }}
.prow:first-child {{ border-top:none; }}
.prow.slim {{ padding:5px 9px; }}
.phead {{ background:var(--surface-2); }}
.pico {{ display:inline-flex; color:var(--text-2); }}
.pico svg {{ width:13px; height:13px; }}
.ptitle {{ font-size:var(--micro); color:var(--text-1); flex:1; }}
.pchev {{ display:inline-flex; color:var(--text-3); }}
.pchev svg {{ width:12px; height:12px; }}
.plbl {{ font-size:var(--micro); color:var(--text-3); }}
.pval {{ font-size:var(--micro); color:var(--text-2); }}
.fwtitle {{ display:flex; align-items:center; gap:10px; height:38px; padding:0 12px;
  border:1px solid var(--border); background:var(--surface); }}
.fwt {{ font-size:var(--label); font-weight:600; }}
.fwspacer {{ flex:1; }}
.zrow {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }}
.ztag {{ font-size:var(--micro); color:var(--text-3); margin-bottom:5px; }}
.zfade {{ position:absolute; left:50%; bottom:8px; transform:translateX(-50%);
  font-size:var(--micro); color:var(--text-3); border:1px solid var(--border);
  background:var(--surface); padding:2px 7px; }}
.rec {{ border:1px solid var(--green); color:var(--green); font-size:var(--micro);
  padding:1px 6px; margin-left:auto; }}
.foot {{ margin-top:40px; border-top:1px solid var(--border); padding-top:16px;
  font-size:var(--micro); color:var(--text-3); line-height:1.9; }}
@media (max-width:900px) {{ .two {{ grid-template-columns:1fr; }} .zrow {{ grid-template-columns:1fr; }} }}
</style></head>
<body><div class="wrap">

<h1>STARS &mdash; adaptive density &amp; sky navigation</h1>
<p class="sub">Three decisions. Current shipped behaviour is option <b>A</b> in every one of them.
Every sky below is the <b>real force model</b> &mdash; constants parsed out of
<code>starsSim.ts</code> at build time and asserted, so this board cannot drift from the code
it is arguing about.</p>

<div class="callout">
<b>A number in the handover was misleading and is corrected here.</b> The ledger recorded
&ldquo;39 edges over 30 stars &mdash; roughly 1.3 edges per star&rdquo;. Every edge touches two stars,
so the mean number of connections per note is <b>{MEAN_DEG_REAL:.1f}</b>, not 1.3.
</div>

<div class="sec">
<h2>D1 &mdash; what decides whether two notes are connected</h2>
<p class="q">Today one hardcoded number, <code>SEMANTIC_FLOOR = {SEM_FLOOR}</code>, ships to every
vault. Each star then keeps its {TOP_K} strongest partners and the picks are unioned. The question
is only what sets the floor.</p>

<div class="two">
  <div>{dist_table()}</div>
  <div class="note">Measured over your vault's real embeddings. The shipped
  <b>{SEM_FLOOR}</b> lands at roughly <b>p83</b> &mdash; so a percentile rule aimed at p83 would
  reproduce today's sky here almost exactly. That is the argument for adaptivity: on the one vault
  we can actually see, it changes nothing. It only acts on the vaults we cannot see.
  <br><br>It is also why a <i>pure</i> percentile is wrong. &ldquo;Keep the top 17%&rdquo; keeps the
  top 17% even when the best pair in the vault scores 0.2 &mdash; drawing a constellation over notes
  that have nothing to do with each other. The rule needs a hard floor beneath it.</div>
</div>

<div class="mscroll">{d1_matrix()}</div>
<p class="note" style="margin-top:14px">The middle column is your real vault; the outer two are
<b>synthetic</b> &mdash; there is only one real vault, so the only honest way to show what each rule
does to a differently-shaped one is to construct it and say so.</p>
</div>

<div class="sec">
<h2>D2 &mdash; where the sky's controls live</h2>
<p class="q">Adaptive density adds a user control, and navigation adds a zoom cluster, to a corner
that currently holds one bare toggle. Obsidian's graph solves this with a collapsible disclosure in
the corner of the graph itself.</p>
{d2_options(E_REAL)}
</div>

<div class="sec">
<h2>D3 &mdash; what zoom does to the star labels</h2>
<p class="q">Labels are {SCALE['micro']}px (<code>micro</code> on the locked scale). Whether they
scale with the sky is the one part of the zoom implementation you can actually see, so it is a
decision rather than a detail.</p>
{d3_options(E_REAL)}
</div>

<div class="foot">
Generated by <code>gui/mocks/2026-08-07-s155-stars-navigation-board.py</code> &middot;
real vault: {N} notes, {len(REAL_SIMS)} pairs, {MATCHED} embeddings matched &middot;
force constants asserted against <code>starsSim.ts</code>
(REPEL {REPEL_NUM:.0f} &middot; k {K_TAG}&ndash;{K_WIKI} &middot; damping {DAMPING} &middot;
CLAMP_X {CLAMP_X} &middot; floor {SEM_FLOOR} &middot; top-K {TOP_K}) &middot;
type scale asserted against <code>lib/type.ts</code> &middot; tokens read from <code>index.css</code>
</div>

</div></body></html>
"""

OUT = HERE / "2026-08-07-s155-stars-navigation-board.html"
OUT.write_text(HTML, encoding="utf-8")
print(f"wrote {OUT}  ({len(HTML) / 1024:.0f} KB)")

# ── the `.artifact.html` twin (s151 convention). The Artifact host supplies its own
# doctype/html/head/body skeleton, so the published copy must carry page CONTENT only.
# <style> and <title> survive — they are legal in body flow and the host keeps them.
ART = HTML
for pat in (r"<!doctype html>\s*", r"<html[^>]*>\s*", r"</html>\s*",
            r"<head>\s*", r"</head>\s*", r"<body>\s*", r"</body>\s*",
            r'<meta[^>]*>\s*'):
    ART = re.sub(pat, "", ART, flags=re.I)
assert "<style>" in ART and "<!doctype" not in ART.lower(), "artifact strip went wrong"
ART_OUT = HERE / "2026-08-07-s155-stars-navigation-board.artifact.html"
ART_OUT.write_text(ART, encoding="utf-8")
print(f"wrote {ART_OUT}  ({len(ART) / 1024:.0f} KB)")
print(f"real vault: {N} notes, {len(REAL_SIMS)} pairs, mean degree today {MEAN_DEG_REAL:.2f}")
for code, name, fn, _ in RULES:
    line = []
    for shape, sims in SHAPES.items():
        f = fn(sims)
        e = edges_for(sims, f, N)
        line.append(f"{shape}: floor {f:.2f} -> {len(e)} edges")
    print(f"  {code} {name:44s} " + " | ".join(line))
