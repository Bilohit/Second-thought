"""Run the test suite one file per process, with a peak-RSS cap.

Why this exists (s149): `pytest` runs all ~66 test files in ONE process, so peak
RSS is the SUM across every file and **no single file owns a resource bug**. A
25x memory regression (126 MB -> 3093 MB in one file) was invisible under the
normal gate and only became a one-line attribution once each file ran alone.
The normal gate is still the correctness gate; this is the *attribution* gate.

    python run_tests_isolated.py                 # whole suite, 400 MB cap
    python run_tests_isolated.py --cap-mb 250    # tighter cap
    python run_tests_isolated.py test_server.py  # just these files
    python run_tests_isolated.py --include-fuzz  # opt the fuzz file back in

Exit code is non-zero if any file failed, errored, or was killed at the cap.

Measured baseline (s149, this machine): 65 files, 1447 passed, ~172s wall,
heaviest single file `test_server.py` at 162 MB, everything else <=136 MB.
**A file above ~200 MB is anomalous by that baseline** -- that is the number the
cap exists to catch.

Two traps this deliberately avoids, both of which cost a session:
  * `stdout=PIPE` drained after exit **deadlocks** on the 64 KB pipe buffer as
    soon as a child is chatty (test_api_surface.py's deprecation warnings fill
    it), and it looks exactly like a hang in the test file. Children write to a
    temp file instead.
  * `test_fuzz_races.py` is opt-in (FUZZ=1, ~250s) and is excluded by default --
    which is why a per-file total legitimately shows no skips where the
    one-process run shows 4. That is not a lost test.

ponytail: psutil is optional and NOT a declared dependency. Without it the run
still gives per-file isolation and timings -- just no RSS numbers, and the cap
cannot be enforced. Install psutil to get the half of this that matters most.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

HERE = Path(__file__).parent
POLL_S = 0.1
# Opt-in only (see module docstring). Excluded unless --include-fuzz.
OPT_IN = {"test_fuzz_races.py"}

_COUNT_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")


def discover() -> list[Path]:
    files = sorted(HERE.glob("test_*.py")) + sorted(HERE.glob("tests/test_*.py"))
    return [f for f in files if f.name not in OPT_IN]


def peak_rss_mb(proc: subprocess.Popen) -> float:
    """Peak RSS of the child AND its descendants, sampled while it runs.

    Descendants matter: a test that spawns uvicorn or a worker would otherwise
    hide its own footprint in a process this never looks at.
    """
    # Every return path below MUST go through proc.wait(). Sampling can stop
    # early (the child exits between poll() and memory_info()), and returning
    # without wait() leaves returncode None -- which this script then read as a
    # failure, reporting "EXIT None" for files that had just passed cleanly.
    if psutil is None:
        proc.wait()
        return 0.0
    peak = 0.0
    try:
        p = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                rss = p.memory_info().rss
                for c in p.children(recursive=True):
                    try:
                        rss += c.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                peak = max(peak, rss / 1024 / 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break  # child raced us to exit; its real status still comes from wait()
            if CAP_MB and peak > CAP_MB:
                for c in p.children(recursive=True):
                    c.kill()
                p.kill()
                break
            time.sleep(POLL_S)
    except psutil.NoSuchProcess:
        pass
    proc.wait()
    return peak


def parse_counts(text: str) -> dict[str, int]:
    """Read pytest's own summary line rather than inferring from the exit code --
    a file can exit 0 with skips, and 'why did the total move' needs the split."""
    counts: dict[str, int] = {}
    for n, word in _COUNT_RE.findall(text):
        counts[word.rstrip("s") if word != "passed" else word] = counts.get(
            word.rstrip("s") if word != "passed" else word, 0) + int(n)
    return counts


def run_one(path: Path, extra: list[str]) -> dict:
    rel = path.relative_to(HERE).as_posix()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as out:
        started = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", rel, "-q", *extra],
            cwd=HERE, stdout=out, stderr=subprocess.STDOUT,
        )
        peak = peak_rss_mb(proc)
        elapsed = time.monotonic() - started
        out.seek(0)
        text = out.read()
    killed = bool(CAP_MB) and peak > CAP_MB
    return {
        "file": rel, "rc": proc.returncode, "peak": peak, "secs": elapsed,
        "killed": killed, "counts": parse_counts(text),
        "tail": "\n".join(text.strip().splitlines()[-25:]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="specific test files (default: discover all)")
    ap.add_argument("--cap-mb", type=float, default=400.0,
                    help="kill a file above this peak RSS; 0 disables (default: 400)")
    ap.add_argument("--include-fuzz", action="store_true",
                    help="also run the opt-in fuzz file (slow)")
    ap.add_argument("-k", dest="k", default=None, help="pass -k EXPRESSION through to pytest")
    args = ap.parse_args()

    global CAP_MB
    CAP_MB = args.cap_mb

    if args.files:
        targets = [HERE / f for f in args.files]
        missing = [t for t in targets if not t.exists()]
        if missing:
            print(f"no such file(s): {', '.join(m.name for m in missing)}")
            return 2
    else:
        targets = discover()
        if args.include_fuzz:
            targets += [HERE / f for f in sorted(OPT_IN) if (HERE / f).exists()]

    if psutil is None:
        print("! psutil not installed - running isolated, but RSS is unmeasured "
              "and --cap-mb cannot be enforced.\n")

    print(f"{len(targets)} files, cap {CAP_MB:.0f} MB\n")
    results, started = [], time.monotonic()
    for i, t in enumerate(targets, 1):
        r = run_one(t, ["-k", args.k] if args.k else [])
        results.append(r)
        flag = "KILLED" if r["killed"] else ("FAIL" if r["rc"] else "ok")
        print(f"[{i:>3}/{len(targets)}] {flag:<6} {r['peak']:>7.1f} MB  "
              f"{r['secs']:>6.1f}s  {r['file']}")
    wall = time.monotonic() - started

    totals: dict[str, int] = {}
    for r in results:
        for k, v in r["counts"].items():
            totals[k] = totals.get(k, 0) + v
    bad = [r for r in results if r["rc"] != 0 or r["killed"]]

    print("\n" + "=" * 62)
    print(f"{len(results)} files - " + " - ".join(f"{v} {k}" for k, v in sorted(totals.items())))
    print(f"wall {wall:.0f}s")
    if psutil is not None:
        heaviest = sorted(results, key=lambda r: -r["peak"])[:5]
        print("heaviest: " + ", ".join(f"{r['file']} {r['peak']:.0f} MB" for r in heaviest))

    for r in bad:
        why = "KILLED AT CAP" if r["killed"] else "EXIT {}".format(r["rc"])
        print("\n" + "-" * 62)
        print("{}: {}  (peak {:.1f} MB)".format(why, r["file"], r["peak"]))
        print(r["tail"])

    return 1 if bad else 0


CAP_MB = 400.0

if __name__ == "__main__":
    sys.exit(main())
