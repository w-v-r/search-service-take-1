"""Query type classification with tracing.

Wraps the ModelProvider's classify_query method with trace recording
and result validation. Ensures the returned query_type is actually
one of the index's expected_query_types.
"""

from __future__ import annotations

from search_service.models.llm import ClassificationResult, ModelProvider
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import TraceStepType
from search_service.schemas.trace import SearchTrace
from search_service.telemetry.tracer import Tracer


def classify_query(
    query: str,
    config: IndexConfig,
    model_provider: ModelProvider,
    tracer: Tracer,
    trace: SearchTrace,
) -> ClassificationResult:
    """Classify a query against the index's expected_query_types vocabulary.

    Skips classification entirely if no expected_query_types are configured.
    Validates that the model's output is a member of the expected vocabulary.

    Returns:
        ClassificationResult with query_type and confidence.
    """
    if not config.expected_query_types:
        return ClassificationResult()

    with tracer.timed(
        trace,
        TraceStepType.classification,
        model_used=model_provider.model_name,
    ) as set_payload:
        result = model_provider.classify_query(
            query,
            config.expected_query_types,
            entity_types=config.entity_types or None,
            example_queries=config.policy.example_queries or None,
        )

        if result.query_type and result.query_type not in config.expected_query_types:
            result = ClassificationResult()

        set_payload({
            "query_type": result.query_type,
            "confidence": result.confidence,
            "expected_types": config.expected_query_types,
        })

    return result
