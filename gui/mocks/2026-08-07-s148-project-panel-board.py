"""Generate the s148 project-panel decision board (v2 — cropped, decluttered).

Renders BROWSE's real drill-in and the old ProjectsPane's real management
strip on true Void surfaces at the shipping type scale, re-deriving fonts and
tokens from the repo at build time (2026-08-06-s147-calendar-board.py's
pattern) rather than hand-copying values. Run:
  python 2026-08-07-s148-project-panel-board.py

v2 rewrite (user rejection): the app chrome (titlebar+5-tab rail) was drawn
once per panel and was 90% of the pixels. Now it is drawn exactly ONCE, near
the top, as labelled context; every option panel after that is CROPPED to
the drill-in region only (title row + affordance + note rows), no window
chrome. Nine equal-weight state panels became one hero RESTING panel per
option with ACTIVE/DELETE-CONFIRM as visibly smaller secondaries. Section 3's
nine renderings became a 4x3 table. Prose cut by roughly half throughout.
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
    assert len(blocks) == 3, f"expected 3 IBM Plex Mono @font-face blocks (400/500/600) in V2 mock, found {len(blocks)}"
    for b in blocks:
        assert "base64," in b, "font block has no embedded base64 payload"
    return "\n".join(blocks)


FONT_FACES = load_font_faces()

# ── icons: inline SVG only, stroke=currentColor ~1.7, 24-grid — exact paths
# pulled from gui/src/components/PillMenu/icons.tsx and NoteEditor.tsx's
# MoreIcon so the board's chrome matches the shipped app, not an approximation.
def ic(paths: str, *, vb: str = "0 0 24 24") -> str:
    return (f'<svg viewBox="{vb}" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


BACK_ICON = ic('<path d="M15 6l-6 6 6 6"/>')
PENCIL_ICON = ic('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>')
TRASH_ICON = ic('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>'
                '<path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>')
CHECK_ICON = ic('<polyline points="4 12 9 17 20 6"/>')
CLOSE_ICON = ic('<path d="M18 6 6 18"/><path d="M6 6l12 12"/>')
FILE_ICON = ic('<path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z"/>'
               '<polyline points="14 3 14 7 18 7"/>')
MORE_ICON = ic('<circle cx="12" cy="5.5" r="1.3" fill="currentColor"/>'
               '<circle cx="12" cy="12" r="1.3" fill="currentColor"/>'
               '<circle cx="12" cy="18.5" r="1.3" fill="currentColor"/>')
# Not in icons.tsx (no repo export) — hand-drawn to the same stroke
# convention, same as the calendar board's own GEAR_ICON precedent for a
# symbol the repo hasn't needed an export for yet.
SLIDERS_ICON = ic('<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/>'
                   '<circle cx="15" cy="7" r="2.3" fill="var(--bg)"/>'
                   '<circle cx="7" cy="17" r="2.3" fill="var(--bg)"/>')
GEAR_ICON = ic('<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3'
               'M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/>')
RAIL_ICONS = {
    "NOTES": ic('<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h5"/>'),
    "BROWSE": ic('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.5-4.5"/>'),
    "CHAT": ic('<path d="M4 5h16v11H9l-5 4z"/>'),
    "SYNC": ic('<path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14.8-3.4M4 14a8 8 0 0 0 14.8 3.4"/>'),
    "SET": GEAR_ICON,
}

# ── real token/scale extraction — index.css (dark) is the source of truth;
# the type scale is lib/type.ts's own exported constants, transcribed with
# an assertion, not invented. ──────────────────────────────────────────────
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
.wrap{{padding:0 var(--space-5) var(--space-7);max-width:900px;margin:0 auto;}}
.head{{padding:var(--space-6) var(--space-5) 0;max-width:900px;margin:0 auto;}}
.head h1{{font-size:var(--fs-hero);margin:0 0 var(--space-3);font-weight:600;letter-spacing:-0.01em;}}
.head .sub{{color:var(--text-2);margin:0 0 var(--space-2);line-height:1.65;}}
.head .ruled{{color:var(--text-1);margin:0 0 var(--space-6);line-height:1.65;}}
.head .ruled b{{color:var(--text-1);}}
h2{{font-size:var(--fs-title);margin:var(--space-7) 0 var(--space-3);font-weight:600;}}
.wrap h2:first-child{{margin-top:0;}}
h2 .n{{color:var(--text-3);font-weight:400;font-size:var(--fs-body);margin-right:8px;}}
.lede{{color:var(--text-2);margin:0 0 var(--space-4);line-height:1.65;max-width:80ch;}}
.lede b{{color:var(--text-1);}}
code{{color:var(--text-1);background:#161616;padding:1px 4px;font-size:var(--fs-micro);}}
.cap{{font-size:var(--fs-label);letter-spacing:0.09em;color:var(--text-3);margin:0 0 6px;}}
.cap.dim{{font-size:var(--fs-micro);color:var(--text-3);opacity:.75;}}

/* ── context window — the ONLY place the full app chrome is drawn ── */
.ctx-note{{color:var(--text-3);font-size:var(--fs-body);margin:0 0 var(--space-3);line-height:1.6;}}
.win{{border:1px solid var(--border);background:var(--bg);display:flex;flex-direction:column;
  width:520px;height:300px;overflow:hidden;}}
.win .titlebar{{display:flex;align-items:center;gap:10px;padding:8px 14px;
  border-bottom:1px solid var(--border);background:#191919;font-size:var(--fs-label);
  color:var(--text-3);flex:0 0 auto;}}
.win .titlebar .app{{color:var(--text-1);font-weight:600;letter-spacing:.1em;}}
.win .body{{flex:1;display:flex;min-height:0;}}
.win .rail{{width:64px;border-right:1px solid var(--border);padding:8px 0;display:flex;
  flex-direction:column;gap:2px;flex:0 0 auto;}}
.win .rail i{{display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 0;
  color:var(--text-3);font-size:7px;letter-spacing:.06em;border-left:2px solid transparent;}}
.win .rail i svg{{width:13px;height:13px;}}
.win .rail i.on{{color:var(--text-1);border-left-color:var(--text-1);}}
.win .scr{{flex:1;min-width:0;display:flex;flex-direction:column;}}
.markregion{{outline:1px dashed var(--accent);outline-offset:-1px;position:relative;}}
.markregion .tag{{position:absolute;top:-1px;left:-1px;transform:translateY(-100%);
  font-size:8px;letter-spacing:.08em;color:var(--accent);white-space:nowrap;padding-bottom:2px;}}

/* ── cropped drill-in fragments — the only thing every panel below the
   context window draws. No rail, no titlebar, no app name. Transcribed 1:1
   from BrowseView.tsx's own inline style objects. ── */
.crop{{border:1px solid var(--border);background:var(--bg);}}
.crop.hero{{max-width:460px;}}
.sub-head{{display:flex;align-items:center;gap:9px;padding:10px 12px;
  border-bottom:1px solid var(--border-2);}}
.sub-back{{background:none;border:none;color:var(--text-3);cursor:pointer;padding:1px;
  display:inline-flex;width:14px;height:14px;flex:0 0 auto;}}
.sub-title{{font-size:var(--fs-lead);font-weight:600;color:var(--text-1);margin:0;flex:0 1 auto;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.sub-cnt{{margin-left:auto;font-size:var(--fs-label);color:var(--text-3);flex:0 0 auto;
  white-space:nowrap;}}
.note-row{{display:flex;align-items:center;gap:9px;padding:8px 12px;
  border-bottom:1px solid var(--border-2);color:var(--text-2);}}
.note-row:last-child{{border-bottom:none;}}
.note-row .ic{{flex:0 0 auto;color:var(--text-3);width:11px;height:11px;}}
.note-row .t{{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:var(--fs-read);color:var(--text-1);}}
.note-row .m{{flex:0 0 auto;font-size:var(--fs-label);color:var(--text-3);}}

/* ── OLD ProjectsPane head — faithful transcription (predates the shared
   type scale: lib/type.ts postdates this file, so its raw px literals are
   historical fact, kept as-shipped, not this board's own new-surface rule). */
.pp-top{{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:10px 12px;border-bottom:1px solid var(--border-2);}}
.pp-name{{font-size:15px;font-weight:600;color:var(--text-1);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}}
.pp-icons{{display:flex;gap:2px;flex:0 0 auto;}}
.pp-iconbtn{{width:24px;height:24px;display:flex;align-items:center;justify-content:center;
  color:var(--text-3);background:none;border:1px solid transparent;flex:0 0 auto;}}
.pp-iconbtn svg{{width:12px;height:12px;}}

/* ── the one legitimate danger state, verbatim copy from confirmStripStyle */
.confirm{{background:rgba(255,100,103,.08);padding:8px 12px;display:flex;align-items:center;
  gap:9px;border-bottom:1px solid var(--border-2);}}
.confirm .txt{{font-size:10.5px;color:var(--text-2);flex:1 1 auto;line-height:1.55;}}
.confirm .txt b{{color:var(--text-1);}}
.ghost{{display:inline-flex;align-items:center;gap:4px;font-size:9.5px;color:var(--text-2);
  border:1px solid var(--border);background:var(--bg);padding:4px 7px;white-space:nowrap;
  flex:0 0 auto;}}
.ghost.danger{{border-color:var(--red);color:var(--red);}}

/* ── section 0 comparison — two crops side by side, no bordered header
   wrapped around them (that was a card-inside-a-card) ── */
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-5);}}
.gapbox{{margin:var(--space-4) 0 0;}}
.gapbox ul{{margin:0;padding-left:1.1rem;color:var(--text-2);font-size:var(--fs-body);}}
.gapbox li{{margin-bottom:5px;line-height:1.5;}}
.gapbox li b{{color:var(--text-1);}}

.flagbox{{border-left:2px solid var(--yellow);padding:2px 0 2px 14px;margin:var(--space-4) 0 0;}}
.flagbox .ft{{font-size:var(--fs-label);letter-spacing:.08em;color:var(--yellow);margin:0 0 6px;}}
.flagbox p{{margin:0;color:var(--text-2);font-size:var(--fs-body);line-height:1.6;}}
.flagbox b{{color:var(--text-1);}}

/* ── options: one hero RESTING panel, ACTIVE/DELETE-CONFIRM subordinate
   underneath at reduced size and reduced label contrast ── */
.optblock{{margin-top:var(--space-6);}}
.optblock .cap{{font-size:var(--fs-body);color:var(--text-1);margin-bottom:2px;}}
.optblock .rationale{{color:var(--text-3);font-size:var(--fs-body);font-weight:400;}}
.sec{{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4);margin-top:var(--space-3);
  max-width:460px;}}

/* option A: 3-dot overflow menu (menuBtnStyle/menuDropStyle/menuRowStyle,
   transcribed from NoteEditor.tsx, the pattern this option mirrors) */
.a-more{{width:20px;height:20px;display:flex;align-items:center;justify-content:center;
  color:var(--text-2);background:none;border:1px solid transparent;flex:0 0 auto;}}
.a-more.active{{background:var(--surface);border-color:var(--accent);color:var(--text-1);}}
.a-more svg{{width:14px;height:14px;}}
.a-menu-wrap{{position:relative;}}
.a-menu{{position:absolute;top:100%;right:0;width:128px;background:var(--surface);
  border:1px solid var(--border);z-index:2;margin-top:5px;}}
.a-menu .row{{display:flex;align-items:center;gap:7px;padding:6px 9px;font-size:11px;
  color:var(--text-2);}}
.a-menu .row svg{{width:11px;height:11px;flex:0 0 auto;}}
.a-menu .row.danger{{color:var(--red);}}

/* option B: inline-editable title + footer danger strip */
.b-title{{border-bottom:1px dashed var(--text-3);padding-bottom:1px;}}
.b-title-input{{flex:1 1 auto;min-width:0;background:var(--bg);border:1px solid var(--border);
  color:var(--text-1);font-family:inherit;font-size:var(--fs-lead);font-weight:600;padding:2px 6px;}}
.b-foot{{border-top:1px solid var(--border);padding:7px 12px;display:flex;justify-content:flex-end;}}

/* option C: quiet manage-reveal */
.c-manage-btn{{width:20px;height:20px;display:flex;align-items:center;justify-content:center;
  color:var(--text-3);background:none;border:1px solid transparent;flex:0 0 auto;}}
.c-manage-btn.active{{color:var(--text-1);border-color:var(--border);}}
.c-manage-btn svg{{width:13px;height:13px;}}
.c-row{{border-bottom:1px solid var(--border-2);background:var(--ctl-face);padding:8px 12px;
  display:flex;align-items:center;gap:7px;}}
.c-row input{{flex:1 1 auto;min-width:0;background:var(--bg);border:1px solid var(--border);
  color:var(--text-1);font-family:inherit;font-size:var(--fs-body);padding:3px 6px;}}

/* ── section 3: one compact table, not nine renderings ── */
table{{width:100%;border-collapse:collapse;font-size:var(--fs-body);margin-top:var(--space-2);}}
th,td{{text-align:left;padding:8px 12px;border:1px solid var(--border-2);vertical-align:top;}}
th{{color:var(--text-3);font-weight:600;font-size:var(--fs-label);letter-spacing:.06em;
  border-color:var(--border);}}
td{{color:var(--text-2);line-height:1.5;}}
td:first-child{{color:var(--text-1);font-weight:600;white-space:nowrap;}}
td .yel{{color:var(--yellow);}}

footer{{max-width:900px;margin:var(--space-7) auto 0;padding:0 var(--space-5);
  color:var(--text-3);font-size:var(--fs-micro);border-top:1px solid var(--border-2);
  padding-top:var(--space-3);line-height:1.6;}}
"""

# ── content builders ────────────────────────────────────────────────────

def rail(active: str) -> str:
    return '<div class="rail">' + "".join(
        f'<i class="{"on" if k == active else ""}">{svg}<span>{k}</span></i>'
        for k, svg in RAIL_ICONS.items()
    ) + "</div>"


def titlebar() -> str:
    return '<div class="titlebar"><span class="app">SECOND THOUGHT</span><span>Browse</span></div>'


NOTE_ROWS = [
    ("Port plan — phase 3 notes", "2h ago"),
    ("Rail geometry measurements", "1d ago"),
    ("BrowseView search debounce", "3d ago"),
]


def note_rows(n: int) -> str:
    return "".join(
        f'<div class="note-row"><span class="ic">{FILE_ICON}</span>'
        f'<span class="t">{t}</span><span class="m">{m}</span></div>'
        for t, m in NOTE_ROWS[:n]
    )


def bare_subhead(extra: str = "") -> str:
    return ('<div class="sub-head">'
            f'<button class="sub-back">{BACK_ICON}</button>'
            '<h4 class="sub-title">void-migration</h4>'
            '<span class="sub-cnt">14 notes</span>' + extra + '</div>')


DELETE_TXT = ('Delete <b>void-migration</b>? Its 14 notes become loose. None is deleted, trashed or '
              'edited, and none moves on disk yet.')


def confirm_strip() -> str:
    return (f'<div class="confirm"><span class="txt">{DELETE_TXT}</span>'
            '<button class="ghost">Cancel</button>'
            '<button class="ghost danger">Delete project only</button></div>')


# ── context window (chrome drawn exactly once) ──────────────────────────

def context_section() -> str:
    marked = ('<div class="markregion"><span class="tag">cropped below</span>'
              + bare_subhead() + note_rows(2) + '</div>')
    return (
        '<p class="ctx-note">Real window proportions, chrome drawn once. Every panel below is '
        'cropped to the dashed region only — no rail, no titlebar, no app name.</p>'
        '<div class="win">' + titlebar() + '<div class="body">' + rail("BROWSE")
        + f'<div class="scr">{marked}</div></div></div>'
    )


# ── panel 0: current state ──────────────────────────────────────────────

def section0() -> str:
    old_crop = ('<div class="crop"><div class="pp-top"><span class="pp-name">void-migration</span>'
                f'<span class="pp-icons"><button class="pp-iconbtn">{PENCIL_ICON}</button>'
                f'<button class="pp-iconbtn">{TRASH_ICON}</button></span></div>'
                + note_rows(2) + '</div>')
    new_crop = f'<div class="crop">{bare_subhead()}{note_rows(2)}</div>'

    P = ['<h2><span class="n">0</span>What ships today</h2>']
    P.append('<p class="lede">Same project, two surfaces. Left: <code>ProjectsPane.tsx</code>, still '
              'shipping — pill-only (<code>VaultManager.tsx</code>). Right: the same project in '
              'BROWSE\'s drill-in, full window, today.</p>')
    P.append('<div class="pair">'
              '<div><div class="cap">PILL &middot; COMPACT VAULT</div>' + old_crop + '</div>'
              '<div><div class="cap">BROWSE DRILL-IN &middot; FULL WINDOW</div>' + new_crop + '</div>'
              '</div>')
    P.append('<div class="gapbox"><ul>')
    P.append('<li><b>Rename</b> — pencil, inline input. <code>ProjectsPane.tsx:663-664</code></li>')
    P.append('<li><b>Delete</b> — trash, red confirm strip. <code>ProjectsPane.tsx:666-674</code></li>')
    P.append('<li><b>Description editing</b> — saves-as-you-type. <code>ProjectsPane.tsx:679-687</code></li>')
    P.append('<li><b>Tidy-preview</b> — post-rename/delete file-move strip. <code>ProjectsPane.tsx:754-793</code></li>')
    P.append('<li><b>Folder-import</b> — offer + checklist. <code>ProjectsPane.tsx:781-807</code></li>')
    P.append('</ul><p style="margin:8px 0 0;color:var(--text-3);font-size:var(--fs-micro)">'
              'Not pictured: a copy-project-tag chip (FR-21) also stays pill-only, out of scope here.</p>'
              '</div>')
    return "\n".join(P)


def fr36_box() -> str:
    return (
        '<div class="flagbox"><p class="ft">FR-36 — STATED AS FACT</p>'
        '<p>BROWSE\'s project tiles go stale after a folder-import until you navigate away and back — '
        'the refetch needs an <code>onApplied</code> seam BROWSE does not have '
        '(<code>BrowseView.tsx:78-83</code>). <b>If folder-import stays pill-only, that seam can never '
        'exist inside BROWSE, and FR-36 stays open by construction.</b></p></div>'
    )


# ── rename + delete options ─────────────────────────────────────────────

def option_a() -> str:
    resting = bare_subhead(
        '<div class="a-menu-wrap"><button class="a-more">' + MORE_ICON + '</button></div>'
    ) + note_rows(2)
    active = bare_subhead(
        '<div class="a-menu-wrap"><button class="a-more active">' + MORE_ICON + '</button>'
        '<div class="a-menu">'
        f'<div class="row">{PENCIL_ICON}Rename</div>'
        f'<div class="row">{FILE_ICON}Set description</div>'
        f'<div class="row danger">{TRASH_ICON}Delete project</div>'
        '</div></div>'
    ) + note_rows(1)
    confirm = bare_subhead(
        '<div class="a-menu-wrap"><button class="a-more">' + MORE_ICON + '</button></div>'
    ) + confirm_strip()

    return option_block(
        "OPTION A", "3-dot overflow menu",
        "Mirrors the note editor's own &ldquo;More&rdquo; menu (<code>NoteEditor.tsx:780-793</code>) — danger last.",
        resting, [("ACTIVE", active), ("DELETE CONFIRM", confirm)],
    )


def option_b() -> str:
    resting = bare_subhead().replace('class="sub-title"', 'class="sub-title b-title"') \
        + note_rows(2) + f'<div class="b-foot"><button class="ghost danger">Delete project</button></div>'
    active = ('<div class="sub-head">'
              f'<button class="sub-back">{BACK_ICON}</button>'
              '<input class="b-title-input" value="void-migration">'
              f'<button class="pp-iconbtn" style="color:var(--text-1)">{CHECK_ICON}</button>'
              f'<button class="pp-iconbtn">{CLOSE_ICON}</button>'
              '<span class="sub-cnt">14 notes</span></div>' + note_rows(1))
    confirm = bare_subhead().replace('class="sub-title"', 'class="sub-title b-title"') \
        + confirm_strip()

    return option_block(
        "OPTION B", "inline-editable title, footer danger strip",
        "Click the title to rename; delete sits in a footer, away from the title, so it can't be hit by accident.",
        resting, [("ACTIVE — EDITING", active), ("DELETE CONFIRM", confirm)],
    )


def option_c() -> str:
    resting = bare_subhead(f'<button class="c-manage-btn">{SLIDERS_ICON}</button>') + note_rows(2)
    active = (bare_subhead(f'<button class="c-manage-btn active">{SLIDERS_ICON}</button>')
              + '<div class="c-row"><input value="void-migration">'
              f'<button class="pp-iconbtn" style="color:var(--text-1)">{CHECK_ICON}</button>'
              f'<button class="ghost danger">{TRASH_ICON}Delete</button></div>')
    confirm = bare_subhead(f'<button class="c-manage-btn active">{SLIDERS_ICON}</button>') + confirm_strip()

    return option_block(
        "OPTION C", "quiet manage reveal, collapsed by default",
        "A sliders icon (distinct from the editor's kebab) expands one row holding rename + delete. Zero header chrome until opened.",
        resting, [("ACTIVE — EXPANDED", active), ("DELETE CONFIRM", confirm)],
    )


def option_block(tag: str, name: str, rationale: str, resting: str, secondaries: list[tuple[str, str]]) -> str:
    sec_cols = "".join(
        f'<div><div class="cap dim">{lbl}</div><div class="crop">{inner}</div></div>'
        for lbl, inner in secondaries
    )
    return (
        f'<div class="optblock"><div class="cap"><b>{tag}</b> — {name} '
        f'<span class="rationale">{rationale}</span></div>'
        f'<div class="cap dim">RESTING</div>'
        f'<div class="crop hero">{resting}</div>'
        f'<div class="sec">{sec_cols}</div></div>'
    )


def section2() -> str:
    P = ['<h2><span class="n">2</span>Rename + delete, inside the drill-in</h2>']
    P.append('<p class="lede">Ruled already: <b>&ldquo;project rename and delete features can exist '
              'when the project panel is opened&rdquo;</b> — inside the drill-in, not on BROWSE\'s home '
              'surface. All three reuse the same confirm-strip copy and danger styling.</p>')
    P.append(option_a() + option_b() + option_c())
    return "\n".join(P)


# ── section 3: compact table, not nine renderings ───────────────────────

def section3() -> str:
    rows = [
        ("Description editing", "Textarea under the head, saves as you type.",
         "A per-project field in a settings list.", "Unchanged — VaultManager only."),
        ("Tidy-preview strip", "Appears after a rename/delete, same trigger.",
         "A vault-wide &ldquo;Tidy vault&rdquo; action, no per-project trigger.",
         "Unchanged — fires only from the pill's pane."),
        ("Folder-import offer", "Re-opens the FR-36 <code>onApplied</code> seam.",
         "A vault-wide &ldquo;Import folder&rdquo; action.",
         '<span class="yel">Unchanged — FR-36 stays open.</span>'),
    ]
    body = "".join(
        f"<tr><td>{name}</td><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for name, a, b, c in rows
    )
    return (
        '<h2><span class="n">3</span>A separate question — not ruled on yet</h2>'
        '<p class="lede">Description editing, tidy-preview and folder-import were not named in the '
        '&ldquo;rename and delete&rdquo; ruling. Independent of section 2 and of each other.</p>'
        '<table><tr><th>Capability</th><th>In the drill-in</th><th>In SET/Settings</th>'
        f'<th>Pill-only</th></tr>{body}</table>'
        + fr36_box()
    )


def build() -> str:
    P = []
    A = P.append
    A('<title>Project panel — rename, delete &amp; the drill-in board</title>')
    A(f"<style>{CSS}</style>")
    A('<div class="head"><h1>Project rename, delete &amp; the BROWSE drill-in — s148 decision board</h1>')
    A('<p class="sub">BROWSE shipped search, tiles, tags and a LIST/STARS toggle — none of the old '
      'panel\'s management affordances. Nothing here is implemented; this is the set of options to '
      'choose from.</p>')
    A('<p class="ruled">Rendered at the shipping face and scale (IBM Plex Mono, fonts embedded; '
      '9/10/11/12/13/16/20/22, half-steps banned) on 0-radius bordered surfaces, dark only. Red is the '
      'one legitimate danger state, used only for delete.</p></div>')
    A('<div class="wrap">')
    A(context_section())
    A(section0())
    A(section2())
    A(section3())
    A('<footer>Re-read at build time, not carried from a prior draft: <b>ProjectsPane.tsx</b>, '
      '<b>BrowseView.tsx</b>, <b>NoteEditor.tsx</b>, <b>index.css</b>, <b>lib/type.ts</b>. Pick one '
      'option from section 2; answer section 3\'s three rows independently.</footer>')
    A('</div>')
    return "\n".join(P)


if __name__ == "__main__":
    body = build()
    head_bits = re.match(r"(<title>.*?</title>\s*<style>.*?</style>)", body, re.S)
    assert head_bits, "title/style block not found at top of generated body"
    rest = body[head_bits.end():]
    doc = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n{head_bits.group(1)}\n'
           f'</head><body>\n{rest}\n</body></html>')

    assert "\x00" not in doc, "NUL byte in generated board"
    assert doc.count("@font-face") == 3, "expected exactly 3 embedded @font-face blocks (400/500/600)"
    assert doc.count("base64,") == 3, "font payloads missing"
    assert "\u2192" not in doc, "banned arrow character (use \u00bb) found in output"
    assert not re.search(r'https?://', doc), "external reference found — must be fully self-contained"
    assert not re.search(r'<(script|link|img)\b[^>]*\bsrc=["\']https?:', doc), "external asset src found"
    EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
    assert not EMOJI_RE.search(doc), "emoji character found in generated board"
    assert doc.count('class="win"') == 1, "app chrome must be drawn exactly once"
    assert doc.count('class="optblock"') == 3, "expected 3 rename/delete option blocks"
    assert doc.count("DELETE CONFIRM") == 3, "expected one delete-confirm state per option"
    assert doc.count("<table") == 1 and doc.count("<tr") == 4, "expected one 4-row table in section 3"
    assert "FR-36" in doc, "FR-36 callout missing"

    out = HERE / "2026-08-07-s148-project-panel-board.html"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out} ({len(doc)} bytes)")
