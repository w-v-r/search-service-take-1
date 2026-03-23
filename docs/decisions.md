# Architectural Decisions

This document captures key architectural decisions baked into v0 and their rationale.

## 0. This is a Harness, Not an Agent

**Decision:** The search service is a **search harness** -- a structured, opinionated framework for iterated search. It is explicitly not an agent.

**Rationale:** An agent implies open-ended autonomy, unpredictable latency, and opaque reasoning. A harness implies bounded behavior, low latency, and a predictable execution model. The product value comes from good structure and good opinions about how to navigate search under uncertainty, not from giving an LLM free rein. The harness ties together the index, backend adapter, and LLM interaction into a coherent, observable pipeline. The LLM is a component inside the harness, not the driver of it.

**Implication:** Every design choice should optimize for harness qualities: predictability, speed, observability, and developer control.

## 0.1 Opinionated Defaults, Out-of-the-Box Excellence

**Decision:** The harness ships with strong opinions that produce excellent search out of the box. Flexibility exists as escape hatches, not as the default posture.

**Rationale:** Developers adopting this SDK should get dramatically better search with minimal configuration. The opinions (bounded iterations, structured follow-up, original query preservation, traces by default) are the product. If everything is configurable and nothing is defaulted, the harness has no point of view. The goal is: plug in your index, run a search, and immediately see the difference.

## 0.2 Iterated Search is the Core Mechanism

**Decision:** The primary mechanism is **iterated search** -- the harness can take multiple bounded steps toward the right answer, rather than relying on a single retrieval pass.

**Rationale:** Simple retrieval always falls short. Queries are underspecified, ambiguous, or mix content terms with metadata constraints. A single search call cannot solve this. The insight is that with good structure and good opinions, you can go much further: detect what's missing, extract structure, add filters, branch, and converge. This is what makes the harness valuable. The LLM, the backend, the adapter -- those are necessary components, but iterated search is what ties them together into something meaningfully better than one-shot retrieval.

## 1. Typesense as the First Backend Adapter

**Decision:** Ship Typesense as the first real backend adapter.

**Rationale:** Typesense has a relatively simple collection-oriented API, strong keyword + filter support, and a good fit for user-facing application search. Its simpler mental model (compared to Elasticsearch/OpenSearch) makes it the fastest path to a working app-search-quality experience.

**Trade-off:** Some Typesense-specific concepts may leak if the adapter boundary is not kept strict. The adapter protocol exists to prevent this.

## 2. Keyword + Filters Before Vector/Hybrid Retrieval

**Decision:** v0 uses keyword search with structured filters only. No vector or hybrid retrieval.

**Rationale:** The core product thesis is about orchestration, not retrieval innovation. Keyword + filters is sufficient to prove the value of query understanding, iterative search, and ambiguity handling. Vector/hybrid retrieval is a retrieval-quality improvement that can be layered on later without changing the orchestration architecture.

## 3. Bounded AITL (AI in the Loop)

**Decision:** AITL is bounded to max 2-3 iterations and max 2 branches.

**Rationale:** Unbounded autonomous search is unpredictable, expensive, and hard to debug. The v0 product value comes from making a small number of smart decisions, not from running many iterations. Bounded AITL is observable, predictable, and trustworthy. The original query must always remain visible in the result envelope and trace.

## 4. Adapter Boundary is Mandatory

**Decision:** All backend communication goes through an adapter protocol from day one. No direct backend calls.

**Rationale:** The orchestration system must be backend-agnostic so it can work with Typesense, Elasticsearch, Postgres, or future backends. The adapter boundary also makes testing trivial via the in-memory adapter. Even if v0 ships with only one real adapter, the boundary prevents coupling.

## 5. SDK Shape Influences Architecture

**Decision:** The SDK API surface (SearchClient -> Index -> search/continue_search) drives the internal architecture.

**Rationale:** The developer experience is the product. The internal architecture should serve the API, not the other way around. Index-centric design with orchestrator ownership makes the API feel minimal and typed while keeping the orchestration logic centralized. Every comparable search/vector DB SDK (Pinecone, Weaviate, Qdrant, Typesense, Elasticsearch, Meilisearch, Algolia) uses a two-level Client -> Index/Collection pattern. Shared defaults belong on the client, and index grouping is handled by naming conventions.

## 6. Traces are Not Optional

**Decision:** Every search request produces a structured trace capturing each pipeline step.

**Rationale:** Tracing is one of the core product advantages. Developers need to understand why a search produced its results, what the system tried, and where it stopped. This makes the product debuggable and trustworthy, which is critical for adoption.

## 7. Pydantic for Public Contracts, Dataclasses for Internals

**Decision:** Use Pydantic v2 models for all public SDK contracts (requests, responses, configs, traces). Use plain `@dataclass` types for internal orchestration state (see Decision #10).

**Rationale:** Pydantic provides runtime validation, serialization, and strong typing. It aligns with modern Python SDK conventions and makes the public API self-documenting. Internal orchestration models use dataclasses because they need to evolve freely without the overhead of being treated as stable, serializable contracts.

## 8. Query Types Are Developer-Defined, Not System-Defined

**Decision:** There is no system-level `QueryType` enum. Query types are plain strings declared per-index by the developer via `expected_query_types`.

**Rationale:** The harness brings the classification structure (the mechanism for understanding queries). The developer brings the vocabulary (what kinds of queries their users actually make). A fixed taxonomy like `entity_lookup` / `document_lookup` assumes the developer's domain. A recipe search app, a legal document system, and a company CRM have fundamentally different query patterns. Hardcoding those patterns into a system enum forces every consumer to map their domain into our vocabulary, which is the opposite of the SDK's design philosophy.

Developer-defined query types also open a natural path to multi-index routing: when a `SearchClient` owns multiple indexes, query type classification can match incoming queries to the index(es) that declared they handle that type.

**Implication:** The harness ships with *suggested* query type strings in documentation (e.g., `"entity_lookup"`, `"document_lookup"`) as conventions, but never enforces them. Classification prompts are built dynamically from the index's declared `expected_query_types`.

## 9. IndexConfig is the Public Surface, SearchPolicy is the Escape Hatch

**Decision:** `IndexConfig` contains only identity, fields, and developer vocabulary. Orchestration policy (iteration budgets, confidence thresholds, canonical filter values, example queries) lives in a separate `SearchPolicy` object, referenced via an optional `policy` field on `IndexConfig`. Every `SearchPolicy` field has real types and a real v0 use case -- untyped placeholder knobs (`ambiguity_rules`, `stop_conditions`, `extraction_hints`) were cut to keep the surface minimal and honest.

**Rationale:** The SDK should feel minimal. A developer creating an index should think about *what their index contains and what kinds of queries it handles* -- not about how the planner scores confidence or when the evaluator stops iterating. Mixing identity with policy turns `IndexConfig` into a framework configuration blob that requires understanding orchestration internals to use. Separating policy means most developers never see it, while power users get a clean escape hatch with opinionated defaults they can override selectively. Keeping only typed, implemented fields prevents the "configurable but does nothing" trap.

**Implication:** `SearchPolicy` ships with strong defaults (`max_iterations=2`, `max_branches=2`, `confidence.stop=0.7`, etc.). The orchestration layer reads policy from `index_config.policy`. Per-call overrides may be supported in the future but are not required for v0. Additional policy knobs can be added when there is real behavior behind them.

## 10. Public SDK Contracts vs Internal Orchestration Models

**Decision:** Models are split into two explicit layers: **public SDK contracts** (Pydantic `BaseModel`) and **internal orchestration models** (plain `@dataclass`). The boundary is structural -- it exists in the document, in the code layout, and in the naming conventions.

**Rationale:** When public contracts and internal state are blended, every internal refactor risks becoming a contract change. Planner output (`SearchPlan`, `PlannedBranch`), evaluator state (`NextAction`), and pipeline context (`SearchContext`) are implementation details that need to evolve freely. The developer never sees these types. Making them dataclasses instead of Pydantic models signals instability by design and prevents them from leaking into the SDK surface. Internal enums (`PlanAction`, `EvaluatorAction`) follow the same principle -- they describe harness behavior but are not part of the developer-facing contract.

**Implication:** Adding a field to an internal model is a refactor. Adding a field to a public model is a contract change. This distinction should be enforced in code review and package structure.

## 11. HITL Returns Structure, Not UI

**Decision:** The HITL follow-up response returns a structured schema (JSON Schema-like), not rendered UI.

**Rationale:** The application owns the UI. The search service should return enough structure for the app to render form-like questions (dropdowns, typed inputs) without prescribing how they look. This keeps the SDK general-purpose across CLI tools, web apps, and programmatic consumers.
