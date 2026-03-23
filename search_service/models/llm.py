"""ModelProvider protocol and result types for query understanding.

The ModelProvider is the abstraction boundary between "what the pipeline
needs" (classification, entity extraction) and "how the model generates it"
(API calls, structured prompts, etc.). Any provider (Mercury 2, OpenAI,
test stubs) implements this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from search_service.schemas.enums import AmbiguityLevel
from search_service.schemas.query import ExtractedEntity


@dataclass
class ClassificationResult:
    """Output of query type classification."""

    query_type: str | None = None
    confidence: float | None = None


@dataclass
class ExtractionResult:
    """Output of entity extraction, filter proposal, and ambiguity detection."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    ambiguity: AmbiguityLevel = AmbiguityLevel.none
    primary_subject: str | None = None
    target_resource_type: str | None = None
    possible_resource_types: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol that all model providers must implement.

    A model provider knows how to classify queries and extract entities.
    The pipeline doesn't care how — it calls these methods and gets
    typed results back.
    """

    @property
    def model_name(self) -> str:
        """Identifier for this model provider (e.g., 'mercury/v2', 'gpt-4o')."""
        ...

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        """Classify a query against the developer-defined query type vocabulary.

        Args:
            query: The raw user query.
            expected_query_types: Developer-defined query types for this index.
            entity_types: Entity types this index contains, for context.
            example_queries: Few-shot examples for classification.

        Returns:
            ClassificationResult with the best-matching query_type and confidence.
        """
        ...

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        """Extract entities, propose filters, and assess ambiguity from a query.

        Args:
            query: The raw user query.
            entity_types: Entity types this index contains, for scoping extraction.
            filterable_fields: Fields available for structured filtering.
            canonical_filters: Known valid filter values per field.

        Returns:
            ExtractionResult with entities, filters, ambiguity, and subject info.
        """
        ...
