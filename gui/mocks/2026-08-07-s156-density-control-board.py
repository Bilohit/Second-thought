#!/usr/bin/env python3
"""s156 — the DENSITY CONTROL decision board.

D1 was already ruled (hybrid floor: `max(absolute_safety, pNN)`) and D2 was ruled
(a collapsible SKY panel). This board decides ONE thing the s155 board did not:
what the 5-step density control physically LOOKS like inside that panel.

Everything visual here is re-derived from source rather than transcribed, so the
board cannot drift from the app it argues about:
  - the Void palette + the type scale are parsed out of `gui/src/index.css` and
    asserted against `gui/src/lib/type.ts`;
  - the three IBM Plex Mono faces are lifted verbatim out of `SecondThoughtV2.html`
    (the Artifact CSP blocks font CDNs, so they must be inlined);
  - the star field is the app's own deterministic `hashPosition` hash, and the
    edge count printed under each control is the real shipped number (39).

Run:  python "Second Thought/gui/mocks/2026-08-07-s156-density-control-board.py"
Writes the board next to this file unless --out is given.
"""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUI = HERE.parent
ROOT = GUI.parent.parent  # workspace root
INDEX_CSS = GUI / "src" / "index.css"
TYPE_TS = GUI / "src" / "lib" / "type.ts"
STARS_SIM = GUI / "src" / "lib" / "starsSim.ts"
V2 = ROOT / "SecondThoughtV2.html"


# ── source-derived values ────────────────────────────────────────────────────────────────────────
def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def font_faces() -> str:
    """The three embedded IBM Plex Mono faces, verbatim. Identity lock: the mock must not
    silently fall back to a system mono, which is exactly what a CDN link would do here."""
    blocks = re.findall(r"@font-face\s*\{.*?\}", read(V2), re.S)
    faces = [b for b in blocks if "IBM Plex Mono" in b]
    assert len(faces) == 3, f"expected 3 IBM Plex Mono faces in SecondThoughtV2.html, found {len(faces)}"
    return "\n".join(faces)


def dark_tokens() -> dict[str, str]:
    """The dark theme's own block from index.css. This board previews an app surface, so it
    commits to the app's dark ground deliberately rather than restyling it for a doc."""
    css = read(INDEX_CSS)
    # The dark block is the one that defines --bg: #0a0a0a.
    idx = css.index("--bg:           #0a0a0a")
    start = css.rindex("{", 0, idx)
    end = css.index("}", idx)
    block = css[start:end]
    out = {}
    for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", block):
        out[name] = value.strip()
    for required in ("--bg", "--surface", "--surface-2", "--border", "--text-1", "--text-2", "--text-3", "--glass-bg"):
        assert required in out, f"{required} missing from index.css dark block"
    return out


def type_scale() -> dict[str, int]:
    """`--fs-*` out of index.css, asserted equal to lib/type.ts's named exports. The two must
    agree numerically (type.test.ts already pins this in-repo); asserting it here means a board
    can never argue with a font size the app does not actually ship."""
    css_scale = {k: int(v) for k, v in re.findall(r"--fs-(\w+):\s*(\d+)px;", read(INDEX_CSS))}
    ts_scale = {k: int(v) for k, v in re.findall(r"export const (\w+) = (\d+);", read(TYPE_TS))}
    for name, px in ts_scale.items():
        assert css_scale.get(name) == px, f"type scale drift: type.ts {name}={px}, index.css --fs-{name}={css_scale.get(name)}"
    assert not any(k in css_scale for k in ("7", "8")), "half-steps are banned"
    return css_scale


def shipped_top_k() -> int:
    m = re.search(r"export const EDGE_TOP_K = (\d+);", read(STARS_SIM))
    assert m, "EDGE_TOP_K not found in starsSim.ts"
    return int(m.group(1))


def shipped_floor() -> float:
    m = re.search(r"export const SEMANTIC_FLOOR = ([\d.]+);", read(STARS_SIM))
    assert m, "SEMANTIC_FLOOR not found in starsSim.ts"
    return float(m.group(1))


# ── the backdrop: the app's own deterministic star hash ──────────────────────────────────────────
def hash_position(i: int, w: float, h: float) -> tuple[float, float]:
    """starsSim.ts `hashPosition`, transcribed. JS `%` keeps the sign of the dividend, and so
    does Python's `math.fmod` — `%` alone would produce a different field."""
    fx = (math.fmod(math.sin(i * 12.9898) * 43758.5453, 1) + 1) % 1
    fy = (math.fmod(math.sin(i * 78.233) * 12543.123, 1) + 1) % 1
    return w * (0.14 + 0.72 * fx), h * (0.12 + 0.7 * fy)


def sky_backdrop(w: int, h: int, n: int = 22) -> str:
    """A quiet, honest star field behind each panel — same hash, same twinkle phase formula."""
    pts = [hash_position(i, w, h) for i in range(n)]
    edges = []
    for i in range(n):
        # deterministic, sparse: each star wires to the nearest star with a higher index
        best, bd = None, 1e9
        for j in range(i + 1, n):
            d = (pts[i][0] - pts[j][0]) ** 2 + (pts[i][1] - pts[j][1]) ** 2
            if d < bd:
                bd, best = d, j
        if best is not None and bd < 9000:
            edges.append((i, best))
    parts = [f'<svg class="fld" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">']
    for a, b in edges:
        parts.append(
            f'<line x1="{pts[a][0]:.1f}" y1="{pts[a][1]:.1f}" x2="{pts[b][0]:.1f}" y2="{pts[b][1]:.1f}" '
            f'stroke="var(--text-1)" stroke-opacity="0.16" stroke-width="1" stroke-dasharray="3 5"/>'
        )
    for i, (x, y) in enumerate(pts):
        r = 2.5 if i % 5 else 3.5
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="var(--text-1)" opacity="0.75">'
            f'<animate attributeName="opacity" values="0.75;0.35;0.75" dur="3.4s" '
            f'begin="{abs(math.sin(i * 7.13)) * 1.7:.2f}s" repeatCount="indefinite"/></circle>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ── the five density steps the control has to express ────────────────────────────────────────────
STEPS = [
    ("Minimal", 92, 1, 15),
    ("Sparse", 88, 2, 28),
    ("Balanced", 83, 3, 39),
    ("Dense", 78, 4, 50),
    ("Maximal", 70, 5, 62),
]
ACTIVE = 2  # Balanced — the default, and the step that reproduces today's shipped sky


CHEVRON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')
MINUS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
         'stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/></svg>')
PLUS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
        'stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>')


def toggle(on: bool = True) -> str:
    return f'<span class="tg {"on" if on else ""}" aria-hidden="true"><i></i></span>'


def panel(control_html: str, *, control_label: str = "DENSITY") -> str:
    """The SKY panel itself — identical in every option so only the control differs. Open state,
    since D2 ruled a collapsible panel that is open on first visit."""
    name, p, k, edges = STEPS[ACTIVE]
    return f"""
<div class="panel">
  <div class="phead"><span class="ptitle">SKY</span><span class="chev">{CHEVRON}</span></div>
  <div class="pbody">
    <div class="grp">
      <div class="glab">{control_label}</div>
      {control_html}
      <div class="ghint">{name} &middot; {edges} connections</div>
    </div>
    <div class="row">
      {toggle(True)}<span class="rlab">Smart connections</span>
    </div>
    <div class="grp">
      <div class="glab">ZOOM</div>
      <div class="zrow">
        <button class="zbtn" type="button" aria-label="Zoom out">{MINUS}</button>
        <span class="zval">100%</span>
        <button class="zbtn" type="button" aria-label="Zoom in">{PLUS}</button>
        <button class="zreset" type="button">RESET</button>
      </div>
    </div>
  </div>
</div>"""


# ── the four candidate controls ──────────────────────────────────────────────────────────────────
def ctl_segmented() -> str:
    cells = "".join(
        f'<button type="button" class="sgc{" on" if i == ACTIVE else ""}" '
        f'aria-pressed="{"true" if i == ACTIVE else "false"}">{"&#9632;" if i == ACTIVE else ""}'
        f'<span class="sr">{n}</span></button>'
        for i, (n, _, _, _) in enumerate(STEPS)
    )
    return f'<div class="sgw" role="group" aria-label="Connection density">{cells}</div>'


def ctl_rail() -> str:
    ticks = "".join(
        f'<span class="tk{" on" if i <= ACTIVE else ""}" style="left:{i * 25}%"></span>'
        for i in range(len(STEPS))
    )
    return (f'<div class="rail" role="slider" tabindex="0" aria-valuemin="1" aria-valuemax="5" '
            f'aria-valuenow="{ACTIVE + 1}" aria-label="Connection density">'
            f'<span class="rtrack"></span><span class="rfill" style="width:{ACTIVE * 25}%"></span>'
            f'{ticks}<span class="thumb" style="left:{ACTIVE * 25}%"></span></div>')


def ctl_native() -> str:
    return (f'<input class="rng" type="range" min="1" max="5" step="1" value="{ACTIVE + 1}" '
            f'aria-label="Connection density">')


def ctl_stepper() -> str:
    return (f'<div class="stp">'
            f'<button class="sbtn" type="button" aria-label="Fewer connections">{MINUS}</button>'
            f'<span class="sval">{ACTIVE + 1} / 5</span>'
            f'<button class="sbtn" type="button" aria-label="More connections">{PLUS}</button>'
            f'</div>')


def ctl_none() -> str:
    return '<div class="nonectl">no density control &mdash; fixed floor, fixed budget</div>'


OPTIONS = [
    (
        "NOW", "No control at all",
        ctl_none,
        "What ships today. The floor is the constant <code>0.62</code> and the budget is a constant "
        "<code>3</code>. Nothing about the sky's density is reachable by the user &mdash; which is the "
        "gap this whole workstream exists to close.",
        [("RN cost", "none"), ("Keyboard", "n/a"), ("Reads the range", "no")],
        False,
    ),
    (
        "A", "Segmented, five cells",
        ctl_segmented,
        "Five sharp cells, the active one filled. The range is visible without touching it, and the "
        "0-radius bordered row is the shape this app already uses everywhere else. On RN it is five "
        "<code>Pressable</code>s &mdash; no dependency, no gesture handling, no custom track.",
        [("RN cost", "5 Pressables"), ("Keyboard", "Tab + Enter, free"), ("Reads the range", "yes, at rest")],
        True,
    ),
    (
        "B", "Tick rail with a square thumb",
        ctl_rail,
        "A slider's affordance, hand-built from a rail, five ticks and a square thumb &mdash; so it "
        "keeps the 0-radius identity a native range control fights. Costs a real drag gesture on both "
        "platforms and a hand-rolled <code>role=\"slider\"</code> keyboard contract.",
        [("RN cost", "PanResponder + layout math"), ("Keyboard", "hand-rolled arrow keys"), ("Reads the range", "yes, at rest")],
        False,
    ),
    (
        "C", "Native range input",
        ctl_native,
        "One familiar control, free keyboard and screen-reader behaviour on desktop. But the thumb and "
        "track are round by default and need heavy overrides to stop looking like a browser default "
        "&mdash; and RN has no range input, so the phone half means adding "
        "<code>@react-native-community/slider</code>. That is a stack change, which needs approval.",
        [("RN cost", "NEW DEPENDENCY"), ("Keyboard", "free on desktop only"), ("Reads the range", "partly &mdash; no step labels")],
        False,
    ),
    (
        "D", "Stepper",
        ctl_stepper,
        "The smallest footprint in the panel, and trivially identical on both platforms. But it hides "
        "the range: at rest you cannot see that there are five steps or where you sit among them, so "
        "every adjustment is a guess followed by a look at the sky.",
        [("RN cost", "2 Pressables"), ("Keyboard", "Tab + Enter, free"), ("Reads the range", "no")],
        False,
    ),
]


def option_card(tag: str, title: str, ctl, prose: str, facts, recommended: bool) -> str:
    rows = "".join(f'<div class="fk">{k}</div><div class="fv">{v}</div>' for k, v in facts)
    rec = '<span class="rec">RECOMMENDED</span>' if recommended else ""
    return f"""
<article class="opt{' isrec' if recommended else ''}">
  <header class="ohead">
    <span class="otag">{tag}</span><h3 class="otitle">{title}</h3>{rec}
  </header>
  <div class="stage">
    {sky_backdrop(320, 210)}
    <div class="stagepanel">{panel(ctl())}</div>
    <span class="stagenote">actual size</span>
  </div>
  <div class="detail">
    <div class="dzoom">{ctl()}</div>
    <span class="stagenote">2&times;</span>
  </div>
  <p class="oprose">{prose}</p>
  <div class="facts">{rows}</div>
</article>"""


def build() -> str:
    tok = dark_tokens()
    fs = type_scale()
    faces = font_faces()
    k = shipped_top_k()
    floor = shipped_floor()
    tokens_css = "\n    ".join(f"{n}: {v};" for n, v in tok.items())
    cards = "".join(option_card(*o) for o in OPTIONS)
    steps_rows = "".join(
        f"<tr{' class=\"now\"' if i == ACTIVE else ''}><td>{i + 1}</td><td>{n}</td><td>p{p}</td>"
        f"<td>{tk}</td><td>{e}</td></tr>"
        for i, (n, p, tk, e) in enumerate(STEPS)
    )

    return f"""<title>SKY density control &mdash; s156 decision board</title>
<style>
{faces}

:root {{
    {tokens_css}
  --mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", "Segoe UI Mono", monospace;
  --track: 0.01em;
  --fs-micro: {fs['micro']}px; --fs-label: {fs['label']}px; --fs-body: {fs['body']}px;
  --fs-read: {fs['read']}px;  --fs-lead: {fs['lead']}px;   --fs-title: {fs['title']}px;
  --fs-display: {fs['display']}px; --fs-hero: {fs['hero']}px;
  --z-panel: 3; --z-note: 4;
}}

/* This board previews a dark app surface. Restyling it for a light viewer would misrepresent the
   exact thing being decided, so it commits to the product's own dark ground in both themes. */
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text-2);
  font-family: var(--mono); font-size: var(--fs-body); letter-spacing: var(--track);
  line-height: 1.65; -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 40px 24px 72px; }}

header.top {{ border-bottom: 1px solid var(--border); padding-bottom: 22px; margin-bottom: 30px; }}
.kicker {{ font-size: var(--fs-micro); color: var(--text-3); text-transform: uppercase; letter-spacing: 0.14em; }}
h1 {{ font-size: var(--fs-display); font-weight: 600; color: var(--text-1); margin: 10px 0 0;
     letter-spacing: var(--track); text-wrap: balance; }}
.lede {{ margin: 12px 0 0; max-width: 68ch; font-size: var(--fs-read); }}
.lede b {{ color: var(--text-1); font-weight: 500; }}
code {{ font-family: var(--mono); color: var(--text-1); background: var(--surface);
        border: 1px solid var(--border-2); padding: 0 4px; font-size: 0.94em; }}

section.ctx {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 340px); gap: 34px;
               align-items: start; margin-bottom: 40px; }}
@media (max-width: 900px) {{ section.ctx {{ grid-template-columns: minmax(0, 1fr); }} }}
h2 {{ font-size: var(--fs-lead); font-weight: 600; color: var(--text-1); margin: 0 0 10px;
      letter-spacing: 0.06em; text-transform: uppercase; }}
.ctx p {{ margin: 0 0 10px; font-size: var(--fs-read); max-width: 66ch; }}

table {{ border-collapse: collapse; width: 100%; font-size: var(--fs-label);
         font-variant-numeric: tabular-nums; }}
th, td {{ border: 1px solid var(--border); padding: 5px 9px; text-align: left; }}
th {{ color: var(--text-3); font-weight: 400; text-transform: uppercase; font-size: var(--fs-micro);
      letter-spacing: 0.1em; }}
td {{ color: var(--text-2); }}
tr.now td {{ color: var(--text-1); background: var(--surface); }}
.tcap {{ font-size: var(--fs-micro); color: var(--text-3); margin-top: 8px; }}

.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 20px; }}
.opt {{ border: 1px solid var(--border); background: var(--glass-bg); display: flex;
        flex-direction: column; }}
.opt.isrec {{ border-color: var(--text-3); }}
.ohead {{ display: flex; align-items: baseline; gap: 10px; padding: 12px 14px;
          border-bottom: 1px solid var(--border); }}
.otag {{ font-size: var(--fs-micro); color: var(--text-3); border: 1px solid var(--border);
         padding: 1px 6px; letter-spacing: 0.12em; }}
.otitle {{ margin: 0; font-size: var(--fs-read); font-weight: 600; color: var(--text-1); }}
.rec {{ margin-left: auto; font-size: var(--fs-micro); color: var(--text-1);
        border: 1px solid var(--text-3); padding: 1px 6px; letter-spacing: 0.1em; }}

.stage {{ position: relative; height: 210px; background:
  radial-gradient(500px 320px at 30% 20%, color-mix(in srgb, var(--surface) 35%, transparent), transparent 70%),
  radial-gradient(600px 400px at 75% 80%, color-mix(in srgb, var(--surface) 28%, transparent), transparent 70%),
  var(--bg); overflow: hidden; border-bottom: 1px solid var(--border); }}
.fld {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.stagepanel {{ position: absolute; top: 10px; right: 12px; z-index: var(--z-panel); }}
.stagenote {{ position: absolute; left: 10px; bottom: 8px; font-size: var(--fs-micro);
              color: var(--text-3); z-index: var(--z-note); }}
.detail {{ position: relative; padding: 26px 14px 22px; border-bottom: 1px solid var(--border);
           background: var(--bg); display: flex; justify-content: center; }}
.dzoom {{ transform: scale(2); transform-origin: center; width: 186px; }}

/* ── the SKY panel (identical in every option) ── */
.panel {{ width: 186px; background: var(--glass-bg); border: 1px solid var(--border); }}
.phead {{ display: flex; align-items: center; justify-content: space-between;
          padding: 6px 8px; border-bottom: 1px solid var(--border); }}
.ptitle {{ font-size: var(--fs-micro); color: var(--text-2); letter-spacing: 0.14em; }}
.chev {{ width: 12px; height: 12px; color: var(--text-3); display: block; }}
.chev svg {{ width: 12px; height: 12px; display: block; }}
.pbody {{ padding: 8px; display: flex; flex-direction: column; gap: 10px; }}
.glab {{ font-size: var(--fs-micro); color: var(--text-3); letter-spacing: 0.12em; margin-bottom: 5px; }}
.ghint {{ font-size: var(--fs-micro); color: var(--text-2); margin-top: 5px; }}
.row {{ display: flex; align-items: center; gap: 7px; }}
.rlab {{ font-size: var(--fs-label); color: var(--text-3); }}
.tg {{ width: 20px; height: 11px; border: 1px solid var(--border); background: var(--bg);
       position: relative; display: inline-block; flex: none; }}
.tg i {{ position: absolute; top: 1px; left: 1px; width: 7px; height: 7px; background: var(--text-3); }}
.tg.on {{ border-color: var(--text-3); }}
.tg.on i {{ left: auto; right: 1px; background: var(--text-1); }}
.zrow {{ display: flex; align-items: center; gap: 5px; }}
.zbtn {{ width: 20px; height: 18px; border: 1px solid var(--border); background: var(--surface);
         color: var(--text-2); display: grid; place-items: center; cursor: pointer; padding: 0; }}
.zbtn svg {{ width: 11px; height: 11px; }}
.zval {{ font-size: var(--fs-micro); color: var(--text-2); min-width: 30px; text-align: center;
         font-variant-numeric: tabular-nums; }}
.zreset {{ margin-left: auto; font-family: var(--mono); font-size: var(--fs-micro); color: var(--text-3);
           background: none; border: 1px solid var(--border); padding: 2px 5px; cursor: pointer;
           letter-spacing: 0.1em; }}
.zbtn:hover, .zreset:hover {{ border-color: var(--text-3); color: var(--text-1); }}
.zbtn:focus-visible, .zreset:focus-visible {{ outline: 1px solid var(--text-1); outline-offset: 1px; }}

/* ── candidate controls ── */
.sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }}
.sgw {{ display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid var(--border); }}
.sgc {{ height: 16px; background: var(--bg); border: none; border-right: 1px solid var(--border);
        color: var(--text-1); font-size: 6px; line-height: 1; cursor: pointer; padding: 0;
        position: relative; }}
.sgc:last-child {{ border-right: none; }}
.sgc.on {{ background: var(--surface-2); }}
.sgc:hover {{ background: var(--surface); }}
.sgc:focus-visible {{ outline: 1px solid var(--text-1); outline-offset: -1px; }}

.rail {{ position: relative; height: 16px; cursor: pointer; }}
.rtrack {{ position: absolute; top: 7px; left: 0; right: 0; height: 1px; background: var(--border); }}
.rfill {{ position: absolute; top: 7px; left: 0; height: 1px; background: var(--text-3); }}
.tk {{ position: absolute; top: 4px; width: 1px; height: 7px; background: var(--border);
       transform: translateX(-50%); }}
.tk.on {{ background: var(--text-3); }}
.thumb {{ position: absolute; top: 2px; width: 7px; height: 11px; background: var(--text-1);
          transform: translateX(-50%); }}
.rail:focus-visible {{ outline: 1px solid var(--text-1); outline-offset: 2px; }}

.rng {{ width: 100%; accent-color: #fafafa; height: 16px; }}

.stp {{ display: flex; align-items: center; gap: 6px; }}
.sbtn {{ width: 22px; height: 16px; border: 1px solid var(--border); background: var(--surface);
         color: var(--text-2); display: grid; place-items: center; cursor: pointer; padding: 0; }}
.sbtn svg {{ width: 10px; height: 10px; }}
.sbtn:hover {{ border-color: var(--text-3); color: var(--text-1); }}
.sval {{ font-size: var(--fs-label); color: var(--text-1); font-variant-numeric: tabular-nums; }}

.nonectl {{ font-size: var(--fs-micro); color: var(--text-3); border: 1px dashed var(--border);
            padding: 4px 6px; }}

.oprose {{ margin: 0; padding: 13px 14px; font-size: var(--fs-label); color: var(--text-2);
           border-bottom: 1px solid var(--border); }}
.facts {{ display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; padding: 11px 14px;
          font-size: var(--fs-micro); }}
.fk {{ color: var(--text-3); letter-spacing: 0.08em; text-transform: uppercase; }}
.fv {{ color: var(--text-2); }}

footer {{ margin-top: 40px; border-top: 1px solid var(--border); padding-top: 18px;
          font-size: var(--fs-label); color: var(--text-3); }}
footer b {{ color: var(--text-1); font-weight: 500; }}

@media (prefers-reduced-motion: reduce) {{ animate {{ display: none; }} }}
</style>

<div class="wrap">
<header class="top">
  <div class="kicker">Second Thought &middot; s156 &middot; STARS</div>
  <h1>What shape is the density control?</h1>
  <p class="lede">D1 and D2 are already ruled: the semantic floor becomes
  <b>max(absolute&nbsp;{floor}, p<i>NN</i>)</b>, and the controls live in a collapsible <b>SKY</b> panel
  that is open on first visit. This board decides only what the five-step density control physically
  looks like inside that panel &mdash; and it is a decision worth its own board because the control is
  <b>186px wide and set in {fs['micro']}&ndash;{fs['label']}px type</b>. At that size, shape is the only
  thing carrying meaning.</p>
</header>

<section class="ctx">
  <div>
    <h2>What the five steps actually do</h2>
    <p>One index moves two knobs: the percentile the semantic floor tracks, and the per-node edge
    budget. Step 3 is the default and reproduces the sky that ships today.</p>
    <p>The budget is why the control can be honest in both directions. On the real vault
    <b>74 pairs already clear the {floor} floor but only 39 are drawn</b> &mdash; today's budget of
    <code>{k}</code> prunes 35 real edges. Turning density up reveals edges that already passed the
    floor; it never invents one, because <code>max()</code> means the floor can rise above {floor} but
    never fall below it.</p>
  </div>
  <div>
    <table>
      <thead><tr><th>Step</th><th>Name</th><th>Floor</th><th>Budget</th><th>Edges</th></tr></thead>
      <tbody>{steps_rows}</tbody>
    </table>
    <p class="tcap">Edge counts are the real vault (30 notes, 435 pairs, real 384-d vectors).
    Step 3 = today's shipped sky.</p>
  </div>
</section>

<h2>The candidates, in the panel, at the size they ship</h2>
<div class="grid">
{cards}
</div>

<footer>
  <b>Everything here is re-derived from source.</b> Palette and type scale parsed from
  <code>gui/src/index.css</code> and asserted against <code>lib/type.ts</code>; the three IBM Plex Mono
  faces lifted from <code>SecondThoughtV2.html</code>; the star field is the app's own
  <code>hashPosition</code> hash; <code>EDGE_TOP_K</code> and <code>SEMANTIC_FLOOR</code> read out of
  <code>starsSim.ts</code>. Generator:
  <code>gui/mocks/2026-08-07-s156-density-control-board.py</code>.
</footer>
</div>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE / "2026-08-07-s156-density-control-board.html")
    args = ap.parse_args()
    args.out.write_text(build(), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
