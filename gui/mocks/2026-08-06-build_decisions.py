# Builds the s145 decision board: embeds the real fonts, and derives the size
# histograms straight from the two repos + the V2 mock so no number is hand-copied.
import base64, io, re, subprocess, sys
from collections import Counter
from pathlib import Path
from fontTools.ttLib import TTFont

ROOT = Path(r"c:\Users\biloh\Claude\Projects\Second Thought Full Codebase")
HERE = Path(__file__).parent
FS = ROOT / "Second Thought/gui/node_modules/@fontsource/ibm-plex-mono/files"
FULL_TTF = ROOT / "Second Thought - Android App/phone/assets/fonts/IBMPlexMono.ttf"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def ttf_to_woff2(path: Path) -> bytes:
    f = TTFont(str(path))
    f.flavor = "woff2"
    buf = io.BytesIO()
    f.save(buf)
    return buf.getvalue()


# ── size counts, re-derived ───────────────────────────────────────────────────
def counts_from(paths, pattern):
    c = Counter()
    rx = re.compile(pattern)
    for base in paths:
        for p in Path(base).rglob("*"):
            if not p.is_file() or p.suffix not in (".ts", ".tsx", ".css", ".html"):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in rx.finditer(txt):
                c[float(m.group(1))] += 1
    return c


desk = counts_from([ROOT / "Second Thought/gui/src"], r"fontSize:\s*([0-9.]+)")
desk += counts_from([ROOT / "Second Thought/gui/src"], r"font-size:\s*([0-9.]+)px")
phone = counts_from(
    [ROOT / "Second Thought - Android App/phone/src", ROOT / "Second Thought - Android App/phone/app"],
    r"fontSize:\s*([0-9.]+)",
)
mock = Counter()
for m in re.finditer(r"font-size:\s*([0-9.]+)px", (ROOT / "SecondThoughtV2.html").read_text(encoding="utf-8", errors="ignore")):
    mock[float(m.group(1))] += 1

BUCKETS = [7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 16, 17, 18, 19, 20, 21, 22]
HALF = {7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5}
LABELLED = {8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 22}


def bars(c: Counter) -> str:
    vals = [c.get(b, 0) for b in BUCKETS]
    top = max(vals) or 1
    peak = max(vals)
    out = []
    for b, v in zip(BUCKETS, vals):
        cls = "bar"
        if b in HALF and v:
            cls += " half"
        elif v == peak and v:
            cls += " hi"
        h = round(v / top * 100)
        title = f"{b:g}px — {v} site{'' if v == 1 else 's'}"
        out.append(f'<span class="{cls}" title="{title}"><i style="height:{h}%"></i></span>')
    return "".join(out)


axis = "".join(f"<span>{b:g}</span>" if b in LABELLED else "<span></span>" for b in BUCKETS)

for name, c in (("desktop", desk), ("phone", phone), ("mock", mock)):
    print(name, "total", sum(c.values()), "half-steps", sum(v for k, v in c.items() if k in HALF))

html = (HERE / "decisions.template.html").read_text(encoding="utf-8")
html = (
    html.replace("__P400__", b64((FS / "ibm-plex-mono-latin-400-normal.woff2").read_bytes()))
    .replace("__P500__", b64((FS / "ibm-plex-mono-latin-500-normal.woff2").read_bytes()))
    .replace("__P600__", b64((FS / "ibm-plex-mono-latin-600-normal.woff2").read_bytes()))
    .replace("__PFULL__", b64(ttf_to_woff2(FULL_TTF)))
    .replace("__HIST_DESK__", bars(desk))
    .replace("__HIST_PHONE__", bars(phone))
    .replace("__HIST_MOCK__", bars(mock))
    .replace("__AXIS__", axis)
)
assert "__" not in html.replace("__mobile_inbox", "").replace("_mobile_inbox", ""), "unfilled placeholder"
out = HERE / "s145-decision-board.html"
out.write_text(html, encoding="utf-8")
print("wrote", out, len(html), "chars")
print("full woff2", len(ttf_to_woff2(FULL_TTF)), "bytes")
