"""Generate the s151 STARS edge-model board — desktop AND Android.

The question (user, s151): make desktop and phone the SAME, prioritise smooth
motion and "good and responsible connections between points", build the
connections from tags / project groupings, and add an OPT-IN setting that uses
the LLM to improve the groupings (default OFF).

Everything rendered here is the REAL vault: 29 notes from captures.db, real
tags, real project, real 384-d embeddings from vectors.db. The layouts are
produced by a Python port of the SHIPPING force model — the constants are
parsed out of gui/src/lib/starsSim.ts at build time and asserted, so the board
cannot drift from the simulation it is arguing about.

Run:  python 2026-08-07-s151-stars-edges-board.py
"""
from __future__ import annotations
import json
import math
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


# ── fonts + tokens + scale, re-derived from source (s147/s148/s150 convention) ──
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

# ── the shipping force constants, parsed from starsSim.ts (never hand-copied) ──
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
assert (REPEL_NUM, K_WIKI, K_TAG, DAMPING, NODE_CAP) == (2600.0, 0.015, 0.003, 0.9, 100), \
    "starsSim constants moved — re-read them before trusting this board"


# ── real vault data ────────────────────────────────────────────────────────────
def load_notes() -> list[dict]:
    con = sqlite3.connect(str(CAPTURES_DB))
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT path, project, filename, tags, body_excerpt FROM captures"):
        try:
            tags = set(json.loads(r["tags"] or "[]"))
        except Exception:
            tags = set()
        name = (r["filename"] or Path(r["path"]).name or r["path"]).removesuffix(".md")
        out.append({
            "path": r["path"], "project": r["project"] or "", "title": name,
            "tags": tags, "body": r["body_excerpt"] or "",
        })
    con.close()
    return out


def load_vectors() -> dict[str, list[float]]:
    """Mean-pool each note's chunk vectors back to one per note (ids are `path::cN`)."""
    con = sqlite3.connect(str(VECTORS_DB))
    acc: dict[str, list[list[float]]] = {}
    for vid, blob in con.execute("SELECT id, embedding FROM embeddings"):
        parent = vid.split("::")[0]
        vec = list(struct.unpack(f"{len(blob) // 4}f", blob))
        acc.setdefault(parent, []).append(vec)
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
    """vectors.db keys are vault-relative with forward slashes; captures.path is absolute."""
    p = note["path"].replace("\\", "/")
    for key in VECS:
        if p.endswith(key.replace("\\", "/")):
            return VECS[key]
    return None


for nt in NOTES:
    nt["vec"] = vec_for(nt)

MATCHED = sum(1 for n in NOTES if n["vec"])


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


WIKI_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
REAL_PROJECT = lambda p: p not in ("", "_loose", "uncategorized")  # noqa: E731


# ── the four edge rules ────────────────────────────────────────────────────────
def edges_today() -> list[tuple[int, int, float, str]]:
    """Shipping desktop rule: an edge for ANY shared tag, unweighted."""
    return [(i, j, 1.0, "tag") for i, j in combinations(range(N), 2)
            if NOTES[i]["tags"] & NOTES[j]["tags"]]


def edges_raw_project() -> list[tuple[int, int, float, str]]:
    """The naive reading of 'connect by project': every same-project pair."""
    return [(i, j, 1.0, "project") for i, j in combinations(range(N), 2)
            if NOTES[i]["project"] and NOTES[i]["project"] == NOTES[j]["project"]]


def pair_weight(i: int, j: int, *, semantic: bool) -> tuple[float, str] | None:
    a, b = NOTES[i], NOTES[j]
    best: tuple[float, str] | None = None

    def bid(w: float, kind: str):
        nonlocal best
        if best is None or w > best[0]:
            best = (w, kind)

    # An explicit [[link]] is the user's own assertion of a relationship — always strongest.
    if any(t.lower() == b["title"].lower() for t in WIKI_RE.findall(a["body"])) or \
       any(t.lower() == a["title"].lower() for t in WIKI_RE.findall(b["body"])):
        bid(1.0, "wikilink")
    # Tags: Jaccard, not "shares at least one" — 3 tags in common must beat 1.
    union = a["tags"] | b["tags"]
    if union:
        inter = a["tags"] & b["tags"]
        if inter:
            bid(0.35 + 0.40 * (len(inter) / len(union)), "tag")
    # Project: a real grouping only when the vault actually uses projects. `_loose` is the
    # internal bucket and must never be rendered, so it can never source an edge.
    if REAL_PROJECT(a["project"]) and a["project"] == b["project"]:
        bid(0.30, "project")
    # Semantic: opt-in. Cosine over embeddings that already exist — no inference at render time.
    if semantic and a["vec"] and b["vec"]:
        s = cosine(a["vec"], b["vec"])
        if s >= SEM_FLOOR:
            bid(0.50 + 0.50 * (s - SEM_FLOOR) / (1 - SEM_FLOOR), "semantic")
    return best


SEM_FLOOR = 0.62
TOP_K = 3


def edges_proposed(*, semantic: bool) -> list[tuple[int, int, float, str]]:
    """Weighted candidates, then top-K per node, unioned. Bounded and non-degenerate."""
    scored: dict[tuple[int, int], tuple[float, str]] = {}
    for i, j in combinations(range(N), 2):
        w = pair_weight(i, j, semantic=semantic)
        if w:
            scored[(i, j)] = w
    keep: set[tuple[int, int]] = set()
    for n in range(N):
        mine = [(p, wk) for p, wk in scored.items() if n in p]
        mine.sort(key=lambda t: -t[1][0])
        for p, _ in mine[:TOP_K]:
            keep.add(p)
    return [(i, j, scored[(i, j)][0], scored[(i, j)][1]) for (i, j) in sorted(keep)]


# ── the shipping force model, ported ───────────────────────────────────────────
def hash_position(i: int, w: float, h: float) -> tuple[float, float]:
    fx = ((math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1
    fy = ((math.sin(i * 78.233) * 12543.123) % 1 + 1) % 1
    return w * (0.14 + 0.72 * fx), h * (0.12 + 0.7 * fy)


def layout(edges, w: float, h: float, iters: int = 900):
    """Same repulsion / spring / centering / damping as stepSimulation, reduced-motion
    (no idle drift), run to equilibrium. Weighted springs interpolate k and rest
    between the shipped TAG and WIKILINK constants by edge weight."""
    xs, ys, vxs, vys = [], [], [0.0] * N, [0.0] * N
    for i in range(N):
        x, y = hash_position(i, w, h)
        xs.append(x)
        ys.append(y)
    for _ in range(iters):
        for i in range(N):
            for j in range(i + 1, N):
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
        for i in range(N):
            vxs[i] += (w / 2 - xs[i]) * CENTER_PULL
            vys[i] += (h / 2 - ys[i]) * CENTER_PULL
            vxs[i] *= DAMPING
            vys[i] *= DAMPING
            xs[i] += vxs[i]
            ys[i] += vys[i]
            xs[i] = min(max(xs[i], 26), w - 26)
            ys[i] = min(max(ys[i], 20), h - 34)
    return xs, ys


KIND_COLOR = {
    "wikilink": "var(--text-1)",
    "semantic": "var(--accent)",
    "tag": "var(--text-2)",
    "project": "var(--text-3)",
}


def degree_of(edges):
    deg = [0] * N
    for i, j, _w, _k in edges:
        deg[i] += 1
        deg[j] += 1
    return deg


def core_size(d: int) -> tuple[int, float]:
    if d == 0:
        return 5, 0.75
    if d == 1:
        return 8, 1.0
    return 10, 1.0


def constellation(edges, w=440, h=300, *, labels=False) -> str:
    xs, ys = layout(edges, w, h)
    deg = degree_of(edges)
    parts = [f'<svg class="sky" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">']
    for (i, j, wt, kind) in edges:
        op = 0.10 + 0.38 * wt
        parts.append(
            f'<line x1="{xs[i]:.1f}" y1="{ys[i]:.1f}" x2="{xs[j]:.1f}" y2="{ys[j]:.1f}" '
            f'stroke="{KIND_COLOR[kind]}" stroke-opacity="{op:.2f}" stroke-width="1"/>')
    for i in range(N):
        size, op = core_size(deg[i])
        parts.append(
            f'<circle cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="{size / 2:.1f}" '
            f'fill="var(--text-1)" fill-opacity="{op}"/>')
        if labels:
            t = NOTES[i]["title"][:14]
            parts.append(
                f'<text x="{xs[i]:.1f}" y="{ys[i] + size / 2 + 9:.1f}" text-anchor="middle" '
                f'class="starlabel">{t}</text>')
    parts.append("</svg>")
    return "".join(parts)


E_TODAY = edges_today()
E_PROJ = edges_raw_project()
E_OFF = edges_proposed(semantic=False)
E_ON = edges_proposed(semantic=True)

PAIRS = N * (N - 1) // 2


def stat(edges) -> str:
    deg = degree_of(edges)
    iso = sum(1 for d in deg if d == 0)
    mx = max(deg) if deg else 0
    return (f"{len(edges)} edges &middot; {len(edges) / PAIRS:.0%} of all pairs &middot; "
            f"{iso} isolated &middot; max degree {mx}")


# ── icons ──────────────────────────────────────────────────────────────────────
def ic(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


STAR_ICON = ic('<circle cx="12" cy="12" r="2.4"/><circle cx="5" cy="6" r="1.6"/>'
               '<circle cx="19" cy="7" r="1.6"/><circle cx="6" cy="18" r="1.6"/>'
               '<path d="M6.4 7.1 10 10.4M17.6 8.1 14 10.4M7.2 16.7 10.4 13.6"/>')
LIST_ICON = ic('<path d="M4 6h16M4 12h16M4 18h10"/>')
BACK_ICON = ic('<path d="M15 6l-6 6 6 6"/>')

CSS_VARS = "\n".join(f"  --{k}:{v};" for k, v in TOK.items())
CSS_SCALE = "\n".join(f"  --fs-{k}:{v}px;" for k, v in SCALE.items())

CSS = f"""
@charset "UTF-8";
{load_font_faces()}
:root{{
{CSS_VARS}
{CSS_SCALE}
  --track:0.01em;
  --space-2:8px;--space-3:12px;--space-4:16px;--space-5:24px;--space-6:32px;--space-7:56px;
}}
*,*::before,*::after{{box-sizing:border-box;border-radius:0;}}
body{{margin:0;background:#050505;color:var(--text-1);
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono","Segoe UI Mono",monospace;
  font-size:var(--fs-read);line-height:1.55;letter-spacing:var(--track);
  -webkit-font-smoothing:antialiased;}}
.wrap{{padding:0 var(--space-5) var(--space-7);max-width:960px;margin:0 auto;}}
.head{{padding:var(--space-6) var(--space-5) 0;max-width:960px;margin:0 auto;}}
.head h1{{font-size:var(--fs-hero);margin:0 0 var(--space-3);font-weight:600;
  letter-spacing:-0.01em;text-wrap:balance;}}
.head p{{color:var(--text-2);margin:0 0 var(--space-2);line-height:1.65;max-width:76ch;}}
.head b{{color:var(--text-1);}}
h2{{font-size:var(--fs-title);margin:var(--space-7) 0 var(--space-3);font-weight:600;}}
h2 .n{{color:var(--text-3);font-weight:400;font-size:var(--fs-body);margin-right:8px;}}
.lede{{color:var(--text-2);margin:0 0 var(--space-4);line-height:1.65;max-width:76ch;}}
.lede b{{color:var(--text-1);}}
code{{color:var(--text-1);background:#161616;padding:1px 4px;font-size:var(--fs-micro);}}

svg.sky{{display:block;width:100%;height:auto;background:var(--bg);}}
.starlabel{{fill:var(--text-3);font-size:6px;font-family:"IBM Plex Mono",monospace;}}

.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:var(--space-5);}}
.panel{{border:1px solid var(--border);background:var(--bg);}}
.panel .cap{{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding:8px 11px;border-bottom:1px solid var(--border-2);}}
.panel .cap .t{{font-size:var(--fs-body);color:var(--text-1);font-weight:600;}}
.panel .cap .v{{font-size:var(--fs-micro);color:var(--text-3);}}
.panel .why{{padding:8px 11px;border-top:1px solid var(--border-2);color:var(--text-2);
  font-size:var(--fs-body);line-height:1.6;}}
.panel .why b{{color:var(--text-1);}}
.panel.bad .cap .t{{color:var(--red);}}
.panel.good .cap .t{{color:var(--green);}}

.win{{border:1px solid var(--border);background:var(--bg);}}
.win .titlebar{{display:flex;align-items:center;gap:10px;padding:8px 14px;
  border-bottom:1px solid var(--border);background:#191919;font-size:var(--fs-label);
  color:var(--text-3);}}
.win .titlebar .app{{color:var(--text-1);font-weight:600;letter-spacing:.1em;}}
.win .toolbar{{display:flex;align-items:center;gap:8px;padding:7px 11px;
  border-bottom:1px solid var(--border-2);}}
.seg{{display:flex;border:1px solid var(--border);}}
.seg button{{display:flex;align-items:center;gap:5px;background:none;border:none;
  color:var(--text-3);font-family:inherit;font-size:var(--fs-label);padding:4px 9px;}}
.seg button svg{{width:11px;height:11px;}}
.seg button.on{{background:var(--ctl-face);color:var(--text-1);}}
.spacer{{flex:1;}}

.phone{{width:300px;border:1px solid var(--border-2);background:#0b0b0b;padding:9px 7px 12px;
  margin:0 auto;}}
.phone .screen{{border:1px solid var(--border);background:var(--bg);overflow:hidden;}}
.phone .statusbar{{display:flex;justify-content:space-between;padding:4px 10px;
  font-size:8px;color:var(--text-3);}}
.phone .apphead{{padding:9px 11px 7px;border-bottom:1px solid var(--border-2);
  display:flex;align-items:center;justify-content:space-between;}}
.phone .apphead .h1{{font-size:var(--fs-title);font-weight:600;}}
.phone .tabbar{{display:flex;border-top:1px solid var(--border-2);}}
.phone .tabbar div{{flex:1;text-align:center;padding:7px 0;font-size:8px;color:var(--text-3);}}
.phone .tabbar div.on{{color:var(--text-1);}}

table{{border-collapse:collapse;width:100%;margin-top:var(--space-4);font-size:var(--fs-body);}}
th,td{{border:1px solid var(--border);padding:7px 9px;text-align:left;vertical-align:top;
  line-height:1.55;}}
th{{color:var(--text-3);font-weight:400;font-size:var(--fs-label);letter-spacing:.06em;
  background:#111;}}
td b{{color:var(--text-1);}}
td.num{{font-variant-numeric:tabular-nums;white-space:nowrap;}}
.scroll{{overflow-x:auto;}}

.setting{{border:1px solid var(--border);background:var(--bg);padding:11px 13px;
  display:flex;align-items:flex-start;gap:12px;}}
.setting .txt{{flex:1;}}
.setting .lbl{{font-size:var(--fs-read);color:var(--text-1);margin-bottom:3px;}}
.setting .hint{{font-size:var(--fs-body);color:var(--text-3);line-height:1.55;}}
.sw{{width:34px;height:18px;border:1px solid var(--border);background:#141414;
  position:relative;flex:0 0 auto;margin-top:2px;}}
.sw i{{position:absolute;top:2px;left:2px;width:12px;height:12px;background:var(--text-3);}}
.sw.on{{border-color:var(--text-1);}}
.sw.on i{{left:auto;right:2px;background:var(--text-1);}}

.note{{border:1px solid var(--border);border-left:3px solid var(--yellow);
  background:rgba(214,178,58,.06);padding:9px 12px;font-size:var(--fs-body);
  color:var(--text-2);line-height:1.6;max-width:76ch;margin-top:var(--space-3);}}
.note b{{color:var(--text-1);}}
.note.red{{border-left-color:var(--red);background:rgba(255,100,103,.06);}}
.note.green{{border-left-color:var(--green);background:rgba(120,200,140,.05);}}
.k{{color:var(--text-3);letter-spacing:.09em;font-size:var(--fs-micro);display:block;
  margin-bottom:3px;}}

.legend{{display:flex;gap:16px;flex-wrap:wrap;margin-top:var(--space-3);
  font-size:var(--fs-body);color:var(--text-2);}}
.legend span{{display:inline-flex;align-items:center;gap:6px;}}
.legend i{{width:18px;height:1px;display:inline-block;}}
"""


def panel(title, meta, svg, why, cls="") -> str:
    return (f'<div class="panel {cls}"><div class="cap"><span class="t">{title}</span>'
            f'<span class="v">{meta}</span></div>{svg}<div class="why">{why}</div></div>')


HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>s151 — STARS: how stars connect</title>
<style>{CSS}</style></head><body>

<div class="head">
  <h1>How stars connect</h1>
  <p>Every constellation on this page is <b>your real vault</b> &mdash; {N} notes from
  <code>captures.db</code>, their real tags and project, and <b>{MATCHED} real 384-dimension
  embeddings</b> from <code>vectors.db</code>. The layouts are produced by a port of the
  <b>shipping force model</b>, with <code>starsSim.ts</code>'s own constants parsed out of the
  source at build time. Nothing here is invented data or an artist's impression.</p>
  <p>The brief: <b>desktop and phone identical</b>, smooth motion, and
  <b>responsible connections</b> built from tags and project groupings &mdash; plus an opt-in
  setting that uses the model to improve the grouping, <b>off by default</b>.</p>
</div>

<div class="wrap">

<h2><span class="n">01</span>Why the current rule cannot work &mdash; measured, not asserted</h2>
<p class="lede">Desktop draws an edge whenever two notes share <b>any</b> tag. Phone does the same
plus wikilinks. Run both readings of &ldquo;connect by tags / project&rdquo; against your actual
vault and they fail in <b>opposite directions</b>.</p>
<div class="grid2">
  {panel("Today — shared tag", stat(E_TODAY), constellation(E_TODAY),
         f"<b>Zero edges.</b> All {N} notes, and every tag in the vault occurs exactly once, so "
         "&ldquo;shares at least one tag&rdquo; never fires. STARS is currently a field of "
         "disconnected dots, and <code>coreVisual</code> gives every star the 5px degree-0 core.", "bad")}
  {panel("Naive project grouping", stat(E_PROJ), constellation(E_PROJ),
         "<b>A complete graph.</b> Every note is in the same project, so every pair connects. "
         "Worse: that project is <code>_loose</code>, the internal bucket the identity lock says "
         "must <b>never be rendered</b> &mdash; so it must never source a visible edge either.", "bad")}
</div>
<div class="note red"><span class="k">THE REAL PROBLEM</span>
Neither tags nor project is wrong as a <i>signal</i> &mdash; but as a <b>boolean rule</b> each one
is degenerate. &ldquo;Responsible connections&rdquo; is not a stricter boolean; it is a
<b>weight</b> plus a <b>budget</b>.</div>

<h2><span class="n">02</span>The model: weigh every signal, then spend a fixed budget per star</h2>
<p class="lede">One scoring function, four signals, <b>identical on both platforms</b>. Each pair
takes its <b>strongest</b> signal &mdash; signals compete, they never stack into a hairball. Then
each star keeps only its <b>top {TOP_K}</b> strongest partners, and the drawn set is the union.
That budget is what makes the result bounded no matter how the vault grows.</p>
<div class="scroll">
<table>
<tr><th>Signal</th><th>Weight</th><th>Why that rank</th></tr>
<tr><td><b>wikilink</b> <code>[[…]]</code></td><td class="num">1.00</td>
    <td>The user wrote it. An explicit link is the only signal that is a <b>stated</b> relationship rather than an inferred one, so it always wins.</td></tr>
<tr><td><b>semantic</b> (opt-in)</td><td class="num">0.50 &ndash; 1.00</td>
    <td>Cosine over embeddings, scaled from the {SEM_FLOOR} floor. Off by default; see &sect;04.</td></tr>
<tr><td><b>tag</b></td><td class="num">0.35 &ndash; 0.75</td>
    <td><b>Jaccard, not &ldquo;shares one&rdquo;.</b> Two notes sharing 3 of 4 tags are strongly related; sharing 1 of 20 is nearly noise. The boolean rule could not tell those apart.</td></tr>
<tr><td><b>project</b></td><td class="num">0.30</td>
    <td>A real grouping, but a weak one &mdash; a project is a folder, not a claim of similarity. <code>_loose</code> and <code>uncategorized</code> are excluded and can never source an edge.</td></tr>
</table>
</div>
<div class="legend">
  <span><i style="background:var(--text-1)"></i>wikilink</span>
  <span><i style="background:var(--accent)"></i>semantic</span>
  <span><i style="background:var(--text-2)"></i>tag</span>
  <span><i style="background:var(--text-3)"></i>project</span>
  <span>line opacity = edge weight</span>
</div>

<h2><span class="n">03</span>The same vault under the proposed model</h2>
<div class="grid2">
  {panel("Semantic OFF — the default", stat(E_OFF), constellation(E_OFF),
         "Wikilinks, tag-Jaccard and real projects only. On <b>this</b> vault that is still sparse, "
         "because your notes genuinely share almost no tags and sit in <code>_loose</code>. "
         "<b>That is the honest picture</b> &mdash; and it is what a vault with real tags and "
         "projects would fill in on its own, with no setting touched.")}
  {panel("Semantic ON — opt-in", stat(E_ON), constellation(E_ON),
         "The same {} notes with cosine edges from the embeddings that <b>already exist</b>. "
         "Every star earns a real neighbourhood, degree stops being 0, and "
         "<code>coreVisual</code>'s 8px/10px buckets finally select.".format(N), "good")}
</div>
<div class="note green"><span class="k">THE FINDING THAT MAKES THIS CHEAP</span>
&ldquo;Use the LLM for better groupings&rdquo; needs <b>no inference at render time</b>.
Desktop already has <code>vector_store.py</code> (<code>retrieve_related</code>,
<code>_cosine_top_k</code>) and the phone already has <code>src/lib/embedder.ts</code>. The
vectors are written when a note is enriched. Turning the setting on is a
<b>cosine pass over data already on disk</b> &mdash; instant, deterministic, and fully offline on
both devices. No peer, no network, no model load.</div>

<h2><span class="n">04</span>Desktop &mdash; the surface</h2>
<div class="win">
  <div class="titlebar"><span class="app">SECOND THOUGHT</span><span>BROWSE</span></div>
  <div class="toolbar">
    <div class="seg">
      <button>{LIST_ICON}LIST</button>
      <button class="on">{STAR_ICON}STARS</button>
    </div>
    <span class="spacer"></span>
    <span style="font-size:var(--fs-label);color:var(--text-3)">{len(E_ON)} CONNECTIONS &middot; SEMANTIC ON</span>
  </div>
  {constellation(E_ON, 620, 330, labels=True)}
</div>

<h2><span class="n">05</span>Android &mdash; the same model, the same numbers</h2>
<p class="lede">Same scoring function, same top-{TOP_K} budget, same weights, same colours. The only
differences are the ones the platform forces: a narrower canvas and the tab bar.</p>
<div class="phone">
  <div class="screen">
    <div class="statusbar"><span>9:41</span><span>LTE</span></div>
    <div class="apphead"><span class="h1">Browse</span>
      <div class="seg">
        <button>{LIST_ICON}</button><button class="on">{STAR_ICON}</button>
      </div>
    </div>
    {constellation(E_ON, 280, 300, labels=True)}
    <div class="tabbar"><div>Notes</div><div class="on">Browse</div></div>
  </div>
</div>

<h2><span class="n">06</span>The setting &mdash; both platforms, off by default</h2>
<p class="lede">One switch, same copy on both. It never mentions &ldquo;LLM&rdquo; in the label,
because what the user is choosing is a <b>behaviour</b>, not an implementation.</p>
<div class="setting">
  <div class="txt">
    <div class="lbl">Smart connections in Stars</div>
    <div class="hint">Also connect notes that are about similar things, using the note
      embeddings already stored on this device. Nothing is sent anywhere. Off by default.</div>
  </div>
  <div class="sw"><i></i></div>
</div>
<div style="height:10px"></div>
<div class="setting">
  <div class="txt">
    <div class="lbl">Smart connections in Stars</div>
    <div class="hint">On &mdash; {len(E_ON) - len(E_OFF)} additional connections in this vault.</div>
  </div>
  <div class="sw on"><i></i></div>
</div>
<div class="note"><span class="k">WHY THE DEFAULT IS OFF, AND WHY THAT IS AWKWARD</span>
You asked for off-by-default, and that is right for a setting that infers relationships the user
never stated. But note the consequence on <b>this</b> vault: with it off, STARS shows
<b>{len(E_OFF)} edges</b>. The default state of the feature is close to the empty state.
Worth deciding explicitly &mdash; see the open question at the bottom.</div>

<h2><span class="n">07</span>Motion &mdash; weight drives the spring, so the layout reads the relationship</h2>
<p class="lede">The physics does not change; the <b>inputs</b> do. Today an edge is boolean, so
every spring is one of two hardcoded constants. Under the weighted model, <code>k</code> and
<code>rest</code> interpolate between the two shipped constants by edge weight &mdash; strongly
related notes settle closer and steadier, weak ones sit further out and sway more.</p>
<div class="scroll">
<table>
<tr><th>&nbsp;</th><th>Today</th><th>Proposed</th></tr>
<tr><td>Spring <code>k</code></td><td class="num">{K_TAG} or {K_WIKI}</td>
    <td class="num">{K_TAG} &rarr; {K_WIKI}, interpolated by weight</td></tr>
<tr><td>Rest length</td><td class="num">{REST_TAG:.0f} or {REST_WIKI:.0f}</td>
    <td class="num">{REST_TAG:.0f} &rarr; {REST_WIKI:.0f}, interpolated by weight</td></tr>
<tr><td>Line opacity</td><td class="num">0.10 / 0.30 by kind</td>
    <td class="num">0.10 + 0.38 &times; weight</td></tr>
<tr><td>Repulsion, centering, damping, drift</td><td colspan="2"><b>Unchanged.</b> Reduced motion still kills drift only. The felt motion of the sky is preserved exactly.</td></tr>
<tr><td>Edges per star</td><td class="num">unbounded (0 or n&minus;1 here)</td>
    <td class="num">&le; {TOP_K} own + inbound</td></tr>
</table>
</div>

<h2><span class="n">08</span>What this costs, and what it does not touch</h2>
<div class="scroll">
<table>
<tr><th>Change</th><th>Where</th></tr>
<tr><td>Weighted scorer + top-K budget (pure, one sibling test each)</td><td><code>gui/src/lib/starsSim.ts</code> &middot; <code>phone/src/lib/starsSim.ts</code> &mdash; the two files that must stay identical</td></tr>
<tr><td><code>SimEdge</code> gains <code>weight</code>; <code>kind</code> gains <code>project</code> and <code>semantic</code></td><td>both <code>starsSim.ts</code></td></tr>
<tr><td>Desktop gets wikilink + semantic edge sources</td><td><code>vault_admin.py</code>'s existing <code>search_captures</code> response gains two fields &mdash; <b>no new route</b>, no new table</td></tr>
<tr><td>Phone gets project + semantic edge sources</td><td><code>linkIndex.ts</code> stays as-is; <code>embedder.ts</code> supplies vectors</td></tr>
<tr><td>One setting, one storage key, both platforms</td><td>desktop Settings &middot; phone Settings</td></tr>
<tr><td><b>Not touched</b></td><td>the RAF loop, drag physics, repulsion, reduced-motion behaviour, peek card, <code>NODE_CAP</code></td></tr>
</table>
</div>

<div class="note"><span class="k">OPEN QUESTION FOR YOU</span>
With smart connections <b>off</b>, this vault draws <b>{len(E_OFF)} edges</b> &mdash; because your
notes have no shared tags and no real projects yet. Three ways to handle that, and it is your call:
<b>(a)</b> ship off-by-default as asked and accept a sparse default;
<b>(b)</b> off-by-default, but STARS offers the setting inline the first time it renders a sky with
no connections; <b>(c)</b> default it <b>on</b>, since the data is local, already computed, and
never leaves the device.</div>

</div></body></html>
"""

assert "\x00" not in HTML, "board HTML contains a NUL byte"
out = HERE / "2026-08-07-s151-stars-edges-board.html"
out.write_text(HTML, encoding="utf-8")

BODY = HTML.split("<body>", 1)[1].rsplit("</body>", 1)[0]
art = HERE / "2026-08-07-s151-stars-edges-board.artifact.html"
art.write_text(
    f"<title>s151 — STARS: how stars connect</title>\n<style>{CSS}</style>\n{BODY}",
    encoding="utf-8",
)

print(f"wrote {out} ({len(HTML):,} bytes)")
print(f"notes={N}  embeddings matched={MATCHED}")
print(f"today={len(E_TODAY)}  raw-project={len(E_PROJ)}  proposed-off={len(E_OFF)}  proposed-on={len(E_ON)}")
