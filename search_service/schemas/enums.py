from enum import StrEnum


class SearchStatus(StrEnum):
    completed = "completed"
    needs_input = "needs_input"
    partial = "partial"
    failed = "failed"


class InteractionMode(StrEnum):
    hitl = "hitl"
    aitl = "aitl"


class AmbiguityLevel(StrEnum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class BranchKind(StrEnum):
    original_query = "original_query"
    filter_augmented = "filter_augmented"
    reformulated = "reformulated"


class TraceStepType(StrEnum):
    query_received = "query_received"
    query_analysis = "query_analysis"
    classification = "classification"
    extraction = "extraction"
    planning = "planning"
    search_execution = "search_execution"
    evaluation = "evaluation"
    follow_up_generation = "follow_up_generation"
    branch_created = "branch_created"
    branch_merge = "branch_merge"
    budget_check = "budget_check"
    decision = "decision"
