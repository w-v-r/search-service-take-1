"""Entity extraction, filter proposal, and ambiguity detection with tracing.

Wraps the ModelProvider's extract_entities method with trace recording
and filter validation against canonical values.
"""

from __future__ import annotations

from search_service.models.llm import ExtractionResult, ModelProvider
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import TraceStepType
from search_service.schemas.trace import SearchTrace
from search_service.telemetry.tracer import Tracer


def extract_from_query(
    query: str,
    config: IndexConfig,
    model_provider: ModelProvider,
    tracer: Tracer,
    trace: SearchTrace,
) -> ExtractionResult:
    """Extract entities, propose filters, and assess ambiguity from a query.

    Validates proposed filters against canonical values when available.
    Filters with values not in the canonical set are discarded.

    Returns:
        ExtractionResult with entities, filters, ambiguity, and subject info.
    """
    with tracer.timed(
        trace,
        TraceStepType.extraction,
        model_used=model_provider.model_name,
    ) as set_payload:
        result = model_provider.extract_entities(
            query,
            entity_types=config.entity_types or None,
            filterable_fields=config.filterable_fields or None,
            canonical_filters=config.policy.canonical_filters or None,
        )

        if config.policy.canonical_filters and result.filters:
            result.filters = _validate_filters(
                result.filters, config.policy.canonical_filters,
            )

        set_payload({
            "entities": [
                {
                    "value": e.value,
                    "entity_type": e.entity_type,
                    "confidence": e.confidence,
                }
                for e in result.entities
            ],
            "filters": result.filters or None,
            "ambiguity": result.ambiguity.value,
            "primary_subject": result.primary_subject,
        })

    return result


def _validate_filters(
    proposed: dict[str, object],
    canonical: dict[str, list[str]],
) -> dict[str, object]:
    """Keep only filters whose values match canonical values (when defined for that field)."""
    validated: dict[str, object] = {}
    for field_name, value in proposed.items():
        if field_name not in canonical:
            validated[field_name] = value
            continue
        if str(value) in canonical[field_name]:
            validated[field_name] = value
    return validated
