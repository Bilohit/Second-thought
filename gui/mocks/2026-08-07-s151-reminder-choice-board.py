"""Generate the s151 reminder-choice decision board.

The question: `App.tsx:894-936`'s date-mention auto-offer fires
`createReminder` once per detected date. Since s148's REM-1 ruling made
frontmatter (`remind_at`, a single scalar) authoritative, those N calls now
collapse to whichever runs LAST. The ruling (DECISIONS §5 s148.6) is that the
surface must become an EXPLICIT SINGLE CHOICE among the detected dates.

Renders the current (defective) surface first, then three candidate surfaces,
on true Void surfaces at the shipping type scale — fonts, palette and scale
re-derived from the repo at build time (2026-08-06-s147 / 2026-08-07-s148
generator convention) rather than hand-copied, so the board cannot drift from
what ships. Toast geometry is transcribed 1:1 from `components/Toast.tsx`'s
own inline style objects. Run:
  python 2026-08-07-s151-reminder-choice-board.py
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(r"c:\Users\biloh\Claude\Projects\Second Thought Full Codebase")
V2_MOCK = ROOT / "SecondThoughtV2.html"
HERE = Path(__file__).parent


# ── fonts: lifted verbatim from the approved V2 mock, not hand-copied ──────
def load_font_faces() -> str:
    html = V2_MOCK.read_text(encoding="utf-8")
    blocks = [b for b in re.findall(r"@font-face\s*\{[^}]*\}", html) if "IBM Plex Mono" in b]
    assert len(blocks) == 3, f"expected 3 IBM Plex Mono @font-face blocks (400/500/600), found {len(blocks)}"
    for b in blocks:
        assert "base64," in b, "font block has no embedded base64 payload"
    return "\n".join(blocks)


FONT_FACES = load_font_faces()

# ── real token/scale extraction — index.css (dark) is the source of truth ──
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
    assert m, f"lib/type.ts export `{name}` not found — scale drifted from source"
    SCALE[name] = int(m.group(1))
assert list(SCALE.values()) == [9, 10, 11, 12, 13, 16, 20, 22], f"type scale drifted: {SCALE}"

# ── icons: inline SVG only, stroke=currentColor ~1.7, 24-grid. CloseIcon is
# the one Toast.tsx actually renders; the clock is hand-drawn to the same
# convention because the repo has no export for it (icons.tsx ships
# MenuIcon/RefreshIcon/ChatIcon/MicIcon/CloseIcon only) — and because the
# shipped toast currently uses a literal emoji there, which the identity lock
# forbids. Same precedent as the s147 board's GEAR_ICON.


def ic(paths: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


CLOCK_ICON = ic('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>')
CLOSE_ICON = ic('<path d="M18 6 6 18"/><path d="M6 6l12 12"/>')
UNDO_ICON = ic('<path d="M4 9h11a5 5 0 0 1 0 10h-6"/><polyline points="8 5 4 9 8 13"/>')

CSS_VARS = "\n".join(f"  --{k}:{v};" for k, v in TOK.items())
CSS_SCALE = "\n".join(f"  --fs-{k}:{v}px;" for k, v in SCALE.items())

CSS = f"""
@charset "UTF-8";
{FONT_FACES}
:root{{
{CSS_VARS}
{CSS_SCALE}
  --track:0.01em;
  --space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:24px;--space-6:32px;--space-7:56px;
}}
*,*::before,*::after{{box-sizing:border-box;border-radius:0;}}
body{{margin:0;background:#050505;color:var(--text-1);
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono","Segoe UI Mono",monospace;
  font-size:var(--fs-read);line-height:1.55;letter-spacing:var(--track);
  -webkit-font-smoothing:antialiased;}}
svg{{display:block;width:100%;height:100%;}}
.wrap{{padding:0 var(--space-5) var(--space-7);max-width:880px;margin:0 auto;}}
.head{{padding:var(--space-6) var(--space-5) 0;max-width:880px;margin:0 auto;}}
.head h1{{font-size:var(--fs-hero);margin:0 0 var(--space-3);font-weight:600;letter-spacing:-0.01em;
  text-wrap:balance;}}
.head .sub{{color:var(--text-2);margin:0 0 var(--space-2);line-height:1.65;max-width:74ch;}}
.head .ruled{{color:var(--text-1);margin:0 0 var(--space-6);line-height:1.65;max-width:74ch;}}
h2{{font-size:var(--fs-title);margin:var(--space-7) 0 var(--space-3);font-weight:600;
  text-wrap:balance;}}
.wrap h2:first-child{{margin-top:0;}}
h2 .n{{color:var(--text-3);font-weight:400;font-size:var(--fs-body);margin-right:8px;}}
.lede{{color:var(--text-2);margin:0 0 var(--space-4);line-height:1.65;max-width:74ch;}}
.lede b{{color:var(--text-1);}}
code{{color:var(--text-1);background:#161616;padding:1px 4px;font-size:var(--fs-micro);}}
.cap{{font-size:var(--fs-label);letter-spacing:0.09em;color:var(--text-3);margin:0 0 6px;}}

/* ── the real toast, transcribed 1:1 from components/Toast.tsx's inline
   styles. The 3px tone stripe, --radius and the 11.5px body size are
   as-shipped facts, reproduced not corrected — this board asks about the
   toast's CONTENT, not its chrome. ── */
.stage{{background:var(--bg);border:1px solid var(--border);padding:var(--space-5);
  display:flex;flex-direction:column;gap:6px;align-items:flex-start;}}
.stage.pillstage{{align-items:center;padding:var(--space-6) var(--space-5);}}
.toast{{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:9px 10px 9px 12px;background:#141414;border:1px solid var(--border);
  border-left:3px solid var(--accent);box-shadow:0 6px 22px rgba(0,0,0,.55);
  min-width:200px;max-width:380px;}}
.toast.ok{{border-left-color:var(--green);}}
.toast .msg{{font-size:11.5px;color:var(--text-2);line-height:1.4;display:flex;
  align-items:center;gap:7px;}}
.toast .msg .ic{{width:12px;height:12px;color:var(--text-3);flex:0 0 auto;}}
.toast .msg b{{color:var(--text-1);font-weight:500;}}
.toast .rt{{display:flex;align-items:center;gap:6px;flex-shrink:0;}}
.toast .act{{background:none;border:1px solid var(--accent);color:var(--text-1);
  font-size:11px;line-height:1;padding:4px 8px;font-family:inherit;white-space:nowrap;}}
.toast .act.ok{{border-color:var(--green);}}
.toast .x{{color:var(--text-3);width:11px;height:11px;flex-shrink:0;}}

/* option A — the chip row. Same toast shell; `action` becomes `actions[]`. */
.toast.chips{{flex-direction:column;align-items:stretch;gap:8px;max-width:340px;}}
.toast.chips .row{{display:flex;align-items:center;justify-content:space-between;gap:10px;}}
.toast.chips .chiprow{{display:flex;gap:6px;flex-wrap:wrap;}}
.chip{{background:none;border:1px solid var(--border);color:var(--text-1);font-size:11px;
  line-height:1;padding:5px 8px;font-family:inherit;white-space:nowrap;}}
.chip.first{{border-color:var(--accent);}}

/* the truth strip — what the surface above actually DOES on the server */
.truth{{border:1px solid var(--border);border-left:3px solid var(--red);background:rgba(255,100,103,.06);
  padding:9px 12px;font-size:var(--fs-body);color:var(--text-2);line-height:1.6;max-width:74ch;
  margin-top:var(--space-3);}}
.truth.good{{border-left-color:var(--green);background:rgba(120,200,140,.05);}}
.truth b{{color:var(--text-1);}}
.truth .k{{color:var(--text-3);letter-spacing:.09em;font-size:var(--fs-micro);display:block;
  margin-bottom:3px;}}

/* pill / capsule bar — geometry from PillOverlay's idle bar */
.pill{{display:inline-flex;align-items:center;gap:9px;height:34px;padding:0 14px;
  background:#141414;border:1px solid var(--border);color:var(--text-1);
  font-size:var(--fs-body);white-space:nowrap;}}
.pill .ic{{width:12px;height:12px;color:var(--text-3);flex:0 0 auto;}}
.pill .hint{{color:var(--text-3);font-size:var(--fs-micro);letter-spacing:.06em;}}

.opt{{margin-bottom:var(--space-3);}}
.optname{{display:flex;align-items:baseline;gap:9px;margin:0 0 var(--space-3);}}
.optname .tag{{font-size:var(--fs-label);letter-spacing:.09em;color:var(--text-3);}}
.optname .nm{{font-size:var(--fs-lead);color:var(--text-1);font-weight:600;}}

table{{border-collapse:collapse;width:100%;margin-top:var(--space-4);font-size:var(--fs-body);}}
th,td{{border:1px solid var(--border);padding:7px 9px;text-align:left;vertical-align:top;
  line-height:1.55;}}
th{{color:var(--text-3);font-weight:400;font-size:var(--fs-label);letter-spacing:.06em;
  background:#111;}}
td b{{color:var(--text-1);}}
td.y{{color:var(--green);}}
td.n{{color:var(--red);}}
.scroll{{overflow-x:auto;}}
"""


def toast(msg_html: str, action: str | None, *, ok: bool = False) -> str:
    act = (f'<button class="act{" ok" if ok else ""}">{action}</button>') if action else ""
    return (f'<div class="toast{" ok" if ok else ""}">'
            f'<span class="msg"><span class="ic">{CLOCK_ICON}</span>{msg_html}</span>'
            f'<span class="rt">{act}<span class="x">{CLOSE_ICON}</span></span></div>')


def truth(kicker: str, body: str, *, good: bool = False) -> str:
    return f'<div class="truth{" good" if good else ""}"><span class="k">{kicker}</span>{body}</div>'


# ── the scenario every option renders, so they are comparable ──────────────
# A captured note whose body mentions three future instants.
D1, D2, D3 = "Fri 8 Aug 09:00", "Mon 11 Aug 14:30", "Fri 15 Aug 18:00"
L1, L2, L3 = "Standup", "Design review", "Retro"

CURRENT = (
    toast(f"<b>{L1}</b> &mdash; {D1} (+2 more)", "Set reminder")
    + truth("WHAT THE SERVER ACTUALLY DOES",
            f"Three POSTs to <code>/reminders</code>, one per date. Each one writes the note's single "
            f"<code>remind_at</code> scalar, so the third overwrites the first two. "
            f"<b>The toast names {D1} and the note ends up holding {D3}.</b> No error, no warning, "
            f"and the <code>(+2 more)</code> is a promise the data model cannot keep.")
)

OPT_A = (
    '<div class="toast chips">'
    f'<div class="row"><span class="msg"><span class="ic">{CLOCK_ICON}</span>'
    f'<b>3 dates</b> in this note</span><span class="x">{CLOSE_ICON}</span></div>'
    f'<div class="chiprow"><button class="chip first">{D1}</button>'
    f'<button class="chip">{D2}</button><button class="chip">{D3}</button></div>'
    '</div>'
    + truth("WHAT IT DOES",
            "One click, one POST, one reminder &mdash; and the user chose which. "
            "Costs <code>ToastItem.action</code> growing to an optional <code>actions[]</code> "
            "(<code>useToasts.ts</code> + <code>Toast.tsx</code>), which every other toast ignores. "
            "Chips wrap at 3; a 4th+ date is dropped with the count still truthful.", good=True)
)

OPT_B = (
    toast(f"<b>{L1}</b> &mdash; {D1}", "Set")
    + toast(f"<b>{L2}</b> &mdash; {D2}", "Set")
    + toast(f"<b>{L3}</b> &mdash; {D3}", "Set")
    + truth("WHAT IT DOES",
            "Three toasts, each with the action shape that already exists &mdash; "
            "<b>zero change to <code>Toast.tsx</code> or <code>useToasts.ts</code></b>. "
            "Picking any one creates it and dismisses its siblings. "
            "The cost is vertical: three stacked toasts is a loud answer to a quiet event, "
            "and <code>ToastHost</code> has no stack cap to lean on.", good=True)
)

OPT_C = (
    toast(f"<b>{L1}</b> &mdash; {D1} <span style='color:var(--text-3)'>&middot; 2 more dates in note</span>",
          "Set reminder")
    + truth("WHAT IT DOES",
            "Creates exactly the earliest date &mdash; the one it names. The suffix is "
            "informational, not clickable. <b>Smallest possible diff and it stops the silent "
            "collapse</b>, but it is not a choice: the ruling asked for an explicit single "
            "choice among the detected dates, and this offers one option, take it or leave it.")
)

PILL = (
    f'<div class="pill"><span class="ic">{CLOCK_ICON}</span>Reminder set &mdash; {D1}'
    f'<span class="ic" style="margin-left:2px">{UNDO_ICON}</span><span class="hint">TAP TO UNDO</span></div>'
    + truth("SHARED BY EVERY OPTION",
            f"Pill and capsule have no room for a chooser, so they keep auto-creating &mdash; but "
            f"<b>exactly one reminder, the earliest date</b>, and the bar now names it. "
            f"Today it fires all three and the bar reads <code>Reminder set (+2 more)</code>, "
            f"which is false twice over: three were attempted, one exists, and it is not the one "
            f"implied. <code>makeReminderUndoState</code>'s <code>+N more</code> suffix goes with it.",
            good=True)
)

HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>s151 — the reminder date choice</title>
<style>{CSS}</style></head><body>

<div class="head">
  <h1>Three dates, one slot</h1>
  <p class="sub">A captured note mentions <b>{D1}</b>, <b>{D2}</b> and <b>{D3}</b>.
  <code>App.tsx:894&ndash;936</code> offers to set reminders for all three. Since s148 made the note's
  frontmatter <code>remind_at</code> authoritative &mdash; one scalar instant, no label &mdash; only one
  of them can survive.</p>
  <p class="ruled">Ruled at s148.6: <b>the surface must become an explicit single choice among the
  detected dates.</b> The silent collapse is the defect, not the one-per-note limit. This board asks
  which shape that choice takes. Everything below is drawn on real Void surfaces at the shipping type
  scale, with the toast chrome transcribed from <code>Toast.tsx</code>.</p>
</div>

<div class="wrap">

<h2><span class="n">00</span>What ships today</h2>
<p class="lede">The current surface, unchanged. It is rendered here because a board that shows only
alternatives hides how bad the thing being replaced actually is.</p>
<div class="stage">{CURRENT}</div>

<h2><span class="n">A</span>Chips in the toast</h2>
<p class="lede">The toast stops naming one date and starts offering all of them. One glance, one click
&mdash; the shape the code comment already claims to want (<i>&ldquo;one glance + one click, never a
form&rdquo;</i>).</p>
<div class="stage">{OPT_A}</div>

<h2><span class="n">B</span>One toast per date</h2>
<p class="lede">Reuses the single-action toast that exists, N times. No new component capability at
all &mdash; the entire change lives in <code>App.tsx</code>.</p>
<div class="stage">{OPT_B}</div>

<h2><span class="n">C</span>Earliest only, no choice</h2>
<p class="lede">Stop lying, don't ask. The toast names the earliest date, creates exactly that, and
mentions the others as context the user can act on by hand.</p>
<div class="stage">{OPT_C}</div>

<h2><span class="n">05</span>Pill and capsule &mdash; the same answer either way</h2>
<p class="lede">The compact shells have no room for a chooser and already auto-create with an undo
window. That posture is unchanged; only the count and the copy are.</p>
<div class="stage pillstage">{PILL}</div>

<h2><span class="n">06</span>What each one costs</h2>
<div class="scroll">
<table>
<tr><th>&nbsp;</th><th>A &mdash; chips</th><th>B &mdash; one per date</th><th>C &mdash; earliest only</th></tr>
<tr><td><b>Satisfies the s148.6 ruling</b></td><td class="y">yes</td><td class="y">yes</td><td class="n">no &mdash; offers no choice</td></tr>
<tr><td><b>Files touched</b></td><td>App.tsx, Toast.tsx, useToasts.ts</td><td>App.tsx</td><td>App.tsx</td></tr>
<tr><td><b>New component capability</b></td><td><code>actions[]</code> on ToastItem</td><td>none</td><td>none</td></tr>
<tr><td><b>Vertical space at 3 dates</b></td><td>one toast, two rows</td><td>three toasts</td><td>one toast, one row</td></tr>
<tr><td><b>Behaviour at 1 date</b></td><td>single chip &mdash; reads oddly, needs a fallback to today's shape</td><td>identical to today</td><td>identical to today</td></tr>
<tr><td><b>Behaviour at 6 dates</b></td><td>chips wrap; cap at 3 + truthful count</td><td>six toasts &mdash; unacceptable, needs its own cap</td><td>unchanged</td></tr>
<tr><td><b>Runnable check it leaves behind</b></td><td>pure chip-list builder + its test</td><td>sibling-dismiss reducer + its test</td><td>earliest-of-N picker + its test</td></tr>
</table>
</div>

<h2><span class="n">07</span>Two things that ride along regardless</h2>
<p class="lede">Both are on the exact lines being rewritten, so they are not scope creep &mdash; they
are the cost of touching this code honestly.</p>
<div class="truth"><span class="k">IDENTITY LOCK VIOLATION, SHIPPED</span>
<code>App.tsx:916</code> puts a literal <b>emoji</b> in the toast message. The lock is
<i>&ldquo;inline SVG only &mdash; never emoji, in app, mocks, or decision previews&rdquo;</i>.
Every toast above draws a real 24-grid stroke icon instead; <code>ToastItem</code> gains an optional
icon slot, or the glyph simply goes.</div>
<div class="truth"><span class="k">TYPE SCALE, PRE-EXISTING</span>
<code>Toast.tsx</code> hard-codes <b>11.5px</b>, 11px and 13px. 11.5 is a banned half-step and all
three are raw px. Reproduced as-shipped above rather than quietly corrected &mdash; this belongs to
<b>P3-F</b>'s source-level sweep, and is recorded here so that sweep has one more known site.</div>

</div></body></html>
"""

assert "\x00" not in HTML, "board HTML contains a NUL byte"
out = HERE / "2026-08-07-s151-reminder-choice-board.html"
out.write_text(HTML, encoding="utf-8")

# Artifact variant: the publish path wraps content in its own doctype/head/body,
# so emit the same page WITHOUT those tags. Deliberately single-theme — this board
# renders the product's own dark surfaces at 1:1, so a light variant would be
# showing the user a surface that does not exist.
BODY = HTML.split("<body>", 1)[1].rsplit("</body>", 1)[0]
art = HERE / "2026-08-07-s151-reminder-choice-board.artifact.html"
art.write_text(
    f'<title>s151 — the reminder date choice</title>\n<style>{CSS}</style>\n{BODY}',
    encoding="utf-8",
)

print(f"wrote {out}  ({len(HTML):,} bytes)")
print(f"wrote {art} ({art.stat().st_size:,} bytes)")
print(f"tokens: {len(TOK)}  scale: {SCALE}")
