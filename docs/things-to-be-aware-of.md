# Things to be aware of

- Separation of concerns: `SearchContext` lives in `_search_sessions` on `SearchClient`; the tracer stays observability-only. That matches the plan.

- Planner ordering: Applying **`unapplied_filters` before `_should_clarify`** is important for continuation; without it, HITL would keep asking for clarification after the user answered.

- Same trace: `continue_orchestrated_search` reuses the existing `SearchTrace`, clears `final_status` so steps can append, and records a **continuation** decision step before the loop.

- Contracts: `needs_input` now carries **`follow_up`** and a **`follow_up_generation`** trace step, which matches `docs/contracts.md` expectations.

- Sessions are keyed only by **`trace_id`**. `continue_search` uses the **`SearchIndex`’s `IndexConfig`** for `execute_plan`, while **`SearchContext.index_config`** is whatever was stored at first search. In normal use (same index, same client) they match. If someone called **`continue_search` on a different index** than the one that produced `trace_id`, you could get inconsistent adapter/config vs context. A follow-up hardening would be to store **`index_name`** (or validate `context.index_config.name` against the index handling continuation).

- On continuation, **`latency_ms`** (and trace **`total_latency_ms`**) reflect **that continuation run only**, not time since the original `search`. That’s reasonable for “this request’s cost” but not for “whole HITL session.” Worth documenting if product cares about end-to-end session latency.

- **`iterations_used` / `branches_used` are reset to 0** on each continuation, so each follow-up gets a **full policy budget** again. That’s a product choice (generous UX) vs strict “single combined budget” for the whole session.

- Sessions are **removed** when the run finishes with **`completed`** (or **`failed`** via `_sync_session_store`). If the app **never** calls `continue_search` after `needs_input`, the **`SearchContext` stays in memory** until process exit. Production code may want TTL, explicit discard, or size limits.

- The **`evaluator_ambiguity`** path always uses **`reason="ambiguous_entity"`** and a generic message, even when the real issue is confidence thresholds. Fine for v0; richer reasons could come later.
