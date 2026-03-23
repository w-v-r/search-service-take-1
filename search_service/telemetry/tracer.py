"""Tracer -- records each pipeline step into a SearchTrace.

The Tracer is a pure telemetry layer. It captures what the search
pipeline does so you can retrospectively analyse queries, review
AITL/HITL decision patterns, and debug search behaviour -- analogous
to what Langsmith or Langfuse provide for LLM chains.

The Tracer does NOT carry search state. The search harness never reads
from a trace to make decisions or return information to the user.
Search state lives in SearchContext; the tracer runs alongside it as
a parallel data capture.

Usage::

    tracer = Tracer()
    trace = tracer.start(query="Telstra", interaction_mode=InteractionMode.hitl)

    with tracer.timed(trace, TraceStepType.query_analysis) as set_payload:
        analysis = analyze(query)
        set_payload({"raw_query": "Telstra", "query_type": analysis.query_type})

    tracer.complete(trace, final_status=SearchStatus.completed, reason="High confidence")
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from search_service.schemas.enums import InteractionMode, SearchStatus, TraceStepType
from search_service.schemas.trace import SearchTrace, TraceStep
from search_service.telemetry import events as events

if TYPE_CHECKING:
    from collections.abc import Callable


class Tracer:
    """Records pipeline steps into SearchTrace instances.

    This is purely observational. The trace store exists so traces can
    be retrieved for debugging, analytics, and retrospective review --
    not for search state management. Search state (for continue_search
    and pipeline decisions) is managed separately via SearchContext.
    """

    def __init__(self) -> None:
        self._traces: dict[str, SearchTrace] = {}

    def start(
        self,
        query: str,
        interaction_mode: InteractionMode,
        *,
        index_name: str | None = None,
        trace_id: str | None = None,
    ) -> SearchTrace:
        """Create a new trace and record the initial query_received step.

        Args:
            query: The raw user query.
            interaction_mode: The interaction mode for this search.
            index_name: Optional index name for the trace payload.
            trace_id: Optional pre-generated trace ID. If None, a UUID4 is generated.

        Returns:
            A new SearchTrace ready for step recording.
        """
        resolved_id = trace_id or uuid.uuid4().hex
        trace = SearchTrace(
            trace_id=resolved_id,
            original_query=query,
            interaction_mode=interaction_mode,
        )

        step = events.query_received(
            raw_query=query,
            interaction_mode=interaction_mode.value,
            index_name=index_name,
        )
        trace.add_step(step)

        self._traces[resolved_id] = trace
        return trace

    def record(
        self,
        trace: SearchTrace,
        step: TraceStep,
    ) -> None:
        """Record a single step into the trace.

        Args:
            trace: The trace to record into.
            step: The TraceStep to append.
        """
        trace.add_step(step)

    @contextmanager
    def timed(
        self,
        trace: SearchTrace,
        step_type: TraceStepType,
        *,
        model_used: str | None = None,
    ) -> Generator[Callable[[dict[str, object]], None], None, None]:
        """Context manager that auto-times a step and records it on exit.

        Yields a callback that accepts a payload dict. The callback must be
        called before the context exits to provide the step-specific data.
        If the callback is not called, a step with an empty payload is recorded.

        Usage::

            with tracer.timed(trace, TraceStepType.query_analysis) as set_payload:
                analysis = analyze(query)
                set_payload({"raw_query": query, "query_type": analysis.query_type})
        """
        payload: dict[str, object] = {}

        def set_payload(data: dict[str, object]) -> None:
            payload.update(data)

        start = time.perf_counter()
        try:
            yield set_payload
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            step = TraceStep(
                step_type=step_type,
                payload=payload,
                latency_ms=round(elapsed_ms, 3),
                model_used=model_used,
            )
            trace.add_step(step)

    def complete(
        self,
        trace: SearchTrace,
        *,
        final_status: SearchStatus,
        reason: str | None = None,
        total_latency_ms: float | None = None,
    ) -> SearchTrace:
        """Finalize a trace with its outcome.

        Args:
            trace: The trace to finalize.
            final_status: The final search status.
            reason: Human-readable explanation of why the search terminated.
            total_latency_ms: End-to-end latency. If None, computed from
                the sum of all step latencies.

        Returns:
            The finalized trace.
        """
        trace.final_status = final_status
        trace.final_decision_reason = reason

        if total_latency_ms is not None:
            trace.total_latency_ms = total_latency_ms
        else:
            trace.total_latency_ms = self._sum_step_latencies(trace)

        return trace

    def get(self, trace_id: str) -> SearchTrace | None:
        """Retrieve a trace by its ID. Returns None if not found."""
        return self._traces.get(trace_id)

    def has(self, trace_id: str) -> bool:
        """Check if a trace with the given ID exists."""
        return trace_id in self._traces

    def remove(self, trace_id: str) -> SearchTrace | None:
        """Remove and return a trace by its ID. Returns None if not found."""
        return self._traces.pop(trace_id, None)

    @property
    def trace_count(self) -> int:
        """Number of traces currently stored."""
        return len(self._traces)

    @staticmethod
    def _sum_step_latencies(trace: SearchTrace) -> float:
        return round(
            sum(s.latency_ms for s in trace.steps if s.latency_ms is not None),
            3,
        )
