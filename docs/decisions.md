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

**Decision:** The SDK API surface (SearchClient -> App -> Index -> search/continue_search) drives the internal architecture.

**Rationale:** The developer experience is the product. The internal architecture should serve the API, not the other way around. Index-centric design with orchestrator ownership makes the API feel minimal and typed while keeping the orchestration logic centralized.

## 6. Traces are Not Optional

**Decision:** Every search request produces a structured trace capturing each pipeline step.

**Rationale:** Tracing is one of the core product advantages. Developers need to understand why a search produced its results, what the system tried, and where it stopped. This makes the product debuggable and trustworthy, which is critical for adoption.

## 7. Pydantic for All Data Models

**Decision:** Use Pydantic v2 models for all requests, responses, configs, and internal data structures.

**Rationale:** Pydantic provides runtime validation, serialization, and strong typing. It aligns with modern Python SDK conventions and makes the API self-documenting. Using a single modeling approach across the entire codebase reduces cognitive load.

## 8. HITL Returns Structure, Not UI

**Decision:** The HITL follow-up response returns a structured schema (JSON Schema-like), not rendered UI.

**Rationale:** The application owns the UI. The search service should return enough structure for the app to render form-like questions (dropdowns, typed inputs) without prescribing how they look. This keeps the SDK general-purpose across CLI tools, web apps, and programmatic consumers.
