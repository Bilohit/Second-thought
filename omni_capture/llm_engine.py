"""
llm_engine.py - Step 3: LLM Decision Engine (Read-Before-Write)

Category-agnostic edition
--------------------------
The system prompt is now built at call time from the caller-supplied
category_descriptions dict (a mapping of folder_name -> description).
This means adding or removing a folder in the vault immediately changes
what the LLM is allowed to classify into — no code changes required.

The CaptureOutput response model is also built dynamically via
models.build_capture_model(categories) so that instructor enforces
only the current vault's folder names in the JSON schema.
"""
from __future__ import annotations

import asyncio
import os
import textwrap
from typing import Dict, Optional

import instructor
from openai import AsyncOpenAI, OpenAI

from models import CaptureOutput, build_capture_model

OLLAMA_API_KEY = "ollama"


class SummarizationError(Exception):
    """Raised when a free-form summarization call fails after all retries."""


# ---------------------------------------------------------------------------
# Free-form summarization prompts (Map-Reduce; not structured output)
# ---------------------------------------------------------------------------

CHUNK_SUMMARY_PROMPT = (
    "You are summarizing one contiguous part of a longer video transcript. "
    "Produce detailed Markdown notes (headings, bullets, code blocks where "
    "code/commands appear). Do not add preamble like 'Here is…'. Capture "
    "concrete facts, steps, and terminology; omit filler."
)

COMBINE_PROMPT = (
    "You are merging section summaries of a single video into one cohesive, "
    "detailed Markdown summary. Deduplicate, order logically, keep all "
    "distinct facts/steps/code. No preamble."
)

DETAILED_SUMMARY_PROMPT = (
    "You are summarizing a full video transcript. Produce a cohesive, "
    "detailed Markdown summary (headings, bullets, code blocks where "
    "code/commands appear). Deduplicate, order logically, keep all distinct "
    "facts/steps/code. Do not add preamble like 'Here is…'. No preamble."
)


def _normalize_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _make_client() -> instructor.Instructor:
    # OLLAMA_BASE_URL is now always bare (canonical host) -- normalize here
    # so the OpenAI-compatible text client still gets "/v1" regardless of
    # whether the env var happens to already have it (idempotent).
    base_url = _normalize_base_url(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    raw = OpenAI(base_url=base_url, api_key=OLLAMA_API_KEY)
    return instructor.from_openai(raw, mode=instructor.Mode.JSON_SCHEMA)


# ---------------------------------------------------------------------------
# Free-form async completion (Map-Reduce summarization)
# ---------------------------------------------------------------------------

async def summarize_async(
    text: str,
    *,
    instruction: str,
    base_url: str,
    model: str,
    temperature: float = 0.2,
    max_retries: int = 3,
    timeout: Optional[float] = None,
    client: AsyncOpenAI,
) -> str:
    """
    Plain (non-structured) chat completion for prose summarization.

    Uses the given AsyncOpenAI client directly -- no instructor -- so callers
    can run many of these concurrently via asyncio.gather. base_url/model are
    accepted explicitly (not read from process env) so a background job
    can't be affected by a concurrent /capture mutating OLLAMA_BASE_URL/MODEL.

    Raises SummarizationError after max_retries transient failures.
    """
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    last_exc: Optional[BaseException] = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": text},
                ],
                temperature=temperature,
                timeout=timeout,
                extra_body={"keep_alive": keep_alive},
            )
            content = response.choices[0].message.content
            if not content:
                raise SummarizationError("Model returned an empty completion.")
            return content
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, 10))
                continue
    raise SummarizationError(
        f"summarize_async failed after {max_retries + 1} attempt(s): {last_exc}"
    ) from last_exc


def summarize(
    text: str,
    *,
    instruction: str,
    base_url: str,
    model: str,
    temperature: float = 0.2,
    max_retries: int = 3,
    timeout: Optional[float] = None,
) -> str:
    """Sync wrapper around summarize_async for the single-pass path and tests."""

    async def _run() -> str:
        client = AsyncOpenAI(base_url=_normalize_base_url(base_url), api_key=OLLAMA_API_KEY)
        try:
            return await summarize_async(
                text, instruction=instruction, base_url=base_url, model=model,
                temperature=temperature, max_retries=max_retries, timeout=timeout,
                client=client,
            )
        finally:
            await client.close()

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------
# {categories} is replaced with a formatted block of "name -> description" lines.
# {today}      is replaced with today's ISO date.

_SYSTEM_PROMPT_TEMPLATE = textwrap.dedent("""
    You are the Decision Engine for a personal Second Brain knowledge system.
    Return a perfectly structured JSON object matching the CaptureOutput schema.

    AVAILABLE CATEGORIES
{categories}

    ROUTING RULES
    * Choose the single best-matching category from the list above.
    * If the content fits none of the categories, choose the closest one and set
      requires_new_category=true with confidence below 0.6. The note will be
      placed in a scratchpad folder for manual review rather than being filed
      under the wrong category.
    * Never invent a category name — only use the names listed above.

    FILENAME RULES
    * suggested_filename must be a SPECIFIC, content-derived kebab-case slug
      that describes the EXACT topic of this capture.
    * Maximum 2 meaningful words. Drop filler/stop words (a, the, of, to, for,
      with, and, how, guide, notes, etc.) — they do not count toward the limit
      and should not appear in the slug at all.
    * Prefer the single most specific noun phrase. Never exceed ~40 characters.
    * Examples: "asyncio-eventloop", "compose-networking",
      "sourdough-starter".
    * NEVER use generic names like "notes", "article", "entry", or the
      category name itself.
    * Notes with the same filename are merged into one file — only reuse a
      name when this content is a direct continuation of that exact topic.
      Different topics MUST get different filenames.

    CONTENT RULES
    * Do NOT start with preamble like "Here is...", "In this note...", or
      "The following is...". Lead directly with the substantive content.
    * Do NOT restate the category name as a heading or opening line.
    * No filler transitions ("Additionally,", "It's worth noting that,").
    * Prefer bullet points over prose when listing facts.
    * Omit empty or placeholder sections — only include sections with real content.
    * Markdown formatting (headings, lists, code blocks) is fine — this is an
      Obsidian vault.

    REASONING FIELDS (always fill these)
    rationale:    1–2 sentences explaining WHY this category was chosen.
    key_signals:  Up to 5 short strings naming the specific cues you noticed.
    confidence:   Float 0.0–1.0.
                    0.95+      obvious match
                    0.70–0.94  mild ambiguity
                    below 0.70 uncertain — consider requires_new_category=true

    TODAY'S DATE: {today}

    DETECTED EVENTS
    * detected_events: list any concrete FUTURE dates/times found in the content
      (meetings, deadlines, appointments). Resolve relative dates (e.g. "next
      Tuesday", "in 3 days") against TODAY'S DATE above into an ISO-8601
      when_iso value. Output plain LOCAL time with NO timezone suffix —
      never append "Z" or "+hh:mm". Leave empty when none are present.
""").lstrip()

_SCRUTINY_PARAGRAPHS = {
    "relaxed": (
        "\n    CLASSIFICATION POSTURE (relaxed)\n"
        "    * Prefer to make a best-effort categorization even with limited signal.\n"
        "    * Lean toward assigning a category rather than expressing uncertainty.\n"
    ),
    "balanced": "",  # current behavior -- no extra instruction
    "strict": (
        "\n    CLASSIFICATION POSTURE (strict)\n"
        "    * Apply high scrutiny. If the content does not clearly and\n"
        "      unambiguously fit a single category, assign a low confidence\n"
        "      score (below the routing threshold) and let it route to the\n"
        "      inbox for manual review. Do not guess.\n"
    ),
}


def _build_system_prompt(
    category_descriptions: Dict[str, str],
    today: str,
    scrutiny: str = "balanced",
) -> str:
    """
    Render the system prompt with the current vault's categories and the
    configured classification posture (relaxed / balanced / strict).

    Each entry in category_descriptions is formatted as:
        Folder_Name    -> Description text
    """
    cat_lines = "\n".join(
        f"    {name:<25} -> {desc}"
        for name, desc in category_descriptions.items()
    )
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(categories=cat_lines, today=today)
    prompt += _SCRUTINY_PARAGRAPHS.get(scrutiny, "")
    return prompt


# ---------------------------------------------------------------------------
# Main engine entry point
# ---------------------------------------------------------------------------

def run_llm_engine(
    enriched: "CaptureOutput",          # actually EnrichedPayload; avoid circular import
    category_descriptions: Dict[str, str],
    existing_context: Optional[str] = None,
    today: Optional[str] = None,
    max_retries: Optional[int] = None,
    temperature: Optional[float] = None,
    scrutiny: str = "balanced",
) -> CaptureOutput:
    """
    Run the LLM Decision Engine and return a validated CaptureOutput.

    Args:
        enriched:               EnrichedPayload from the enrichment router.
        category_descriptions:  {folder_name: description} mapping built from
                                 the vault's current top-level directories.
                                 Drive this with storage_engine.build_category_descriptions().
        existing_context:       Optional pre-loaded vault context (from pre_resolver
                                 or a prior read-before-write pass).
        today:                  ISO date string (defaults to today).
        max_retries:            Overrides config.toml [capture] llm_max_retries (default 3).
        temperature:            Overrides config.toml [capture] llm_temperature (default 0.1).
        scrutiny:               Classification posture: "relaxed" / "balanced" / "strict".
                                 Overrides config.toml [capture] llm_scrutiny (default "balanced").
    """
    from datetime import date
    from models import EnrichedPayload  # local import to keep top-level clean
    from config import get_config  # local import to keep top-level clean

    today_str = today or date.today().isoformat()
    request_timeout_s = get_config().ollama.request_timeout_s

    if not category_descriptions:
        raise ValueError(
            "run_llm_engine() received an empty category_descriptions dict. "
            "Make sure the vault root contains at least one non-system folder."
        )

    # Build a fresh CaptureOutput model constrained to the current categories.
    categories = list(category_descriptions.keys())
    CaptureModel = build_capture_model(categories)

    system = _build_system_prompt(category_descriptions, today_str, scrutiny=scrutiny)

    user_parts = [
        f"INPUT TYPE: {enriched.input_type}",
        f"SOURCE URL: {enriched.source_url or 'N/A'}",
    ]
    if enriched.source_metadata:
        user_parts.append(f"METADATA: {enriched.source_metadata}")
    if existing_context:
        user_parts.append(
            f"\n--- EXISTING VAULT CONTEXT (do NOT duplicate) ---\n{existing_context}\n---"
        )
    user_parts.append(f"\n--- CONTENT TO CAPTURE ---\n{enriched.enriched_text}")

    user_message = "\n".join(user_parts)
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    response: CaptureOutput = _make_client().chat.completions.create(
        model=model,
        response_model=CaptureModel,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_message},
        ],
        max_retries=max_retries if max_retries is not None else 3,
        temperature=temperature if temperature is not None else 0.1,
        extra_body={"keep_alive": keep_alive},
        timeout=request_timeout_s,
    )
    return response


# ---------------------------------------------------------------------------
# Smoke tests  (python llm_engine.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import unittest.mock as mock

    def _mock_client(content: Optional[str] = "mock summary", *, fail_times: int = 0):
        client = mock.MagicMock()
        msg = mock.MagicMock()
        msg.choices = [mock.MagicMock(message=mock.MagicMock(content=content))]
        if fail_times:
            calls = {"n": 0}

            async def side_effect(*_a, **_k):
                calls["n"] += 1
                if calls["n"] <= fail_times:
                    raise RuntimeError("transient failure")
                return msg
            client.chat.completions.create = mock.AsyncMock(side_effect=side_effect)
        else:
            client.chat.completions.create = mock.AsyncMock(return_value=msg)
        return client

    async def _run_async_tests() -> None:
        # T1: happy path returns model content
        client = _mock_client("**Summary.**")
        result = await summarize_async(
            "hello", instruction=CHUNK_SUMMARY_PROMPT, base_url="http://x/v1",
            model="llama3.2", client=client,
        )
        assert result == "**Summary.**"
        print("[T1] summarize_async happy path  PASS")

        # T2: retries then succeeds
        client = _mock_client("recovered", fail_times=2)
        result = await summarize_async(
            "hello", instruction=COMBINE_PROMPT, base_url="http://x/v1",
            model="llama3.2", client=client, max_retries=3,
        )
        assert result == "recovered"
        print("[T2] summarize_async retries then succeeds  PASS")

        # T3: exhausts retries -> SummarizationError
        client = _mock_client(fail_times=99)
        try:
            await summarize_async(
                "hello", instruction=DETAILED_SUMMARY_PROMPT, base_url="http://x/v1",
                model="llama3.2", client=client, max_retries=1,
            )
            assert False, "expected SummarizationError"
        except SummarizationError:
            print("[T3] summarize_async raises SummarizationError after exhausting retries  PASS")

        # T4: empty completion content treated as failure
        client = _mock_client(content="")
        try:
            await summarize_async(
                "hello", instruction=CHUNK_SUMMARY_PROMPT, base_url="http://x/v1",
                model="llama3.2", client=client, max_retries=0,
            )
            assert False, "expected SummarizationError"
        except SummarizationError:
            print("[T4] summarize_async treats empty content as failure  PASS")

    asyncio.run(_run_async_tests())

    # T5: sync summarize() wrapper constructs/closes its own client
    with mock.patch(f"{__name__}.AsyncOpenAI") as MockAsyncOpenAI:
        instance = mock.MagicMock()
        msg = mock.MagicMock()
        msg.choices = [mock.MagicMock(message=mock.MagicMock(content="sync result"))]
        instance.chat.completions.create = mock.AsyncMock(return_value=msg)
        instance.close = mock.AsyncMock()
        MockAsyncOpenAI.return_value = instance

        result = summarize(
            "hello", instruction=DETAILED_SUMMARY_PROMPT,
            base_url="http://localhost:11434", model="llama3.2",
        )
        assert result == "sync result"
        MockAsyncOpenAI.assert_called_once()
        called_base_url = MockAsyncOpenAI.call_args.kwargs.get("base_url")
        assert called_base_url == "http://localhost:11434/v1", called_base_url
        instance.close.assert_awaited_once()
        print("[T5] summarize() sync wrapper normalizes base_url and closes client  PASS")

    # T6: prompt constants are non-empty and distinct
    prompts = {CHUNK_SUMMARY_PROMPT, COMBINE_PROMPT, DETAILED_SUMMARY_PROMPT}
    assert len(prompts) == 3 and all(p.strip() for p in prompts)
    print("[T6] prompt constants are non-empty and distinct  PASS")

    # T7: _make_client() normalizes a BARE OLLAMA_BASE_URL env value to /v1.
    # Regression: _make_client() used to read OLLAMA_BASE_URL directly and
    # trust it already had "/v1" (default "http://localhost:11434/v1"). Now
    # that server.py/main.py write the env var bare (the root fix for the
    # vision-capture /v1 leak), _make_client() must normalize it itself so
    # the OpenAI-compatible text client still gets "/v1".
    with mock.patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://localhost:11434"}, clear=False):
        client7 = _make_client()
        called_base_url = str(client7.client.base_url)
        assert called_base_url.rstrip("/") == "http://localhost:11434/v1", called_base_url
        print("[T7] _make_client() normalizes a bare OLLAMA_BASE_URL to /v1  PASS")

    # T7b: _make_client() also tolerates an env value that already has /v1
    # (idempotent -- must not become /v1/v1).
    with mock.patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://localhost:11434/v1"}, clear=False):
        client7b = _make_client()
        called_base_url2 = str(client7b.client.base_url)
        assert called_base_url2.rstrip("/") == "http://localhost:11434/v1", called_base_url2
        print("[T7b] _make_client() is idempotent when env already has /v1  PASS")

    print("\nAll llm_engine.py smoke tests passed.")
