class SearchServiceError(Exception):
    """Base exception for all search service errors."""


class IndexNotFoundError(SearchServiceError):
    """Raised when attempting to access an index that does not exist."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Index '{name}' not found")


class IndexAlreadyExistsError(SearchServiceError):
    """Raised when attempting to create an index with a name that already exists."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Index '{name}' already exists")


class ConfigurationError(SearchServiceError):
    """Raised when an IndexConfig or SearchPolicy is invalid."""


class AdapterError(SearchServiceError):
    """Raised when a backend adapter encounters an error during search execution."""


class SearchExecutionError(SearchServiceError):
    """Raised when the search pipeline fails during execution."""


class TraceNotFoundError(SearchServiceError):
    """Raised when a trace_id cannot be resolved for continue_search."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        super().__init__(f"Trace '{trace_id}' not found")
