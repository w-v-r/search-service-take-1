# Search Service v0 Build Plan

## 1. Purpose

Build a Python-first search orchestration service and SDK that sits on top of an existing structured search backend and adds LLM-powered query understanding, iterative search, and ambiguity handling.

This is **not** a new vector database or search engine.

It is a **search harness** that turns an ordinary index into a guided search experience for humans and applications.

The v0 product goal is to help developers build better search in apps where humans interact with structured business data.

---

## 2. Product Thesis

Most search systems treat retrieval as a single request-response action.

This service treats search as a **decision process under uncertainty**:

* understand the user query
* detect when it is underspecified or ambiguous
* extract structured signals from natural language
* run the best possible first search
* decide whether to stop, ask a follow-up question, or perform another search step
* preserve the original query and surface the reasoning/traces to the developer

This creates two key interaction modes:

### HITL (Human in the Loop)

The system detects ambiguity or missing structure and returns a structured follow-up request to the application. The application can render this however it wants.

### AITL (AI in the Loop)

The system is allowed to take a small number of additional search actions autonomously: retry, add filters, branch once, and merge results.

---

## 3. Target Users for v0

Primary users:

* SaaS teams building user-facing app search
* Internal app developers searching structured business data

The product is optimized for **human-computer interaction around search**, not just retrieval quality in isolation.

---

## 4. Hero Use Cases

### Hero Use Case 1: Company / Entity Search

Example queries:

* "show me Telstra stuff"
* "find Apple in Australia"
* "show me all entities related to Acme"

Key problems:

* ambiguous entity names
* underspecified target entity type
* missing disambiguating filters
* noisy results caused by broad search

### Hero Use Case 2: Document + Metadata Search

Example queries:

* "show me contracts for Telstra from last year"
* "find onboarding docs for enterprise customers"
* "show me support docs related to billing"

Key problems:

* users mix content terms with metadata constraints
* applications often know metadata structure but users do not
* search should extract structure and turn it into filters

These two use cases are enough to shape the first SDK and API.

---

## 5. v0 Scope

### In scope

* Python SDK
* Structured search only
* Existing backend wrapped via adapter
* Keyword + filters retrieval
* Query analysis and classification
* Entity extraction / structured input extraction
* HITL flow via `needs_input` responses
* AITL flow with bounded multi-step retries
* Branch-and-merge search in limited form
* Transparent traces and debugging output
* Opinionated defaults with escape hatches

### Out of scope

* Unstructured long-document recursive search
* Multimodal search
* Learning-to-rank
* Hosted control plane / admin UI
* Authentication / billing / multitenancy
* Browser UI
* Full vector / hybrid retrieval in v0 core

---

## 6. Design Principles

1. **The developer should feel like they are using our API, not the underlying backend.**
2. **The original user query must always remain represented in the search process and result traces.**
3. **LLM assistance should improve search, not hide uncertainty.**
4. **Ask for clarification when uncertainty is material.**
5. **AITL must be bounded and observable.**
6. **Use simple defaults, but expose hooks for custom behavior.**
7. **The first product should optimize for API simplicity, debugging, and transparent traces.**

---

## 7. Recommended v0 Architecture

The architecture should be layered so that the orchestration system is independent from the underlying backend.

### Core layers

#### 7.1 SDK Layer

Developer-facing Python API.

Responsibilities:

* client construction
* index registration
* schema definition
* search execution
* trace retrieval
* configuration overrides

#### 7.2 Orchestration Layer

The main product logic.

Responsibilities:

* query analysis
* query classification
* ambiguity detection
* structured extraction
* search planning
* iteration control
* follow-up generation
* stopping decisions
* branch and merge

#### 7.3 Adapter Layer

Backend abstraction.

Responsibilities:

* create / validate index bindings
* translate generic query plans into backend-native search calls
* normalize backend results into internal result format

#### 7.4 Model Layer

LLM and optional future model providers.

Responsibilities:

* classification
* extraction
* clarification generation
* planner decisions
* result summarization / interpretation where needed

#### 7.5 Trace / Telemetry Layer

Observability and debugging.

Responsibilities:

* capture each search step
* capture prompts, inputs, outputs, latency, confidence, filters, candidate branches
* expose structured traces for developers

---

## 8. Backend Recommendation for v0

### Recommendation: start with a backend adapter boundary and ship one real adapter

The adapter boundary is mandatory from day one.

### Candidate: Typesense

**Pros**

* relatively simple collection-oriented API
* strong keyword + filter story
* good fit for user-facing application search
* Python client exists
* easier mental model than Elasticsearch/OpenSearch

**Cons**

* some platform-specific concepts may leak if the adapter boundary is weak
* you may eventually want richer backend options for enterprise structured data or hybrid retrieval

### Candidate: PostgreSQL / custom SQL adapter

**Pros**

* extremely common
* structured data friendly
* easy to understand for internal business search
* likely useful for many SaaS/internal tools teams

**Cons**

* weaker out-of-the-box search UX than a dedicated search engine
* more work to make fuzzy / ranking behavior feel polished

### Candidate: Elasticsearch / OpenSearch

**Pros**

* strongest long-term search platform baseline
* native keyword ranking and filters are mature
* broad future path

**Cons**

* more complexity for v0
* can make the first build heavier than necessary

### Decision recommendation

For v0, choose **Typesense** as the first wrapped backend **if** the goal is a faster path to an app-search-quality experience.

But implement the internal interfaces so a second adapter can be added later.

Suggested order:

1. In-memory test adapter
2. Typesense adapter
3. Optional Postgres or Elasticsearch adapter later

---

## 9. Core Concepts in the SDK

### 9.1 Client

Top-level entry point.

```python
client = SearchClient(api_key="...", model="mercury-2")
```

### 9.2 Search App / Search Service

A broader orchestrator object that owns one or more indexes and global defaults.

```python
app = client.app(name="customer-search")
```

### 9.3 Search Index

Represents a search target and its retrieval configuration.

This should be a first-class object, but conceptually it lives inside the orchestrator.

```python
index = app.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(...),
    search_backend="keyword_filters",
    interaction_mode="hitl"
)
```

### 9.4 Search Profile

Optional named config bundle for expected query patterns.

Examples:

* `entity_lookup`
* `document_lookup`
* `catalog_lookup`

A profile defines:

* expected intents
* likely extracted entities
* ambiguity rules
* default filters
* max iterations
* follow-up style

### 9.5 Search Result Envelope

Every search call should return a structured envelope, not raw backend output.

---

## 10. Proposed Developer Experience

### 10.1 Minimal happy path

```python
client = SearchClient(model="mercury-2")

app = client.app("crm-search")

index = app.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(...),
    search_backend="keyword_filters",
    interaction_mode="hitl"
)

result = index.search("show me Telstra stuff")
```

### 10.2 Suggested result shape

```python
{
  "status": "needs_input",
  "reason": "underspecified_query",
  "message": "I found multiple possible interpretations of your query.",
  "original_query": "show me Telstra stuff",
  "requested_input": {
    "schema": {
      "type": "object",
      "properties": {
        "entity_type": {"type": "string", "enum": ["company", "documents", "tickets"]},
        "region": {"type": "string"},
        "time_range": {"type": "string"}
      },
      "required": ["entity_type"]
    }
  },
  "candidates": [
    {"label": "Telstra company records", "confidence": 0.62},
    {"label": "Telstra-related documents", "confidence": 0.31}
  ],
  "trace_id": "..."
}
```

### 10.3 Follow-up continuation

```python
result = index.continue_search(
    trace_id=previous.trace_id,
    user_input={"entity_type": "company", "region": "AU"}
)
```

### 10.4 AITL example

```python
result = index.search(
    "show me Telstra stuff",
    interaction_mode="aitl"
)
```

Response:

```python
{
  "status": "completed",
  "original_query": "show me Telstra stuff",
  "query_analysis": {...},
  "results": [...],
  "branches": [...],
  "trace_id": "..."
}
```

---

## 11. Required Developer Inputs for Index Definition

The developer should define an index in terms of search behavior, not just backend schema.

### Required in v0

* `name`
* `schema`
* `adapter`
* `search_backend` (initially `keyword_filters`)
* `default_interaction_mode`
* `searchable_fields`
* `filterable_fields`
* `id_field`
* `display_fields`
* `entity_types` or `resource_types`
* `profiles` or expected query types

### Optional but highly valuable

* example queries
* ambiguity rules
* canonical filters
* stop conditions
* max search iterations
* branch limit
* confidence thresholds
* developer-provided extraction hints

### Example

```python
index = app.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(...),
    search_backend="keyword_filters",
    default_interaction_mode="hitl",
    searchable_fields=["company_name", "aliases", "description"],
    filterable_fields=["country", "industry", "status"],
    id_field="company_id",
    display_fields=["company_name", "country", "status"],
    entity_types=["company"],
    profiles=["entity_lookup"]
)
```

---

## 12. Query Lifecycle

Each search request should follow a predictable pipeline.

### Step 1: Receive request

Input:

* natural-language query
* index name
* optional interaction override
* optional developer context

### Step 2: Query analysis

Classify:

* likely intent
* entity mentions
* candidate structured constraints
* ambiguity level
* whether the query is underposed

### Step 3: Query plan

Decide one of:

* direct search
* search + filter injection
* multi-branch search
* needs clarification

### Step 4: Execute search

Run backend search via adapter.

### Step 5: Evaluate results

Assess:

* confidence
* ambiguity
* result quality
* whether more information is needed

### Step 6: Decide next action

Return one of:

* `completed`
* `needs_input`
* `failed`
* `partial`

### Step 7: Trace and persist context

Store the step graph so search can continue.

---

## 13. Query Classification and Extraction

This is a major differentiator and should be a first-class subsystem.

### v0 responsibilities

* identify likely query type
* extract important entities from raw text
* map extracted entities to index fields where possible
* propose filters
* detect missing required fields

### Example

Input:

`"show me Telstra stuff"`

Potential extracted structure:

```json
{
  "query_type": "entity_lookup",
  "mentioned_entity": "Telstra",
  "target_resource_type": null,
  "possible_resource_types": ["company", "document", "ticket"],
  "filters": {},
  "ambiguity": "high"
}
```

This should then power either HITL or AITL.

---

## 14. HITL Flow

In HITL mode, the service should not guess when ambiguity is material.

### HITL behavior

* return `needs_input`
* explain what is missing in plain language
* return a structured schema for the app to render
* include candidate interpretations when useful

### Important implementation detail

Use dynamic schema generation for follow-up inputs so the app can render form-like structured questions.

This is where a tool like dydantic can be valuable in v0 experiments.

### HITL contract

The backend should return structure, not UI.

That means the app owns:

* prompt rendering
* forms
* dropdowns
* re-submission

---

## 15. AITL Flow

In AITL mode, the orchestrator may navigate the search process autonomously.

### v0 allowed actions

* reformulate query terms conservatively
* add filters from extracted structure
* run a second search branch
* merge branch results
* stop when confidence is acceptable

### v0 limits

* max 2-3 iterations
* max 2 branches
* preserve original query results
* never silently discard the original interpretation

### Critical rule

The original query must remain visible in the result envelope and trace.

If the system runs a modified query, it should appear as an additional branch, not a replacement.

### Example branch structure

```json
{
  "branches": [
    {
      "kind": "original_query",
      "query": "show me Telstra stuff",
      "results": [...]
    },
    {
      "kind": "filter_augmented",
      "query": "Telstra",
      "filters": {"entity_type": "company"},
      "results": [...]
    }
  ]
}
```

---

## 16. Result Model

A normalized result envelope is essential.

### Suggested top-level fields

* `status`
* `original_query`
* `interaction_mode`
* `query_analysis`
* `results`
* `candidates`
* `branches`
* `needs_input`
* `message`
* `trace_id`
* `latency_ms`

### Status values

* `completed`
* `needs_input`
* `partial`
* `failed`

### Result item fields

* `id`
* `title`
* `snippet`
* `score`
* `source`
* `matched_fields`
* `metadata`

---

## 17. Trace Model

Tracing is not optional. It is one of the core product advantages.

### Every trace should capture

* original query
* normalized query
* classifier output
* extraction output
* planner decision
* executed backend queries
* filters added
* branch decisions
* result counts
* latencies per step
* model prompts and outputs (redactable)
* final decision reason

### Trace access API

```python
trace = client.traces.get(trace_id)
```

This should make the product easy to debug and trust.

---

## 18. Proposed Python Package Structure

```text
search_service/
  client.py
  app.py
  indexes/
    base.py
    config.py
    runtime.py
  adapters/
    base.py
    in_memory.py
    typesense.py
  orchestration/
    analyzer.py
    classifier.py
    extractor.py
    planner.py
    executor.py
    evaluator.py
    followup.py
  models/
    llm.py
    mercury.py
  schemas/
    result.py
    trace.py
    query.py
    followup.py
  telemetry/
    tracer.py
    events.py
  exceptions.py
```

---

## 19. Core Internal Interfaces

### Adapter interface

```python
class SearchAdapter(Protocol):
    def search(self, request: BackendSearchRequest) -> BackendSearchResponse: ...
    def validate_schema(self, schema: type) -> None: ...
```

### Analyzer interface

```python
class QueryAnalyzer(Protocol):
    def analyze(self, query: str, context: SearchContext) -> QueryAnalysis: ...
```

### Planner interface

```python
class SearchPlanner(Protocol):
    def plan(self, analysis: QueryAnalysis, context: SearchContext) -> SearchPlan: ...
```

### Evaluator interface

```python
class ResultEvaluator(Protocol):
    def decide(self, state: SearchState) -> NextAction: ...
```

---

## 20. Suggested Implementation Phases

## Phase 0: Design and scaffolding

Deliverables:

* package structure
* Pydantic models for configs/results/traces
* adapter protocol
* in-memory adapter
* dummy model provider
* basic search result envelope

Success criteria:

* developer can define an index and run a direct search with no LLM

## Phase 1: Basic keyword + filters orchestration

Deliverables:

* index config
* simple analyzer
* structured extraction
* planner for direct search vs needs_input
* search pipeline execution
* trace capture

Success criteria:

* `show me Telstra stuff` can produce either direct results or `needs_input`

## Phase 2: HITL iteration

Deliverables:

* follow-up schema generation
* `continue_search()` flow
* trace continuation
* dynamic structured questions

Success criteria:

* app can receive structured follow-up schema and continue the search

## Phase 3: AITL iteration

Deliverables:

* bounded retries
* filter augmentation
* branch + merge logic
* stop conditions
* confidence thresholds

Success criteria:

* AITL can run 1-2 extra search steps without losing the original query path

## Phase 4: Typesense adapter

Deliverables:

* schema mapping
* query translation
* filter translation
* response normalization
* integration tests

Success criteria:

* real backend can support both hero use cases

## Phase 5: Developer quality improvements

Deliverables:

* better docs
* examples for company search and document+metadata search
* easier config defaults
* trace inspection helpers
* logging hooks / OpenTelemetry-friendly interface

Success criteria:

* coding agent or external developer can use docs alone to integrate the SDK

---

## 21. Testing Strategy

### Unit tests

* analyzer behavior
* planner decisions
* evaluator stop conditions
* schema generation
* result normalization

### Golden tests

Create a set of query fixtures for both hero flows:

* ambiguous entity names
* underspecified queries
* typo queries
* mixed text + metadata requests

### Adapter tests

* query translation correctness
* filters correctness
* normalized result shape

### End-to-end tests

* HITL search continuation
* AITL retry + branch merge
* original query preservation

---

## 22. Default Behaviors for v0

These defaults should be opinionated.

* max iterations: `2`
* max branches: `2`
* direct search first: `True`
* ask for clarification on high ambiguity: `True`
* preserve original branch: `True`
* return trace metadata by default: `True`
* expose backend-native raw results optionally: `False`

---

## 23. Recommended Configuration Surface

### SearchClient config

* model provider
* default model
* telemetry hooks
* debug mode

### App config

* default interaction mode
* trace retention settings
* global prompt policy

### Index config

* adapter
* schema
* searchable/filterable/display fields
* search profile
* ambiguity policy
* iteration policy

---

## 24. Developer Experience Goals

The SDK should feel:

* minimal
* typed
* index-centric but orchestrator-owned
* debuggable
* easy to read in code

### Style recommendation

Use a modern typed Python client style inspired by:

* index-centric search SDKs for the object model
* modern generated/typed SDKs for request/response models

Recommendation:

* sync and async APIs eventually
* Pydantic models for requests/responses/config
* explicit but short method names
* small number of top-level concepts

---

## 25. Example v0 API Sketch

```python
from search_service import SearchClient, TypesenseAdapter
from my_models import CompanySchema

client = SearchClient(model="mercury-2", debug=True)
app = client.app("customer-search")

companies = app.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(
        host="localhost",
        port=8108,
        api_key="xyz"
    ),
    search_backend="keyword_filters",
    default_interaction_mode="hitl",
    searchable_fields=["company_name", "aliases", "description"],
    filterable_fields=["country", "industry", "status"],
    display_fields=["company_name", "country", "status"],
    profiles=["entity_lookup"]
)

result = companies.search("show me Telstra stuff")

if result.status == "needs_input":
    result = companies.continue_search(
        trace_id=result.trace_id,
        user_input={"entity_type": "company", "country": "AU"}
    )
```

---

## 26. Open Questions to Leave Flexible in the Codebase

These should remain configurable rather than prematurely fixed.

* exact prompt templates
* confidence scoring strategy
* branch merge strategy
* query classification taxonomy
* whether search profiles are code-defined or config-defined
* whether dynamic follow-up schemas use dydantic directly or a custom schema builder abstraction
* exact backend query DSL translation model

---

## 27. Future State / Post-v0 Roadmap

### Near-term

* second backend adapter
* vector or hybrid retrieval mode
* reranking
* more polished typo handling
* better ambiguity scoring
* richer query taxonomy
* OpenTelemetry / Langfuse style tracing integrations

### Medium-term

* document + metadata search as a polished first-class package
* better branch ranking and evidence fusion
* built-in evaluation harness
* admin/trace inspection UI
* TypeScript SDK

### Long-term

* unstructured long-document search
* recursive language-model search over large documents
* search as navigation over mixed indexes
* best-in-class human search UX inside applications
* autonomous search workflows for AI agents
* better/faster/cheaper search than conventional single-shot systems

---

## 28. Recommended First Build Order for the Coding Agent

1. Create the package skeleton and core Pydantic models.
2. Implement `SearchClient`, `App`, and `Index` objects.
3. Implement the in-memory adapter.
4. Implement the result envelope and trace model.
5. Implement direct search with keyword + filters, no LLM.
6. Add the analyzer/classifier/extractor pipeline.
7. Add `needs_input` responses and `continue_search()`.
8. Add bounded AITL retry + branch/merge.
9. Implement Typesense adapter.
10. Write example apps for company/entity search and document+metadata search.
11. Add docs and test fixtures.

---

## 29. Final Recommendation

The right v0 is a **structured search orchestration SDK** with:

* a clean Python API
* one wrapped backend
* strong query understanding
* HITL and AITL modes
* transparent traces
* bounded iterative search

Do **not** try to solve every search problem in v0.

Prove that this product can make structured search feel dramatically smarter and more usable without losing developer control.

That is enough to build a real wedge into the market.
