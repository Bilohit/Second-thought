"""
interceptor.py
--------------
Step 1 — Trigger & Ingest

Reads the system clipboard and normalises the content into a typed
payload.  Designed to be invoked by a global OS hotkey (e.g. via
AutoHotkey on Windows, Hammerspoon on macOS, or xbindkeys on Linux).

Supported input shapes
  • Plain text / Markdown snippets
  • HTTP/HTTPS URLs (further classified by the Enrichment Router)
  • Raw image bytes copied from a screenshot tool (e.g. Snip & Sketch)

Usage (direct)
  python interceptor.py
  # prints the detected InputPayload as JSON, then hands off to main.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

try:
    import pyperclip
except ImportError as e:
    raise ImportError(
        "pyperclip is required: pip install pyperclip"
    ) from e


# ── Typed clipboard exceptions ────────────────────────────────────────────────

class ClipboardError(RuntimeError):
    """Raised when the clipboard cannot be accessed (backend/platform error)."""


class ClipboardEmpty(ValueError):
    """Raised when the clipboard contains no usable text or image."""


# ── Regex patterns ────────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r"^https?://"          # scheme
    r"[^\s/$.?#]"          # host start
    r"[^\s]*$",            # rest of URL (no whitespace)
    re.IGNORECASE,
)


@dataclass
class InputPayload:
    """Raw, unprocessed input from the clipboard."""

    raw: str
    input_type: str          # "text" | "url" | "image_bytes"
    image_bytes: Optional[bytes] = field(default=None, repr=False)

    def is_url(self) -> bool:
        return self.input_type == "url"

    def is_image(self) -> bool:
        return self.input_type == "image_bytes"


# ── Clipboard reader ──────────────────────────────────────────────────────────

def _try_read_image_from_clipboard() -> Optional[bytes]:
    """
    Attempt to read raw image bytes from the clipboard.

    pyperclip only handles text; for image data we use platform-specific
    backends.  Returns None if no image is present or the platform is
    unsupported — the caller falls back to text handling.
    """
    try:
        import platform
        os_name = platform.system()

        if os_name == "Windows":
            from PIL import ImageGrab
            import io
            img = ImageGrab.grabclipboard()
            if img is not None:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()

        elif os_name == "Darwin":
            from PIL import ImageGrab
            import io
            img = ImageGrab.grabclipboard()
            if img is not None:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()

        elif os_name == "Linux":
            import subprocess, io
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                capture_output=True,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout

    except Exception:
        pass  # Gracefully degrade — no image in clipboard

    return None


def read_clipboard() -> InputPayload:
    """
    Read the current clipboard and return a typed InputPayload.

    Priority order:
      1. Image bytes (screenshot / copied image)
      2. URL string
      3. Plain text

    Raises:
        ClipboardError: clipboard backend failed (e.g. no display server).
        ClipboardEmpty: clipboard has no usable text or image.
    """
    # 1. Try image first (doesn't go through pyperclip)
    image_bytes = _try_read_image_from_clipboard()
    if image_bytes:
        return InputPayload(
            raw="<image_data>",
            input_type="image_bytes",
            image_bytes=image_bytes,
        )

    # 2. Read text via pyperclip
    try:
        text: str = pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        raise ClipboardError(f"Clipboard read failed: {exc}") from exc

    if not text or not text.strip():
        raise ClipboardEmpty("Clipboard is empty — nothing to capture.")

    text = text.strip()

    # 3. Classify: URL vs plain text
    input_type = "url" if _URL_RE.match(text) else "text"

    return InputPayload(raw=text, input_type=input_type)


# ── CLI entry-point / smoke test ──────────────────────────────────────────────
if __name__ == "__main__":
    import unittest.mock as mock

    # ── T1: ClipboardEmpty raised (not sys.exit) when clipboard is blank ───
    with mock.patch("pyperclip.paste", return_value="   "):
        try:
            read_clipboard()
            assert False, "Should have raised ClipboardEmpty"
        except ClipboardEmpty as e:
            print(f"[T1] ClipboardEmpty raised correctly: {e}  PASS")

    # ── T2: ClipboardError raised on pyperclip backend failure ─────────────
    with mock.patch("pyperclip.paste", side_effect=pyperclip.PyperclipException("no xclip")):
        try:
            read_clipboard()
            assert False, "Should have raised ClipboardError"
        except ClipboardError as e:
            print(f"[T2] ClipboardError raised correctly: {e}  PASS")

    # ── T3: URL detection works on non-empty text ──────────────────────────
    with mock.patch("pyperclip.paste", return_value="https://example.com/page"):
        p = read_clipboard()
        assert p.input_type == "url", f"Expected 'url', got {p.input_type!r}"
        print(f"[T3] URL detection: input_type={p.input_type!r}  PASS")

    # ── T4: plain text passes through ─────────────────────────────────────
    with mock.patch("pyperclip.paste", return_value="Hello, Second Brain!"):
        p = read_clipboard()
        assert p.input_type == "text"
        print(f"[T4] Text passthrough: input_type={p.input_type!r}  PASS")

    print("\nAll interceptor.py smoke tests passed.")

    # ── Live clipboard read (skipped when clipboard unavailable) ───────────
    print("\n[Live] Attempting real clipboard read …")
    try:
        payload = read_clipboard()
        print(f"  Detected type : {payload.input_type}")
        print(f"  Content (100c): {payload.raw[:100]!r}")
    except ClipboardEmpty as e:
        print(f"  (empty): {e}")
    except ClipboardError as e:
        print(f"  (error): {e}", file=sys.stderr)
