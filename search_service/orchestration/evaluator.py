"""Evaluator -- assesses search results and makes the stopping decision.

The evaluator examines branch results in the context of the current
SearchContext and decides what happens next:

- completed: results are good enough, return them
- needs_input: uncertainty too high, ask the user for clarification
- iterate: results can be improved, send back to the planner

Behavior varies by interaction mode:
- HITL: returns needs_input immediately on material ambiguity
- AITL: tries to resolve within budget, falls back to needs_input
  when autonomous resolution fails
"""

from __future__ import annotations

from search_service._internal.context import NextAction, SearchContext
from search_service._internal.enums import EvaluatorAction
from search_service.orchestration.aitl_context import (
    build_aitl_context,
    has_actionable_next_step,
    resolve_raw_query,
)
from search_service.schemas.enums import AmbiguityLevel, InteractionMode
from search_service.schemas.result import BranchResult
from search_service.schemas.trace import SearchTrace
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer


def evaluate_results(
    branch_results: list[BranchResult],
    context: SearchContext,
    tracer: Tracer,
    trace: SearchTrace,
) -> NextAction:
    """Evaluate search results and decide the next pipeline action.

    Args:
        branch_results: Results from the latest plan execution.
        context: Current pipeline state (budget, analysis, prior results).
        tracer: Tracer for recording the evaluation step.
        trace: Active trace to record into.

    Returns:
        NextAction indicating completed, needs_input, or iterate.
    """
    confidence = assess_confidence(branch_results, context)

    for branch in branch_results:
        if branch.confidence is None:
            branch.confidence = confidence

    next_action = _decide(confidence, context)
    _record_evaluation_step(
        confidence, next_action, branch_results, context, tracer, trace,
    )
    return next_action


def assess_confidence(
    branch_results: list[BranchResult],
    context: SearchContext,
) -> float:
    """Heuristic confidence assessment for v0.

    Uses result count and ambiguity level as proxy signals.
    The confidence model will be refined based on production data
    (see docs/open-questions.md).
    """
    if not branch_results:
        return 0.0

    total_results = sum(len(b.results) for b in branch_results)

    if total_results == 0:
        return 0.0

    if total_results <= 5:
        base = 0.8
    elif total_results <= 20:
        base = 0.6
    else:
        base = 0.4

    if context.query_analysis is not None:
        ambiguity = context.query_analysis.ambiguity
        if ambiguity == AmbiguityLevel.high:
            base *= 0.5
        elif ambiguity == AmbiguityLevel.medium:
            base *= 0.7
        elif ambiguity == AmbiguityLevel.low:
            base *= 0.9

    if any(b.filters for b in branch_results):
        base = min(1.0, base + 0.1)

    return round(min(1.0, base), 2)


def _decide(confidence: float, context: SearchContext) -> NextAction:
    """Core stopping/continuation logic."""
    thresholds = context.policy.confidence_thresholds

    if confidence >= thresholds.stop:
        return NextAction(
            action=EvaluatorAction.completed,
            reason=(
                f"Confidence {confidence:.2f} meets stop threshold "
                f"{thresholds.stop}"
            ),
        )

    if context.budget_exhausted:
        return NextAction(
            action=EvaluatorAction.completed,
            reason=(
                f"Budget exhausted. Returning best available results "
                f"at confidence {confidence:.2f}"
            ),
        )

    if context.interaction_mode == InteractionMode.hitl:
        if _is_materially_ambiguous(context):
            return NextAction(
                action=EvaluatorAction.needs_input,
                reason=(
                    f"HITL mode: material ambiguity "
                    f"({_ambiguity_label(context)}) detected"
                ),
            )

    query = resolve_raw_query(context)
    if has_actionable_next_step(context, query):
        return NextAction(
            action=EvaluatorAction.iterate,
            reason=(
                f"Confidence {confidence:.2f} below stop threshold "
                f"{thresholds.stop}. {context.iterations_remaining} "
                f"iteration(s) remaining. Actionable improvement available."
            ),
        )

    if context.interaction_mode == InteractionMode.aitl:
        if confidence < thresholds.escalate:
            return NextAction(
                action=EvaluatorAction.needs_input,
                reason=(
                    f"AITL: confidence {confidence:.2f} below escalate "
                    f"threshold {thresholds.escalate}, no actionable "
                    f"improvement available. Falling back to user input."
                ),
            )

    return NextAction(
        action=EvaluatorAction.completed,
        reason=f"Returning results at confidence {confidence:.2f}",
    )


def _is_materially_ambiguous(context: SearchContext) -> bool:
    """Check if the query has material ambiguity."""
    if context.query_analysis is None:
        return False
    return context.query_analysis.ambiguity in {
        AmbiguityLevel.high,
        AmbiguityLevel.medium,
    }


def _ambiguity_label(context: SearchContext) -> str:
    if context.query_analysis is not None:
        return context.query_analysis.ambiguity.value
    return "unknown"


def _record_evaluation_step(
    confidence: float,
    next_action: NextAction,
    branch_results: list[BranchResult],
    context: SearchContext,
    tracer: Tracer,
    trace: SearchTrace,
) -> None:
    """Record an evaluation trace step."""
    total_results = sum(len(b.results) for b in branch_results)
    q = resolve_raw_query(context)
    tracer.record(
        trace,
        events.evaluation(
            confidence=confidence,
            action_chosen=next_action.action.value,
            decision_reason=next_action.reason,
            result_count=total_results,
            aitl_context=build_aitl_context(context, query=q),
        ),
    )
