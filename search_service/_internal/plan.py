from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from search_service._internal.enums import PlanAction
from search_service.schemas.enums import BranchKind


@dataclass
class PlannedBranch:
    """A single branch in a search plan.

    Carries provenance so the original query is explicitly
    represented from plan creation, not implicitly "the first
    item in a list."
    """

    kind: BranchKind
    """How this branch relates to the original query."""

    query: str
    """The query string for this branch."""

    filters: dict[str, Any] = field(default_factory=dict)
    """Filters to apply for this branch. Each branch carries its
    own filters -- there are no "global" plan-level filters."""


@dataclass
class SearchPlan:
    """Output of the planner. Specifies what search action(s) to execute.

    The unit of planning is the branch, not the query string. Each planned
    branch carries its own provenance (kind), query, and filters.
    """

    action: PlanAction
    """The chosen action for this planning step."""

    branches: list[PlannedBranch]
    """Branches to execute. For direct_search or search_with_filters,
    contains one branch. For multi_branch, contains one branch per
    search path. The original_query branch is always present."""

    reasoning: str | None = None
    """Human-readable explanation of why this plan was chosen.
    Included in the trace for debugging."""
