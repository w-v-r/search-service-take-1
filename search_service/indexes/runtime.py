"""Runtime search execution -- wires the search pipeline end to end.

Two execution paths are available:

1. Direct search (no LLM):
       index.search(query) -> plan -> executor -> adapter -> result envelope

2. Orchestrated search (with QueryAnalyzer):
       analyze -> plan -> execute -> evaluate -> (iterate or return)

   The orchestrated path runs the full planner/evaluator decision loop,
   enabling budget-aware iteration, filter application, and multi-branch
   search. It falls back to the direct path when no analyzer is provided.
"""

from __future__ import annotations

import time
from typing import Any

from search_service._internal.context import SearchContext
from search_service._internal.enums import EvaluatorAction, PlanAction
from search_service._internal.plan import PlannedBranch, SearchPlan
from search_service.exceptions import AdapterError, SearchExecutionError, TraceNotFoundError
from search_service.orchestration.evaluator import evaluate_results
from search_service.orchestration.executor import execute_plan
from search_service.orchestration.analyzer import QueryAnalyzer
from search_service.orchestration.followup import (
    TerminationSource,
    build_follow_up_request,
    merge_continuation_input,
)
from search_service.orchestration.planner import create_plan
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import (
    BranchKind,
    InteractionMode,
    SearchStatus,
)
from search_service.schemas.result import SearchResultEnvelope, SearchResultItem
from search_service.schemas.trace import SearchTrace
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer


def execute_search(
    query: str,
    config: IndexConfig,
    tracer: Tracer,
    *,
    interaction_mode: InteractionMode | None = None,
    filters: dict[str, Any] | None = None,
) -> SearchResultEnvelope:
    """Execute an end-to-end direct search (no LLM).

    Builds a single-branch plan from the raw query, executes it
    against the index's adapter, and returns a SearchResultEnvelope
    with full trace recording.

    Args:
        query: The user's search query string.
        config: Index configuration with adapter and field definitions.
        tracer: Tracer instance for recording the search trace.
        interaction_mode: Override the index default. Falls back to
            config.default_interaction_mode.
        filters: Optional pre-specified filters to apply.

    Returns:
        SearchResultEnvelope with status, results, branches, and trace_id.

    Raises:
        AdapterError: If the backend adapter fails.
        SearchExecutionError: If the pipeline fails unexpectedly.
    """
    start = time.perf_counter()
    mode = interaction_mode or config.default_interaction_mode

    trace = tracer.start(
        query=query,
        interaction_mode=mode,
        index_name=config.name,
    )

    try:
        plan = _build_direct_plan(query, filters=filters)

        tracer.record(
            trace,
            events.planning(
                action=plan.action.value,
                branches=[
                    {"kind": b.kind.value, "query": b.query, "filters": b.filters}
                    for b in plan.branches
                ],
                reasoning=plan.reasoning,
            ),
        )

        branch_results = execute_plan(
            plan=plan,
            adapter=config.adapter,
            config=config,
            tracer=tracer,
            trace=trace,
        )

        all_results = []
        for branch in branch_results:
            all_results.extend(branch.results)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

        tracer.complete(
            trace,
            final_status=SearchStatus.completed,
            reason="Direct search completed",
            total_latency_ms=elapsed_ms,
        )

        return SearchResultEnvelope(
            status=SearchStatus.completed,
            original_query=query,
            interaction_mode=mode,
            results=all_results,
            branches=branch_results,
            trace_id=trace.trace_id,
            latency_ms=elapsed_ms,
            message="Search completed",
        )

    except AdapterError:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason="Adapter error during search execution",
            total_latency_ms=elapsed_ms,
        )
        raise

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason=f"Unexpected error: {exc}",
            total_latency_ms=elapsed_ms,
        )
        raise SearchExecutionError(f"Search pipeline failed: {exc}") from exc


def _build_direct_plan(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
) -> SearchPlan:
    """Build a simple single-branch plan for direct search."""
    resolved_filters = filters or {}
    action = PlanAction.search_with_filters if resolved_filters else PlanAction.direct_search

    return SearchPlan(
        action=action,
        branches=[
            PlannedBranch(
                kind=BranchKind.original_query,
                query=query,
                filters=resolved_filters,
            ),
        ],
        reasoning="Direct search -- no LLM analysis",
    )


# ---------------------------------------------------------------------------
# Orchestrated search pipeline (with QueryAnalyzer)
# ---------------------------------------------------------------------------


def execute_orchestrated_search(
    query: str,
    config: IndexConfig,
    tracer: Tracer,
    analyzer: QueryAnalyzer,
    *,
    interaction_mode: InteractionMode | None = None,
    filters: dict[str, Any] | None = None,
    sessions: dict[str, SearchContext] | None = None,
) -> SearchResultEnvelope:
    """Execute the full orchestrated search pipeline.

    Runs: analyze -> plan -> execute -> evaluate -> (iterate or return).

    When a QueryAnalyzer is available, this path enables budget-aware
    iteration, filter application from extracted structure, and
    multi-branch search. The loop is bounded by SearchPolicy.max_iterations.

    Args:
        query: The user's search query string.
        config: Index configuration with adapter and field definitions.
        tracer: Tracer instance for recording the search trace.
        analyzer: QueryAnalyzer for classification and extraction.
        interaction_mode: Override the index default.
        filters: Optional pre-specified filters to apply.
        sessions: Optional store for ``needs_input`` continuation (trace_id -> context).

    Returns:
        SearchResultEnvelope with status, results, branches, and trace_id.
    """
    start = time.perf_counter()
    mode = interaction_mode or config.default_interaction_mode

    trace = tracer.start(
        query=query,
        interaction_mode=mode,
        index_name=config.name,
    )

    try:
        context = SearchContext(
            index_config=config,
            interaction_mode=mode,
            policy=config.policy,
        )

        analysis = analyzer.analyze(query, config, tracer, trace)
        context.query_analysis = analysis

        if analysis.filters:
            context.unapplied_filters = dict(analysis.filters)

        if filters:
            context.unapplied_filters.update(filters)

        return _run_orchestration_loop(
            query=query,
            config=config,
            tracer=tracer,
            trace=trace,
            context=context,
            start=start,
            sessions=sessions,
        )

    except AdapterError:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason="Adapter error during orchestrated search",
            total_latency_ms=elapsed_ms,
        )
        raise

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason=f"Unexpected error: {exc}",
            total_latency_ms=elapsed_ms,
        )
        raise SearchExecutionError(
            f"Orchestrated search pipeline failed: {exc}"
        ) from exc


def continue_orchestrated_search(
    trace_id: str,
    user_input: dict[str, Any],
    config: IndexConfig,
    tracer: Tracer,
    *,
    sessions: dict[str, SearchContext],
) -> SearchResultEnvelope:
    """Resume orchestration after ``needs_input``, reusing trace and context."""
    if trace_id not in sessions:
        raise TraceNotFoundError(trace_id)

    trace = tracer.get(trace_id)
    if trace is None:
        raise TraceNotFoundError(trace_id)

    context = sessions[trace_id]
    start = time.perf_counter()

    try:
        trace.final_status = None
        trace.final_decision_reason = None

        merge_continuation_input(context, user_input)
        context.iterations_used = 0
        context.branches_used = 0
        context.actions_taken.append("continuation")

        tracer.record(
            trace,
            events.decision(
                action_chosen="continuation",
                decision_reason=(
                    "Received follow-up input: "
                    + ", ".join(sorted(user_input.keys()))
                ),
            ),
        )

        return _run_orchestration_loop(
            query=trace.original_query,
            config=config,
            tracer=tracer,
            trace=trace,
            context=context,
            start=start,
            sessions=sessions,
        )

    except AdapterError:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason="Adapter error during continued search",
            total_latency_ms=elapsed_ms,
        )
        raise

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason=f"Unexpected error: {exc}",
            total_latency_ms=elapsed_ms,
        )
        raise SearchExecutionError(
            f"Orchestrated search continuation failed: {exc}"
        ) from exc


def _run_orchestration_loop(
    query: str,
    config: IndexConfig,
    tracer: Tracer,
    trace: SearchTrace,
    context: SearchContext,
    start: float,
    *,
    sessions: dict[str, SearchContext] | None,
) -> SearchResultEnvelope:
    """Planner / executor / evaluator loop (shared by search and continuation)."""
    mode = context.interaction_mode
    analysis = context.query_analysis

    status = SearchStatus.completed
    follow_source: TerminationSource | None = None

    while context.iterations_used < config.policy.max_iterations:
        context.iterations_used += 1

        if mode == InteractionMode.aitl:
            tracer.record(
                trace,
                events.budget_check(
                    iterations_remaining=context.iterations_remaining,
                    branches_remaining=context.branches_remaining,
                    budget_exhausted=context.budget_exhausted,
                    at_final_iteration=context.at_final_iteration,
                ),
            )

        plan = create_plan(query, context, tracer, trace)

        if plan.action == PlanAction.needs_clarification:
            status = SearchStatus.needs_input
            follow_source = "planner_clarification"
            break

        branch_results = execute_plan(
            plan=plan,
            adapter=config.adapter,
            config=config,
            tracer=tracer,
            trace=trace,
        )
        context.branches.extend(branch_results)

        if len(branch_results) > 1:
            tracer.record(
                trace,
                events.branch_merge(
                    branch_count=len(branch_results),
                    merged_result_count=sum(len(b.results) for b in branch_results),
                    strategy="per_branch_then_dedupe",
                ),
            )

        if any(b.kind == BranchKind.reformulated for b in plan.branches):
            context.reformulation_attempted = True

        if plan.action in (
            PlanAction.search_with_filters,
            PlanAction.multi_branch,
        ):
            context.unapplied_filters.clear()

        non_original = sum(
            1 for b in plan.branches if b.kind != BranchKind.original_query
        )
        context.branches_used += non_original
        context.actions_taken.append(plan.action.value)

        next_action = evaluate_results(
            branch_results, context, tracer, trace,
        )

        if next_action.action == EvaluatorAction.completed:
            status = SearchStatus.completed
            break
        if next_action.action == EvaluatorAction.needs_input:
            status = SearchStatus.needs_input
            follow_source = "evaluator_ambiguity"
            break

    all_results = _dedup_results(context.branches)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

    follow_up = None
    if status == SearchStatus.needs_input and follow_source is not None:
        follow_up = build_follow_up_request(context, source=follow_source)
        tracer.record(
            trace,
            events.follow_up_generation(
                follow_up.reason,
                candidate_count=len(follow_up.candidates),
            ),
        )

    _sync_session_store(sessions, trace.trace_id, context, status)

    tracer.complete(
        trace,
        final_status=status,
        reason=f"Orchestrated search: {status.value}",
        total_latency_ms=elapsed_ms,
    )

    return SearchResultEnvelope(
        status=status,
        original_query=query,
        interaction_mode=mode,
        query_analysis=analysis,
        results=all_results,
        branches=list(context.branches),
        follow_up=follow_up,
        trace_id=trace.trace_id,
        latency_ms=elapsed_ms,
        message=_orchestrated_message(status, context),
    )


def _sync_session_store(
    sessions: dict[str, SearchContext] | None,
    trace_id: str,
    context: SearchContext,
    status: SearchStatus,
) -> None:
    if sessions is None:
        return
    if status == SearchStatus.needs_input:
        sessions[trace_id] = context
    else:
        sessions.pop(trace_id, None)


def _dedup_results(branches: list[Any]) -> list[SearchResultItem]:
    """Collect results from all branches, deduplicating by document ID."""
    seen: set[str] = set()
    deduped: list[SearchResultItem] = []

    for branch in branches:
        for item in branch.results:
            if item.id not in seen:
                seen.add(item.id)
                deduped.append(item)

    return deduped


def _orchestrated_message(status: SearchStatus, context: SearchContext) -> str:
    """Build a human-readable message for the orchestrated search result."""
    total = sum(len(b.results) for b in context.branches)

    if status == SearchStatus.needs_input:
        return "Additional information needed to refine search results"

    if total == 0:
        return "No results found"

    iterations = context.iterations_used
    branch_count = len(context.branches)
    suffix = f" ({iterations} iteration(s), {branch_count} branch(es))"
    return f"Search completed with {total} result(s){suffix}"
