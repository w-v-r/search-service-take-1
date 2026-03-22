# Roadmap -- Future Capabilities Beyond v0

This document captures planned capabilities that are out of scope for v0 but inform the architecture and extension points.

## Near-Term

- **Second backend adapter** -- Postgres or Elasticsearch adapter to validate the adapter boundary
- **Vector or hybrid retrieval mode** -- Combine keyword search with embedding-based retrieval
- **Reranking** -- Cross-encoder or LLM-based reranking of initial search results
- **Polished typo handling** -- More robust fuzzy matching and did-you-mean suggestions
- **Better ambiguity scoring** -- Calibrated confidence model for ambiguity detection
- **Richer query taxonomy** -- Expanded classification categories beyond entity/document lookup
- **OpenTelemetry / Langfuse integrations** -- First-class tracing export to external observability platforms

## Medium-Term

- **Document + metadata search as a polished first-class package** -- Dedicated abstractions for mixed content/metadata retrieval
- **Better branch ranking and evidence fusion** -- Smarter merging of multi-branch results
- **Built-in evaluation harness** -- Automated quality measurement for search pipelines
- **Admin / trace inspection UI** -- Web-based dashboard for exploring search traces
- **TypeScript SDK** -- First-class TypeScript client for frontend and Node.js use cases

## Long-Term

- **Unstructured long-document search** -- Recursive language-model search over large documents
- **Search as navigation over mixed indexes** -- Cross-index search with unified result handling
- **Best-in-class human search UX inside applications** -- Reference UI components for common search patterns
- **Autonomous search workflows for AI agents** -- Agents that use search as a tool with multi-step planning
- **Better/faster/cheaper search** -- Outperform conventional single-shot systems through iterative refinement
