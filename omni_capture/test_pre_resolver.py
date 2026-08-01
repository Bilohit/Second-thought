"""
test_pre_resolver.py
--------------------
Unit tests for the pre_resolver module.

Projects S1 (2026-08-01, s125 item 5): the Finance/CRM keyword+regex fast
paths (and _slugify, which only existed to build CRM slugs) are deleted --
authorised feature subtraction, since there is no fixed "Finance"/"CRM"
project any registry-driven vault is guaranteed to have. pre_resolve() now
always defers to the LLM (certainty="low"); this file's old Finance/CRM/
slugify test classes tested exactly the deleted behaviour and are replaced
below.

Run:
  python test_pre_resolver.py        # plain output
  python -m pytest test_pre_resolver.py -v
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

# Make sure omni_capture modules are importable when running from the package dir
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from models import EnrichedPayload
from pre_resolver import pre_resolve, ResolverResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ep(text: str, input_type: str = "text") -> EnrichedPayload:
    return EnrichedPayload(raw_input=text, input_type=input_type, enriched_text=text)


class TempVault:
    """Context manager: creates a bare temp dir (no Finance/CRM subdirs needed
    any more -- pre_resolve no longer looks for them)."""
    def __enter__(self) -> pathlib.Path:
        self._tmp = tempfile.TemporaryDirectory()
        return pathlib.Path(self._tmp.name)

    def __exit__(self, *_) -> None:
        self._tmp.cleanup()


# ── pre_resolve always defers ───────────────────────────────────────────────────

class TestAlwaysDefers(unittest.TestCase):
    """No fast path remains; every input, regardless of shape, returns the
    same low-certainty, no-context result. `category_hint` is gone with the
    category concept itself (Projects S1, Task 13)."""

    def _assert_defers(self, text: str, input_type: str = "text") -> None:
        with TempVault() as vault:
            r = pre_resolve(_ep(text, input_type), vault)
        self.assertEqual(r.certainty, "low")
        self.assertIsNone(r.existing_context)
        self.assertIsNone(r.path)

    def test_generic_tech_note(self):
        self._assert_defers("Here's how to use Python asyncio for concurrent tasks.")

    def test_finance_shaped_text_no_longer_fast_pathed(self):
        # Previously asserted a "Finance" hint -- that fast path is deleted.
        self._assert_defers("Paid $42.99 for the AWS invoice.")

    def test_crm_shaped_text_no_longer_fast_pathed(self):
        # Previously asserted a "CRM" hint -- that fast path is deleted.
        self._assert_defers("email from John Smith about the Q3 proposal")

    def test_watch_later_url(self):
        with TempVault() as vault:
            r = pre_resolve(
                EnrichedPayload(
                    raw_input="https://youtube.com/watch?v=abc",
                    input_type="url_youtube",
                    enriched_text="# YouTube Transcript\n\nLearn about machine learning basics.",
                ),
                vault,
            )
        self.assertEqual(r.certainty, "low")

    def test_result_is_named_tuple(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Just some random note."), vault)
        self.assertIsInstance(r, ResolverResult)
        self.assertEqual(r.certainty, "low")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
