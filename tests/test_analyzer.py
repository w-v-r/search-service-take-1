"""Tests for the query understanding pipeline: analyzer, classifier, extractor, and ModelProvider protocol.

Covers:
- ModelProvider protocol conformance
- classify_query orchestration wrapper (tracing, validation, skip behavior)
- extract_from_query orchestration wrapper (tracing, filter validation)
- QueryAnalyzer end-to-end (classification + extraction → QueryAnalysis)

All tests use simple inline stubs that return predetermined results.
The real ModelProvider (Mercury 2) will be tested separately via integration tests.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from search_service.adapters.in_memory import InMemoryAdapter
from search_service.models.llm import (
    ClassificationResult,
    ExtractionResult,
    ModelProvider,
)
from search_service.orchestration.analyzer import QueryAnalyzer
from search_service.orchestration.classifier import classify_query
from search_service.orchestration.extractor import extract_from_query
from search_service.schemas.config import IndexConfig, SearchPolicy
from search_service.schemas.enums import (
    AmbiguityLevel,
    InteractionMode,
    TraceStepType,
)
from search_service.schemas.query import ExtractedEntity, QueryAnalysis
from search_service.telemetry.tracer import Tracer


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class CompanyDocument(BaseModel):
    id: str
    company_name: str
    country: str
    status: str
    industry: str


def _make_config(
    *,
    expected_query_types: list[str] | None = None,
    entity_types: list[str] | None = None,
    filterable_fields: list[str] | None = None,
    canonical_filters: dict[str, list[str]] | None = None,
    example_queries: list[str] | None = None,
) -> IndexConfig:
    return IndexConfig(
        name="companies",
        document_schema=CompanyDocument,
        adapter=InMemoryAdapter(),
        searchable_fields=["company_name"],
        id_field="id",
        filterable_fields=filterable_fields or [],
        entity_types=entity_types or [],
        expected_query_types=expected_query_types or [],
        policy=SearchPolicy(
            canonical_filters=canonical_filters or {},
            example_queries=example_queries or [],
        ),
    )


def _start_trace(tracer: Tracer, query: str = "test"):
    return tracer.start(query=query, interaction_mode=InteractionMode.hitl)


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
        self.classify_calls: list[dict[str, Any]] = []
        self.extract_calls: list[dict[str, Any]] = []

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
        self.classify_calls.append({
            "query": query,
            "expected_query_types": expected_query_types,
            "entity_types": entity_types,
            "example_queries": example_queries,
        })
        return self._classification

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        self.extract_calls.append({
            "query": query,
            "entity_types": entity_types,
            "filterable_fields": filterable_fields,
            "canonical_filters": canonical_filters,
        })
        return self._extraction


# ===================================================================
# ModelProvider protocol conformance
# ===================================================================

class TestModelProviderProtocol:
    def test_stub_satisfies_protocol(self) -> None:
        assert isinstance(StubModelProvider(), ModelProvider)

    def test_protocol_requires_model_name(self) -> None:
        class Incomplete:
            def classify_query(self, *a, **kw): ...
            def extract_entities(self, *a, **kw): ...

        assert not isinstance(Incomplete(), ModelProvider)

    def test_protocol_requires_classify_query(self) -> None:
        class Incomplete:
            @property
            def model_name(self) -> str:
                return "x"
            def extract_entities(self, *a, **kw): ...

        assert not isinstance(Incomplete(), ModelProvider)

    def test_protocol_requires_extract_entities(self) -> None:
        class Incomplete:
            @property
            def model_name(self) -> str:
                return "x"
            def classify_query(self, *a, **kw): ...

        assert not isinstance(Incomplete(), ModelProvider)


# ===================================================================
# classify_query orchestration wrapper
# ===================================================================

class TestClassifyQuery:
    def test_skips_when_no_expected_types(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=[])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="should_not_appear"),
        )

        result = classify_query("show me Telstra", config, provider, tracer, trace)

        assert result.query_type is None
        assert result.confidence is None
        assert len(provider.classify_calls) == 0

    def test_calls_provider_with_correct_args(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(
            expected_query_types=["entity_lookup", "status_filter"],
            entity_types=["company"],
            example_queries=["find Telstra"],
        )
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup", confidence=0.9),
        )

        classify_query("find Telstra", config, provider, tracer, trace)

        assert len(provider.classify_calls) == 1
        call = provider.classify_calls[0]
        assert call["query"] == "find Telstra"
        assert call["expected_query_types"] == ["entity_lookup", "status_filter"]
        assert call["entity_types"] == ["company"]
        assert call["example_queries"] == ["find Telstra"]

    def test_returns_provider_result(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup", confidence=0.85),
        )

        result = classify_query("test", config, provider, tracer, trace)

        assert result.query_type == "entity_lookup"
        assert result.confidence == 0.85

    def test_rejects_query_type_not_in_expected(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="hallucinated_type", confidence=0.9),
        )

        result = classify_query("test", config, provider, tracer, trace)

        assert result.query_type is None
        assert result.confidence is None

    def test_records_classification_trace_step(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup", confidence=0.8),
            name="mercury/v2",
        )

        classify_query("find Telstra", config, provider, tracer, trace)

        classification_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.classification
        ]
        assert len(classification_steps) == 1
        step = classification_steps[0]
        assert step.model_used == "mercury/v2"
        assert step.payload["query_type"] == "entity_lookup"
        assert step.payload["confidence"] == 0.8
        assert step.payload["expected_types"] == ["entity_lookup"]
        assert step.latency_ms is not None

    def test_no_trace_step_when_skipped(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=[])

        classify_query("test", config, StubModelProvider(), tracer, trace)

        classification_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.classification
        ]
        assert len(classification_steps) == 0

    def test_passes_none_for_empty_entity_types(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["type_a"], entity_types=[])
        provider = StubModelProvider()

        classify_query("test", config, provider, tracer, trace)

        assert provider.classify_calls[0]["entity_types"] is None

    def test_passes_none_for_empty_example_queries(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["type_a"], example_queries=[])
        provider = StubModelProvider()

        classify_query("test", config, provider, tracer, trace)

        assert provider.classify_calls[0]["example_queries"] is None


# ===================================================================
# extract_from_query orchestration wrapper
# ===================================================================

class TestExtractFromQuery:
    def test_calls_provider_with_correct_args(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(
            entity_types=["company"],
            filterable_fields=["country", "status"],
            canonical_filters={"country": ["AU", "US"]},
        )
        provider = StubModelProvider()

        extract_from_query("Telstra in AU", config, provider, tracer, trace)

        assert len(provider.extract_calls) == 1
        call = provider.extract_calls[0]
        assert call["query"] == "Telstra in AU"
        assert call["entity_types"] == ["company"]
        assert call["filterable_fields"] == ["country", "status"]
        assert call["canonical_filters"] == {"country": ["AU", "US"]}

    def test_returns_provider_result(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config()
        provider = StubModelProvider(
            extraction=ExtractionResult(
                primary_subject="Telstra",
                ambiguity=AmbiguityLevel.low,
                entities=[ExtractedEntity(value="Telstra", entity_type="company")],
            ),
        )

        result = extract_from_query("Telstra", config, provider, tracer, trace)

        assert result.primary_subject == "Telstra"
        assert result.ambiguity == AmbiguityLevel.low
        assert len(result.entities) == 1

    def test_records_extraction_trace_step(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config()
        provider = StubModelProvider(
            extraction=ExtractionResult(
                primary_subject="Telstra",
                ambiguity=AmbiguityLevel.none,
                entities=[ExtractedEntity(value="Telstra")],
            ),
            name="mercury/v2",
        )

        extract_from_query("Telstra", config, provider, tracer, trace)

        extraction_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.extraction
        ]
        assert len(extraction_steps) == 1
        step = extraction_steps[0]
        assert step.model_used == "mercury/v2"
        assert step.payload["primary_subject"] == "Telstra"
        assert step.payload["ambiguity"] == "none"
        assert len(step.payload["entities"]) == 1
        assert step.latency_ms is not None

    def test_validates_filters_against_canonical_values(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(canonical_filters={"country": ["AU", "US"]})
        provider = StubModelProvider(
            extraction=ExtractionResult(filters={"country": "AU"}),
        )

        result = extract_from_query("Telstra in AU", config, provider, tracer, trace)

        assert result.filters == {"country": "AU"}

    def test_discards_invalid_canonical_filter_values(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(canonical_filters={"country": ["AU", "US"]})
        provider = StubModelProvider(
            extraction=ExtractionResult(filters={"country": "FR"}),
        )

        result = extract_from_query("France", config, provider, tracer, trace)

        assert "country" not in result.filters

    def test_preserves_filters_for_fields_without_canonical_list(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(canonical_filters={"country": ["AU"]})
        provider = StubModelProvider(
            extraction=ExtractionResult(
                filters={"status": "active", "country": "XX"},
            ),
        )

        result = extract_from_query("active companies", config, provider, tracer, trace)

        assert result.filters["status"] == "active"
        assert "country" not in result.filters

    def test_no_validation_without_canonical_filters(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config()
        provider = StubModelProvider(
            extraction=ExtractionResult(filters={"anything": "goes"}),
        )

        result = extract_from_query("test", config, provider, tracer, trace)

        assert result.filters == {"anything": "goes"}

    def test_passes_none_for_empty_lists(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(entity_types=[], filterable_fields=[])
        provider = StubModelProvider()

        extract_from_query("test", config, provider, tracer, trace)

        call = provider.extract_calls[0]
        assert call["entity_types"] is None
        assert call["filterable_fields"] is None
        assert call["canonical_filters"] is None


# ===================================================================
# QueryAnalyzer end-to-end
# ===================================================================

class TestQueryAnalyzer:
    def test_produces_query_analysis(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer, "show me Telstra")
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup", confidence=0.9),
            extraction=ExtractionResult(
                primary_subject="Telstra",
                target_resource_type="company",
                entities=[ExtractedEntity(value="Telstra", entity_type="company")],
            ),
        )
        analyzer = QueryAnalyzer(provider)

        analysis = analyzer.analyze("show me Telstra", config, tracer, trace)

        assert isinstance(analysis, QueryAnalysis)
        assert analysis.raw_query == "show me Telstra"

    def test_merges_classification_and_extraction(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup", confidence=0.9),
            extraction=ExtractionResult(
                primary_subject="Telstra",
                target_resource_type="company",
                possible_resource_types=["company", "person"],
                filters={"country": "AU"},
                ambiguity=AmbiguityLevel.low,
                missing_fields=["status"],
                entities=[
                    ExtractedEntity(value="Telstra", entity_type="company", confidence=0.95),
                    ExtractedEntity(value="AU", entity_type="country", field_mapping="country"),
                ],
            ),
        )
        analyzer = QueryAnalyzer(provider)

        analysis = analyzer.analyze("Telstra in AU", config, tracer, trace)

        assert analysis.query_type == "entity_lookup"
        assert analysis.primary_subject == "Telstra"
        assert analysis.target_resource_type == "company"
        assert analysis.possible_resource_types == ["company", "person"]
        assert analysis.filters == {"country": "AU"}
        assert analysis.ambiguity == AmbiguityLevel.low
        assert analysis.missing_fields == ["status"]
        assert len(analysis.extracted_entities) == 2

    def test_records_classification_extraction_and_analysis_steps(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        analyzer = QueryAnalyzer(StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup"),
        ))

        analyzer.analyze("test", config, tracer, trace)

        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.query_received in step_types
        assert TraceStepType.classification in step_types
        assert TraceStepType.extraction in step_types
        assert TraceStepType.query_analysis in step_types

    def test_query_analysis_trace_step_captures_combined_output(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="entity_lookup"),
            extraction=ExtractionResult(
                primary_subject="Telstra",
                ambiguity=AmbiguityLevel.medium,
                filters={"country": "AU"},
            ),
            name="mercury/v2",
        )
        analyzer = QueryAnalyzer(provider)

        analyzer.analyze("Telstra in AU", config, tracer, trace)

        qa_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.query_analysis
        ]
        assert len(qa_steps) == 1
        step = qa_steps[0]
        assert step.model_used == "mercury/v2"
        assert step.payload["raw_query"] == "Telstra in AU"
        assert step.payload["query_type"] == "entity_lookup"
        assert step.payload["ambiguity"] == "medium"
        assert step.payload["primary_subject"] == "Telstra"
        assert step.payload["filters"] == {"country": "AU"}

    def test_no_classification_step_when_no_expected_types(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=[])
        provider = StubModelProvider()
        analyzer = QueryAnalyzer(provider)

        analysis = analyzer.analyze("test", config, tracer, trace)

        assert analysis.query_type is None
        assert len(provider.classify_calls) == 0
        classification_steps = [
            s for s in trace.steps if s.step_type == TraceStepType.classification
        ]
        assert len(classification_steps) == 0

    def test_extraction_always_runs(self) -> None:
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=[])
        provider = StubModelProvider(
            extraction=ExtractionResult(primary_subject="Telstra"),
        )
        analyzer = QueryAnalyzer(provider)

        analysis = analyzer.analyze("Telstra", config, tracer, trace)

        assert len(provider.extract_calls) == 1
        assert analysis.primary_subject == "Telstra"

    def test_model_provider_accessible(self) -> None:
        provider = StubModelProvider()
        analyzer = QueryAnalyzer(provider)
        assert analyzer.model_provider is provider

    def test_rejected_classification_still_produces_analysis(self) -> None:
        """If provider returns an invalid query_type, analysis still works with None."""
        tracer = Tracer()
        trace = _start_trace(tracer)
        config = _make_config(expected_query_types=["entity_lookup"])
        provider = StubModelProvider(
            classification=ClassificationResult(query_type="invalid_type", confidence=0.9),
            extraction=ExtractionResult(primary_subject="Telstra"),
        )
        analyzer = QueryAnalyzer(provider)

        analysis = analyzer.analyze("Telstra", config, tracer, trace)

        assert analysis.query_type is None
        assert analysis.primary_subject == "Telstra"
