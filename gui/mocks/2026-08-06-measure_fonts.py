"""Ground truth for the Phase 2 geometry gate, read straight out of the font binaries.

Independent of any browser: parses hmtx advances and the cmap, so it answers two questions the
plan currently assumes rather than verifies:
  1. Does IBM Plex Mono's advance actually differ from Geist Mono's?
  2. Does the V2 mock's Plex subset cover the glyphs the specimen uses?
"""
import base64, io, re, sys
from fontTools.ttLib import TTFont

ROOT = r"c:\Users\biloh\Claude\Projects\Second Thought Full Codebase"
GEIST = ROOT + r"\Second Thought\gui\node_modules\@fontsource\geist-mono\files\geist-mono-latin-{w}-normal.woff2"

LABEL = "Second Thought"
PROBES = "\u00b7\u2014\u2013\u2605\u2192\u201c\u2026\u00d7#@"


def load_plex():
    """Lift the base64 payloads out of the approved V2 mock."""
    html = open(ROOT + r"\SecondThoughtV2.html", encoding="utf-8").read()
    out = {}
    for block in re.findall(r"@font-face\s*\{[^}]*\}", html):
        if "IBM Plex Mono" not in block:
            continue
        w = int(re.search(r"font-weight:(\d+)", block).group(1))
        b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", block).group(1)
        out[w] = TTFont(io.BytesIO(base64.b64decode(b64)))
    return out


def advances(font):
    """Distinct advance widths in font units, plus units-per-em."""
    upem = font["head"].unitsPerEm
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    widths = {hmtx[cmap[ord(c)]][0] for c in LABEL if ord(c) in cmap}
    return upem, widths


def label_px(font, size_px, tracking_em):
    upem, _ = advances(font)
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    total = 0.0
    for ch in LABEL:
        if ord(ch) not in cmap:
            return None
        total += hmtx[cmap[ord(ch)]][0] / upem * size_px
    return total + tracking_em * size_px * len(LABEL)


def missing(font, chars):
    cmap = font.getBestCmap()
    return [c for c in chars if ord(c) not in cmap]


plex = load_plex()
geist = {w: TTFont(GEIST.format(w=w)) for w in (400, 500, 600)}

print("=== advance widths (weight 500, the capsule label's weight) ===")
for name, f in (("Geist Mono", geist[500]), ("IBM Plex Mono", plex[500])):
    upem, widths = advances(f)
    per_em = sorted(w / upem for w in widths)
    print(f"{name:16} upem={upem:5}  advance/em={per_em}  -> {per_em[0]*12:.4f}px at 12px")

print()
print("=== 'Second Thought' at 12px / weight 500 ===")
print(f"{'config':38} {'width':>10}  {'vs bar':>10}")
BAR, INSET = 154, 35
rows = [
    ("A  Geist Mono, tracking 0",        geist[500], 0.0),
    ("A' Geist Mono, tracking 0.01em",   geist[500], 0.01),
    ("B  IBM Plex Mono, tracking 0.01em", plex[500], 0.01),
    ("C  IBM Plex Mono, tracking 0",      plex[500], 0.0),
]
for name, f, tr in rows:
    w = label_px(f, 12, tr)
    if w is None:
        print(f"{name:38} {'GLYPH MISSING':>10}")
        continue
    slack = BAR - INSET - w
    print(f"{name:38} {w:9.4f}px {slack:9.4f}px slack")

print()
print("committed baseline recorded 100.8125px on the real binary -> row A is the calibration check")

print()
print("=== glyph coverage in the mock's Plex subset ===")
for w, f in sorted(plex.items()):
    gone = missing(f, PROBES)
    print(f"Plex {w}: " + ("all present" if not gone else "MISSING " + " ".join(gone)))
for w, f in sorted(geist.items()):
    gone = missing(f, PROBES)
    print(f"Geist {w}: " + ("all present" if not gone else "MISSING " + " ".join(gone)))
