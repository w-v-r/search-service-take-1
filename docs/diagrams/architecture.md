# Architecture -- Runtime Data Flow

```mermaid
flowchart TB
    subgraph SDK["SDK Layer"]
        SC["SearchClient"]
        APP["App"]
        IDX["SearchIndex"]
    end

    subgraph ORCH["Orchestration Layer"]
        ANALYZER["QueryAnalyzer"]
        CLASSIFIER["Classifier"]
        EXTRACTOR["Extractor"]
        PLANNER["SearchPlanner"]
        EXECUTOR["Executor"]
        EVALUATOR["ResultEvaluator"]
        FOLLOWUP["FollowUpGenerator"]
    end

    subgraph MODEL["Model Layer"]
        LLM["ModelProvider"]
    end

    subgraph ADAPTER["Adapter Layer"]
        PROTOCOL["SearchAdapter Protocol"]
        INMEM["InMemoryAdapter"]
        TS["TypesenseAdapter"]
    end

    subgraph TRACE["Trace / Telemetry Layer"]
        TRACER["Tracer"]
        EVENTS["Events"]
    end

    subgraph RESULT["Result"]
        ENVELOPE["SearchResultEnvelope"]
    end

    SC --> APP
    APP --> IDX

    IDX -->|"search(query)"| ANALYZER
    ANALYZER --> CLASSIFIER
    ANALYZER --> EXTRACTOR
    CLASSIFIER -.->|uses| LLM
    EXTRACTOR -.->|uses| LLM

    ANALYZER -->|QueryAnalysis| PLANNER
    PLANNER -.->|uses| LLM
    PLANNER -->|SearchPlan| EXECUTOR

    EXECUTOR -->|BackendSearchRequest| PROTOCOL
    PROTOCOL --> INMEM
    PROTOCOL --> TS

    EXECUTOR -->|raw results| EVALUATOR
    EVALUATOR -.->|uses| LLM

    EVALUATOR -->|"completed"| ENVELOPE
    EVALUATOR -->|"needs_input"| FOLLOWUP
    EVALUATOR -->|"retry/branch"| PLANNER

    FOLLOWUP --> ENVELOPE

    ANALYZER -.->|step| TRACER
    PLANNER -.->|step| TRACER
    EXECUTOR -.->|step| TRACER
    EVALUATOR -.->|step| TRACER
    TRACER --> EVENTS
    TRACER -.->|trace_id| ENVELOPE
```

## Data Flow Summary

1. **Developer calls** `index.search("show me Telstra stuff")`
2. **SDK Layer** routes the request to the orchestration pipeline
3. **QueryAnalyzer** classifies the query and extracts entities/filters using the Model Layer
4. **SearchPlanner** decides the action: direct search, search+filters, multi-branch, or needs_clarification
5. **Executor** translates the plan into a backend request via the Adapter Protocol
6. **ResultEvaluator** assesses the results and decides: completed, needs_input, or retry
7. **Tracer** captures each step for observability
8. **SearchResultEnvelope** is returned with status, results, branches, and trace_id
