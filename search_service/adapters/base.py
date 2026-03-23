from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class BackendSearchRequest(BaseModel):
    """Request sent from the orchestration layer to a backend adapter."""

    query: str
    """Search query string to send to the backend."""

    filters: dict[str, Any] = {}
    """Structured filters to apply. The adapter translates these
    into backend-native filter syntax."""

    fields: list[str] = []
    """Fields to search against. If empty, the adapter uses
    the index's searchable_fields."""

    limit: int = Field(default=20, ge=1, le=250)
    """Maximum results to return."""

    offset: int = Field(default=0, ge=0)
    """Pagination offset."""


class BackendSearchResponse(BaseModel):
    """Response returned from a backend adapter to the orchestration layer."""

    hits: list[dict[str, Any]] = []
    """Raw result documents from the backend."""

    total_count: int = 0
    """Total number of matching documents in the backend
    (may exceed len(hits) due to pagination)."""

    query_time_ms: float | None = None
    """Backend-reported query execution time."""

    raw_response: dict[str, Any] = {}
    """Full raw response from the backend for debugging."""


@runtime_checkable
class SearchAdapter(Protocol):
    """Protocol that all backend adapters must implement.

    The adapter boundary is mandatory -- all backend communication
    goes through this protocol. This keeps the orchestration layer
    backend-agnostic and makes testing trivial via in-memory adapters.
    """

    def search(self, request: BackendSearchRequest) -> BackendSearchResponse: ...
