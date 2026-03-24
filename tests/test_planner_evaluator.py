"""Tests for the search planner, evaluator, and orchestrated pipeline.

Covers:
- Planner: action selection based on analysis, budget, and interaction mode
- Evaluator: confidence assessment, stopping decisions, iteration control
- Orchestrated pipeline: full analyze -> plan -> execute -> evaluate loop

All tests use inline StubModelProvider instances with predetermined results.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from search_service._internal.context import NextAction, SearchContext
from search_service._internal.enums import EvaluatorAction, PlanAction
from search_service._internal.plan import SearchPlan
from search_service.adapters.in_memory import InMemoryAdapter
from search_service.client import SearchClient
from search_service.exceptions import SearchExecutionError, TraceNotFoundError
from search_service.models.llm import ClassificationResult, ExtractionResult
from search_service.orchestration.analyzer import QueryAnalyzer
from search_service.orchestration.evaluator import assess_confidence, evaluate_results
from search_service.orchestration.planner import create_plan
from search_service.schemas.config import (
    ConfidenceThresholds,
    IndexConfig,
    SearchPolicy,
)
from search_service.schemas.enums import (
    AmbiguityLevel,
    BranchKind,
    InteractionMode,
    SearchStatus,
    TraceStepType,
)
from search_service.schemas.query import ExtractedEntity, QueryAnalysis
from search_service.schemas.result import BranchResult, SearchResultEnvelope, SearchResultItem
from search_service.telemetry.tracer import Tracer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class CompanyDocument(BaseModel):
    id: str
    name: str
    country: str
    status: str


SAMPLE_DOCS = [
    {"id": "1", "name": "Telstra Corporation", "country": "AU", "status": "active"},
    {"id": "2", "name": "Optus Networks", "country": "AU", "status": "active"},
    {"id": "3", "name": "Vodafone Australia", "country": "AU", "status": "inactive"},
    {"id": "4", "name": "British Telecom", "country": "UK", "status": "active"},
    {"id": "5", "name": "AT&T Inc", "country": "US", "status": "active"},
]


class StubModelProvider:
    """Minimal stub that returns configurable, predetermined results."""

    def __init__(
        self,
        *,
        classification: ClassificationResult | None = None,
        extraction: ExtractionResult | None = None,
        name: str = "stub/test",
    ) -> None:
        self._classification = classification or ClassificationResult()
        self._extraction = extraction or ExtractionResult()
        self._name = name

    @property
    def model_name(self) -> str:
        return self._name

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return self._classification

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        return self._extraction


def _make_config(
    *,
    interaction_mode: InteractionMode = InteractionMode.hitl,
    max_iterations: int = 2,
    max_branches: int = 2,
    canonical_filters: dict[str, list[str]] | None = None,
    stop_threshold: float = 0.7,
    escalate_threshold: float = 0.3,
    docs: list[dict[str, Any]] | None = None,
) -> IndexConfig:
    adapter = InMemoryAdapter(
        documents=docs or SAMPLE_DOCS,
        searchable_fields=["name"],
    )
    return IndexConfig(
        name="companies",
        document_schema=CompanyDocument,
        adapter=adapter,
        searchable_fields=["name"],
        filterable_fields=["country", "status"],
        display_fields=["name", "country", "status"],
        id_field="id",
        entity_types=["company"],
        expected_query_types=["entity_lookup", "name_search"],
        default_interaction_mode=interaction_mode,
        policy=SearchPolicy(
            max_iterations=max_iterations,
            max_branches=max_branches,
            canonical_filters=canonical_filters or {},
            confidence_thresholds=ConfidenceThresholds(
                stop=stop_threshold,
                escalate=escalate_threshold,
            ),
        ),
    )


def _make_context(
    *,
    interaction_mode: InteractionMode = InteractionMode.hitl,
    max_iterations: int = 2,
    max_branches: int = 2,
    iterations_used: int = 0,
    branches_used: int = 0,
    query_analysis: QueryAnalysis | None = None,
    unapplied_filters: dict[str, Any] | None = None,
    branches: list[BranchResult] | None = None,
    stop_threshold: float = 0.7,
    escalate_threshold: float = 0.3,
) -> SearchContext:
    config = _make_config(
        interaction_mode=interaction_mode,
        max_iterations=max_iterations,
        max_branches=max_branches,
        stop_threshold=stop_threshold,
        escalate_threshold=escalate_threshold,
    )
    ctx = SearchContext(
        index_config=config,
        interaction_mode=interaction_mode,
        policy=config.policy,
        iterations_used=iterations_used,
        branches_used=branches_used,
        query_analysis=query_analysis,
    )
    if unapplied_filters:
        ctx.unapplied_filters = dict(unapplied_filters)
    if branches:
        ctx.branches = list(branches)
    return ctx


def _make_analysis(
    *,
    ambiguity: AmbiguityLevel = AmbiguityLevel.none,
    filters: dict[str, Any] | None = None,
    missing_fields: list[str] | None = None,
    query_type: str | None = None,
    primary_subject: str | None = None,
) -> QueryAnalysis:
    return QueryAnalysis(
        raw_query="test query",
        query_type=query_type,
        ambiguity=ambiguity,
        filters=filters or {},
        missing_fields=missing_fields or [],
        primary_subject=primary_subject,
    )


def _make_branch_results(
    *,
    result_count: int = 1,
    kind: BranchKind = BranchKind.original_query,
    filters: dict[str, Any] | None = None,
) -> list[BranchResult]:
    items = [
        SearchResultItem(id=str(i), title=f"Result {i}", source="test")
        for i in range(result_count)
    ]
    return [
        BranchResult(
            kind=kind,
            query="test query",
            filters=filters or {},
            results=items,
            total_backend_hits=result_count,
        ),
    ]


def _start_trace(tracer: Tracer, query: str = "test query") -> Any:
    return tracer.start(query=query, interaction_mode=InteractionMode.hitl)


# ===========================================================================
# Planner tests
# ===========================================================================


class TestPlannerNoAnalysis:
    """When no query analysis is available, planner defaults to direct search."""

    def test_returns_direct_search(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(query_analysis=None)

        plan = create_plan("Telstra", ctx, tracer, trace)

        assert plan.action == PlanAction.direct_search
        assert len(plan.branches) == 1
        assert plan.branches[0].kind == BranchKind.original_query
        assert plan.branches[0].query == "Telstra"

    def test_reasoning_mentions_no_structure(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(query_analysis=None)

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.reasoning is not None
        assert "no extracted structure" in plan.reasoning.lower()


class TestPlannerDirectSearch:
    """When analysis exists but no special conditions, planner uses direct search."""

    def test_no_ambiguity_no_filters(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.none)
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(query_analysis=analysis)

        plan = create_plan("Telstra", ctx, tracer, trace)

        assert plan.action == PlanAction.direct_search
        assert len(plan.branches) == 1

    def test_low_ambiguity_no_filters(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.low)
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(query_analysis=analysis)

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action == PlanAction.direct_search


class TestPlannerNeedsClarification:
    """Planner requests clarification based on mode and ambiguity."""

    def test_hitl_high_ambiguity(self) -> None:
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country"],
        )
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )

        plan = create_plan("Telstra", ctx, tracer, trace)

        assert plan.action == PlanAction.needs_clarification
        assert len(plan.branches) == 0

    def test_hitl_medium_ambiguity(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.medium)
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action == PlanAction.needs_clarification

    def test_hitl_low_ambiguity_does_not_clarify(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.low)
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action != PlanAction.needs_clarification

    def test_aitl_high_ambiguity_with_budget_and_filters_does_not_clarify(self) -> None:
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.high,
            filters={"country": "AU"},
        )
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action != PlanAction.needs_clarification

    def test_aitl_high_ambiguity_budget_exhausted_no_filters_clarifies(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.high)
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            iterations_used=2,
            max_iterations=2,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action == PlanAction.needs_clarification

    def test_reasoning_includes_ambiguity(self) -> None:
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country"],
        )
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.reasoning is not None
        assert "ambiguity" in plan.reasoning.lower()


class TestPlannerFilterApplication:
    """When unapplied filters exist, planner applies them."""

    def test_single_branch_at_final_iteration(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
            iterations_used=1,
            max_iterations=2,
        )

        plan = create_plan("Telstra", ctx, tracer, trace)

        assert plan.action == PlanAction.search_with_filters
        assert len(plan.branches) == 1
        assert plan.branches[0].kind == BranchKind.filter_augmented
        assert plan.branches[0].filters == {"country": "AU"}

    def test_single_branch_when_branches_exhausted(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"status": "active"},
            branches_used=2,
            max_branches=2,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.action == PlanAction.search_with_filters
        assert len(plan.branches) == 1


class TestPlannerMultiBranch:
    """When conditions allow, planner creates multi-branch plans."""

    def test_multi_branch_with_budget_and_filters(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
            iterations_used=0,
            max_iterations=3,
            max_branches=2,
        )

        plan = create_plan("Telstra", ctx, tracer, trace)

        assert plan.action == PlanAction.multi_branch
        assert len(plan.branches) == 2

        kinds = {b.kind for b in plan.branches}
        assert BranchKind.original_query in kinds
        assert BranchKind.filter_augmented in kinds

    def test_original_branch_has_no_filters(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
            iterations_used=0,
            max_iterations=3,
            max_branches=2,
        )

        plan = create_plan("Telstra", ctx, tracer, trace)

        original = [b for b in plan.branches if b.kind == BranchKind.original_query][0]
        assert original.filters == {}

    def test_filter_branch_carries_extracted_filters(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"country": "AU", "status": "active"},
            iterations_used=0,
            max_iterations=3,
            max_branches=2,
        )

        plan = create_plan("test", ctx, tracer, trace)

        filtered = [b for b in plan.branches if b.kind == BranchKind.filter_augmented][0]
        assert filtered.filters == {"country": "AU", "status": "active"}

    def test_reasoning_mentions_multi_branch(self) -> None:
        analysis = _make_analysis()
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
            iterations_used=0,
            max_iterations=3,
            max_branches=2,
        )

        plan = create_plan("test", ctx, tracer, trace)

        assert plan.reasoning is not None
        assert "multi-branch" in plan.reasoning.lower()


class TestPlannerReformulation:
    """AITL reformulation: original query alongside primary_subject branch."""

    def test_aitl_multi_branch_reformulation(self) -> None:
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.none,
            primary_subject="Telstra Corporation",
        )
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            max_iterations=3,
            max_branches=2,
        )

        plan = create_plan("test query", ctx, tracer, trace)

        assert plan.action == PlanAction.multi_branch
        kinds = {b.kind for b in plan.branches}
        assert BranchKind.original_query in kinds
        assert BranchKind.reformulated in kinds

    def test_hitl_ignores_reformulation_for_direct_search(self) -> None:
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.none,
            primary_subject="Telstra",
        )
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )

        plan = create_plan("test query", ctx, tracer, trace)

        assert plan.action == PlanAction.direct_search


class TestPlannerTracing:
    """Planning step is recorded in the trace."""

    def test_planning_step_recorded(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()

        create_plan("test", ctx, tracer, trace)

        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.planning in step_types

    def test_planning_payload_includes_budget(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(iterations_used=1, max_iterations=3)

        create_plan("test", ctx, tracer, trace)

        planning_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.planning
        ]
        assert len(planning_steps) == 1
        payload = planning_steps[0].payload
        assert payload["iterations_remaining"] == 2
        assert "branches_remaining" in payload

    def test_planning_payload_includes_aitl_context(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()

        create_plan("test", ctx, tracer, trace)

        planning_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.planning
        ]
        payload = planning_steps[0].payload
        assert "aitl_context" in payload
        ac = payload["aitl_context"]
        assert "instructions" in ac
        assert "self_knowledge" in ac
        assert "problem_state" in ac


# ===========================================================================
# Evaluator tests
# ===========================================================================


class TestEvaluatorConfidence:
    """Confidence assessment heuristics."""

    def test_zero_results_zero_confidence(self) -> None:
        ctx = _make_context()
        results = _make_branch_results(result_count=0)
        confidence = assess_confidence(results, ctx)
        assert confidence == 0.0

    def test_empty_results_list_zero_confidence(self) -> None:
        ctx = _make_context()
        confidence = assess_confidence([], ctx)
        assert confidence == 0.0

    def test_few_results_high_confidence(self) -> None:
        ctx = _make_context()
        results = _make_branch_results(result_count=3)
        confidence = assess_confidence(results, ctx)
        assert confidence >= 0.7

    def test_many_results_lower_confidence(self) -> None:
        ctx = _make_context()
        results = _make_branch_results(result_count=25)
        confidence = assess_confidence(results, ctx)
        assert confidence < 0.7

    def test_high_ambiguity_reduces_confidence(self) -> None:
        analysis = _make_analysis(ambiguity=AmbiguityLevel.high)
        ctx_none = _make_context()
        ctx_high = _make_context(query_analysis=analysis)

        results = _make_branch_results(result_count=3)
        conf_none = assess_confidence(results, ctx_none)
        conf_high = assess_confidence(results, ctx_high)

        assert conf_high < conf_none

    def test_filters_boost_confidence(self) -> None:
        ctx = _make_context()
        results_no_filter = _make_branch_results(result_count=3)
        results_with_filter = _make_branch_results(
            result_count=3,
            filters={"country": "AU"},
        )

        conf_no = assess_confidence(results_no_filter, ctx)
        conf_yes = assess_confidence(results_with_filter, ctx)

        assert conf_yes > conf_no


class TestEvaluatorCompleted:
    """Evaluator returns completed when confidence is high or budget exhausted."""

    def test_high_confidence_completed(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(stop_threshold=0.7)
        results = _make_branch_results(result_count=1)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.completed

    def test_budget_exhausted_returns_completed(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.high)
        ctx = _make_context(
            query_analysis=analysis,
            iterations_used=2,
            max_iterations=2,
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.completed
        assert "budget exhausted" in action.reason.lower()

    def test_zero_results_budget_exhausted_completed(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(iterations_used=2, max_iterations=2)
        results = _make_branch_results(result_count=0)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.completed


class TestEvaluatorNeedsInput:
    """Evaluator returns needs_input based on mode and ambiguity."""

    def test_hitl_medium_ambiguity_needs_input(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.medium)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.needs_input
        assert "hitl" in action.reason.lower()

    def test_hitl_high_ambiguity_needs_input(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.high)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.needs_input

    def test_hitl_no_ambiguity_does_not_need_input(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.none)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            query_analysis=analysis,
        )
        results = _make_branch_results(result_count=1)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action != EvaluatorAction.needs_input

    def test_aitl_low_confidence_no_actionable_step_escalates(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.none)
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            stop_threshold=0.99,
            escalate_threshold=0.5,
        )
        results = _make_branch_results(result_count=25)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.needs_input
        assert "aitl" in action.reason.lower()


class TestEvaluatorIterate:
    """Evaluator returns iterate when improvement is possible."""

    def test_iterate_with_unapplied_filters(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(ambiguity=AmbiguityLevel.none)
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            unapplied_filters={"country": "AU"},
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.iterate
        assert "actionable" in action.reason.lower()

    def test_iterate_when_reformulation_available(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        analysis = _make_analysis(
            ambiguity=AmbiguityLevel.none,
            primary_subject="Telstra",
        )
        ctx = _make_context(
            interaction_mode=InteractionMode.aitl,
            query_analysis=analysis,
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action == EvaluatorAction.iterate
        assert "actionable" in action.reason.lower()

    def test_no_iterate_without_actionable_step(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context(
            interaction_mode=InteractionMode.hitl,
            stop_threshold=0.99,
        )
        results = _make_branch_results(result_count=3)

        action = evaluate_results(results, ctx, tracer, trace)

        assert action.action != EvaluatorAction.iterate


class TestEvaluatorBranchConfidence:
    """Evaluator sets confidence scores on branch results."""

    def test_sets_confidence_on_branches(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()
        results = _make_branch_results(result_count=2)
        assert results[0].confidence is None

        evaluate_results(results, ctx, tracer, trace)

        assert results[0].confidence is not None
        assert results[0].confidence > 0

    def test_does_not_overwrite_existing_confidence(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()
        results = _make_branch_results(result_count=2)
        results[0].confidence = 0.95

        evaluate_results(results, ctx, tracer, trace)

        assert results[0].confidence == 0.95


class TestEvaluatorTracing:
    """Evaluation step is recorded in the trace."""

    def test_evaluation_step_recorded(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()
        results = _make_branch_results(result_count=1)

        evaluate_results(results, ctx, tracer, trace)

        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.evaluation in step_types

    def test_evaluation_payload_has_confidence(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()
        results = _make_branch_results(result_count=1)

        evaluate_results(results, ctx, tracer, trace)

        eval_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.evaluation
        ]
        assert len(eval_steps) == 1
        assert "confidence" in eval_steps[0].payload
        assert "action_chosen" in eval_steps[0].payload

    def test_evaluation_payload_has_result_count(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        ctx = _make_context()
        results = _make_branch_results(result_count=5)

        evaluate_results(results, ctx, tracer, trace)

        eval_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.evaluation
        ]
        assert eval_steps[0].payload["result_count"] == 5


# ===========================================================================
# Orchestrated pipeline integration tests
# ===========================================================================


class TestOrchestratedPipelineSimple:
    """Full pipeline: analyzer + planner + executor + evaluator."""

    def test_simple_search_returns_completed(self) -> None:
        provider = StubModelProvider(
            classification=ClassificationResult(
                query_type="entity_lookup",
                confidence=0.9,
            ),
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra",
                target_resource_type="company",
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert isinstance(result, SearchResultEnvelope)
        assert result.status == SearchStatus.completed
        assert result.original_query == "Telstra"
        assert len(result.results) == 1
        assert result.results[0].title == "Telstra Corporation"

    def test_query_analysis_included_in_envelope(self) -> None:
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="name_search"),
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra",
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert result.query_analysis is not None
        assert result.query_analysis.query_type == "name_search"
        assert result.query_analysis.primary_subject == "Telstra"

    def test_no_results_returns_completed(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(ambiguity=AmbiguityLevel.none),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("NonexistentCorp")

        assert result.status == SearchStatus.completed
        assert len(result.results) == 0


class TestOrchestratedPipelineHITL:
    """HITL flow: needs_input on material ambiguity."""

    def test_hitl_high_ambiguity_returns_needs_input(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                missing_fields=["country"],
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert result.status == SearchStatus.needs_input
        assert len(result.results) == 0
        assert len(result.branches) == 0

    def test_hitl_needs_input_message(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(ambiguity=AmbiguityLevel.medium),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("show me stuff")

        assert result.status == SearchStatus.needs_input
        assert result.message is not None
        assert "additional" in result.message.lower() or "information" in result.message.lower()


class TestHITLFollowUpAndContinuation:
    """Structured follow_up and continue_search after needs_input."""

    def test_needs_input_includes_follow_up_schema(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                missing_fields=["country"],
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(
            interaction_mode=InteractionMode.hitl,
            canonical_filters={"country": ["AU", "US", "UK"]},
        )
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert result.status == SearchStatus.needs_input
        assert result.follow_up is not None
        assert result.follow_up.input_schema["type"] == "object"
        assert "country" in result.follow_up.input_schema["properties"]
        assert "country" in result.follow_up.input_schema["required"]

    def test_continue_search_resolves_and_completes(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                missing_fields=["country"],
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(
            interaction_mode=InteractionMode.hitl,
            canonical_filters={"country": ["AU", "US", "UK"]},
        )
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        first = index.search("Telstra")
        assert first.status == SearchStatus.needs_input
        assert first.follow_up is not None

        second = index.continue_search(first.trace_id, {"country": "AU"})
        assert second.status == SearchStatus.completed
        assert second.trace_id == first.trace_id
        assert len(second.results) >= 1
        assert second.results[0].title == "Telstra Corporation"

    def test_continue_search_unknown_trace_raises(self) -> None:
        provider = StubModelProvider()
        analyzer = QueryAnalyzer(provider)
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        with pytest.raises(TraceNotFoundError):
            index.continue_search("nonexistent-trace-id", {"country": "AU"})

    def test_continue_search_without_analyzer_raises(self) -> None:
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config)

        with pytest.raises(SearchExecutionError):
            index.continue_search("any", {"country": "AU"})


class TestOrchestratedPipelineAITL:
    """AITL flow: autonomous resolution with extracted filters."""

    def test_aitl_applies_extracted_filters(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                filters={"country": "AU"},
                primary_subject="Telstra",
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(
            interaction_mode=InteractionMode.aitl,
            canonical_filters={"country": ["AU", "US", "UK"]},
        )
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert result.status == SearchStatus.completed
        assert len(result.results) >= 1
        has_filter_branch = any(
            b.kind == BranchKind.filter_augmented for b in result.branches
        )
        assert has_filter_branch

    def test_aitl_reformulation_branch_in_history(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra",
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(
            interaction_mode=InteractionMode.aitl,
            max_iterations=1,
            max_branches=2,
            stop_threshold=0.99,
        )
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("major telco in AU")

        assert result.status == SearchStatus.completed
        assert any(
            b.kind == BranchKind.reformulated for b in result.branches
        )


class TestOrchestratedPipelineTracing:
    """Trace contains all expected pipeline steps."""

    def test_trace_has_analysis_and_evaluation_steps(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(ambiguity=AmbiguityLevel.none),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")
        trace = client.tracer.get(result.trace_id)

        assert trace is not None
        step_types = [s.step_type for s in trace.steps]

        assert TraceStepType.query_received in step_types
        assert TraceStepType.query_analysis in step_types
        assert TraceStepType.planning in step_types
        assert TraceStepType.search_execution in step_types
        assert TraceStepType.evaluation in step_types

    def test_trace_marked_complete(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(ambiguity=AmbiguityLevel.none),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")
        trace = client.tracer.get(result.trace_id)

        assert trace is not None
        assert trace.is_complete
        assert trace.final_status == SearchStatus.completed

    def test_trace_needs_input_status(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(ambiguity=AmbiguityLevel.high),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("ambiguous query")
        trace = client.tracer.get(result.trace_id)

        assert trace is not None
        assert trace.final_status == SearchStatus.needs_input

    def test_latency_is_recorded(self) -> None:
        provider = StubModelProvider()
        analyzer = QueryAnalyzer(provider)
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        assert result.latency_ms is not None
        assert result.latency_ms >= 0


class TestOrchestratedPipelineDedup:
    """Result deduplication across branches."""

    def test_deduplicates_results_across_branches(self) -> None:
        provider = StubModelProvider(
            extraction=ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                filters={"country": "AU"},
            ),
        )
        analyzer = QueryAnalyzer(provider)
        config = _make_config(
            interaction_mode=InteractionMode.aitl,
            max_iterations=3,
            max_branches=2,
        )
        client = SearchClient()
        index = client.indexes.create(config, analyzer=analyzer)

        result = index.search("Telstra")

        ids = [r.id for r in result.results]
        assert len(ids) == len(set(ids))


class TestOrchestratedPipelineBackwardCompat:
    """Verify that direct search still works when no analyzer is provided."""

    def test_no_analyzer_uses_direct_search(self) -> None:
        config = _make_config()
        client = SearchClient()
        index = client.indexes.create(config)

        result = index.search("Telstra")

        assert result.status == SearchStatus.completed
        assert result.query_analysis is None
        assert len(result.results) == 1

    def test_interaction_mode_override_still_works(self) -> None:
        config = _make_config(interaction_mode=InteractionMode.hitl)
        client = SearchClient()
        index = client.indexes.create(config)

        result = index.search("Telstra", interaction_mode=InteractionMode.aitl)

        assert result.interaction_mode == InteractionMode.aitl
