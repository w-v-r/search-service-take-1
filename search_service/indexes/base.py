from __future__ import annotations

from typing import Any

from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import InteractionMode
from search_service.schemas.result import SearchResultEnvelope


class SearchIndex:
    """A configured search index that can execute searches.

    Created via `client.indexes.create(config)`. Holds the index
    configuration and provides the search API surface.
    """

    def __init__(self, config: IndexConfig) -> None:
        self._config = config

    @property
    def config(self) -> IndexConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._config.name

    def search(
        self,
        query: str,
        *,
        interaction_mode: InteractionMode | None = None,
    ) -> SearchResultEnvelope:
        """Execute a search query against this index.

        Args:
            query: The user's search query string.
            interaction_mode: Override the index's default interaction mode
                for this search. If None, uses the index's default.

        Returns:
            SearchResultEnvelope with status, results, and trace.
        """
        raise NotImplementedError(
            "Search pipeline not yet wired. "
            "The orchestration layer (analyzer -> planner -> executor -> evaluator) "
            "will be connected in a subsequent step."
        )

    def continue_search(
        self,
        trace_id: str,
        user_input: dict[str, Any],
    ) -> SearchResultEnvelope:
        """Continue a search that returned status='needs_input'.

        Resumes the search pipeline with the user's response to a
        follow-up request. The trace is preserved across continuations.

        Args:
            trace_id: The trace_id from the original SearchResultEnvelope.
            user_input: User's response matching the follow_up.input_schema.

        Returns:
            SearchResultEnvelope with updated status and results.
        """
        raise NotImplementedError(
            "Continue search not yet wired. "
            "The HITL continuation flow will be connected in a subsequent step."
        )

    def __repr__(self) -> str:
        return f"SearchIndex(name={self.name!r})"
