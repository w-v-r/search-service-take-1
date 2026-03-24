from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from search_service._internal.enums import EvaluatorAction
from search_service.schemas.config import IndexConfig, SearchPolicy
from search_service.schemas.enums import InteractionMode
from search_service.schemas.query import QueryAnalysis
from search_service.schemas.result import BranchResult


@dataclass
class SearchContext:
    """Mutable runtime state passed through the orchestration pipeline.

    Accumulates state across iterations. This is an internal model
    that the developer never sees through the SDK surface.
    """

    index_config: IndexConfig
    interaction_mode: InteractionMode
    policy: SearchPolicy

    iterations_used: int = 0
    branches_used: int = 0

    query_analysis: QueryAnalysis | None = None
    branches: list[BranchResult] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    unapplied_filters: dict[str, Any] = field(default_factory=dict)
    user_input: dict[str, Any] = field(default_factory=dict)
    reformulation_attempted: bool = False
    """Set after a reformulated branch is executed; prevents duplicate reformulation."""

    @property
    def iterations_remaining(self) -> int:
        return max(0, self.policy.max_iterations - self.iterations_used)

    @property
    def branches_remaining(self) -> int:
        return max(0, self.policy.max_branches - self.branches_used)

    @property
    def budget_exhausted(self) -> bool:
        return self.iterations_remaining == 0

    @property
    def at_final_iteration(self) -> bool:
        return self.iterations_remaining == 1

    @property
    def can_branch(self) -> bool:
        return self.branches_remaining > 0


@dataclass
class NextAction:
    """Output of the evaluator. Determines what happens next in the pipeline."""

    action: EvaluatorAction
    reason: str
    updated_context: dict[str, Any] = field(default_factory=dict)
