"""Event factory functions for creating TraceStep instances.

Each function creates a TraceStep with the appropriate step_type and
a structured payload. The orchestration layer calls these instead of
manually constructing TraceStep instances with raw dicts.

Payload keys are conventions, not enforced schema -- but using these
factories keeps the conventions consistent across the codebase.
"""

from __future__ import annotations

from typing import Any

from search_service.schemas.enums import TraceStepType
from search_service.schemas.trace import TraceStep


def query_received(
    raw_query: str,
    interaction_mode: str,
    *,
    index_name: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {
        "raw_query": raw_query,
        "interaction_mode": interaction_mode,
    }
    if index_name is not None:
        payload["index_name"] = index_name
    return TraceStep(step_type=TraceStepType.query_received, payload=payload)


def query_analysis(
    raw_query: str,
    *,
    query_type: str | None = None,
    ambiguity: str | None = None,
    primary_subject: str | None = None,
    filters: dict[str, Any] | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"raw_query": raw_query}
    if query_type is not None:
        payload["query_type"] = query_type
    if ambiguity is not None:
        payload["ambiguity"] = ambiguity
    if primary_subject is not None:
        payload["primary_subject"] = primary_subject
    if filters:
        payload["filters"] = filters
    return TraceStep(
        step_type=TraceStepType.query_analysis,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def classification(
    query_type: str,
    *,
    confidence: float | None = None,
    candidates: list[str] | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"query_type": query_type}
    if confidence is not None:
        payload["confidence"] = confidence
    if candidates is not None:
        payload["candidates"] = candidates
    return TraceStep(
        step_type=TraceStepType.classification,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def extraction(
    entities: list[dict[str, Any]],
    *,
    filters: dict[str, Any] | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"entities": entities}
    if filters:
        payload["filters"] = filters
    return TraceStep(
        step_type=TraceStepType.extraction,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def planning(
    action: str,
    *,
    branches: list[dict[str, Any]] | None = None,
    reasoning: str | None = None,
    iterations_remaining: int | None = None,
    branches_remaining: int | None = None,
    aitl_context: dict[str, Any] | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"action": action}
    if branches is not None:
        payload["branches"] = branches
    if reasoning is not None:
        payload["reasoning"] = reasoning
    if iterations_remaining is not None:
        payload["iterations_remaining"] = iterations_remaining
    if branches_remaining is not None:
        payload["branches_remaining"] = branches_remaining
    if aitl_context is not None:
        payload["aitl_context"] = aitl_context
    return TraceStep(
        step_type=TraceStepType.planning,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def search_execution(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    result_count: int | None = None,
    total_backend_hits: int | None = None,
    branch_kind: str | None = None,
    latency_ms: float | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"query": query}
    if filters:
        payload["filters"] = filters
    if result_count is not None:
        payload["result_count"] = result_count
    if total_backend_hits is not None:
        payload["total_backend_hits"] = total_backend_hits
    if branch_kind is not None:
        payload["branch_kind"] = branch_kind
    return TraceStep(
        step_type=TraceStepType.search_execution,
        payload=payload,
        latency_ms=latency_ms,
    )


def evaluation(
    confidence: float,
    action_chosen: str,
    *,
    decision_reason: str | None = None,
    result_count: int | None = None,
    aitl_context: dict[str, Any] | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {
        "confidence": confidence,
        "action_chosen": action_chosen,
    }
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    if result_count is not None:
        payload["result_count"] = result_count
    if aitl_context is not None:
        payload["aitl_context"] = aitl_context
    return TraceStep(
        step_type=TraceStepType.evaluation,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def follow_up_generation(
    reason: str,
    *,
    candidate_count: int | None = None,
    latency_ms: float | None = None,
    model_used: str | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"reason": reason}
    if candidate_count is not None:
        payload["candidate_count"] = candidate_count
    return TraceStep(
        step_type=TraceStepType.follow_up_generation,
        payload=payload,
        latency_ms=latency_ms,
        model_used=model_used,
    )


def branch_created(
    kind: str,
    query: str,
    *,
    filters: dict[str, Any] | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"kind": kind, "query": query}
    if filters:
        payload["filters"] = filters
    return TraceStep(step_type=TraceStepType.branch_created, payload=payload)


def branch_merge(
    branch_count: int,
    *,
    merged_result_count: int | None = None,
    strategy: str | None = None,
    latency_ms: float | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {"branch_count": branch_count}
    if merged_result_count is not None:
        payload["merged_result_count"] = merged_result_count
    if strategy is not None:
        payload["strategy"] = strategy
    return TraceStep(
        step_type=TraceStepType.branch_merge,
        payload=payload,
        latency_ms=latency_ms,
    )


def budget_check(
    iterations_remaining: int,
    branches_remaining: int,
    *,
    budget_exhausted: bool = False,
    at_final_iteration: bool = False,
) -> TraceStep:
    return TraceStep(
        step_type=TraceStepType.budget_check,
        payload={
            "iterations_remaining": iterations_remaining,
            "branches_remaining": branches_remaining,
            "budget_exhausted": budget_exhausted,
            "at_final_iteration": at_final_iteration,
        },
    )


def decision(
    action_chosen: str,
    decision_reason: str,
    *,
    iterations_remaining: int | None = None,
    branches_remaining: int | None = None,
    confidence: float | None = None,
) -> TraceStep:
    payload: dict[str, Any] = {
        "action_chosen": action_chosen,
        "decision_reason": decision_reason,
    }
    if iterations_remaining is not None:
        payload["iterations_remaining"] = iterations_remaining
    if branches_remaining is not None:
        payload["branches_remaining"] = branches_remaining
    if confidence is not None:
        payload["confidence"] = confidence
    return TraceStep(step_type=TraceStepType.decision, payload=payload)
