"""QueryAnalyzer -- coordinates classification and extraction into a unified QueryAnalysis.

The analyzer is the entry point for the query understanding pipeline.
It runs classification (query type detection) and extraction (entity
extraction, filter proposal, ambiguity assessment) in sequence, then
merges their outputs into a single QueryAnalysis that the planner and
evaluator consume downstream.
"""

from __future__ import annotations

from search_service.models.llm import ModelProvider
from search_service.orchestration.classifier import classify_query
from search_service.orchestration.extractor import extract_from_query
from search_service.schemas.config import IndexConfig
from search_service.schemas.query import QueryAnalysis
from search_service.schemas.trace import SearchTrace
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer


class QueryAnalyzer:
    """Coordinates query classification and entity extraction.

    Owns a ModelProvider and runs both pipeline stages, producing
    a single QueryAnalysis output with trace recording.
    """

    def __init__(self, model_provider: ModelProvider) -> None:
        self._model_provider = model_provider

    @property
    def model_provider(self) -> ModelProvider:
        return self._model_provider

    def analyze(
        self,
        query: str,
        config: IndexConfig,
        tracer: Tracer,
        trace: SearchTrace,
    ) -> QueryAnalysis:
        """Run the full query understanding pipeline.

        Runs classification then extraction, merges results into a
        QueryAnalysis, and records a combined query_analysis trace step.

        Args:
            query: The raw user query.
            config: Index configuration with field definitions and policy.
            tracer: Tracer instance for recording pipeline steps.
            trace: The active SearchTrace to record into.

        Returns:
            QueryAnalysis combining classification and extraction outputs.
        """
        classification = classify_query(
            query, config, self._model_provider, tracer, trace,
        )
        extraction = extract_from_query(
            query, config, self._model_provider, tracer, trace,
        )

        analysis = QueryAnalysis(
            raw_query=query,
            query_type=classification.query_type,
            primary_subject=extraction.primary_subject,
            target_resource_type=extraction.target_resource_type,
            possible_resource_types=extraction.possible_resource_types,
            filters=extraction.filters,
            ambiguity=extraction.ambiguity,
            missing_fields=extraction.missing_fields,
            extracted_entities=extraction.entities,
        )

        tracer.record(
            trace,
            events.query_analysis(
                raw_query=query,
                query_type=classification.query_type,
                ambiguity=extraction.ambiguity.value,
                primary_subject=extraction.primary_subject,
                filters=extraction.filters or None,
                model_used=self._model_provider.model_name,
            ),
        )

        return analysis
