"""AITL context snapshots for planning and evaluation.

The AITL loop uses three concrete context categories (see docs/aitl.md):
instructions (static), self-knowledge (dynamic), and problem state (accumulated).
These structures are attached to trace payloads for observability only.
"""

from __future__ import annotations

from typing import Any

from search_service._internal.context import SearchContext
from search_service.schemas.enums import BranchKind, InteractionMode


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def resolve_raw_query(context: SearchContext) -> str:
    if context.query_analysis is not None:
        return context.query_analysis.raw_query
    return ""


def has_equivalent_original_branch(context: SearchContext, query: str) -> bool:
    """True if we already ran an original_query branch with the same text and no filters."""
    nq = _norm(query)
    if not nq:
        return False
    for b in context.branches:
        if b.kind != BranchKind.original_query:
            continue
        if b.filters:
            continue
        if _norm(b.query) == nq:
            return True
    return False


def can_reformulate_branch(context: SearchContext) -> bool:
    """True if a reformulation branch is allowed and not yet tried."""
    if context.interaction_mode != InteractionMode.aitl:
        return False
    if context.reformulation_attempted:
        return False
    if any(b.kind == BranchKind.reformulated for b in context.branches):
        return False
    if not context.can_branch:
        return False
    analysis = context.query_analysis
    if analysis is None or not analysis.primary_subject:
        return False
    raw = _norm(analysis.raw_query)
    sub = _norm(analysis.primary_subject)
    if not sub or sub == raw:
        return False

    has_original = has_equivalent_original_branch(context, analysis.raw_query)
    if not has_original and context.at_final_iteration:
        # Need a baseline original search first; never reformulation-only here.
        return False
    return True


def would_repeat_redundant_direct(context: SearchContext, query: str) -> bool:
    """True if the next plain direct search would duplicate an already-run baseline."""
    if context.unapplied_filters:
        return False
    if has_equivalent_original_branch(context, query):
        return True
    if "direct_search" in context.actions_taken:
        return True
    return False


def current_navigation_state(context: SearchContext) -> str:
    """Coarse label for self-knowledge: where we are in the budget loop."""
    if context.budget_exhausted:
        return "budget_exhausted"
    if context.at_final_iteration:
        return "at_final_iteration"
    if context.iterations_remaining <= 1:
        return "approaching_budget_limit"
    if context.iterations_used <= 1:
        return "early_iteration"
    return "mid_iteration"


def build_instructions_snapshot(context: SearchContext) -> dict[str, Any]:
    cfg = context.index_config
    th = context.policy.confidence_thresholds
    return {
        "interaction_mode": context.interaction_mode.value,
        "max_iterations": context.policy.max_iterations,
        "max_branches": context.policy.max_branches,
        "confidence_thresholds": {
            "stop": th.stop,
            "escalate": th.escalate,
            "ambiguity": th.ambiguity,
        },
        "index_name": cfg.name,
        "expected_query_types": list(cfg.expected_query_types),
        "entity_types": list(cfg.entity_types),
    }


def build_self_knowledge_snapshot(context: SearchContext) -> dict[str, Any]:
    return {
        "iterations_used": context.iterations_used,
        "iterations_remaining": context.iterations_remaining,
        "branches_used": context.branches_used,
        "branches_remaining": context.branches_remaining,
        "budget_exhausted": context.budget_exhausted,
        "at_final_iteration": context.at_final_iteration,
        "actions_taken": list(context.actions_taken),
        "current_state": current_navigation_state(context),
    }


def build_problem_state_snapshot(
    context: SearchContext,
    *,
    query: str,
) -> dict[str, Any]:
    analysis = context.query_analysis
    total_hits = sum(len(b.results) for b in context.branches)
    state: dict[str, Any] = {
        "original_query": query,
        "accumulated_result_items": total_hits,
        "unapplied_filter_keys": sorted(context.unapplied_filters.keys()),
        "reformulation_attempted": context.reformulation_attempted,
    }
    if analysis is not None:
        state["query_type"] = analysis.query_type
        state["ambiguity"] = analysis.ambiguity.value
        state["primary_subject"] = analysis.primary_subject
        state["missing_fields"] = list(analysis.missing_fields)
    return state


def build_aitl_context(
    context: SearchContext,
    *,
    query: str,
) -> dict[str, Any]:
    """Full three-part snapshot for trace payloads (AITL and HITL)."""
    return {
        "instructions": build_instructions_snapshot(context),
        "self_knowledge": build_self_knowledge_snapshot(context),
        "problem_state": build_problem_state_snapshot(context, query=query),
    }


def has_actionable_next_step(context: SearchContext, query: str) -> bool:
    """Whether another iteration could improve results (AITL) or apply filters (both modes)."""
    if context.unapplied_filters:
        return True
    if context.interaction_mode != InteractionMode.aitl:
        return False
    if can_reformulate_branch(context):
        return True
    if would_repeat_redundant_direct(context, query):
        return False
    return False
