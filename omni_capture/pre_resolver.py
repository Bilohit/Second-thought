"""
pre_resolver.py
---------------
Cheap deterministic resolver for the Second Thought pipeline.

Purpose
  Infer existing-note context before the LLM runs, so run_llm_engine can be
  called exactly once per capture in the common case.

Projects S1 (2026-08-01, s125 item 5): the Finance/CRM keyword+regex fast
paths this module used to run are deleted -- authorised feature subtraction.
They were hardcoded folder-name hints from the retired `category` concept
(Finance -> always Finance/Expenses.md, CRM -> name-extraction + CRM/<slug>.md),
which cannot survive the move to registry-driven, user-named projects: there
is no fixed "Finance" or "CRM" project any vault is guaranteed to have.

pre_resolve() is kept as the seam main.py/server.py already call through
(ResolverResult's shape is unchanged) so those two hand-duplicated pipelines
need no wiring change from this task alone -- it now always defers to the
LLM / semantic retrieval for existing-context assembly, i.e. always returns
certainty="low".
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Optional

from models import EnrichedPayload


# ── Public result type ─────────────────────────────────────────────────────────

class ResolverResult(NamedTuple):
    path: Optional[Path]            # resolved target .md file, or None
    existing_context: Optional[str] # pre-loaded vault content for the LLM, or None
    certainty: str                  # "high" | "low" -- always "low" post rip-out


# ── Core resolver ──────────────────────────────────────────────────────────────

def pre_resolve(
    enriched: EnrichedPayload,
    vault_root: Path,
) -> ResolverResult:
    """
    No fast path remains (Finance/CRM hints deleted, s125 item 5). Always
    defers to the LLM -- callers fall back to their normal
    read_existing_context / semantic-retrieval path unconditionally.
    """
    return ResolverResult(path=None, existing_context=None, certainty="low")


# ── Smoke tests ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    r = pre_resolve(
        EnrichedPayload(raw_input="Paid $42.99 for an invoice.", input_type="text",
                         enriched_text="Paid $42.99 for an invoice."),
        Path("."),
    )
    assert r.certainty == "low"
    assert r.path is None
    assert r.existing_context is None
    print("[T1] pre_resolve always defers to the LLM (no Finance/CRM fast path)  PASS")
