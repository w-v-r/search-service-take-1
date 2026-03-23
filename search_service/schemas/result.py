from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from search_service.schemas.enums import BranchKind, InteractionMode, SearchStatus
from search_service.schemas.followup import FollowUpRequest
from search_service.schemas.query import QueryAnalysis


class SearchResultItem(BaseModel):
    """A single search result normalized from the backend response."""

    id: str
    """Document ID from the backend. Corresponds to the index's id_field."""

    title: str | None = None
    """Display title for the result."""

    snippet: str | None = None
    """Text snippet showing the match context."""

    score: float | None = None
    """Relevance score from the backend. Scale varies by backend;
    not normalized across adapters in v0."""

    source: str | None = None
    """Backend or index name that produced this result."""

    matched_fields: list[str] = []
    """Fields that contributed to this match."""

    metadata: dict[str, Any] = {}
    """Arbitrary metadata from the document. Contains fields
    from the display_fields configuration."""


class BranchResult(BaseModel):
    """Results from a single search branch.

    Each branch represents one search path -- the original query,
    a filter-augmented version, or a reformulated version.
    """

    kind: BranchKind
    """How this branch was created."""

    query: str
    """The query string used for this branch."""

    filters: dict[str, Any] = {}
    """Filters applied in this branch."""

    results: list[SearchResultItem] = []
    """Search results for this branch."""

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Confidence that this branch's results answer the user's intent.
    Set by the evaluator after results are returned."""

    total_backend_hits: int = 0
    """Total number of matching documents reported by the backend."""


class SearchResultEnvelope(BaseModel):
    """Top-level response from every search call.

    This is the primary contract between the SDK and the consuming application.
    """

    status: SearchStatus
    """Outcome of the search request."""

    original_query: str
    """The raw user query, always preserved unmodified."""

    interaction_mode: InteractionMode
    """The interaction mode used for this search."""

    query_analysis: QueryAnalysis | None = None
    """Full query analysis output. None if analysis was skipped."""

    results: list[SearchResultItem] = []
    """Merged, deduplicated result list."""

    branches: list[BranchResult] = []
    """Per-branch results preserving search provenance."""

    follow_up: FollowUpRequest | None = None
    """Structured follow-up when status is 'needs_input'.
    None for all other statuses."""

    message: str | None = None
    """Human-readable message explaining the result status."""

    trace_id: str
    """Unique identifier for this search trace."""

    latency_ms: float | None = None
    """Total end-to-end latency in milliseconds."""
