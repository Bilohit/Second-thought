"""
notifier.py
-----------
Cross-platform desktop notifications for Second Thought.

Tries the best available backend for each OS.  Fails silently — a broken
notification must never crash the pipeline.

Backends (by platform)
  macOS   → osascript (built-in, zero deps)
  Windows → win10toast (pip install win10toast)  ← falls back to plyer
  Linux   → notify-send (system binary)          ← falls back to plyer
  Any OS  → plyer (pip install plyer)            ← universal fallback
"""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Optional


_OS = platform.system()   # "Darwin" | "Windows" | "Linux"


# ── Backend implementations ───────────────────────────────────────────────────

def _applescript_escape(s: str) -> str:
    """Escape double quotes and backslashes for safe embedding in an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _notify_macos(title: str, message: str, subtitle: str = "") -> None:
    title    = _applescript_escape(title)
    message  = _applescript_escape(message)
    subtitle = _applescript_escape(subtitle)
    script = (
        f'display notification "{message}" '
        f'with title "{title}"'
        + (f' subtitle "{subtitle}"' if subtitle else "")
    )
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _plyer_notify(full_title: str, message: str) -> None:
    try:
        from plyer import notification  # type: ignore
        notification.notify(title=full_title, message=message, timeout=5)
    except Exception:
        pass


def _notify_windows(full_title: str, message: str) -> None:
    try:
        from win10toast import ToastNotifier  # type: ignore
        ToastNotifier().show_toast(full_title, message, duration=5, threaded=True)
        return
    except ImportError:
        pass
    _plyer_notify(full_title, message)


def _notify_linux(full_title: str, message: str) -> None:
    result = subprocess.run(
        ["notify-send", full_title, message],
        check=False, capture_output=True,
    )
    if result.returncode == 0:
        return
    _plyer_notify(full_title, message)


# ── Public API ────────────────────────────────────────────────────────────────

def send_notification(
    title: str,
    message: str,
    subtitle: str = "",
) -> None:
    """
    Send a desktop notification.  Never raises — all errors are silently swallowed
    so a broken notification path cannot interrupt a capture.

    Args:
        title:    Notification title (e.g. "Second Thought").
        message:  Body text (e.g. "→ CRM/jane-smith.md").
        subtitle: Optional subtitle shown on macOS (e.g. "CRM").
    """
    try:
        full_title = f"{title} — {subtitle}" if subtitle else title
        if _OS == "Darwin":
            _notify_macos(title, message, subtitle)
        elif _OS == "Windows":
            _notify_windows(full_title, message)
        else:
            _notify_linux(full_title, message)
    except Exception as exc:
        # Notification failure must never surface to the user as a crash
        print(f"[Notifier] Non-fatal: {exc}", file=sys.stderr)


def notify_capture_success(
    category: str,
    filepath: str,
    title_prefix: str = "Second Thought",
) -> None:
    """Convenience wrapper for a successful vault write."""
    import os
    short_path = os.path.basename(filepath)
    send_notification(
        title=title_prefix,
        subtitle=category,
        message=f"→ {category}/{short_path}",
    )


def notify_capture_error(
    error_message: str,
    title_prefix: str = "Second Thought",
) -> None:
    """Convenience wrapper for pipeline errors."""
    send_notification(
        title=f"{title_prefix} — Error",
        message=error_message[:120],
    )


if __name__ == "__main__":
    # CLI for OS-scheduled reminders: python notifier.py "title" "message"
    if len(sys.argv) >= 3:
        send_notification(sys.argv[1], sys.argv[2])
    else:
        send_notification("Second Thought", "notifier CLI smoke test")
