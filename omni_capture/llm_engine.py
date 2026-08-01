"""
llm_engine.py - Step 3: LLM Decision Engine (Read-Before-Write)

Projects S1 edition (2026-08-01, s125)
---------------------------------------
The system prompt is now built at call time from the project registry (see
project_registry.load()) instead of the retired folder-name category concept.
Callers pass the loaded Registry dict straight through -- this module stays
pure/I-O-free, same as before; it just reads {"projects": {name: {description}}}
instead of a caller-built category_descriptions dict.

The CaptureOutput response model is built dynamically via
models.build_capture_model(project_names) so that instructor enforces only
the registry's EXISTING project names (or null) in the JSON schema. The
engine may never invent a project.
"""
from __future__ import annotations

import asyncio
import os
import textwrap
from typing import TYPE_CHECKING, Any, Dict, Optional

import instructor
from openai import AsyncOpenAI, OpenAI

from models import CaptureOutput, build_capture_model

if TYPE_CHECKING:
    # OF-15: annotate `enriched` with its real type without a runtime circular import
    # (models imports from this module's siblings). `from __future__ import annotations` above
    # keeps the annotation a lazy string, so this import only exists for the type checker.
    from models import EnrichedPayload

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


def _ollama_setting(env_name: str, attr: str, default: str) -> str:
    """Resolve one Ollama setting: explicit process env first (main.py's CLI
    overrides and tests set these), then the loaded config, then the built-in
    default.

    SRV-16: server.py used to publish cfg into os.environ before every capture
    so these getenv() reads would see it. Two concurrent captures shared that
    one mutable global, and the write also pinned the value against later
    config.toml edits (config.py treats the same vars as overrides). Reading
    config here instead removes the shared mutation without threading base_url/
    model through every call site.
    """
    val = os.getenv(env_name)
    if val:
        return val
    try:
        from config import get_config
        return getattr(get_config().ollama, attr, "") or default
    except Exception:
        return default


def _make_client() -> instructor.Instructor:
    # The resolved base_url is always bare (canonical host) -- normalize here
    # so the OpenAI-compatible text client still gets "/v1" regardless of
    # whether the value happens to already have it (idempotent).
    base_url = _normalize_base_url(
        _ollama_setting("OLLAMA_BASE_URL", "base_url", "http://localhost:11434")
    )
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
# {projects} is replaced with a formatted block of "name -> description" lines
#            (or a placeholder line when the registry has no projects yet).
# {today}    is replaced with today's ISO date.

_SYSTEM_PROMPT_TEMPLATE = textwrap.dedent("""
    You are the Decision Engine for a personal Second Brain knowledge system.
    Return a perfectly structured JSON object matching the CaptureOutput schema.

    AVAILABLE PROJECTS
{projects}

    ROUTING RULES
    * Choose the single best-matching EXISTING project from the list above, or
      leave `project` null when nothing fits well or the list is empty.
    * Never invent a project name — only use a name listed above, or null.
      A note with project=null is simply unfiled ("loose"); that is a normal,
      safe outcome, not a failure.

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
      project name itself.
    * Notes with the same filename are merged into one file — only reuse a
      name when this content is a direct continuation of that exact topic.
      Different topics MUST get different filenames.

    CONTENT RULES
    * Do NOT start with preamble like "Here is...", "In this note...", or
      "The following is...". Lead directly with the substantive content.
    * Do NOT restate the project name as a heading or opening line.
    * No filler transitions ("Additionally,", "It's worth noting that,").
    * Prefer bullet points over prose when listing facts.
    * Omit empty or placeholder sections — only include sections with real content.
    * Markdown formatting (headings, lists, code blocks) is fine — this is an
      Obsidian vault.

    REASONING FIELDS (always fill these)
    rationale:    1–2 sentences explaining WHY this project was chosen (or why
                  none fit, when project is null).
    key_signals:  Up to 5 short strings naming the specific cues you noticed.
    confidence:   Float 0.0–1.0.
                    0.95+      obvious match
                    0.70–0.94  mild ambiguity
                    below 0.70 uncertain — prefer project=null over guessing

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
        "    * Prefer to make a best-effort project assignment even with limited signal.\n"
        "    * Lean toward assigning a project rather than expressing uncertainty.\n"
    ),
    "balanced": "",  # current behavior -- no extra instruction
    "strict": (
        "\n    CLASSIFICATION POSTURE (strict)\n"
        "    * Apply high scrutiny. If the content does not clearly and\n"
        "      unambiguously fit a single project, leave `project` null\n"
        "      (or use a low confidence score). Do not guess.\n"
    ),
}


def _build_system_prompt(
    project_descriptions: Dict[str, str],
    today: str,
    scrutiny: str = "balanced",
) -> str:
    """
    Render the system prompt with the registry's current projects and the
    configured classification posture (relaxed / balanced / strict).

    Each entry in project_descriptions is formatted as:
        project_name    -> Description text
    """
    if project_descriptions:
        proj_lines = "\n".join(
            f"    {name:<25} -> {desc}"
            for name, desc in project_descriptions.items()
        )
    else:
        proj_lines = "    (no projects exist yet — leave `project` null.)"
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(projects=proj_lines, today=today)
    prompt += _SCRUTINY_PARAGRAPHS.get(scrutiny, "")
    return prompt


# ---------------------------------------------------------------------------
# Main engine entry point
# ---------------------------------------------------------------------------

def run_llm_engine(
    enriched: "EnrichedPayload",
    registry: Dict[str, Any],
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
        registry:                The project registry, as returned by
                                 project_registry.load(vault_root):
                                 {"schema": 1, "projects": {name: {"description": ..., ...}}}.
                                 The engine picks only from these EXISTING projects (or
                                 leaves `project` null) -- it may never invent one. An
                                 empty/missing registry is a normal state, not an error.
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

    projects_ = (registry or {}).get("projects") or {}
    project_descriptions = {
        name: ((entry.get("description") or "").strip() or "(no description)")
        for name, entry in projects_.items()
    }

    # Build a fresh CaptureOutput model constrained to the registry's current
    # projects. An empty registry is normal (no projects yet) -- build_capture_model
    # returns the base CaptureOutput unchanged in that case, never an error.
    CaptureModel = build_capture_model(list(project_descriptions.keys()))

    system = _build_system_prompt(project_descriptions, today_str, scrutiny=scrutiny)

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
    model = _ollama_setting("OLLAMA_MODEL", "model", "llama3.2")
    keep_alive = _ollama_setting("OLLAMA_KEEP_ALIVE", "keep_alive", "30m")

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
