# Pydantic Model Contracts

Implementation-ready specifications for all core data models. Each section defines exact field names, Python types, defaults, validation constraints, and purpose. These contracts are the source of truth for Step 1 implementation.

All models use Pydantic v2 (`pydantic.BaseModel`). Enums use Python `str, Enum` (string enums) for JSON serialization.

### Public vs Internal

These contracts are split into two layers:

**Public SDK contracts** -- the types a developer sees when using the SDK. These are stable, product-shaped, and minimal. They include configuration (`IndexConfig`, `SearchPolicy`), request/response envelopes (`SearchResultEnvelope`, `FollowUpRequest`), and observability (`SearchTrace`, `TraceStep`). Public models are Pydantic `BaseModel` subclasses.

**Internal orchestration models** -- the runtime state the harness uses to plan, execute, and evaluate searches. These are unstable by design and should evolve freely. They include planner output (`SearchPlan`, `PlannedBranch`), evaluator state (`NextAction`), and pipeline context (`SearchContext`). Internal models are plain `@dataclass` types, not Pydantic models.

The boundary matters: adding a field to an internal model is a refactor; adding a field to a public model is a contract change.

---

## Design Principle: The Harness Brings Structure, the Developer Brings Vocabulary

The harness owns the *mechanism* -- classification, extraction, planning, iteration, tracing. These are system concerns and use system-defined enums (`SearchStatus`, `PlanAction`, `AmbiguityLevel`, etc.).

The developer owns the *vocabulary* -- what kinds of queries their users make, what entity types exist, what filters matter. These are domain concerns and use developer-defined strings, not system enums.

This is why there is no `QueryType` enum. Query types are declared per-index by the developer via `expected_query_types`. The harness classifies incoming queries against that vocabulary using LLM-powered classification, but the categories themselves come from the developer who knows their problem domain. This also opens a natural path to multi-index routing: when a `SearchClient` owns multiple indexes, query type classification can help route queries to the index(es) that declared they handle that type.

**System-owned (enums):** `SearchStatus`, `InteractionMode`, `AmbiguityLevel`, `BranchKind`, `TraceStepType` -- these describe harness behavior visible to the developer and are fixed by the system. Internal enums (`PlanAction`, `EvaluatorAction`) also describe harness behavior but are not part of the public SDK surface.

**Developer-owned (strings):** `query_type`, `entity_types`, `expected_query_types` -- these describe the problem domain and are defined by the developer.

---

# Public SDK Contracts

## Enums

### `SearchStatus`

```python
class SearchStatus(str, Enum):
    completed = "completed"
    needs_input = "needs_input"
    partial = "partial"
    failed = "failed"
```

Every search request resolves to one of these statuses. `completed` means results are ready. `needs_input` means the harness needs more information from the user or application. `partial` means results are returned but the harness believes they are incomplete. `failed` means the search could not be executed.

### `InteractionMode`

```python
class InteractionMode(str, Enum):
    hitl = "hitl"
    aitl = "aitl"
```

Controls how the harness responds to uncertainty. HITL returns `needs_input` immediately on material ambiguity. AITL attempts autonomous resolution within budget before escalating.

### `AmbiguityLevel`

```python
class AmbiguityLevel(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
```

Qualitative assessment of how ambiguous the query is relative to the index. Drives the decision between direct search and asking for clarification.

### `BranchKind`

```python
class BranchKind(str, Enum):
    original_query = "original_query"
    filter_augmented = "filter_augmented"
    reformulated = "reformulated"
```

Identifies how a branch was created. The `original_query` branch is always preserved -- reformulated and filter-augmented branches are additive, never replacements.

### `TraceStepType`

```python
class TraceStepType(str, Enum):
    query_received = "query_received"
    query_analysis = "query_analysis"
    classification = "classification"
    extraction = "extraction"
    planning = "planning"
    search_execution = "search_execution"
    evaluation = "evaluation"
    follow_up_generation = "follow_up_generation"
    branch_created = "branch_created"
    branch_merge = "branch_merge"
    budget_check = "budget_check"
    decision = "decision"
```

Covers every distinct step in the query lifecycle pipeline. `budget_check` and `decision` are specific to AITL flow and capture the harness's budget-aware reasoning.

---

## Core Models

### `IndexConfig`

Defines a search index and its retrieval behavior. The developer provides this when creating an index via `client.indexes.create()`.

IndexConfig is the public SDK surface. It answers: **what is this index, what does it contain, and what kinds of queries should it handle?** It deliberately does not expose orchestration internals like confidence thresholds or iteration budgets. Those live in `SearchPolicy`, which most developers never need to touch.

```python
class IndexConfig(BaseModel):
    # --- Required fields ---
    name: str
    """Unique index name. Used as the primary identifier for the index."""

    schema: type
    """Pydantic model class defining the document shape in the index.
    Used for field discovery, validation, and display field resolution."""

    adapter: SearchAdapter
    """Backend adapter instance (e.g., TypesenseAdapter, InMemoryAdapter).
    Must implement the SearchAdapter protocol."""

    searchable_fields: list[str]
    """Fields the backend should search against for keyword queries.
    Must be a subset of fields defined in the schema."""

    id_field: str
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
    strings are domain-specific and owned by the developer.

    When a SearchClient has multiple indexes, query types can serve
    as routing signals: the harness can match a classified query type
    to the index(es) that declare they handle it."""

    # --- Advanced / opt-in ---
    policy: SearchPolicy = Field(default_factory=lambda: SearchPolicy())
    """Orchestration policy for this index. Controls iteration budgets,
    confidence thresholds, and other planner/evaluator behavior.
    Defaults are opinionated and designed to work well out of the
    box -- most developers should not need to set this."""
```

**Validation rules:**
- `name` must be a non-empty string, matching pattern `^[a-z][a-z0-9_]*$`
- `searchable_fields` must be non-empty
- `id_field` must be a non-empty string
- `adapter` is excluded from serialization (runtime object, not config)
- `schema` is excluded from serialization (type reference, not config)

### `SearchPolicy`

Orchestration policy that controls how the harness plans, evaluates, and iterates. Separated from `IndexConfig` so the public SDK surface stays minimal. Developers who want to tune harness behavior can provide a custom policy; developers who don't will get opinionated defaults.

```python
class SearchPolicy(BaseModel):
    max_iterations: int = Field(default=2, ge=1, le=10)
    """Maximum search iterations for AITL mode. Default 2.
    Hard upper bound prevents runaway loops."""

    max_branches: int = Field(default=2, ge=1, le=5)
    """Maximum parallel branches for AITL mode. Default 2.
    Original query always occupies one branch."""

    confidence_thresholds: ConfidenceThresholds = Field(
        default_factory=lambda: ConfidenceThresholds()
    )
    """Thresholds that control stopping, escalation, and
    ambiguity decisions."""

    canonical_filters: dict[str, list[str]] = {}
    """Known valid filter values per field. Used by the extractor to
    validate proposed filters.
    Example: {'country': ['AU', 'US', 'UK']}"""

    example_queries: list[str] = []
    """Example queries for this index. Used as few-shot examples in
    LLM prompts for classification and extraction."""
```

### `ConfidenceThresholds`

```python
class ConfidenceThresholds(BaseModel):
    stop: float = Field(default=0.7, ge=0.0, le=1.0)
    """Minimum confidence to stop and return results as 'completed'."""

    escalate: float = Field(default=0.3, ge=0.0, le=1.0)
    """Below this confidence, escalate to needs_input (HITL)
    or attempt resolution (AITL)."""

    ambiguity: float = Field(default=0.5, ge=0.0, le=1.0)
    """Ambiguity score above which the query is considered
    materially ambiguous."""
```

**Validation rules:**
- All values must be between 0.0 and 1.0 inclusive
- `escalate` should be less than `stop` (validated via model_validator)

---

## Query Models

### `QueryAnalysis`

Output of the query understanding pipeline. Captures everything the analyzer, classifier, and extractor produce from a raw query.

```python
class QueryAnalysis(BaseModel):
    raw_query: str
    """The original user query, unmodified."""

    query_type: str | None = None
    """Classified intent of the query, drawn from the index's
    expected_query_types vocabulary. This is a developer-defined
    string, not a system enum. None if classification was not
    performed or was inconclusive.

    Example: 'entity_lookup' for a company index,
    'recipe_search' for a cooking app, 'case_lookup' for a
    legal document system."""

    primary_subject: str | None = None
    """Primary subject of the query (e.g., 'Telstra', 'billing',
    'onboarding'). This is the main thing the user is searching for,
    whether it's an entity name, a topic, or a concept. None if no
    clear subject was detected."""

    target_resource_type: str | None = None
    """The resource type the user most likely wants
    (e.g., 'company'). None if ambiguous or undetected."""

    possible_resource_types: list[str] = []
    """All plausible resource types for this query, ranked by
    likelihood. Used to generate candidates for follow-up."""

    filters: dict[str, Any] = {}
    """Structured filters extracted from natural language.
    Keys are field names, values are filter values.
    Example: {'country': 'AU', 'status': 'active'}"""

    ambiguity: AmbiguityLevel = AmbiguityLevel.none
    """Assessed ambiguity level of the query relative to the index."""

    missing_fields: list[str] = []
    """Fields that would disambiguate the query but were not
    provided. Drives follow-up question generation."""

    extracted_entities: list[ExtractedEntity] = []
    """All entities extracted from the query with their types
    and positions. Richer than primary_subject for complex queries."""
```

### `ExtractedEntity`

```python
class ExtractedEntity(BaseModel):
    value: str
    """The extracted entity text (e.g., 'Telstra')."""

    entity_type: str | None = None
    """Detected type (e.g., 'company_name', 'person', 'date').
    None if type could not be determined."""

    field_mapping: str | None = None
    """Index field this entity maps to, if resolved.
    Example: 'company_name' for a company index."""

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Confidence in the extraction. None if not scored."""
```

---

## Result Models

### `SearchResultItem`

A single search result normalized from the backend response.

```python
class SearchResultItem(BaseModel):
    id: str
    """Document ID from the backend. Corresponds to the index's id_field."""

    title: str | None = None
    """Display title for the result. Resolved from the document
    using the index's display_fields configuration."""

    snippet: str | None = None
    """Text snippet showing the match context. May be generated
    by the backend or constructed from matched fields."""

    score: float | None = None
    """Relevance score from the backend. Scale varies by backend;
    not normalized across adapters in v0."""

    source: str | None = None
    """Backend or index name that produced this result.
    Useful when results come from multiple branches."""

    matched_fields: list[str] = []
    """Fields that contributed to this match."""

    metadata: dict[str, Any] = {}
    """Arbitrary metadata from the document. Contains fields
    from the display_fields configuration."""
```

### `BranchResult`

Results from a single search branch. Each branch represents one search path -- the original query, a filter-augmented version, or a reformulated version.

```python
class BranchResult(BaseModel):
    kind: BranchKind
    """How this branch was created."""

    query: str
    """The query string used for this branch."""

    filters: dict[str, Any] = {}
    """Filters applied in this branch. Empty for the original query
    branch unless the user's query contained explicit filters."""

    results: list[SearchResultItem] = []
    """Search results for this branch."""

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Confidence that this branch's results answer the user's intent.
    Set by the evaluator after results are returned."""

    total_backend_hits: int = 0
    """Total number of matching documents reported by the backend.
    May exceed len(results) due to pagination or truncation."""
```

### `Candidate`

A candidate interpretation of an ambiguous query. Returned when the harness identifies multiple plausible interpretations.

```python
class Candidate(BaseModel):
    label: str
    """Human-readable description of this interpretation.
    Example: 'Telstra company records'"""

    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence that this interpretation matches the user's intent."""
```

### `SearchResultEnvelope`

Top-level response from every search call. This is the primary contract between the SDK and the consuming application.

```python
class SearchResultEnvelope(BaseModel):
    status: SearchStatus
    """Outcome of the search request."""

    original_query: str
    """The raw user query, always preserved unmodified."""

    interaction_mode: InteractionMode
    """The interaction mode used for this search
    (may differ from the index default if overridden per-call)."""

    query_analysis: QueryAnalysis | None = None
    """Full query analysis output. None if analysis was skipped
    (e.g., direct keyword-only search)."""

    results: list[SearchResultItem] = []
    """Merged, deduplicated result list. For single-branch searches,
    this is the branch results directly. For multi-branch, results
    are merged according to the branch merge strategy."""

    branches: list[BranchResult] = []
    """Per-branch results preserving the search provenance.
    Always includes the original_query branch when branches
    were used. Empty for single-pass searches."""

    follow_up: FollowUpRequest | None = None
    """Structured follow-up when status is 'needs_input'.
    Contains reason, message, input schema, and candidates.
    None for all other statuses."""

    message: str | None = None
    """Human-readable message explaining the result status.
    Example: 'I found multiple possible interpretations of your query.'"""

    trace_id: str
    """Unique identifier for this search trace. Used for
    continue_search() and trace retrieval."""

    latency_ms: float | None = None
    """Total end-to-end latency in milliseconds."""
```

**Invariants:**
- `original_query` is always set and never mutated
- When `status` is `needs_input`, `follow_up` must not be None
- When `status` is `completed`, `results` should be non-empty (though the harness may return `completed` with zero results if the backend matched nothing)
- `trace_id` is always set and unique per search request
- When branches were used, the `original_query` branch is always present in `branches`

---

## Follow-Up Models

### `FollowUpRequest`

Structured follow-up returned when the harness needs more information. The application renders this however it wants -- the harness returns structure, not UI.

```python
class FollowUpRequest(BaseModel):
    reason: str
    """Machine-readable reason code.
    Examples: 'underspecified_query', 'ambiguous_entity',
    'missing_required_filter'"""

    message: str
    """Human-readable explanation for the application to display.
    Example: 'I found multiple possible interpretations of your query.'"""

    input_schema: dict[str, Any]
    """JSON Schema describing the input the application should collect.
    The application can render this as a form, dropdown, or free text.

    Example:
    {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "enum": ["company", "documents", "tickets"]
            },
            "region": {"type": "string"},
            "time_range": {"type": "string"}
        },
        "required": ["entity_type"]
    }
    """

    candidates: list[Candidate] = []
    """Candidate interpretations with confidence scores.
    The application can use these to pre-populate selections
    or show ranked options."""
```

---

## Trace Models

### `TraceStep`

A single step in the search trace. Kept deliberately minimal for v0 — the `payload` dict carries step-specific data without forcing every orchestration change into a schema migration. As patterns stabilize, frequently-used payload keys can be promoted to first-class fields.

```python
class TraceStep(BaseModel):
    step_type: TraceStepType
    """What kind of pipeline step this is."""

    payload: dict[str, Any] = {}
    """Step-specific data. Contents vary by step_type and are
    intentionally unstructured for v0. The orchestration layer
    writes whatever is relevant; consumers read what they need.

    Common keys by step_type (conventions, not enforced):
      query_analysis:  {raw_query, query_type, ambiguity, ...}
      planning:        {action, branches, reasoning, iterations_remaining, ...}
      search_execution:{query, filters, result_count, ...}
      evaluation:      {confidence, decision_reason, action_chosen, ...}
      decision:        {action_chosen, decision_reason, iterations_remaining,
                        branches_remaining, ...}
    """

    latency_ms: float | None = None
    """Time taken for this step in milliseconds."""

    model_used: str | None = None
    """LLM model identifier if this step involved a model call.
    None for steps that don't use an LLM."""
```

### `SearchTrace`

Complete trace of a search request from start to finish. Every search request produces a trace, regardless of interaction mode.

```python
class SearchTrace(BaseModel):
    trace_id: str
    """Unique trace identifier. Matches the trace_id in the
    SearchResultEnvelope. Used for trace retrieval and
    continue_search() correlation."""

    original_query: str
    """The raw user query that initiated this trace."""

    normalized_query: str | None = None
    """Normalized form of the query (lowercase, trimmed, etc.)
    if normalization was applied."""

    steps: list[TraceStep] = []
    """Ordered list of pipeline steps. Each step captures one
    stage of the search lifecycle."""

    total_latency_ms: float | None = None
    """End-to-end latency for the entire search request."""

    final_status: SearchStatus | None = None
    """The final status of the search request."""

    final_decision_reason: str | None = None
    """Human-readable explanation of why the search terminated
    with its final status. Example: 'Confidence 0.85 exceeds
    stop threshold 0.7 after filter augmentation.'"""

    interaction_mode: InteractionMode | None = None
    """The interaction mode used for this search trace."""

    iterations_used: int = 0
    """Total iterations consumed during this search."""

    branches_used: int = 0
    """Total branches created during this search."""
```

**Invariants:**
- `trace_id` is unique and immutable once created
- `original_query` is never modified after trace creation
- `steps` are ordered chronologically
- When `final_status` is set, the trace is considered complete
- For continued searches (`continue_search()`), new steps are appended to the existing trace; the trace_id is preserved across continuations

---

## Model Relationship Summary

```
SearchClient
  └── indexes.create(IndexConfig)
        └── SearchIndex
              ├── search(query) -> SearchResultEnvelope
              │     ├── .status: SearchStatus
              │     ├── .query_analysis: QueryAnalysis
              │     │     ├── .query_type: str (developer-defined)
              │     │     ├── .ambiguity: AmbiguityLevel
              │     │     └── .extracted_entities: [ExtractedEntity]
              │     ├── .results: [SearchResultItem]
              │     ├── .branches: [BranchResult]
              │     │     ├── .kind: BranchKind
              │     │     └── .results: [SearchResultItem]
              │     ├── .follow_up: FollowUpRequest
              │     │     ├── .input_schema: dict (JSON Schema)
              │     │     └── .candidates: [Candidate]
              │     └── .trace_id -> SearchTrace
              │           ├── .steps: [TraceStep]
              │           │     ├── .step_type: TraceStepType
              │           │     ├── .payload: dict (step-specific)
              │           │     └── .latency_ms
              │           └── .final_status: SearchStatus
              └── continue_search(trace_id, user_input) -> SearchResultEnvelope
```

---

# Orchestration Internals

These are internal runtime objects, not public contracts. They are documented here for completeness but should be implemented as plain dataclasses (not Pydantic models) so they can evolve freely without being treated as stable API. The developer never sees these types through the SDK surface.

### Internal Enums

#### `PlanAction`

```python
class PlanAction(str, Enum):
    direct_search = "direct_search"
    search_with_filters = "search_with_filters"
    multi_branch = "multi_branch"
    needs_clarification = "needs_clarification"
```

The four actions the planner can choose. In AITL mode, the priority order is: stop and return > apply filters > branch > escalate.

#### `EvaluatorAction`

```python
class EvaluatorAction(str, Enum):
    completed = "completed"
    needs_input = "needs_input"
    iterate = "iterate"
```

The three outcomes the evaluator can produce. `completed` and `needs_input` terminate the loop and map to `SearchStatus` values. `iterate` sends control back to the planner with updated context.

### `SearchPlan`

Output of the planner. Specifies what search action(s) to execute. Implemented as a `@dataclass`.

The unit of planning is the branch, not the query string. Each planned branch carries its own provenance (kind), query, and filters. This ensures the original query is explicitly represented from the moment the plan is created, not implicitly "the first item in a list."

```python
@dataclass
class SearchPlan:
    action: PlanAction
    """The chosen action for this planning step."""

    branches: list[PlannedBranch]
    """Branches to execute. For direct_search or search_with_filters,
    contains one branch. For multi_branch, contains one branch per
    search path. The original_query branch is always present."""

    reasoning: str | None = None
    """Human-readable explanation of why this plan was chosen.
    Included in the trace for debugging."""
```

**Invariants:**
- `branches` is never empty
- When `action` is `multi_branch`, `branches` contains at least two entries
- When `action` is `needs_clarification`, `branches` may be empty (no search to execute)
- Exactly one branch with `kind == original_query` must be present (unless `action` is `needs_clarification`)

### `PlannedBranch`

A single branch in a search plan. Implemented as a `@dataclass`.

```python
@dataclass
class PlannedBranch:
    kind: BranchKind
    """How this branch relates to the original query."""

    query: str
    """The query string for this branch."""

    filters: dict[str, Any] = field(default_factory=dict)
    """Filters to apply for this branch. Each branch carries its
    own filters -- there are no "global" plan-level filters."""
```

### `SearchContext`

Mutable runtime state passed through the orchestration pipeline. Accumulates state across iterations. Implemented as a `@dataclass`, not a `BaseModel`.

**The trace is NOT part of SearchContext.** Telemetry (`Tracer` / `SearchTrace`) runs as a parallel data capture alongside the pipeline. The harness never reads from the trace to make decisions. The orchestrator holds the tracer separately and passes it alongside the context. This keeps the trace as a pure observability layer (analogous to Langsmith / Langfuse) that can be reviewed retrospectively without coupling it to runtime search behaviour.

```python
@dataclass
class SearchContext:
    index_config: IndexConfig
    interaction_mode: InteractionMode
    policy: SearchPolicy

    iterations_used: int = 0
    branches_used: int = 0

    query_analysis: QueryAnalysis | None = None
    branches: list[BranchResult] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    unapplied_filters: dict[str, Any] = field(default_factory=dict)
    user_input: dict[str, Any] = field(default_factory=dict)

    @property
    def iterations_remaining(self) -> int:
        return max(0, self.policy.max_iterations - self.iterations_used)

    @property
    def branches_remaining(self) -> int:
        return max(0, self.policy.max_branches - self.branches_used)

    @property
    def budget_exhausted(self) -> bool:
        return self.iterations_remaining == 0

    @property
    def at_final_iteration(self) -> bool:
        return self.iterations_remaining == 1

    @property
    def can_branch(self) -> bool:
        return self.branches_remaining > 0
```

### `NextAction`

Output of the evaluator. Implemented as a `@dataclass`.

```python
@dataclass
class NextAction:
    action: EvaluatorAction
    reason: str
    updated_context: dict[str, Any] = field(default_factory=dict)
```

---

# Adapter Protocol

These models define the contract between the orchestration layer and backend adapters. They are public for adapter implementors but not part of the end-developer SDK surface.

### `BackendSearchRequest`

```python
class BackendSearchRequest(BaseModel):
    query: str
    """Search query string to send to the backend."""

    filters: dict[str, Any] = {}
    """Structured filters to apply. The adapter translates these
    into backend-native filter syntax."""

    fields: list[str] = []
    """Fields to search against. If empty, the adapter uses
    the index's searchable_fields."""

    limit: int = Field(default=20, ge=1, le=250)
    """Maximum results to return."""

    offset: int = Field(default=0, ge=0)
    """Pagination offset."""
```

### `BackendSearchResponse`

```python
class BackendSearchResponse(BaseModel):
    hits: list[dict[str, Any]] = []
    """Raw result documents from the backend."""

    total_count: int = 0
    """Total number of matching documents in the backend
    (may exceed len(hits) due to pagination)."""

    query_time_ms: float | None = None
    """Backend-reported query execution time."""

    raw_response: dict[str, Any] = {}
    """Full raw response from the backend. Included for debugging
    but not exposed to the SDK consumer by default."""
```

---

## Serialization Notes

- All models serialize to JSON via Pydantic's `.model_dump()` and `.model_dump_json()`
- `IndexConfig.adapter` and `IndexConfig.schema` are excluded from serialization (they are runtime objects)
- Enum fields serialize as their string values (e.g., `"completed"` not `"SearchStatus.completed"`)
- `None` fields are excluded from serialization by default to keep payloads compact
- `dict[str, Any]` fields accept arbitrary JSON-serializable values
- All `confidence` and threshold fields are constrained to `[0.0, 1.0]`
- `trace_id` values should be generated as UUID4 strings
