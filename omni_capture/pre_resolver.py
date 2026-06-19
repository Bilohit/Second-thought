"""
pre_resolver.py
---------------
Cheap deterministic resolver for the Second Thought pipeline.

Purpose
  Infer the likely capture category and target file *before* the LLM runs,
  so that existing vault context can be loaded in a single pass.  This lets
  run_llm_engine be called exactly once per capture in the common case.

Certainty levels
  "high"  Resolver is confident — pass existing_context to the LLM on the
          first (and only) call.  No second pass needed.
  "low"   Resolver couldn't determine category — run the LLM once without
          pre-context, then fall back to the normal read_existing_context
          check if the LLM picks CRM or Finance.

Supported fast paths
  Finance  ≥2 financial signals (price literals, currency keywords) in the
           enriched text.  Target is always Finance/Expenses.md.
  CRM      A recognised "interaction" trigger phrase followed by a Proper Name
           (e.g. "email from John Smith", "meeting with Jane Doe").
           Target is CRM/<slug>.md — loaded if it already exists.

All other input types return certainty="low" and defer to the LLM.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple, Optional

from models import EnrichedPayload


# ── Finance signal patterns ────────────────────────────────────────────────────

_FINANCE_RE = re.compile(
    r"""
    (?:
        [\$€£¥₹]\s*[\d,]+\.?\d*                                   # $12.50  €100
      | [\d,]+\.?\d*\s*(?:USD|EUR|GBP|JPY|INR|CAD|AUD|CHF)\b      # 12.50 USD
      | \b(?:invoice|receipt|expense|bill|payment|paid|spent
            |cost|price|total|charge|fee|purchase|refund)\b        # finance keywords
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Minimum number of distinct finance signals required to assert Finance category
_FINANCE_MIN_HITS = 2


# ── CRM name extraction patterns ───────────────────────────────────────────────

# Primary: explicit interaction verb + preposition + Proper Name
_CRM_TRIGGER_RE = re.compile(
    r"""
    (?:
        (?:email|message|msg|note|call|meeting|met|talked|spoke|chat|dm
           |contact|follow.?up|caught\s+up)\s+
        (?:from|with|to)\s+
      | (?:from|with|to)\s+(?=[A-Z])
    )
    (?P<name>[A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){0,2})
    """,
    re.VERBOSE,
)

# Fallback: proximity of a contact-flavoured word to a capitalised name pair
_NAME_CONTEXT_RE = re.compile(
    r"\b(?:from|with|to|contact|person|client|customer|colleague|lead|prospect)\b"
    r"[^A-Z]{0,20}"
    r"(?P<name>[A-Z][a-zA-Z\-\']+\s+[A-Z][a-zA-Z\-\']+)",
)


def _slugify(name: str) -> str:
    """'John Smith' → 'john-smith'"""
    return re.sub(r"[^\w]+", "-", name.strip().lower()).strip("-")


# ── Public result type ─────────────────────────────────────────────────────────

class ResolverResult(NamedTuple):
    path: Optional[Path]            # resolved target .md file, or None
    existing_context: Optional[str] # pre-loaded vault content for the LLM, or None
    category_hint: Optional[str]    # "Finance" | "CRM" | None
    certainty: str                  # "high" | "low"


# ── Core resolver ──────────────────────────────────────────────────────────────

def pre_resolve(
    enriched: EnrichedPayload,
    vault_root: Path,
) -> ResolverResult:
    """
    Examine enriched_text and infer the likely target path + existing context
    without invoking the LLM.

    Usage pattern in the pipeline::

        resolved = pre_resolve(enriched, vault_root)
        output   = run_llm_engine(enriched, existing_context=resolved.existing_context)
        # two-pass fallback — only when resolver was uncertain:
        if resolved.certainty == "low":
            existing = read_existing_context(output, vault_root=vault_root)
            if existing:
                output = run_llm_engine(enriched, existing_context=existing)
    """
    text = enriched.enriched_text

    # ── Fast path 1: Finance ──────────────────────────────────────────────────
    # Only assert high certainty when the Finance folder actually exists in the
    # vault.  Dynamic vaults without a Finance folder fall through to the LLM.
    finance_hits = len(set(_FINANCE_RE.findall(text)))
    if finance_hits >= _FINANCE_MIN_HITS and (vault_root / "Finance").is_dir():
        expenses_path = vault_root / "Finance" / "Expenses.md"
        existing_context: Optional[str] = None
        if expenses_path.exists():
            content = expenses_path.read_text(encoding="utf-8")
            table_rows = [ln for ln in content.splitlines() if ln.startswith("|")]
            existing_context = (
                "Last entries in Expenses.md:\n" + "\n".join(table_rows[-10:])
            )
        return ResolverResult(
            path=expenses_path,
            existing_context=existing_context,
            category_hint="Finance",
            certainty="high",
        )

    # ── Fast path 2: CRM ──────────────────────────────────────────────────────
    # Only assert high certainty when the CRM folder actually exists in the vault.
    name: Optional[str] = None
    m = _CRM_TRIGGER_RE.search(text)
    if not m:
        m = _NAME_CONTEXT_RE.search(text)
    if m:
        name = m.group("name").strip()

    if name and (vault_root / "CRM").is_dir():
        slug = _slugify(name)
        crm_path = vault_root / "CRM" / f"{slug}.md"
        existing_context = None
        if crm_path.exists():
            existing_context = crm_path.read_text(encoding="utf-8")[:2000]
        return ResolverResult(
            path=crm_path,
            existing_context=existing_context,
            category_hint="CRM",
            certainty="high",
        )

    # ── Uncertain — defer to LLM ──────────────────────────────────────────────
    return ResolverResult(
        path=None,
        existing_context=None,
        category_hint=None,
        certainty="low",
    )


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, pathlib

    def _ep(text: str) -> EnrichedPayload:
        return EnrichedPayload(
            raw_input=text, input_type="text", enriched_text=text
        )

    with tempfile.TemporaryDirectory() as tmp:
        vault = pathlib.Path(tmp)
        (vault / "Finance").mkdir()
        (vault / "CRM").mkdir()

        # ── T1: Finance — price literal + keyword ─────────────────────────
        r = pre_resolve(_ep("Paid $42.99 for the AWS invoice."), vault)
        assert r.category_hint == "Finance", f"T1 hint: {r.category_hint}"
        assert r.certainty == "high", f"T1 certainty: {r.certainty}"
        assert r.path is not None and r.path.name == "Expenses.md"
        print(f"[T1] Finance detection  PASS  (hits: {len(_FINANCE_RE.findall('Paid $42.99 for the AWS invoice.'))})")

        # ── T2: Finance — existing Expenses.md context loaded ─────────────
        (vault / "Finance" / "Expenses.md").write_text(
            "| Date | Desc | Amount |\n|------|------|--------|\n| 2026-01-01 | Coffee | $4.50 |\n"
        )
        r2 = pre_resolve(_ep("Receipt: $9.99 subscription fee paid."), vault)
        assert r2.existing_context is not None and "Expenses.md" in r2.existing_context
        print(f"[T2] Finance context loaded  PASS")

        # ── T3: CRM trigger — explicit phrase ─────────────────────────────
        r3 = pre_resolve(_ep("email from John Smith about the Q3 proposal"), vault)
        assert r3.category_hint == "CRM", f"T3 hint: {r3.category_hint}"
        assert r3.certainty == "high"
        assert r3.path is not None and r3.path.name == "john-smith.md"
        print(f"[T3] CRM trigger phrase  PASS  (name: {r3.path.name})")

        # ── T4: CRM — existing file context loaded ────────────────────────
        (vault / "CRM" / "john-smith.md").write_text("# John Smith\n\n## Interactions\n\n- 2026-01-10 initial call\n")
        r4 = pre_resolve(_ep("meeting with John Smith to discuss contract renewal"), vault)
        assert r4.existing_context is not None and "John Smith" in r4.existing_context
        print(f"[T4] CRM context loaded  PASS")

        # ── T5: CRM — new contact (no existing file) ──────────────────────
        r5 = pre_resolve(_ep("call with Jane Doe about onboarding"), vault)
        assert r5.category_hint == "CRM"
        assert r5.path is not None and r5.path.name == "jane-doe.md"
        assert r5.existing_context is None  # file doesn't exist yet
        print(f"[T5] CRM new contact  PASS  (path: {r5.path.name}, context=None)")

        # ── T6: Uncertain — generic Tech content ──────────────────────────
        r6 = pre_resolve(_ep("Here's how to use Python asyncio for concurrent tasks."), vault)
        assert r6.certainty == "low"
        assert r6.category_hint is None
        assert r6.existing_context is None
        print(f"[T6] Uncertain -> certainty=low  PASS")

        # ── T7: Finance threshold — single signal not enough ──────────────
        r7 = pre_resolve(_ep("I bought some coffee today."), vault)
        assert r7.certainty == "low", f"T7 should be low, got {r7.certainty}"
        print(f"[T7] Finance single-hit threshold  PASS")

        # ── T8: CRM fallback pattern ──────────────────────────────────────
        r8 = pre_resolve(_ep("Note about client Alice Johnson re: contract"), vault)
        assert r8.category_hint == "CRM"
        assert r8.path is not None and "alice-johnson" in r8.path.name
        print(f"[T8] CRM fallback pattern  PASS  (name: {r8.path.name})")

    print("\nAll pre_resolver.py smoke tests passed.")
