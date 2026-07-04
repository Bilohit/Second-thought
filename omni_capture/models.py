"""
models.py - Pydantic schemas for the LLM Decision Engine structured output.

Categories are now dynamic: derived at runtime from the folders in the vault
root.  Call build_capture_model(categories) to get a CaptureOutput subclass
whose 'category' field is constrained to exactly the discovered folder names.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Type

from pydantic import BaseModel, Field, create_model


class EnrichedPayload(BaseModel):
    raw_input: str = Field(description="Original clipboard text/URL.")
    input_type: str
    enriched_text: str = Field(description="Processed/extracted content ready for the LLM.")
    source_url: Optional[str] = None
    source_metadata: dict = Field(default_factory=dict)


class DetectedEvent(BaseModel):
    when_iso: str = Field(
        description="ISO-8601 local datetime, e.g. 2026-07-05T15:00. Only concrete, resolvable dates/times."
    )
    label: str = Field(description="Short label for what happens then, e.g. 'Dentist appointment'.")


class CaptureOutput(BaseModel):
    """
    Base capture output schema.

    Use build_capture_model(categories) to obtain a subclass whose 'category'
    field is constrained (via a dynamic Enum) to exactly the folder names that
    exist in the vault.  All other pipeline code (storage_engine, main) accepts
    this base class for type hints.
    """

    category: str = Field(description="Which vault folder this content belongs to.")
    suggested_filename: str = Field(
        description="Kebab-case slug, lowercase, MAX 2 meaningful words, ≤40 chars, no extension, no filler words."
    )
    markdown_content: str = Field(
        description="Fully formatted Markdown to write or append to the note."
    )
    rationale: str = Field(default="", description="Why this category was chosen.")
    key_signals: List[str] = Field(default_factory=list, description="Up to 5 signal strings.")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    requires_new_category: bool = Field(
        default=False,
        description=(
            "True when content fits none of the available categories. "
            "Routes to scratchpad for manual review."
        ),
    )
    detected_events: List[DetectedEvent] = Field(
        default_factory=list,
        description=(
            "Concrete FUTURE dates/times found in the content (meetings, deadlines, "
            "appointments). Resolve relative dates against today's date. Empty when none."
        ),
    )


def filter_future_events(events: List[DetectedEvent], now: datetime) -> List[DetectedEvent]:
    """Drop unparseable and past events. LLM output is untrusted input."""
    kept: List[DetectedEvent] = []
    for e in events:
        try:
            when = datetime.fromisoformat(e.when_iso)
        except ValueError:
            continue
        # LLM sometimes suffixes "Z"/"+05:30" despite the local-datetime
        # instruction. The value IS local wall-clock time — the suffix is
        # noise, not a real UTC conversion. Strip it (astimezone() here
        # shifted +05:30 and turned "tomorrow 19:30" into 01:00 next day).
        # Also rewrite when_iso so every downstream consumer (reminder_offer
        # SSE, POST /reminders, fire_at storage, due_reminders' lexical
        # compare, schtasks) sees a naive local ISO string.
        if when.tzinfo is not None:
            when = when.replace(tzinfo=None)
            e.when_iso = when.isoformat(timespec="minutes")
        if when > now:
            kept.append(e)
    return kept


def build_capture_model(categories: List[str]) -> Type[CaptureOutput]:
    """
    Return a CaptureOutput subclass whose 'category' field is constrained
    to exactly the provided list of category names.

    The dynamic Enum causes Pydantic (and therefore instructor) to emit a JSON
    schema with 'enum': [...] for the 'category' field, forcing the LLM to
    pick only from the vault's actual folders.
    """
    if not categories:
        raise ValueError(
            "build_capture_model() requires at least one category. "
            "Make sure the vault root contains at least one non-system folder."
        )

    # Build a StrEnum-compatible base class that returns the plain value from
    # __str__, so str(output.category) == "Tech_Notes" everywhere.
    class _CategoryBase(str, Enum):
        def __str__(self) -> str:
            return self.value

    CategoryEnum = _CategoryBase("CategoryEnum", {c: c for c in categories})

    DynamicModel: Type[CaptureOutput] = create_model(
        "CaptureOutput",
        __base__=CaptureOutput,
        category=(
            CategoryEnum,
            Field(description="Which vault folder this content belongs to."),
        ),
    )
    return DynamicModel
