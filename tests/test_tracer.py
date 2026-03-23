from __future__ import annotations

import time

from search_service.schemas.enums import (
    InteractionMode,
    SearchStatus,
    TraceStepType,
)
from search_service.schemas.trace import SearchTrace, TraceStep
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer


# --- Tracer lifecycle ---


class TestTracerStart:
    def test_start_creates_trace_with_uuid(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="Telstra", interaction_mode=InteractionMode.hitl)
        assert len(trace.trace_id) == 32  # uuid4 hex
        assert trace.original_query == "Telstra"
        assert trace.interaction_mode == InteractionMode.hitl

    def test_start_records_query_received_step(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="Telstra", interaction_mode=InteractionMode.hitl)
        assert len(trace.steps) == 1
        step = trace.steps[0]
        assert step.step_type == TraceStepType.query_received
        assert step.payload["raw_query"] == "Telstra"
        assert step.payload["interaction_mode"] == "hitl"

    def test_start_with_index_name(self) -> None:
        tracer = Tracer()
        trace = tracer.start(
            query="Telstra",
            interaction_mode=InteractionMode.hitl,
            index_name="companies",
        )
        assert trace.steps[0].payload["index_name"] == "companies"

    def test_start_with_custom_trace_id(self) -> None:
        tracer = Tracer()
        trace = tracer.start(
            query="test",
            interaction_mode=InteractionMode.aitl,
            trace_id="custom-id-123",
        )
        assert trace.trace_id == "custom-id-123"

    def test_start_stores_trace_for_retrieval(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)
        assert tracer.get(trace.trace_id) is trace


class TestTracerRecord:
    def test_record_appends_step(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        step = TraceStep(
            step_type=TraceStepType.planning,
            payload={"action": "direct_search"},
        )
        tracer.record(trace, step)

        assert len(trace.steps) == 2
        assert trace.steps[1].step_type == TraceStepType.planning

    def test_record_preserves_step_order(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        tracer.record(trace, TraceStep(step_type=TraceStepType.classification, payload={}))
        tracer.record(trace, TraceStep(step_type=TraceStepType.extraction, payload={}))
        tracer.record(trace, TraceStep(step_type=TraceStepType.planning, payload={}))

        types = [s.step_type for s in trace.steps]
        assert types == [
            TraceStepType.query_received,
            TraceStepType.classification,
            TraceStepType.extraction,
            TraceStepType.planning,
        ]


class TestTracerTimed:
    def test_timed_records_latency(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        with tracer.timed(trace, TraceStepType.query_analysis) as set_payload:
            time.sleep(0.01)
            set_payload({"raw_query": "test"})

        timed_step = trace.steps[1]
        assert timed_step.step_type == TraceStepType.query_analysis
        assert timed_step.latency_ms is not None
        assert timed_step.latency_ms >= 10.0
        assert timed_step.payload["raw_query"] == "test"

    def test_timed_with_model_used(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        with tracer.timed(trace, TraceStepType.classification, model_used="gpt-4o") as set_payload:
            set_payload({"query_type": "entity_lookup"})

        assert trace.steps[1].model_used == "gpt-4o"

    def test_timed_without_callback_records_empty_payload(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        with tracer.timed(trace, TraceStepType.planning):
            pass

        assert trace.steps[1].payload == {}

    def test_timed_records_step_even_on_exception(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        try:
            with tracer.timed(trace, TraceStepType.search_execution) as set_payload:
                set_payload({"query": "test"})
                raise ValueError("simulated failure")
        except ValueError:
            pass

        assert len(trace.steps) == 2
        assert trace.steps[1].step_type == TraceStepType.search_execution
        assert trace.steps[1].latency_ms is not None


class TestTracerComplete:
    def test_complete_sets_final_status(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        tracer.complete(trace, final_status=SearchStatus.completed)

        assert trace.final_status == SearchStatus.completed
        assert trace.is_complete

    def test_complete_sets_reason(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        tracer.complete(
            trace,
            final_status=SearchStatus.completed,
            reason="Confidence 0.85 exceeds stop threshold 0.7",
        )

        assert trace.final_decision_reason == "Confidence 0.85 exceeds stop threshold 0.7"

    def test_complete_with_explicit_latency(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        tracer.complete(
            trace,
            final_status=SearchStatus.completed,
            total_latency_ms=42.5,
        )

        assert trace.total_latency_ms == 42.5

    def test_complete_computes_latency_from_steps(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        tracer.record(
            trace,
            TraceStep(step_type=TraceStepType.planning, payload={}, latency_ms=10.0),
        )
        tracer.record(
            trace,
            TraceStep(step_type=TraceStepType.search_execution, payload={}, latency_ms=25.5),
        )

        tracer.complete(trace, final_status=SearchStatus.completed)

        assert trace.total_latency_ms == 35.5

    def test_complete_returns_trace(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)

        result = tracer.complete(trace, final_status=SearchStatus.failed)

        assert result is trace


# --- Trace store ---


class TestTraceStore:
    def test_get_returns_none_for_missing(self) -> None:
        tracer = Tracer()
        assert tracer.get("nonexistent") is None

    def test_has(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)
        assert tracer.has(trace.trace_id)
        assert not tracer.has("nonexistent")

    def test_remove_returns_trace(self) -> None:
        tracer = Tracer()
        trace = tracer.start(query="test", interaction_mode=InteractionMode.hitl)
        trace_id = trace.trace_id

        removed = tracer.remove(trace_id)
        assert removed is trace
        assert not tracer.has(trace_id)

    def test_remove_returns_none_for_missing(self) -> None:
        tracer = Tracer()
        assert tracer.remove("nonexistent") is None

    def test_trace_count(self) -> None:
        tracer = Tracer()
        assert tracer.trace_count == 0

        tracer.start(query="one", interaction_mode=InteractionMode.hitl)
        tracer.start(query="two", interaction_mode=InteractionMode.aitl)
        assert tracer.trace_count == 2

    def test_multiple_traces_independent(self) -> None:
        tracer = Tracer()
        t1 = tracer.start(query="first", interaction_mode=InteractionMode.hitl)
        t2 = tracer.start(query="second", interaction_mode=InteractionMode.aitl)

        tracer.record(
            t1,
            TraceStep(step_type=TraceStepType.planning, payload={"action": "direct_search"}),
        )

        assert len(t1.steps) == 2
        assert len(t2.steps) == 1


# --- Event factories ---


class TestEventFactories:
    def test_query_received(self) -> None:
        step = events.query_received("Telstra", "hitl", index_name="companies")
        assert step.step_type == TraceStepType.query_received
        assert step.payload == {
            "raw_query": "Telstra",
            "interaction_mode": "hitl",
            "index_name": "companies",
        }

    def test_query_analysis(self) -> None:
        step = events.query_analysis(
            "Telstra",
            query_type="entity_lookup",
            ambiguity="low",
            latency_ms=15.2,
            model_used="gpt-4o",
        )
        assert step.step_type == TraceStepType.query_analysis
        assert step.payload["raw_query"] == "Telstra"
        assert step.payload["query_type"] == "entity_lookup"
        assert step.latency_ms == 15.2
        assert step.model_used == "gpt-4o"

    def test_classification(self) -> None:
        step = events.classification(
            "entity_lookup",
            confidence=0.9,
            candidates=["entity_lookup", "name_search"],
        )
        assert step.step_type == TraceStepType.classification
        assert step.payload["query_type"] == "entity_lookup"
        assert step.payload["confidence"] == 0.9
        assert step.payload["candidates"] == ["entity_lookup", "name_search"]

    def test_extraction(self) -> None:
        step = events.extraction(
            [{"value": "Telstra", "entity_type": "company_name"}],
            filters={"country": "AU"},
        )
        assert step.step_type == TraceStepType.extraction
        assert step.payload["entities"] == [{"value": "Telstra", "entity_type": "company_name"}]
        assert step.payload["filters"] == {"country": "AU"}

    def test_planning(self) -> None:
        step = events.planning(
            "direct_search",
            reasoning="Single clear entity",
            iterations_remaining=2,
            branches_remaining=2,
        )
        assert step.step_type == TraceStepType.planning
        assert step.payload["action"] == "direct_search"
        assert step.payload["reasoning"] == "Single clear entity"
        assert step.payload["iterations_remaining"] == 2

    def test_search_execution(self) -> None:
        step = events.search_execution(
            "Telstra",
            filters={"country": "AU"},
            result_count=3,
            total_backend_hits=3,
            branch_kind="original_query",
            latency_ms=8.5,
        )
        assert step.step_type == TraceStepType.search_execution
        assert step.payload["query"] == "Telstra"
        assert step.payload["result_count"] == 3
        assert step.latency_ms == 8.5

    def test_evaluation(self) -> None:
        step = events.evaluation(
            0.85,
            "completed",
            decision_reason="Confidence exceeds stop threshold",
            result_count=5,
        )
        assert step.step_type == TraceStepType.evaluation
        assert step.payload["confidence"] == 0.85
        assert step.payload["action_chosen"] == "completed"
        assert step.payload["decision_reason"] == "Confidence exceeds stop threshold"

    def test_follow_up_generation(self) -> None:
        step = events.follow_up_generation("ambiguous_entity", candidate_count=3)
        assert step.step_type == TraceStepType.follow_up_generation
        assert step.payload["reason"] == "ambiguous_entity"
        assert step.payload["candidate_count"] == 3

    def test_branch_created(self) -> None:
        step = events.branch_created("filter_augmented", "Telstra", filters={"country": "AU"})
        assert step.step_type == TraceStepType.branch_created
        assert step.payload["kind"] == "filter_augmented"
        assert step.payload["query"] == "Telstra"
        assert step.payload["filters"] == {"country": "AU"}

    def test_branch_merge(self) -> None:
        step = events.branch_merge(2, merged_result_count=8, strategy="interleave")
        assert step.step_type == TraceStepType.branch_merge
        assert step.payload["branch_count"] == 2
        assert step.payload["merged_result_count"] == 8

    def test_budget_check(self) -> None:
        step = events.budget_check(1, 0, at_final_iteration=True)
        assert step.step_type == TraceStepType.budget_check
        assert step.payload["iterations_remaining"] == 1
        assert step.payload["branches_remaining"] == 0
        assert step.payload["at_final_iteration"] is True
        assert step.payload["budget_exhausted"] is False

    def test_decision(self) -> None:
        step = events.decision(
            "completed",
            "Confidence 0.85 exceeds stop threshold 0.7",
            iterations_remaining=1,
            confidence=0.85,
        )
        assert step.step_type == TraceStepType.decision
        assert step.payload["action_chosen"] == "completed"
        assert step.payload["decision_reason"] == "Confidence 0.85 exceeds stop threshold 0.7"


# --- Full pipeline simulation ---


class TestTracerEndToEnd:
    def test_full_search_trace(self) -> None:
        """Simulate a complete search pipeline recording through the tracer."""
        tracer = Tracer()

        trace = tracer.start(
            query="Telstra",
            interaction_mode=InteractionMode.hitl,
            index_name="companies",
        )

        tracer.record(
            trace,
            events.query_analysis(
                "Telstra",
                query_type="entity_lookup",
                ambiguity="none",
                latency_ms=12.0,
                model_used="gpt-4o",
            ),
        )

        tracer.record(
            trace,
            events.planning(
                "direct_search",
                reasoning="Clear entity lookup, no ambiguity",
                iterations_remaining=2,
            ),
        )

        tracer.record(
            trace,
            events.search_execution(
                "Telstra",
                result_count=1,
                total_backend_hits=1,
                branch_kind="original_query",
                latency_ms=5.0,
            ),
        )

        tracer.record(
            trace,
            events.evaluation(
                0.95,
                "completed",
                decision_reason="High confidence single result",
                latency_ms=2.0,
            ),
        )

        tracer.complete(
            trace,
            final_status=SearchStatus.completed,
            reason="High confidence single result",
        )

        assert trace.is_complete
        assert trace.final_status == SearchStatus.completed
        assert trace.total_latency_ms == 19.0
        assert len(trace.steps) == 5

        step_types = [s.step_type for s in trace.steps]
        assert step_types == [
            TraceStepType.query_received,
            TraceStepType.query_analysis,
            TraceStepType.planning,
            TraceStepType.search_execution,
            TraceStepType.evaluation,
        ]

    def test_needs_input_trace(self) -> None:
        """Simulate a search that ends in needs_input."""
        tracer = Tracer()

        trace = tracer.start(
            query="show me Telstra stuff",
            interaction_mode=InteractionMode.hitl,
        )

        tracer.record(
            trace,
            events.query_analysis(
                "show me Telstra stuff",
                ambiguity="high",
                primary_subject="Telstra",
                latency_ms=10.0,
            ),
        )

        tracer.record(
            trace,
            events.follow_up_generation("underspecified_query", candidate_count=3),
        )

        tracer.complete(
            trace,
            final_status=SearchStatus.needs_input,
            reason="Query is ambiguous -- multiple resource types possible",
        )

        assert trace.final_status == SearchStatus.needs_input
        assert "ambiguous" in (trace.final_decision_reason or "")

    def test_trace_continuation(self) -> None:
        """Traces support appending steps for continue_search."""
        tracer = Tracer()

        trace = tracer.start(query="Telstra", interaction_mode=InteractionMode.hitl)
        tracer.complete(trace, final_status=SearchStatus.needs_input)

        initial_step_count = len(trace.steps)

        trace.final_status = None
        tracer.record(
            trace,
            events.query_received("Telstra", "hitl"),
        )
        tracer.record(
            trace,
            events.search_execution("Telstra", result_count=1, latency_ms=3.0),
        )
        tracer.complete(trace, final_status=SearchStatus.completed)

        assert len(trace.steps) == initial_step_count + 2
        assert trace.final_status == SearchStatus.completed
