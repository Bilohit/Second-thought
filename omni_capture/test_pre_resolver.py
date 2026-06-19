"""
test_pre_resolver.py
--------------------
Unit tests for the pre_resolver module.

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
from pre_resolver import pre_resolve, ResolverResult, _slugify


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ep(text: str, input_type: str = "text") -> EnrichedPayload:
    return EnrichedPayload(raw_input=text, input_type=input_type, enriched_text=text)


class TempVault:
    """Context manager: creates a temp dir with Finance/ and CRM/ subdirs."""
    def __enter__(self) -> pathlib.Path:
        self._tmp = tempfile.TemporaryDirectory()
        vault = pathlib.Path(self._tmp.name)
        (vault / "Finance").mkdir()
        (vault / "CRM").mkdir()
        return vault

    def __exit__(self, *_) -> None:
        self._tmp.cleanup()


# ── slugify ───────────────────────────────────────────────────────────────────

class TestSlugify(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_slugify("John Smith"), "john-smith")

    def test_three_words(self):
        self.assertEqual(_slugify("Mary Jane Watson"), "mary-jane-watson")

    def test_hyphenated(self):
        self.assertEqual(_slugify("Anne-Marie Dupont"), "anne-marie-dupont")

    def test_apostrophe(self):
        self.assertEqual(_slugify("O'Brien"), "o-brien")

    def test_strips_trailing_dash(self):
        slug = _slugify("  John  ")
        self.assertFalse(slug.startswith("-"))
        self.assertFalse(slug.endswith("-"))


# ── Finance resolution ────────────────────────────────────────────────────────

class TestFinanceResolution(unittest.TestCase):

    def test_price_plus_keyword_is_finance(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Paid $42.99 for the AWS invoice."), vault)
        self.assertEqual(r.category_hint, "Finance")
        self.assertEqual(r.certainty, "high")
        self.assertIsNotNone(r.path)
        self.assertEqual(r.path.name, "Expenses.md")

    def test_two_price_literals_is_finance(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("$9.99/month subscription, normally $19.99."), vault)
        self.assertEqual(r.category_hint, "Finance")
        self.assertEqual(r.certainty, "high")

    def test_currency_code_plus_keyword(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Spent 150 USD on the hotel receipt."), vault)
        self.assertEqual(r.category_hint, "Finance")
        self.assertEqual(r.certainty, "high")

    def test_single_signal_not_finance(self):
        # Only one financial hit — below threshold
        with TempVault() as vault:
            r = pre_resolve(_ep("I bought some coffee today."), vault)
        self.assertNotEqual(r.category_hint, "Finance")

    def test_existing_expenses_loads_context(self):
        with TempVault() as vault:
            expenses = vault / "Finance" / "Expenses.md"
            expenses.write_text(
                "| Date | Desc | Amount |\n"
                "|------|------|--------|\n"
                "| 2026-01-01 | Coffee | $4.50 |\n"
            )
            r = pre_resolve(_ep("Receipt: $9.99 subscription fee paid."), vault)
        self.assertIsNotNone(r.existing_context)
        self.assertIn("Expenses.md", r.existing_context)
        self.assertIn("Coffee", r.existing_context)

    def test_missing_expenses_gives_no_context(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Invoice $200 total payment due."), vault)
        self.assertIsNone(r.existing_context)

    def test_path_always_points_to_expenses(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Paid $5 fee plus $3 charge."), vault)
        self.assertEqual(r.path, vault / "Finance" / "Expenses.md")

    def test_euro_symbol_detected(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Paid €49.00 for the annual subscription fee."), vault)
        self.assertEqual(r.category_hint, "Finance")

    def test_finance_takes_priority_over_crm_name(self):
        # Text mentions a name AND has finance signals — Finance wins (checked first)
        with TempVault() as vault:
            r = pre_resolve(
                _ep("Email from John Smith: invoice $200 payment due."), vault
            )
        self.assertEqual(r.category_hint, "Finance")


# ── CRM resolution ────────────────────────────────────────────────────────────

class TestCRMResolution(unittest.TestCase):

    def test_email_from_name(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("email from John Smith about the proposal"), vault)
        self.assertEqual(r.category_hint, "CRM")
        self.assertEqual(r.certainty, "high")
        self.assertEqual(r.path.name, "john-smith.md")

    def test_meeting_with_name(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("meeting with Jane Doe to discuss contract"), vault)
        self.assertEqual(r.category_hint, "CRM")
        self.assertEqual(r.path.name, "jane-doe.md")

    def test_call_with_name(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Had a call with Bob Johnson today"), vault)
        self.assertEqual(r.category_hint, "CRM")
        self.assertEqual(r.path.name, "bob-johnson.md")

    def test_existing_crm_file_loads_context(self):
        with TempVault() as vault:
            crm_file = vault / "CRM" / "john-smith.md"
            crm_file.write_text(
                "# John Smith\n\n## Interactions\n\n- 2026-01-10 initial call\n"
            )
            r = pre_resolve(_ep("meeting with John Smith re: renewal"), vault)
        self.assertIsNotNone(r.existing_context)
        self.assertIn("John Smith", r.existing_context)
        self.assertIn("initial call", r.existing_context)

    def test_new_crm_contact_gives_no_context(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("call with Jane Doe about onboarding"), vault)
        self.assertEqual(r.category_hint, "CRM")
        self.assertIsNone(r.existing_context)

    def test_context_truncated_at_2000_chars(self):
        with TempVault() as vault:
            crm_file = vault / "CRM" / "long-person.md"
            crm_file.write_text("# Long Person\n\n" + "x" * 3000)
            r = pre_resolve(_ep("email from Long Person updates"), vault)
        # context should be at most 2000 chars
        if r.existing_context:
            self.assertLessEqual(len(r.existing_context), 2000)

    def test_fallback_client_pattern(self):
        # Uses _NAME_CONTEXT_RE (no explicit trigger verb)
        with TempVault() as vault:
            r = pre_resolve(_ep("Note about client Alice Johnson re: contract"), vault)
        self.assertEqual(r.category_hint, "CRM")
        self.assertIn("alice-johnson", r.path.name)

    def test_no_name_gives_low_certainty(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Had a meeting today about the roadmap."), vault)
        self.assertNotEqual(r.certainty, "high")


# ── Uncertain / fallback ──────────────────────────────────────────────────────

class TestUncertain(unittest.TestCase):

    def test_generic_tech_note(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Here's how to use Python asyncio for concurrent tasks."), vault)
        self.assertEqual(r.certainty, "low")
        self.assertIsNone(r.category_hint)
        self.assertIsNone(r.existing_context)
        self.assertIsNone(r.path)

    def test_recipe_text(self):
        with TempVault() as vault:
            r = pre_resolve(_ep("Mix flour, eggs, and butter. Bake at 350°F for 30 minutes."), vault)
        self.assertEqual(r.certainty, "low")

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
        self.assertIn(r.certainty, ("high", "low"))


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
