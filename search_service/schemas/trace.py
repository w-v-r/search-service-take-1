from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from search_service.schemas.enums import InteractionMode, SearchStatus, TraceStepType


class TraceStep(BaseModel):
    """A single step in the search trace.

    Kept deliberately minimal for v0 -- the payload dict carries
    step-specific data without forcing every orchestration change
    into a schema migration.
    """

    step_type: TraceStepType
    """What kind of pipeline step this is."""

    payload: dict[str, Any] = {}
    """Step-specific data. Contents vary by step_type and are
    intentionally unstructured for v0.

    Common keys by step_type (conventions, not enforced):
      query_analysis:   {raw_query, query_type, ambiguity, ...}
      planning:         {action, branches, reasoning, iterations_remaining, ...}
      search_execution: {query, filters, result_count, ...}
      evaluation:       {confidence, decision_reason, action_chosen, ...}
      decision:         {action_chosen, decision_reason, iterations_remaining,
                         branches_remaining, ...}
    """

    latency_ms: float | None = None
    """Time taken for this step in milliseconds."""

    model_used: str | None = None
    """LLM model identifier if this step involved a model call.
    None for steps that don't use an LLM."""


class SearchTrace(BaseModel):
    """Complete trace of a search request from start to finish.

    Every search request produces a trace, regardless of interaction mode.
    """

    trace_id: str
    """Unique trace identifier. Matches the trace_id in the
    SearchResultEnvelope."""

    original_query: str
    """The raw user query that initiated this trace."""

    normalized_query: str | None = None
    """Normalized form of the query (lowercase, trimmed, etc.)
    if normalization was applied."""

    steps: list[TraceStep] = []
    """Ordered list of pipeline steps."""

    total_latency_ms: float | None = None
    """End-to-end latency for the entire search request."""

    final_status: SearchStatus | None = None
    """The final status of the search request."""

    final_decision_reason: str | None = None
    """Human-readable explanation of why the search terminated
    with its final status."""

    interaction_mode: InteractionMode | None = None
    """The interaction mode used for this search trace."""

    iterations_used: int = 0
    """Total iterations consumed during this search."""

    branches_used: int = 0
    """Total branches created during this search."""

    def add_step(self, step: TraceStep) -> None:
        """Append a step to the trace."""
        self.steps.append(step)

    @property
    def is_complete(self) -> bool:
        return self.final_status is not None
