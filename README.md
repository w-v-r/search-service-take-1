# Search Service v0

A Python-first search orchestration SDK that sits on top of existing structured search backends and adds LLM-powered query understanding, iterative search, and ambiguity handling.

This is **not** a new vector database or search engine. It is a **search harness** that turns an ordinary index into a guided search experience for humans and applications.

## Product Thesis

Most search systems treat retrieval as a single request-response action. This service treats search as a **decision process under uncertainty**:

- Understand the user query
- Detect when it is underspecified or ambiguous
- Extract structured signals from natural language
- Run the best possible first search
- Decide whether to stop, ask a follow-up question, or perform another search step
- Preserve the original query and surface the reasoning/traces to the developer

### Interaction Modes

**HITL (Human in the Loop)** -- The system detects ambiguity or missing structure and returns a structured follow-up request to the application. The application can render this however it wants.

**AITL (AI in the Loop)** -- The system is allowed to take a small number of additional search actions autonomously: retry, add filters, branch once, and merge results.

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
- Structured search only
- Existing backend wrapped via adapter (Typesense first)
- Keyword + filters retrieval
- Query analysis and classification
- Entity extraction / structured input extraction
- HITL flow via `needs_input` responses
- AITL flow with bounded multi-step retries
- Branch-and-merge search in limited form
- Transparent traces and debugging output
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

The system is layered so that orchestration is independent from the underlying backend:

1. **SDK Layer** -- Developer-facing Python API (client, index, search, trace)
2. **Orchestration Layer** -- Query analysis, classification, planning, iteration, follow-up generation
3. **Adapter Layer** -- Backend abstraction (Typesense, in-memory, future adapters)
4. **Model Layer** -- LLM providers for classification, extraction, and planning
5. **Trace / Telemetry Layer** -- Step-level observability and debugging

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
