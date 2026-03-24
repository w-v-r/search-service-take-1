"""Structured follow-up generation for HITL `needs_input` responses."""

from __future__ import annotations

from typing import Any, Literal

from search_service._internal.context import SearchContext
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import AmbiguityLevel
from search_service.schemas.followup import Candidate, FollowUpRequest
from search_service.schemas.query import QueryAnalysis

TerminationSource = Literal["planner_clarification", "evaluator_ambiguity"]


def merge_continuation_input(
    context: SearchContext,
    user_input: dict[str, Any],
) -> None:
    """Merge user follow-up into context: filters, ambiguity, and user_input map."""
    context.user_input.update(user_input)
    cfg = context.index_config
    analysis = context.query_analysis

    for key, value in user_input.items():
        if key in cfg.filterable_fields or (
            analysis is not None and key in analysis.missing_fields
        ):
            context.unapplied_filters[key] = value

    if analysis is None:
        return

    missing = set(analysis.missing_fields)
    if missing and missing <= set(context.user_input.keys()):
        analysis.ambiguity = AmbiguityLevel.low


def build_follow_up_request(
    context: SearchContext,
    *,
    source: TerminationSource,
) -> FollowUpRequest:
    """Build a FollowUpRequest from current harness state."""
    analysis = context.query_analysis
    cfg = context.index_config

    if source == "planner_clarification":
        reason = "missing_required_filter"
        if analysis and analysis.ambiguity in (AmbiguityLevel.high, AmbiguityLevel.medium):
            reason = "ambiguous_entity"
        message = _planner_message(analysis)
    else:
        reason = "ambiguous_entity"
        message = (
            "The search could not proceed with enough confidence. "
            "Please narrow your query or provide additional detail."
        )

    schema = _build_input_schema(cfg, analysis)
    candidates = _build_candidates(analysis)

    return FollowUpRequest(
        reason=reason,
        message=message,
        input_schema=schema,
        candidates=candidates,
    )


def _planner_message(analysis: QueryAnalysis | None) -> str:
    if analysis is None:
        return "More information is needed before searching."
    missing = analysis.missing_fields
    if missing:
        fields = ", ".join(missing)
        return (
            f"The query needs clarification. Please provide values for: {fields}."
        )
    return (
        "Your query is ambiguous or underspecified. "
        "Please choose how to proceed or add missing details."
    )


def _build_input_schema(
    cfg: IndexConfig,
    analysis: QueryAnalysis | None,
) -> dict[str, Any]:
    """JSON Schema for the application's follow-up form."""
    policy = cfg.policy
    properties: dict[str, Any] = {}
    required: list[str] = []

    keys: list[str] = []
    if analysis and analysis.missing_fields:
        keys.extend(analysis.missing_fields)
    for f in cfg.filterable_fields:
        if f not in keys:
            keys.append(f)

    for field in keys:
        prop: dict[str, Any] = {"type": "string"}
        if field in policy.canonical_filters:
            prop["enum"] = list(policy.canonical_filters[field])
        properties[field] = prop

    if analysis and analysis.missing_fields:
        required = list(dict.fromkeys(analysis.missing_fields))

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def _build_candidates(analysis: QueryAnalysis | None) -> list[Candidate]:
    if analysis is None:
        return []

    out: list[Candidate] = []
    subject = analysis.primary_subject or analysis.raw_query
    for i, rt in enumerate(analysis.possible_resource_types):
        conf = max(0.1, 0.75 - i * 0.12)
        out.append(
            Candidate(
                label=f"{subject} — {rt}",
                confidence=round(min(1.0, conf), 2),
            ),
        )

    for ent in analysis.extracted_entities[:5]:
        if ent.confidence is not None:
            out.append(
                Candidate(
                    label=f"{ent.value} ({ent.entity_type or 'entity'})",
                    confidence=round(ent.confidence, 2),
                ),
            )

    return out[:10]
