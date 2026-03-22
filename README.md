# Search Service v0

Simple retrieval disappoints. Queries are underspecified, ambiguous, or both -- and single-shot search just shrugs and returns whatever it finds.

This SDK is a **search harness**: an opinionated, low-latency framework that wraps an existing search backend and **iterates toward the right answer**. It detects ambiguity, extracts structure, asks follow-up questions when they matter, and takes bounded additional search steps -- all while preserving the original query and surfacing every decision as a trace.

Inside the harness: an index, a backend adapter, LLM-powered query understanding. But those are components. The harness is the logic that ties them together -- the structure and opinions that let you go much further with search than simple retrieval ever could.

This is **not an agent**. It is a harness. Bounded, predictable, fast.

## Product Thesis

Most search queries against structured business data are underspecified. Users say *"show me Telstra stuff"* and mean something precise -- but the system has to figure out what.

This SDK treats search as a **decision process under uncertainty**:

- Detect when a query is ambiguous or underspecified
- Extract structured signals (entities, filters, intent) from natural language
- Run the best possible first search
- Decide whether to stop, ask a structured follow-up, or take another bounded search step
- **Always preserve the original query** and surface the full reasoning trace to the developer

The differentiator is not the retrieval and not the LLM -- it is the **iterated search** that navigates uncertainty, asks for clarification when it matters, and never silently discards the user's original intent.

### Interaction Modes

**HITL (Human in the Loop)** -- When ambiguity is material, the system returns a structured follow-up request (`needs_input`) with a schema the application can render however it wants. The search service returns structure, not UI.

**AITL (AI in the Loop)** -- The system takes a small, bounded number of additional search actions autonomously: add filters from extracted structure, branch once, merge results. Max 2-3 iterations, max 2 branches, original query path always preserved.

## Target Users

- SaaS teams building user-facing app search
- Internal app developers searching structured business data

The product is optimized for **human-computer interaction around search**, not just retrieval quality in isolation.

## Quick Start

```python
from search_service import SearchClient, TypesenseAdapter
from my_models import CompanySchema

client = SearchClient(model="mercury-2", debug=True)
app = client.app("customer-search")

companies = app.indexes.create(
    name="companies",
    schema=CompanySchema,
    adapter=TypesenseAdapter(host="localhost", port=8108, api_key="xyz"),
    search_backend="keyword_filters",
    default_interaction_mode="hitl",
    searchable_fields=["company_name", "aliases", "description"],
    filterable_fields=["country", "industry", "status"],
    display_fields=["company_name", "country", "status"],
    profiles=["entity_lookup"],
)

result = companies.search("show me Telstra stuff")

if result.status == "needs_input":
    result = companies.continue_search(
        trace_id=result.trace_id,
        user_input={"entity_type": "company", "country": "AU"},
    )
```

## v0 Scope

### In scope

- Python SDK
- Structured search only (existing backend wrapped via adapter, Typesense first)
- Keyword + filters retrieval
- Ambiguity detection and underspecified query handling
- Query analysis and classification
- Entity extraction and structured filter proposal
- HITL flow: structured follow-up via `needs_input` responses
- AITL flow: bounded iterative search with branch-and-merge (max 2-3 iterations, max 2 branches)
- Original query preservation across all branches and iterations
- Transparent traces capturing every decision step
- Opinionated defaults with escape hatches

### Out of scope

- Unstructured long-document recursive search
- Multimodal search
- Learning-to-rank
- Hosted control plane / admin UI
- Authentication / billing / multitenancy
- Browser UI
- Full vector / hybrid retrieval in v0 core

## Architecture

The system is layered so that the orchestration logic (where the product value lives) is independent from the underlying search backend:

1. **SDK Layer** -- Developer-facing Python API (client, index, search, continue_search, trace)
2. **Orchestration Layer** -- Ambiguity detection, query understanding, search planning, iteration control, follow-up generation, stopping decisions
3. **Adapter Layer** -- Backend abstraction (Typesense, in-memory, future adapters)
4. **Model Layer** -- LLM providers for classification, extraction, and planning decisions
5. **Trace / Telemetry Layer** -- Step-level observability capturing every decision in the search process

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
