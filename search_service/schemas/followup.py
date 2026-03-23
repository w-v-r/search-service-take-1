from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    """A candidate interpretation of an ambiguous query.

    Returned when the harness identifies multiple plausible interpretations.
    """

    label: str
    """Human-readable description of this interpretation.
    Example: 'Telstra company records'"""

    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence that this interpretation matches the user's intent."""


class FollowUpRequest(BaseModel):
    """Structured follow-up returned when the harness needs more information.

    The application renders this however it wants -- the harness returns
    structure, not UI.
    """

    reason: str
    """Machine-readable reason code.
    Examples: 'underspecified_query', 'ambiguous_entity',
    'missing_required_filter'"""

    message: str
    """Human-readable explanation for the application to display."""

    input_schema: dict[str, Any]
    """JSON Schema describing the input the application should collect.
    The application can render this as a form, dropdown, or free text."""

    candidates: list[Candidate] = []
    """Candidate interpretations with confidence scores.
    The application can use these to pre-populate selections
    or show ranked options."""
