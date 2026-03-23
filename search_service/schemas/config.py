from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from search_service.adapters.base import SearchAdapter
from search_service.schemas.enums import InteractionMode


class ConfidenceThresholds(BaseModel):
    """Thresholds that control stopping, escalation, and ambiguity decisions."""

    stop: float = Field(default=0.7, ge=0.0, le=1.0)
    """Minimum confidence to stop and return results as 'completed'."""

    escalate: float = Field(default=0.3, ge=0.0, le=1.0)
    """Below this confidence, escalate to needs_input (HITL)
    or attempt resolution (AITL)."""

    ambiguity: float = Field(default=0.5, ge=0.0, le=1.0)
    """Ambiguity score above which the query is considered
    materially ambiguous."""

    @model_validator(mode="after")
    def validate_escalate_below_stop(self) -> ConfidenceThresholds:
        if self.escalate >= self.stop:
            raise ValueError(
                f"escalate threshold ({self.escalate}) must be less than "
                f"stop threshold ({self.stop})"
            )
        return self


class SearchPolicy(BaseModel):
    """Orchestration policy controlling how the harness plans, evaluates, and iterates.

    Separated from IndexConfig so the public SDK surface stays minimal.
    Most developers never need to touch this -- the defaults are opinionated
    and designed to work well out of the box.
    """

    max_iterations: int = Field(default=2, ge=1, le=10)
    """Maximum search iterations for AITL mode."""

    max_branches: int = Field(default=2, ge=1, le=5)
    """Maximum parallel branches for AITL mode.
    Original query always occupies one branch."""

    confidence_thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    """Thresholds that control stopping, escalation, and ambiguity decisions."""

    canonical_filters: dict[str, list[str]] = {}
    """Known valid filter values per field. Used by the extractor to
    validate proposed filters.
    Example: {'country': ['AU', 'US', 'UK']}"""

    example_queries: list[str] = []
    """Example queries for this index. Used as few-shot examples in
    LLM prompts for classification and extraction."""


class IndexConfig(BaseModel):
    """Defines a search index and its retrieval behavior.

    IndexConfig is the public SDK surface. It answers: what is this index,
    what does it contain, and what kinds of queries should it handle?

    It deliberately does not expose orchestration internals like confidence
    thresholds or iteration budgets. Those live in SearchPolicy.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- Required fields ---

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """Unique index name. Used as the primary identifier for the index."""

    document_schema: type = Field(exclude=True)
    """Pydantic model class defining the document shape in the index.
    Used for field discovery, validation, and display field resolution.
    Named document_schema to avoid shadowing BaseModel.schema()."""

    adapter: SearchAdapter = Field(exclude=True)
    """Backend adapter instance (e.g., TypesenseAdapter, InMemoryAdapter).
    Must implement the SearchAdapter protocol."""

    searchable_fields: list[str] = Field(min_length=1)
    """Fields the backend should search against for keyword queries.
    Must be a subset of fields defined in the schema."""

    id_field: str = Field(min_length=1)
    """Primary key field name in the schema. Used to deduplicate results
    across branches and identify documents uniquely."""

    # --- Fields with defaults ---

    search_backend: str = "keyword_filters"
    """Retrieval strategy. v0 supports 'keyword_filters' only."""

    default_interaction_mode: InteractionMode = InteractionMode.hitl
    """Default interaction mode for searches on this index.
    Can be overridden per-search call."""

    filterable_fields: list[str] = []
    """Fields available for structured filtering. The analyzer/extractor
    uses this list to propose filters from natural language queries."""

    display_fields: list[str] = []
    """Fields included in search result display. If empty, defaults to
    all schema fields."""

    entity_types: list[str] = []
    """Entity types this index contains (e.g., ['company', 'person']).
    Used by the classifier and extractor to scope entity recognition."""

    expected_query_types: list[str] = []
    """Developer-defined query type vocabulary for this index.
    The harness classifies incoming queries against these types.
    Examples: ['entity_lookup', 'name_search', 'status_filter'].

    The harness brings the classification structure; the developer
    brings the vocabulary. There is no system-level enum -- these
    strings are domain-specific and owned by the developer."""

    # --- Advanced / opt-in ---

    policy: SearchPolicy = Field(default_factory=SearchPolicy)
    """Orchestration policy for this index. Controls iteration budgets,
    confidence thresholds, and other planner/evaluator behavior.
    Defaults are opinionated and designed to work well out of the box."""

    @model_validator(mode="after")
    def validate_fields_against_schema(self) -> IndexConfig:
        """Validate that referenced fields exist in the document schema if the schema is a Pydantic model."""
        if not _is_pydantic_model(self.document_schema):
            return self

        schema_fields = set(self.document_schema.model_fields.keys())  # type: ignore[union-attr]

        if self.id_field not in schema_fields:
            raise ValueError(f"id_field '{self.id_field}' not found in schema fields: {schema_fields}")

        missing_searchable = set(self.searchable_fields) - schema_fields
        if missing_searchable:
            raise ValueError(f"searchable_fields not found in schema: {missing_searchable}")

        missing_filterable = set(self.filterable_fields) - schema_fields
        if missing_filterable:
            raise ValueError(f"filterable_fields not found in schema: {missing_filterable}")

        missing_display = set(self.display_fields) - schema_fields
        if missing_display:
            raise ValueError(f"display_fields not found in schema: {missing_display}")

        return self


def _is_pydantic_model(cls: type) -> bool:
    """Check if a class is a Pydantic BaseModel subclass without importing BaseModel."""
    return hasattr(cls, "model_fields")
