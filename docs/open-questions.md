# Open Questions

These areas are deliberately left flexible in the v0 codebase. They should remain configurable rather than prematurely fixed.

## 1. Exact Prompt Templates

The LLM prompts for classification, extraction, planning, and follow-up generation are not locked down. v0 will ship with working defaults, but the prompt strategy should be easy to swap and iterate on.

## 2. Confidence Scoring Strategy

How confidence scores are computed for ambiguity detection, result quality assessment, and branch comparison is not finalized. v0 will use simple heuristics; a calibrated model may replace them later.

## 3. Branch Merge Strategy

When AITL runs multiple branches, how results are merged (interleaved, ranked, deduplicated) is underspecified. v0 will use a simple concatenation/dedup approach.

## 4. Query Classification Taxonomy

The set of query types (entity_lookup, document_lookup, catalog_lookup, etc.) is not closed. v0 will ship with a small taxonomy that covers the hero use cases; it should be extensible.

## 5. Search Profiles as Code vs Config

Whether search profiles (expected intents, ambiguity rules, default filters) are defined in Python code or in a configuration file/format is an open decision. v0 will use code-defined profiles.

## 6. Dynamic Follow-Up Schema Approach

Whether dynamic follow-up schemas use a library like dydantic directly or a custom schema builder abstraction is not decided. v0 will experiment and pick the simpler path.

## 7. Backend Query DSL Translation Model

The exact model for translating a generic search plan into backend-native query DSL (Typesense multi_search, Elasticsearch query DSL, SQL) is underspecified. The adapter protocol defines the boundary, but the internal translation strategy may evolve.
