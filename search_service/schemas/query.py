from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from search_service.schemas.enums import AmbiguityLevel


class ExtractedEntity(BaseModel):
    """An entity extracted from the user's query."""

    value: str
    """The extracted entity text (e.g., 'Telstra')."""

    entity_type: str | None = None
    """Detected type (e.g., 'company_name', 'person', 'date').
    None if type could not be determined."""

    field_mapping: str | None = None
    """Index field this entity maps to, if resolved.
    Example: 'company_name' for a company index."""

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Confidence in the extraction. None if not scored."""


class QueryAnalysis(BaseModel):
    """Output of the query understanding pipeline.

    Captures everything the analyzer, classifier, and extractor
    produce from a raw query.
    """

    raw_query: str
    """The original user query, unmodified."""

    query_type: str | None = None
    """Classified intent of the query, drawn from the index's
    expected_query_types vocabulary. This is a developer-defined
    string, not a system enum. None if classification was not
    performed or was inconclusive."""

    primary_subject: str | None = None
    """Primary subject of the query (e.g., 'Telstra', 'billing',
    'onboarding'). None if no clear subject was detected."""

    target_resource_type: str | None = None
    """The resource type the user most likely wants
    (e.g., 'company'). None if ambiguous or undetected."""

    possible_resource_types: list[str] = []
    """All plausible resource types for this query, ranked by likelihood."""

    filters: dict[str, Any] = {}
    """Structured filters extracted from natural language.
    Keys are field names, values are filter values.
    Example: {'country': 'AU', 'status': 'active'}"""

    ambiguity: AmbiguityLevel = AmbiguityLevel.none
    """Assessed ambiguity level of the query relative to the index."""

    missing_fields: list[str] = []
    """Fields that would disambiguate the query but were not provided.
    Drives follow-up question generation."""

    extracted_entities: list[ExtractedEntity] = []
    """All entities extracted from the query with their types and positions."""
