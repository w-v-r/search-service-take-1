from enum import StrEnum


class PlanAction(StrEnum):
    """The four actions the planner can choose.

    In AITL mode, the priority order is:
    stop and return > apply filters > branch > escalate.
    """

    direct_search = "direct_search"
    search_with_filters = "search_with_filters"
    multi_branch = "multi_branch"
    reformulated_search = "reformulated_search"
    needs_clarification = "needs_clarification"


class EvaluatorAction(StrEnum):
    """The three outcomes the evaluator can produce.

    `completed` and `needs_input` terminate the loop and map to
    SearchStatus values. `iterate` sends control back to the
    planner with updated context.
    """

    completed = "completed"
    needs_input = "needs_input"
    iterate = "iterate"
