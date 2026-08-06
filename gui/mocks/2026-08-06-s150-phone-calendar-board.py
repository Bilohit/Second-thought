"""Generate the s150 phone-calendar motion + design board.

v2 REWRITE (user decisions on the round-1 board):
  - Option A "Quiet Grid" WINS as the base.
  - Its selection mark becomes ONE TRAVELLING BOX, borrowing option C's
    indicator-travel motion but applied to A's inset 1px box.
  - The `+n` overflow badge is REJECTED: more than three dots shows a plain
    `+` icon, no number.
  - Three arrows on one screen is too many. The header Back arrow stays;
    the two month-nav arrows must go. Three arrow-free replacements are
    rendered live for the user to pick from.

Round 1's A/B/C comparison is retired — the decision is made. This board now
shows the decided design once, large, then isolates the single open question.

Follows 2026-08-07-s148-project-panel-board.py's convention: fonts and tokens
are RE-DERIVED from the repo at build time (V2 mock @font-face blocks, the
phone's own tokens.ts dark palette + type scale) instead of hand-copied, so the
board cannot drift from the shipping identity. Run:
  python 2026-08-06-s150-phone-calendar-board.py

Output is an artifact-shaped fragment (no doctype/html/head/body of its own) so
the same file both publishes via the Artifact tool and opens in a browser.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(r"c:\Users\biloh\Claude\Projects\Second Thought Full Codebase")
V2_MOCK = ROOT / "SecondThoughtV2.html"
TOKENS_TS = ROOT / "Second Thought - Android App" / "phone" / "src" / "lib" / "tokens.ts"
HERE = Path(__file__).parent
OUT = HERE / "2026-08-06-s150-phone-calendar-board.html"


# ── fonts: lifted verbatim from the approved V2 mock, not hand-copied ──────
def load_font_faces() -> str:
    html = V2_MOCK.read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"@font-face\s*\{[^}]*\}", html) if "IBM Plex Mono" in b]
    assert len(blocks) == 3, f"expected 3 IBM Plex Mono @font-face blocks, found {len(blocks)}"
    for b in blocks:
        assert "base64," in b, "font block has no embedded base64 payload"
    return "\n".join(blocks)


# ── tokens: parsed out of the phone's own tokens.ts, never re-typed ────────
def load_dark_palette() -> dict[str, str]:
    ts = TOKENS_TS.read_text(encoding="utf-8")
    m = re.search(r"export const THEMES[^{]*\{\s*dark:\s*\{(.*?)\n  \},", ts, re.S)
    assert m, "could not locate THEMES.dark in tokens.ts"
    pal = dict(re.findall(r'(\w+):\s*"([^"]+)"', m.group(1)))
    for required in ("bg", "surface", "surface2", "border", "border2", "text1", "text2",
                     "text3", "accentDim", "red", "green", "yellow"):
        assert required in pal, f"tokens.ts THEMES.dark is missing {required}"
    return pal


def load_type_scale() -> dict[str, int]:
    ts = TOKENS_TS.read_text(encoding="utf-8")
    m = re.search(r"scale:\s*\{(.*?)\}", ts, re.S)
    assert m, "could not locate font.scale in tokens.ts"
    scale = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))}
    assert scale.get("body") == 11 and scale.get("hero") == 22, f"unexpected scale {scale}"
    return scale


def load_space() -> dict[str, int]:
    ts = TOKENS_TS.read_text(encoding="utf-8")
    m = re.search(r"export const space = \{(.*?)\}", ts, re.S)
    assert m, "could not locate space in tokens.ts"
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))}


FONT_FACES = load_font_faces()
PAL = load_dark_palette()
SCALE = load_type_scale()
SPACE = load_space()

TOKEN_VARS = "\n".join(f"      --{k}: {v};" for k, v in PAL.items())
SCALE_VARS = "\n".join(f"      --fs-{k}: {v}px;" for k, v in SCALE.items())
SPACE_VARS = "\n".join(f"      --sp-{k}: {v}px;" for k, v in SPACE.items())


PAGE = r"""<title>Second Thought · phone calendar — the implementation contract (s150)</title>
<style>
__FONTS__

:root {
__TOKENS__
__SCALES__
__SPACES__
  /* motion vocabulary, verbatim from phone/src/components/motion.ts */
  --travel: cubic-bezier(0.22, 1, 0.36, 1);   /* TRAVEL  — entrances, indicator travel */
  --settle: cubic-bezier(0.16, 1, 0.3, 1);    /* SETTLE  — reveals, leave */
  --standard: 260ms;                           /* STANDARD */
  --micro: 160ms;                              /* MICRO */
  --stagger: 45ms;                             /* STAGGER */
  --press: 120ms;                              /* interaction-and-motion.md §2 press feedback */
  --boxdur: var(--micro);                      /* selection-box travel — MICRO by default, picker below */
  --mo: 1;                                     /* slow-mo multiplier, set by the toggle */
  --mono: "IBM Plex Mono", ui-monospace, monospace;
  --track: 0.01em;
}

/* The board renders one committed visual world — the app's own Void dark.
   A light theme here would misreport what the surface actually looks like. */
:root[data-theme="light"], :root[data-theme="dark"] { color-scheme: dark; }

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text2);
  font-family: var(--mono);
  letter-spacing: var(--track);
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 1180px; margin: 0 auto; padding: 40px 24px 96px; }

/* ── page chrome ─────────────────────────────────────────────────────── */
.kicker { font-size: 10px; letter-spacing: 2.4px; text-transform: uppercase; color: var(--text3); margin: 0 0 12px; }
h1 {
  font-family: var(--mono); font-weight: 600; color: var(--text1);
  font-size: clamp(24px, 3.4vw, 34px); line-height: 1.15; letter-spacing: -0.4px;
  margin: 0 0 14px; text-wrap: balance; max-width: 24ch;
}
.lede { color: var(--text2); max-width: 74ch; margin: 0 0 8px; }
.lede strong { color: var(--text1); font-weight: 500; }
h2 { font-family: var(--mono); font-weight: 600; color: var(--text1); font-size: 20px; letter-spacing: -0.2px; margin: 0 0 6px; }
h3 { font-family: var(--mono); font-weight: 600; color: var(--text1); font-size: 14px; margin: 26px 0 8px; }
p { margin: 0 0 12px; max-width: 74ch; }
code { font-family: var(--mono); font-size: 0.88em; color: var(--text1); background: var(--surface); padding: 1px 5px; border: 1px solid var(--border2); }
hr { border: 0; border-top: 1px solid var(--border); margin: 44px 0; }

section { margin: 0 0 8px; }
.sec-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin: 0 0 18px; }
.sec-head .tag { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--text3); border: 1px solid var(--border); padding: 3px 8px; }
.sec-head .tag.pick { color: var(--green); border-color: var(--green); }
.sec-head .tag.open { color: var(--yellow); border-color: var(--yellow); }
.sec-head .tag.rec { color: var(--text1); border-color: var(--text1); }

/* ── sticky control bar ──────────────────────────────────────────────── */
.controls {
  position: sticky; top: 0; z-index: 40;
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
  background: var(--bg); border-bottom: 1px solid var(--border);
  padding: 12px 0; margin: 0 0 34px;
}
.controls .lbl { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--text3); margin-right: 4px; }
.ctl {
  font-family: var(--mono); font-size: 12px; letter-spacing: var(--track);
  color: var(--text2); background: transparent;
  border: 1px solid var(--border); padding: 7px 12px; min-height: 34px;
  cursor: pointer; transition: background var(--micro) var(--settle), color var(--micro) var(--settle);
}
.ctl:hover { background: var(--surface); color: var(--text1); }
.ctl[aria-pressed="true"] { background: var(--text1); color: var(--bg); border-color: var(--text1); }
.ctl:focus-visible { outline: 2px solid var(--text1); outline-offset: 2px; }

/* ── layouts ─────────────────────────────────────────────────────────── */
.opt { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 40px; align-items: start; }
@media (max-width: 900px) { .opt { grid-template-columns: minmax(0, 1fr); gap: 26px; } }

.three { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 34px; align-items: start; }

.stage { display: flex; flex-direction: column; gap: 10px; }
.stage-cap { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--text3); }
.stage-cap b { color: var(--text1); font-weight: 500; letter-spacing: 2px; }

/* ── the phone ───────────────────────────────────────────────────────── */
.phone {
  width: 360px; max-width: 100%; height: 700px;
  border: 1px solid var(--border); background: var(--bg);
  display: flex; flex-direction: column; overflow: hidden;
  position: relative; user-select: none;
}
.phone.short { height: 560px; }
.phone * { font-family: var(--mono); letter-spacing: var(--track); }

.p-header { display: flex; align-items: center; gap: var(--sp-md); padding: var(--sp-md) var(--sp-lg); }
.p-h1 { flex: 1; color: var(--text1); font-weight: 600; font-size: var(--fs-hero); letter-spacing: -0.6px; }
.p-today {
  border: 1px solid var(--border); color: var(--text2); font-size: var(--fs-body);
  padding: 0 var(--sp-sm); min-height: 32px; display: flex; align-items: center;
  background: transparent; cursor: pointer;
}
.p-body { flex: 1; overflow-y: auto; padding: 0 var(--sp-lg) 40px; }
.p-body::-webkit-scrollbar { width: 0; }

.navbtn { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: transparent; border: 0; cursor: pointer; color: var(--text2); }

/* month nav — one shared row, three different fillings */
.monthnav { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-sm) 0; min-height: 40px; }
.monthlabel { color: var(--text1); font-weight: 600; font-size: var(--fs-lead); }

/* N1 · neighbour months as the controls */
.mnb {
  background: transparent; border: 0; cursor: pointer;
  color: var(--text3); font-size: var(--fs-label); letter-spacing: 2px; text-transform: uppercase;
  min-height: 40px; min-width: 56px; padding: 0 var(--sp-sm);
  display: flex; align-items: center;
}
.mnb.r { justify-content: flex-end; }
.mnb.l { justify-content: flex-start; }
.mnb:active { color: var(--text1); }

/* N2 · the label itself is the control, opening a year panel */
.monthbtn {
  background: transparent; border: 0; cursor: pointer; padding: 0; margin: 0 auto;
  color: var(--text1); font-weight: 600; font-size: var(--fs-lead);
  border-bottom: 1px solid var(--border); min-height: 40px;
}
.monthbtn.on { border-bottom-color: var(--text1); }
.yearpanel { border: 1px solid var(--border); margin-top: var(--sp-xs); padding: var(--sp-sm); }
.yearrow { display: flex; align-items: center; justify-content: center; gap: var(--sp-lg); padding-bottom: var(--sp-sm); }
.yearrow button {
  background: transparent; border: 0; cursor: pointer; min-height: 34px; padding: 0 var(--sp-sm);
  color: var(--text3); font-size: var(--fs-body); font-family: var(--mono); letter-spacing: var(--track);
  font-variant-numeric: tabular-nums;
}
.yearrow button.cur { color: var(--text1); font-weight: 600; }
.monthsgrid { display: grid; grid-template-columns: repeat(4, 1fr); }
.monthsgrid button {
  background: transparent; border: 0; cursor: pointer; min-height: 44px;
  color: var(--text2); font-size: var(--fs-body); font-family: var(--mono); letter-spacing: 1.4px;
  text-transform: uppercase; position: relative;
  transition: transform calc(var(--press) * var(--mo)) var(--settle), color calc(var(--micro) * var(--mo)) var(--settle);
}
.monthsgrid button:active { transform: scale(0.97); }
.monthsgrid button.cur { color: var(--text1); font-weight: 600; }
.monthsgrid button.cur::after { content: ""; position: absolute; left: 50%; transform: translateX(-50%); bottom: 8px; width: 14px; height: 1px; background: var(--text1); }

/* N3 · an always-visible month strip */
.strip { display: flex; gap: 0; overflow-x: auto; border-bottom: 1px solid var(--border); scrollbar-width: none; }
.strip::-webkit-scrollbar { height: 0; }
.strip button {
  flex: none; background: transparent; border: 0; cursor: pointer;
  min-height: 40px; padding: 0 var(--sp-md); position: relative;
  color: var(--text3); font-size: var(--fs-label); letter-spacing: 1.8px; text-transform: uppercase;
  font-family: var(--mono); white-space: nowrap;
  transition: color calc(var(--micro) * var(--mo)) var(--settle);
}
.strip button.cur { color: var(--text1); font-weight: 600; }
.stripbar {
  position: absolute; height: 2px; background: var(--text1); bottom: 0; left: 0; width: 0;
  transition: transform calc(var(--standard) * var(--mo)) var(--travel), width calc(var(--standard) * var(--mo)) var(--travel);
}
.stripwrap { position: relative; }

.weekdays { display: grid; grid-template-columns: repeat(7, 1fr); }
.weekdays span { text-align: center; color: var(--text3); font-size: var(--fs-micro); letter-spacing: 1px; }

.gridwrap { position: relative; overflow: hidden; margin-top: var(--sp-xs); }
.grid { display: flex; flex-direction: column; border: 1px solid var(--border); }
.week { display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid var(--border2); }
.week:last-child { border-bottom: 0; }
.cell {
  position: relative; min-height: 46px; background: transparent; border: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; padding: var(--sp-xs) 0; cursor: pointer; color: inherit;
  transition: transform calc(var(--press) * var(--mo)) var(--settle);
}
.cell:active { transform: scale(0.97); }
.cell .num { color: var(--text2); font-size: var(--fs-body); position: relative; }
.cell.out .num { color: var(--text3); }          /* single dim — no stacked opacity */
.cell.today .num { color: var(--text1); font-weight: 600; }
.cell.today .num::after {
  content: ""; position: absolute; left: 50%; transform: translateX(-50%);
  bottom: -3px; width: 10px; height: 1px; background: var(--text1);
}
.dots { display: flex; align-items: center; gap: 2px; min-height: 6px; }
.dot { width: 4px; height: 4px; border-radius: 2px; background: var(--text2); }
.dot.overdue { background: var(--red); }
.dot.fired { background: var(--text3); }
.more { display: flex; align-items: center; color: var(--text3); }   /* the plain + , never +n */

/* THE TRAVELLING SELECTION BOX — one element per grid, slides between cells */
.selbox {
  position: absolute; top: 0; left: 0; border: 1px solid var(--text1);
  pointer-events: none; opacity: 0;
  transition: transform calc(var(--boxdur) * var(--mo)) var(--travel),
              width calc(var(--boxdur) * var(--mo)) var(--travel),
              height calc(var(--boxdur) * var(--mo)) var(--travel),
              opacity calc(var(--micro) * var(--mo)) var(--settle);
}
.selbox.on { opacity: 1; }
.selbox.warp { transition: opacity calc(var(--micro) * var(--mo)) var(--settle); }  /* month change: no travel across a redraw */

.dayhead { display: flex; align-items: center; gap: var(--sp-md); padding: var(--sp-lg) 0 var(--sp-sm); }
.dayhead .lbl { color: var(--text3); font-size: var(--fs-label); letter-spacing: 2.2px; text-transform: uppercase; white-space: nowrap; }
.dayhead .rule { flex: 1; height: 1px; background: var(--border); }

.daylist { display: flex; flex-direction: column; }
.empty { color: var(--text3); font-size: var(--fs-body); padding: var(--sp-md) 0; }
.dayrow {
  display: flex; align-items: center; gap: var(--sp-sm); min-height: 44px;
  padding: var(--sp-sm) 0; border-bottom: 1px solid var(--border2);
  background: transparent; border-left: 0; border-right: 0; border-top: 0;
  cursor: pointer; text-align: left; width: 100%;
  transition: transform calc(var(--press) * var(--mo)) var(--settle), background calc(var(--press) * var(--mo)) var(--settle);
}
.dayrow:active { background: var(--surface); transform: scale(0.98); }
.dayrow .title { flex: 1; color: var(--text1); font-size: var(--fs-lead); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dayrow .time { color: var(--text3); font-size: var(--fs-body); font-variant-numeric: tabular-nums; }
.dayrow svg { flex: none; }

.addrow {
  display: flex; align-items: center; gap: var(--sp-sm); min-height: 44px;
  margin-top: var(--sp-sm); padding: 0 var(--sp-md);
  border: 1px solid var(--border); background: transparent;
  color: var(--text2); font-size: var(--fs-lead); cursor: pointer; width: 100%;
  transition: transform calc(var(--press) * var(--mo)) var(--settle), background calc(var(--press) * var(--mo)) var(--settle);
}
.addrow:active, .p-today:active { background: var(--surface); transform: scale(0.98); }
.p-today { transition: transform calc(var(--press) * var(--mo)) var(--settle), background calc(var(--press) * var(--mo)) var(--settle); }

.composer { margin-top: var(--sp-sm); border: 1px solid var(--border); padding: var(--sp-md); display: flex; flex-direction: column; gap: var(--sp-sm);
  animation: riseIn calc(var(--standard) * var(--mo)) var(--settle) 1; }
.composer input, .composer textarea { font-family: var(--mono); letter-spacing: var(--track); background: transparent; color: var(--text1); border: 0; outline: 0; }
.composer .f-title { font-size: var(--fs-lead); font-weight: 600; border-bottom: 1px solid var(--border2); padding: var(--sp-sm) 0; min-height: 44px; }
.composer .f-body { font-size: var(--fs-read); border-bottom: 1px solid var(--border2); padding: var(--sp-sm) 0; min-height: 60px; resize: none; }
.composer .flabel { color: var(--text3); font-size: var(--fs-micro); letter-spacing: 0.6px; text-transform: uppercase; margin-top: var(--sp-xs); }
.composer .f-time { font-size: var(--fs-lead); font-weight: 600; border: 1px solid var(--border); padding: 0 var(--sp-sm); min-height: 44px; width: 96px; font-variant-numeric: tabular-nums; }
.composer .f-proj { font-size: var(--fs-read); border: 1px solid var(--border); padding: 0 var(--sp-sm); min-height: 44px; }
.composer .btns { display: flex; gap: var(--sp-sm); margin-top: var(--sp-xs); }
.composer .btns button {
  flex: 1; min-height: 44px; background: transparent; cursor: pointer;
  font-size: var(--fs-lead); font-family: var(--mono); letter-spacing: var(--track);
  transition: transform calc(var(--press) * var(--mo)) var(--settle), background calc(var(--press) * var(--mo)) var(--settle);
}
.composer .btns button:active { background: var(--surface); transform: scale(0.98); }
.composer .b-cancel { border: 1px solid var(--border); color: var(--text2); }
.composer .b-create { border: 1px solid var(--text1); color: var(--text1); font-weight: 600; }
.composer .b-create[disabled] { border-color: var(--border); color: var(--text3); opacity: 0.5; cursor: default; }
.composer ::placeholder { color: var(--text3); }

@keyframes riseIn { 0% { opacity: 0; transform: translateY(8px); } 100% { opacity: 1; transform: none; } }

.daylist .dayrow, .daylist .empty {
  animation: rowIn calc(var(--standard) * var(--mo)) var(--travel) both;
  animation-delay: calc(var(--i, 0) * var(--stagger) * var(--mo));
}
@keyframes rowIn { 0% { opacity: 0; transform: translateY(6px); } 100% { opacity: 1; transform: none; } }

.grid.swap-l { animation: swapL calc(var(--micro) * var(--mo)) var(--travel) 1; }
.grid.swap-r { animation: swapR calc(var(--micro) * var(--mo)) var(--travel) 1; }
@keyframes swapL { 0% { opacity: 0; transform: translateX(-3px); } 100% { opacity: 1; transform: none; } }
@keyframes swapR { 0% { opacity: 0; transform: translateX(3px); } 100% { opacity: 1; transform: none; } }

.dayrow.justmade { animation: arrive calc(var(--standard) * var(--mo) * 2) var(--settle) 1; }
@keyframes arrive { 0% { background: var(--surface2); } 100% { background: transparent; } }

/* ── reduced motion: the mandatory fallback, shown on demand ──────────── */
body.reduced .phone, body.reduced .phone * {
  animation: none !important;
  transition-property: background, color, opacity, border-color !important;
  transition-duration: 0ms !important;
}
body.reduced .selbox, body.reduced .stripbar { transition: none !important; }
/* press feedback survives reduced motion as a background flip — feedback is not
   decoration, and haptics are not motion either. */
body.reduced .phone .cell:active { transform: none !important; background: var(--surface); }
body.reduced .phone .dayrow:active, body.reduced .phone .addrow:active { transform: none !important; }

@media (prefers-reduced-motion: reduce) { .ctl { transition: none; } }

/* ── notes column ────────────────────────────────────────────────────── */
.notes { min-width: 0; }
.why { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 14px 0; margin: 0 0 18px; }
.why p:last-child { margin-bottom: 0; }

table { border-collapse: collapse; width: 100%; font-size: 12.5px; margin: 0 0 18px; }
.tablewrap { overflow-x: auto; }
th, td { text-align: left; padding: 8px 12px 8px 0; border-bottom: 1px solid var(--border2); vertical-align: top; }
th { color: var(--text3); font-weight: 400; font-size: 10px; letter-spacing: 1.6px; text-transform: uppercase; border-bottom-color: var(--border); }
td { color: var(--text2); }
td strong { color: var(--text1); font-weight: 500; }
td.n { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--text3); }

ul { margin: 0 0 14px; padding-left: 18px; }
li { margin: 0 0 6px; color: var(--text2); }
li strong { color: var(--text1); font-weight: 500; }

.ruled { border: 1px solid var(--border); padding: 16px 18px; margin: 0 0 26px; background: var(--surface); }
.ruled .kicker { margin-bottom: 8px; }
.ruled ul { margin-bottom: 0; }
.ruled.warn { border-color: var(--yellow); background: transparent; }
.ruled.warn .kicker { color: var(--yellow); }

.legend { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; margin: 0 0 20px; font-size: 12px; }
.legend span { display: flex; align-items: center; gap: 7px; color: var(--text3); }
.legend i { width: 6px; height: 6px; border-radius: 3px; display: block; }

.foot { color: var(--text3); font-size: 12px; }
.verdict { color: var(--text1); }
</style>

<div class="wrap">

  <p class="kicker">Second Thought · Android · session s150 · board v2</p>
  <h1>Quiet Grid, with the box that travels</h1>
  <p class="lede">
    Round 1 is decided: <strong>A · Quiet Grid</strong> is the base, its selection mark becomes
    <strong>one box that slides between days</strong>, and the <code>+n</code> badge is replaced by a
    plain <strong><code>+</code></strong> when a day carries more than three. All three are built below.
  </p>
  <p class="lede">
    The arrows are settled too: <strong>both month chevrons are gone</strong>, replaced by the
    neighbouring month names, with a horizontal drag on the grid as the accelerator. Header Back is now
    the screen's only arrow. <strong>Drag the grid sideways</strong> to feel it.
  </p>

  <div class="controls" role="group" aria-label="Board controls">
    <span class="lbl">Controls</span>
    <button class="ctl" id="c-slow" aria-pressed="false">4× slow-mo</button>
    <button class="ctl" id="c-reduced" aria-pressed="false">Reduced motion</button>
    <button class="ctl" id="c-replay">Replay entrances</button>
    <span class="lbl" style="margin-left:10px">Box travel</span>
    <button class="ctl" id="c-box">160ms · MICRO</button>
  </div>

  <div class="legend">
    <span><i style="background:var(--red)"></i> overdue — today, clock time passed</span>
    <span><i style="background:var(--text3)"></i> fired — an earlier day, elapsed</span>
    <span><i style="background:var(--text2)"></i> upcoming — later today or a future day</span>
  </div>

  <hr>

  <!-- ── THE DECIDED DESIGN ──────────────────────────────────────────── -->
  <section>
    <div class="sec-head">
      <h2>The decided design</h2>
      <span class="tag pick">agreed</span>
    </div>
    <div class="opt">
      <div class="stage">
        <div class="stage-cap">Quiet Grid · <b>tap days · drag the grid sideways</b></div>
        <div class="phone" data-variant="hero" data-nav="n1"></div>
      </div>
      <div class="notes">
        <div class="why">
          <p><strong>Tap a few days in a row.</strong> The box does not blink out and reappear — it
          travels, so your eye follows one object instead of re-finding a new one. That is the whole
          reason the motion is worth having.</p>
        </div>
        <h3>What changed from round 1</h3>
        <ul>
          <li><strong>The selection box travels.</strong> One element per grid, 1px <code>text1</code>, inset 3px, sliding on TRAVEL/260ms — option C's indicator idiom applied to A's box.</li>
          <li><strong><code>+n</code> is gone.</strong> Four or more reminders on a day shows three dots and a plain <code>+</code>. The exact count was never actionable at 9px; the day list underneath is where you read it.</li>
          <li>Vertical cell dividers dropped — a month is scanned by <em>week</em>, so the week rules carry the grid and the dots stop competing with 36 vertical lines.</li>
          <li>Out-of-month days stop being dimmed twice (<code>text3</code> <em>and</em> <code>opacity 0.5</code>); once is enough.</li>
          <li>Today keeps a semibold numeral and gains a 10px underline, so today and selected never read the same.</li>
        </ul>

        <h3>Motion</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>Interaction</th><th>Motion</th><th class="n">Timing</th></tr></thead>
          <tbody>
            <tr><td>Any press</td><td>scale 0.97 — cells, rows, buttons</td><td class="n">120ms SETTLE</td></tr>
            <tr><td><strong>Select a day</strong></td><td><strong>the box travels</strong> to the new cell</td><td class="n">260ms TRAVEL</td></tr>
            <tr><td>Change month</td><td>crossfade + 3px directional nudge</td><td class="n">160ms TRAVEL</td></tr>
            <tr><td>Change month, selection off-screen</td><td>box fades out; no travel across a redraw</td><td class="n">160ms SETTLE</td></tr>
            <tr><td>Day list</td><td>fade + rise 6px, staggered</td><td class="n">260ms · 45ms step</td></tr>
            <tr><td>Composer</td><td><code>useRiseIn</code> — fade + rise 8px</td><td class="n">260ms SETTLE</td></tr>
          </tbody>
        </table></div>

        <h3>What the travelling box costs</h3>
        <p>It needs cell geometry, which a pure style flag did not. It stays cheap because the grid is
        uniform: <strong>one <code>onLayout</code> on the grid gives width; cell width is width ÷ 7 and
        row height is the fixed row height.</strong> No per-cell measurement, no measurement on every
        selection. The box is a single <code>Animated.View</code> driven by
        <code>useNativeDriver: true</code>, like every other primitive in <code>motion.ts</code>.</p>
      </div>
    </div>
  </section>

  <hr>

  <!-- ── THE ARROW PROBLEM ───────────────────────────────────────────── -->
  <section>
    <div class="sec-head">
      <h2>Too many arrows</h2>
      <span class="tag open">open question</span>
    </div>
    <div class="tablewrap"><table>
      <thead><tr><th>Arrow</th><th>Source</th><th>Verdict</th></tr></thead>
      <tbody>
        <tr><td>Header back</td><td><code>BackIcon</code>, dismisses the screen</td><td class="verdict"><strong>stays</strong> — it is the screen's only exit</td></tr>
        <tr><td>Previous month</td><td><code>BackIcon</code> at 18px</td><td>replace</td></tr>
        <tr><td>Next month</td><td>the same <code>BackIcon</code>, mirrored <code>scaleX(-1)</code></td><td>replace</td></tr>
      </tbody>
    </table></div>
    <p>Three chevrons in the top 90px, two of which are literally the same glyph pointing opposite
    ways, is the problem. Each replacement below removes both month arrows and leaves Back alone.
    <strong>All three are the decided Quiet Grid</strong> — only the navigation row differs.</p>

    <div class="ruled warn">
      <p class="kicker">Worth saying out loud</p>
      <p style="margin:0">s147's ruling 1 ends <em>"month at a time, arrows both ways."</em> Removing the
      month arrows amends that clause. The shape is untouched — still one month at a time, still
      reachable both ways — so this is a control change, not a re-opened decision. It gets recorded as
      an amendment either way.</p>
    </div>
  </section>

  <hr>

  <section>
    <div class="sec-head">
      <h2>The implementation contract</h2>
      <span class="tag pick">everything below is decided</span>
    </div>
    <p>The phone above <em>is</em> the spec. This is what goes into
    <code>app/calendar.tsx</code> and <code>src/components/motion.ts</code>, nothing more.</p>

    <h3>Structure</h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Element</th><th>Decision</th></tr></thead>
      <tbody>
        <tr><td><strong>Month nav</strong></td><td>N1 — <code>JUL · August 2026 · SEP</code>. <strong>Both month arrows deleted.</strong> Header Back is the screen's only chevron.</td></tr>
        <tr><td><strong>Swipe</strong></td><td>horizontal pan on the grid steps the month. An <strong>accelerator only</strong> — the neighbour labels stay as the visible equivalent the gesture model demands.</td></tr>
        <tr><td><strong>Selection</strong></td><td>one travelling 1px <code>text1</code> box, inset 3px. Replaces the <code>accentDim</code> fill.</td></tr>
        <tr><td><strong>Overflow</strong></td><td>3 dots + a plain <code>+</code> icon at 7px. <strong>No number.</strong></td></tr>
        <tr><td><strong>Grid</strong></td><td>vertical dividers removed; week rules in <code>border2</code>; outer frame in <code>border</code>.</td></tr>
        <tr><td><strong>Today</strong></td><td>semibold <code>text1</code> numeral + a 10px underline — never confusable with selected.</td></tr>
        <tr><td><strong>Out-of-month</strong></td><td><code>text3</code> at full opacity. The stacked <code>opacity: 0.5</code> goes.</td></tr>
      </tbody>
    </table></div>

    <h3>Motion — every value is an existing token</h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Interaction</th><th>Motion</th><th class="n">Timing</th></tr></thead>
      <tbody>
        <tr><td>Any press</td><td>scale 0.97</td><td class="n">120ms SETTLE</td></tr>
        <tr><td><strong>Select a day</strong></td><td>the box travels</td><td class="n"><strong>160ms MICRO</strong> · TRAVEL</td></tr>
        <tr><td>Change month</td><td>crossfade + 3px directional nudge</td><td class="n">160ms MICRO · TRAVEL</td></tr>
        <tr><td>Month change, selection off-grid</td><td>box fades out; never travels across a redraw</td><td class="n">160ms MICRO · SETTLE</td></tr>
        <tr><td>Day list</td><td>fade + rise 6px, staggered</td><td class="n">260ms STANDARD · 45ms STAGGER</td></tr>
        <tr><td>Composer</td><td><code>useRiseIn</code> — fade + rise 8px</td><td class="n">260ms STANDARD · SETTLE</td></tr>
      </tbody>
    </table></div>
    <p class="foot">No new duration constant is introduced. <code>MICRO</code> already means
    "small state flips" in <code>motion.ts</code>, which is exactly what a selection box is.
    Use the <strong>Box travel</strong> control above to compare it against 120ms and the original
    260ms before this is final.</p>

    <h3>Already settled, carried forward</h3>
    <div class="tablewrap"><table>
      <thead><tr><th>Concern</th><th>Behaviour</th></tr></thead>
      <tbody>
        <tr><td><strong>Press primitive</strong></td><td>lands once in <code>src/components/motion.ts</code> — scale 0.97, 120ms SETTLE, native driver, ≥44px targets untouched</td></tr>
        <tr><td><strong>Reduced motion</strong></td><td>scale drops, <strong>background flip stays</strong>; the box jumps instead of sliding; nothing becomes invisible</td></tr>
        <tr><td><strong>Haptics — day tap</strong></td><td><code>Haptics.selectionAsync()</code></td></tr>
        <tr><td><strong>Haptics — reminder created</strong></td><td><code>Haptics.notificationAsync(Success)</code></td></tr>
        <tr><td><strong>Haptics — month change</strong></td><td>none, deliberately — scrubbing months would machine-gun the motor</td></tr>
        <tr><td>Both haptics</td><td>wrapped in <code>.catch(() =&gt; {})</code>, <strong>never gated on reduced motion</strong> — the existing rule in <code>app/(tabs)/index.tsx</code></td></tr>
      </tbody>
    </table></div>
  </section>

</div>

<script>
(function () {
  "use strict";

  // ── the fixture: a real August 2026 with a real spread of statuses ─────
  var TODAY = "2026-08-06";
  var NOW = new Date(2026, 7, 6, 15, 40).getTime();
  var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];
  var ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  var REMINDERS = [
    ["2026-07-29T09:00", "Cancel the trial before it renews"],
    ["2026-08-02T18:30", "Water the plants"],
    ["2026-08-03T09:00", "Renew the domain"],
    ["2026-08-03T16:00", "Call the letting agent"],
    ["2026-08-06T08:00", "Send the Q3 draft to Priya"],
    ["2026-08-06T09:30", "Write up standup notes"],
    ["2026-08-06T19:00", "Pick up the prescription"],
    ["2026-08-07T08:00", "Dentist"],
    ["2026-08-11T08:00", "Passport photos"],
    ["2026-08-14T10:00", "Rent"],
    ["2026-08-14T13:00", "Team retro"],
    ["2026-08-14T17:00", "Book the flights"],
    ["2026-08-14T20:00", "Ring Mum"],
    ["2026-08-20T08:00", "Insurance renewal"],
    ["2026-08-27T08:00", "Submit expenses"],
    ["2026-09-02T08:00", "Quarterly review"]
  ];

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function iso(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function parseLocal(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(s);
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  }
  // reminderDotStatus, ported verbatim from src/lib/calendarMonth.ts
  function dotStatus(s) {
    var d = parseLocal(s), day = iso(d);
    if (day < TODAY) return "fired";
    if (day > TODAY) return "upcoming";
    return d.getTime() <= NOW ? "overdue" : "upcoming";
  }
  // buildMonthGrid, ported verbatim
  function buildMonthGrid(year, month) {
    var first = new Date(year, month, 1);
    var startWeekday = first.getDay();
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var total = Math.ceil((startWeekday + daysInMonth) / 7) * 7;
    var cells = [];
    for (var i = 0; i < total; i++) {
      var d = new Date(year, month, 1 - startWeekday + i);
      cells.push({
        day: d.getDate(), dayIso: iso(d),
        inMonth: d.getMonth() === month && d.getFullYear() === year,
        isToday: iso(d) === TODAY
      });
    }
    return cells;
  }
  function fmtTime(s) { var d = parseLocal(s); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function dayHeaderLabel(dayIso) {
    var p = dayIso.split("-");
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    var suffix = WEEKDAYS[d.getDay()] + " " + (+p[1]) + "/" + (+p[2]);
    return dayIso === TODAY ? "Today · " + suffix : suffix;
  }
  function shift(year, month, delta) {
    var d = new Date(year, month + delta, 1);
    return { year: d.getFullYear(), month: d.getMonth() };
  }

  function icon(d, size, color) {
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="' +
      color + '" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      d + '</svg>';
  }
  var BACK = '<path d="M15 5l-7 7 7 7"/>';
  var PLUS = '<path d="M12 5v14M5 12h14"/>';
  var BELL = '<path d="M12 4a4.5 4.5 0 00-4.5 4.5v3.4c0 .8-.32 1.56-.88 2.12L5 15.5h14l-1.62-1.48a3 3 0 01-.88-2.12V8.5A4.5 4.5 0 0012 4z"/><path d="M10.2 18a1.9 1.9 0 003.6 0"/>';

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]; });
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

  // ── one screen instance ───────────────────────────────────────────────
  function Screen(root) {
    this.root = root;
    this.nav = root.getAttribute("data-nav");
    this.year = 2026; this.month = 7;
    this.sel = TODAY;
    this.composerOpen = false;
    this.yearOpen = false;
    this.pickYear = 2026;
    this.title = ""; this.time = "08:00"; this.proj = ""; this.body = "";
    this.extra = [];
    this.dir = 0;
    this.warp = true;       // month changed (and first paint): the box must not travel across a redraw
    this.justMade = null;
    this.build();
    this.render();
  }

  Screen.prototype.all = function () { return REMINDERS.concat(this.extra); };

  Screen.prototype.navHtml = function () {
    if (this.nav === "n1") {
      var p = shift(this.year, this.month, -1), n = shift(this.year, this.month, 1);
      return '<div class="monthnav">' +
        '<button class="mnb l" data-act="prev" aria-label="Previous month, ' + MONTHS[p.month] + ' ' + p.year + '">' + ABBR[p.month] + '</button>' +
        '<div class="monthlabel"></div>' +
        '<button class="mnb r" data-act="next" aria-label="Next month, ' + MONTHS[n.month] + ' ' + n.year + '">' + ABBR[n.month] + '</button>' +
        '</div>';
    }
    if (this.nav === "n2") {
      return '<div class="monthnav"><button class="monthbtn" data-act="year" aria-expanded="' +
        (this.yearOpen ? "true" : "false") + '"></button></div><div class="yearslot"></div>';
    }
    return '<div class="monthnav"><div class="monthlabel"></div></div>' +
      '<div class="stripwrap"><div class="strip"></div><div class="stripbar"></div></div>';
  };

  Screen.prototype.build = function () {
    var r = this.root;
    r.innerHTML =
      '<div class="p-header">' +
        '<button class="navbtn" aria-label="Back">' + icon(BACK, 22, "var(--text2)") + '</button>' +
        '<div class="p-h1">Calendar</div>' +
        '<button class="p-today" data-act="today">Today</button>' +
      '</div>' +
      '<div class="p-body">' +
        '<div class="navslot"></div>' +
        '<div class="weekdays">' + WEEKDAYS.map(function (w) { return "<span>" + w + "</span>"; }).join("") + '</div>' +
        '<div class="gridwrap"><div class="grid"></div><div class="selbox"></div></div>' +
        '<div class="daysec"></div>' +
      '</div>';
    this.elNavSlot = r.querySelector(".navslot");
    this.elNavSlot.innerHTML = this.navHtml();
    this.elGrid = r.querySelector(".grid");
    this.elGridWrap = r.querySelector(".gridwrap");
    this.elBox = r.querySelector(".selbox");
    this.elDaySec = r.querySelector(".daysec");
    var self = this;
    r.addEventListener("click", function (e) { self.onClick(e); });
    this.wireSwipe();
  };

  // The accelerator, never the only way: a horizontal pan on the grid steps the month,
  // while the JUL/SEP labels remain the visible equivalent the gesture model requires.
  // Locks to one axis before it acts so it cannot fight the vertical scroll — the same
  // rule react-native-gesture-handler's activeOffsetX/failOffsetY encode natively.
  Screen.prototype.wireSwipe = function () {
    var self = this, x0 = 0, y0 = 0, axis = null, down = false;
    var g = this.elGridWrap;
    g.addEventListener("pointerdown", function (e) {
      down = true; axis = null; x0 = e.clientX; y0 = e.clientY;
    });
    g.addEventListener("pointermove", function (e) {
      if (!down) return;
      var dx = e.clientX - x0, dy = e.clientY - y0;
      if (axis === null) {
        if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy)) axis = "x";
        else if (Math.abs(dy) > 12) axis = "y";
      }
      if (axis === "x" && Math.abs(dx) > 48) {
        self.step(dx < 0 ? 1 : -1);   // drag left -> next month, like a page
        self.swiped = true;           // swallow the click this drag would otherwise fire
        down = false;
      }
    });
    g.addEventListener("pointerup", function () { down = false; });
    g.addEventListener("pointercancel", function () { down = false; });
  };

  Screen.prototype.onClick = function (e) {
    if (this.swiped) { this.swiped = false; return; }
    var t = e.target.closest ? e.target.closest("[data-act]") : null;
    if (!t) return;
    var act = t.getAttribute("data-act");
    if (act === "prev") this.step(-1);
    else if (act === "next") this.step(1);
    else if (act === "today") { this.year = 2026; this.month = 7; this.warp = true; this.yearOpen = false; this.select(TODAY); }
    else if (act === "day") this.select(t.getAttribute("data-day"));
    else if (act === "open") { this.composerOpen = true; this.render(); }
    else if (act === "cancel") { this.composerOpen = false; this.reset(); this.render(); }
    else if (act === "create") this.create();
    else if (act === "year") { this.yearOpen = !this.yearOpen; this.pickYear = this.year; this.render(); }
    else if (act === "pickyear") { this.pickYear = +t.getAttribute("data-y"); this.render(); }
    else if (act === "pickmonth") {
      this.year = this.pickYear; this.month = +t.getAttribute("data-m");
      this.yearOpen = false; this.warp = true; this.dir = 0; this.render();
    } else if (act === "stripmonth") {
      var y = +t.getAttribute("data-y"), m = +t.getAttribute("data-m");
      this.dir = (y * 12 + m) > (this.year * 12 + this.month) ? 1 : -1;
      this.year = y; this.month = m; this.warp = true; this.render();
    }
    if (SYNC && !this.echo) mirror(this, act, t);
  };

  Screen.prototype.step = function (delta) {
    var s = shift(this.year, this.month, delta);
    this.year = s.year; this.month = s.month;
    this.dir = delta; this.warp = true; this.render();
  };

  Screen.prototype.select = function (dayIso) {
    this.sel = dayIso; this.composerOpen = false; this.render();
  };

  Screen.prototype.reset = function () { this.title = ""; this.body = ""; this.time = "08:00"; this.proj = ""; };

  Screen.prototype.create = function () {
    if (!this.title.trim()) return;
    var t = /^(\d{1,2}):(\d{2})$/.exec(this.time.trim());
    if (!t) return;
    var hh = Math.min(23, Math.max(0, +t[1])), mm = Math.min(59, Math.max(0, +t[2]));
    var stamp = this.sel + "T" + pad(hh) + ":" + pad(mm);
    this.extra.push([stamp, this.title.trim()]);
    this.justMade = stamp;
    this.composerOpen = false;
    this.reset();
    this.render();
  };

  Screen.prototype.render = function () {
    var self = this;

    // ── nav row ──
    if (this.nav === "n1") {
      this.elNavSlot.innerHTML = this.navHtml();
      this.elNavSlot.querySelector(".monthlabel").textContent = MONTHS[this.month] + " " + this.year;
    } else if (this.nav === "n2") {
      var btn = this.elNavSlot.querySelector(".monthbtn");
      btn.textContent = MONTHS[this.month] + " " + this.year;
      btn.className = "monthbtn" + (this.yearOpen ? " on" : "");
      btn.setAttribute("aria-expanded", this.yearOpen ? "true" : "false");
      var slot = this.elNavSlot.querySelector(".yearslot");
      if (this.yearOpen) {
        var yh = '<div class="yearpanel"><div class="yearrow">';
        for (var yy = this.pickYear - 1; yy <= this.pickYear + 1; yy++) {
          yh += '<button data-act="pickyear" data-y="' + yy + '" class="' + (yy === this.pickYear ? "cur" : "") + '">' + yy + '</button>';
        }
        yh += '</div><div class="monthsgrid">';
        for (var mm2 = 0; mm2 < 12; mm2++) {
          var cur = (mm2 === this.month && this.pickYear === this.year);
          yh += '<button data-act="pickmonth" data-m="' + mm2 + '" class="' + (cur ? "cur" : "") + '">' + ABBR[mm2] + '</button>';
        }
        yh += '</div></div>';
        slot.innerHTML = yh;
      } else slot.innerHTML = "";
    } else {
      this.elNavSlot.querySelector(".monthlabel").textContent = MONTHS[this.month] + " " + this.year;
      var strip = this.elNavSlot.querySelector(".strip");
      var sh = "";
      for (var k = -6; k <= 6; k++) {
        var s = shift(this.year, this.month, k);
        var lbl = ABBR[s.month] + (s.year !== this.year ? " '" + String(s.year).slice(2) : "");
        sh += '<button data-act="stripmonth" data-y="' + s.year + '" data-m="' + s.month + '" class="' +
          (k === 0 ? "cur" : "") + '">' + lbl + '</button>';
      }
      strip.innerHTML = sh;
    }

    // ── grid ──
    var cells = buildMonthGrid(this.year, this.month);
    var dots = {};
    this.all().forEach(function (r) {
      var k = r[0].slice(0, 10);
      (dots[k] = dots[k] || []).push(dotStatus(r[0]));
    });

    var html = "";
    for (var w = 0; w < cells.length / 7; w++) {
      html += '<div class="week">';
      for (var i = 0; i < 7; i++) {
        var c = cells[w * 7 + i];
        var ds = dots[c.dayIso] || [];
        var shown = ds.slice(0, 3), over = ds.length > 3;
        var cls = "cell";
        if (!c.inMonth) cls += " out";
        if (c.isToday) cls += " today";
        if (c.dayIso === this.sel) cls += " sel";
        var a11y = c.day + (c.isToday ? ", today" : "") +
          (ds.length ? ", " + ds.length + " reminder" + (ds.length === 1 ? "" : "s") : "");
        html += '<button class="' + cls + '" data-act="day" data-day="' + c.dayIso +
          '" aria-label="' + a11y + '" aria-pressed="' + (c.dayIso === this.sel) + '">' +
          '<span class="num">' + c.day + '</span><span class="dots">' +
          shown.map(function (s) { return '<i class="dot ' + s + '"></i>'; }).join("") +
          (over ? '<span class="more">' + icon(PLUS, 7, "var(--text3)") + '</span>' : '') +
          '</span></button>';
      }
      html += "</div>";
    }
    this.elGrid.innerHTML = html;

    this.elGrid.classList.remove("swap-l", "swap-r");
    if (this.dir !== 0) {
      void this.elGrid.offsetWidth;
      this.elGrid.classList.add(this.dir > 0 ? "swap-r" : "swap-l");
    }
    this.dir = 0;

    this.placeBox();

    // ── day section ──
    var list = this.all()
      .filter(function (r) { return r[0].slice(0, 10) === self.sel; })
      .sort(function (a, b) { return parseLocal(a[0]) - parseLocal(b[0]); });

    var dhtml = '<div class="dayhead"><span class="lbl">' + dayHeaderLabel(this.sel) +
      '</span><span class="rule"></span></div><div class="daylist">';
    if (!list.length) {
      dhtml += '<div class="empty" style="--i:0">No reminders this day.</div>';
    } else {
      list.forEach(function (r, idx) {
        var st = dotStatus(r[0]);
        var col = st === "overdue" ? "var(--red)" : st === "fired" ? "var(--text3)" : "var(--text2)";
        dhtml += '<button class="dayrow' + (r[0] === self.justMade ? " justmade" : "") +
          '" style="--i:' + idx + '">' + icon(BELL, 15, col) +
          '<span class="title">' + escapeHtml(r[1]) + '</span>' +
          '<span class="time">' + fmtTime(r[0]) + '</span></button>';
      });
    }
    dhtml += "</div>";

    if (this.composerOpen) {
      dhtml +=
        '<div class="composer">' +
          '<input class="f-title" placeholder="Title" value="' + escapeAttr(this.title) + '" data-f="title" aria-label="Reminder title">' +
          '<textarea class="f-body" placeholder="Note (optional)" data-f="body" aria-label="Note body, optional">' + escapeHtml(this.body) + '</textarea>' +
          '<div class="flabel">Time — defaults to 08:00, edit anytime</div>' +
          '<input class="f-time" value="' + escapeAttr(this.time) + '" data-f="time" aria-label="Reminder time, defaults to 08:00">' +
          '<div class="flabel">#project@ (optional)</div>' +
          '<input class="f-proj" placeholder="project-name" value="' + escapeAttr(this.proj) + '" data-f="proj" aria-label="Project tag, optional">' +
          '<div class="btns">' +
            '<button class="b-cancel" data-act="cancel">Cancel</button>' +
            '<button class="b-create" data-act="create"' + (this.title.trim() ? "" : " disabled") + '>Create</button>' +
          '</div>' +
        '</div>';
    } else {
      dhtml += '<button class="addrow" data-act="open">' + icon(PLUS, 16, "var(--text2)") +
        '<span>Add reminder</span></button>';
    }

    this.elDaySec.innerHTML = dhtml;
    this.justMade = null;

    var self2 = this;
    var fields = this.elDaySec.querySelectorAll("[data-f]");
    for (var f = 0; f < fields.length; f++) {
      (function (el) {
        el.addEventListener("input", function () {
          var key = el.getAttribute("data-f");
          self2[key] = el.value;
          if (key === "title") {
            var b = self2.elDaySec.querySelector(".b-create");
            if (b) b.disabled = !el.value.trim();
          }
        });
      })(fields[f]);
    }

    if (this.nav === "n3") this.placeStripBar();
  };

  // The travelling box. `warp` suppresses travel across a month redraw — sliding
  // between two cells that are not the same day would be a lie about the motion.
  Screen.prototype.placeBox = function () {
    var cell = this.elGrid.querySelector(".cell.sel");
    var box = this.elBox;
    if (this.warp) { box.classList.add("warp"); }
    if (!cell) { box.classList.remove("on"); this.finishWarp(); return; }
    var g = this.elGrid.getBoundingClientRect(), c = cell.getBoundingClientRect();
    if (!c.width) { this.finishWarp(); return; }
    box.style.width = Math.round(c.width - 6) + "px";
    box.style.height = Math.round(c.height - 6) + "px";
    box.style.transform = "translate(" + Math.round(c.left - g.left + 3) + "px," +
      Math.round(c.top - g.top + 3) + "px)";
    box.classList.add("on");
    this.finishWarp();
  };

  Screen.prototype.finishWarp = function () {
    if (!this.warp) return;
    var box = this.elBox;
    this.warp = false;
    requestAnimationFrame(function () { box.classList.remove("warp"); });
  };

  Screen.prototype.placeStripBar = function () {
    var bar = this.root.querySelector(".stripbar");
    var cur = this.root.querySelector(".strip button.cur");
    var wrap = this.root.querySelector(".stripwrap");
    if (!bar || !cur || !wrap) return;
    var w = wrap.getBoundingClientRect(), c = cur.getBoundingClientRect();
    bar.style.width = Math.round(c.width) + "px";
    bar.style.transform = "translateX(" + Math.round(c.left - w.left) + "px)";
    // keep the active month in view without yanking the page
    var strip = this.root.querySelector(".strip");
    strip.scrollLeft = cur.offsetLeft - strip.clientWidth / 2 + cur.offsetWidth / 2;
  };

  // ── boot ──────────────────────────────────────────────────────────────
  var screens = [];
  var nodes = document.querySelectorAll(".phone");
  for (var i = 0; i < nodes.length; i++) screens.push(new Screen(nodes[i]));

  function replace() {
    screens.forEach(function (s) {
      s.warp = true; s.placeBox();
      if (s.nav === "n3") s.placeStripBar();
    });
  }
  window.addEventListener("resize", replace);
  requestAnimationFrame(replace);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(replace);

  // ── mirroring: drive one, watch the others react ──────────────────────
  var SYNC = true;
  function mirror(origin, act, node) {
    var day = node.getAttribute("data-day");
    screens.forEach(function (s) {
      if (s === origin) return;
      s.echo = true;
      if (act === "prev") s.step(-1);
      else if (act === "next") s.step(1);
      else if (act === "today") { s.year = 2026; s.month = 7; s.warp = true; s.yearOpen = false; s.select(TODAY); }
      else if (act === "day") s.select(day);
      else if (act === "open") { s.composerOpen = true; s.render(); }
      else if (act === "cancel") { s.composerOpen = false; s.reset(); s.render(); }
      else if (act === "pickmonth" || act === "stripmonth") {
        // a jump made in one nav lands in every nav, so they stay comparable
        var y = act === "stripmonth" ? +node.getAttribute("data-y") : origin.year;
        var m = act === "stripmonth" ? +node.getAttribute("data-m") : origin.month;
        s.year = y; s.month = m; s.warp = true; s.yearOpen = false; s.render();
      }
      s.echo = false;
    });
  }

  // ── controls ──────────────────────────────────────────────────────────
  function toggle(btn, on) { btn.setAttribute("aria-pressed", on ? "true" : "false"); }

  var slow = document.getElementById("c-slow");
  slow.addEventListener("click", function () {
    var on = slow.getAttribute("aria-pressed") !== "true";
    toggle(slow, on);
    document.documentElement.style.setProperty("--mo", on ? "4" : "1");
  });

  var red = document.getElementById("c-reduced");
  red.addEventListener("click", function () {
    var on = red.getAttribute("aria-pressed") !== "true";
    toggle(red, on);
    document.body.classList.toggle("reduced", on);
  });

  // Box-travel picker. MICRO is the default because motion.ts already defines it as
  // "small state flips" — a selection box is exactly that. The other two are here to
  // be rejected by feel, not by argument.
  var SPEEDS = [["160ms · MICRO", "160ms"], ["120ms", "120ms"], ["260ms · STANDARD", "260ms"]];
  var speedIdx = 0;
  var boxBtn = document.getElementById("c-box");
  boxBtn.addEventListener("click", function () {
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    boxBtn.textContent = SPEEDS[speedIdx][0];
    document.documentElement.style.setProperty("--boxdur", SPEEDS[speedIdx][1]);
  });

  document.getElementById("c-replay").addEventListener("click", function () {
    screens.forEach(function (s) { s.render(); });
  });
})();
</script>
"""

html = (PAGE
        .replace("__FONTS__", FONT_FACES)
        .replace("__TOKENS__", TOKEN_VARS)
        .replace("__SCALES__", SCALE_VARS)
        .replace("__SPACES__", SPACE_VARS))

assert "__FONTS__" not in html and "__TOKENS__" not in html
assert "\x00" not in html, "NUL byte in output"
OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT} ({len(html):,} bytes)")
print(f"palette keys: {len(PAL)} · scale: {SCALE} · space: {SPACE}")
