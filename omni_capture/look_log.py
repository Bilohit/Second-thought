"""
look_log.py — debug logging for the Look panel and rag_engine.

Stdout is captured by the Tauri shell into the unified log file (scope
python:stdout). Verbose lines are gated by set_look_verbose(), which the
server sets from the GUI's X-Log-Level header (DEBUG/TRACE). Warnings and
errors always emit so failures are never silent.
"""
from __future__ import annotations

from contextvars import ContextVar

_verbose: ContextVar[bool] = ContextVar("look_verbose", default=False)

LVL_DEBUG = 20  # mirror frontend LogLevel.DEBUG


def debug_logging_from_level(level_header: str | None) -> bool:
    """True when the GUI log level is DEBUG (20) or TRACE (10)."""
    if not level_header:
        return False
    try:
        return int(level_header) <= LVL_DEBUG
    except ValueError:
        return False


def set_look_verbose(enabled: bool) -> None:
    _verbose.set(enabled)


def look_debug(msg: str) -> None:
    if _verbose.get():
        print(f"[look] [DEBUG] {msg}", flush=True)


def look_info(msg: str) -> None:
    if _verbose.get():
        print(f"[look] [INFO] {msg}", flush=True)


def look_warn(msg: str) -> None:
    print(f"[look] [WARN] {msg}", flush=True)


def look_error(msg: str) -> None:
    print(f"[look] [ERROR] {msg}", flush=True)


if __name__ == "__main__":
    assert not debug_logging_from_level(None)
    assert debug_logging_from_level("10")
    assert debug_logging_from_level("20")
    assert not debug_logging_from_level("30")
    set_look_verbose(True)
    look_debug("test debug")
    look_warn("test warn")
    print("look_log smoke OK")
