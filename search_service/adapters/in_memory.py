from __future__ import annotations

import time
from typing import Any

from search_service.adapters.base import (
    BackendSearchRequest,
    BackendSearchResponse,
)


class InMemoryAdapter:
    """Full working in-memory adapter for testing.

    Supports keyword matching across specified fields and
    structured filtering with exact-match, list-in, and
    comparison operators.

    Documents are stored as plain dicts. This adapter is
    deliberately simple -- it exists so the entire orchestration
    pipeline can be tested without a real backend.

    Usage::

        adapter = InMemoryAdapter(
            documents=[
                {"id": "1", "name": "Telstra", "country": "AU"},
                {"id": "2", "name": "Optus", "country": "AU"},
            ],
            searchable_fields=["name"],
        )
        response = adapter.search(BackendSearchRequest(query="Telstra"))
    """

    def __init__(
        self,
        documents: list[dict[str, Any]] | None = None,
        searchable_fields: list[str] | None = None,
    ) -> None:
        self._documents: list[dict[str, Any]] = list(documents or [])
        self._searchable_fields: list[str] = list(searchable_fields or [])

    @property
    def documents(self) -> list[dict[str, Any]]:
        return self._documents

    def add_documents(self, documents: list[dict[str, Any]]) -> None:
        """Append documents to the store."""
        self._documents.extend(documents)

    def clear(self) -> None:
        """Remove all documents."""
        self._documents.clear()

    def search(self, request: BackendSearchRequest) -> BackendSearchResponse:
        start = time.perf_counter()

        fields = request.fields or self._searchable_fields
        matched = self._keyword_match(request.query, fields)
        filtered = self._apply_filters(matched, request.filters)
        total_count = len(filtered)

        page = filtered[request.offset : request.offset + request.limit]

        elapsed_ms = (time.perf_counter() - start) * 1000

        return BackendSearchResponse(
            hits=page,
            total_count=total_count,
            query_time_ms=round(elapsed_ms, 3),
            raw_response={
                "matched_before_filters": len(matched),
                "matched_after_filters": total_count,
                "offset": request.offset,
                "limit": request.limit,
            },
        )

    def _keyword_match(
        self,
        query: str,
        fields: list[str],
    ) -> list[dict[str, Any]]:
        """Case-insensitive substring matching across specified fields.

        An empty query matches all documents (useful for filter-only searches).
        Each whitespace-delimited token must appear in at least one field
        for the document to match.
        """
        if not query.strip():
            return list(self._documents)

        tokens = query.lower().split()
        results: list[dict[str, Any]] = []

        for doc in self._documents:
            if _doc_matches_tokens(doc, tokens, fields):
                results.append(doc)

        return results

    def _apply_filters(
        self,
        documents: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not filters:
            return documents

        return [doc for doc in documents if _doc_matches_filters(doc, filters)]


def _doc_matches_tokens(
    doc: dict[str, Any],
    tokens: list[str],
    fields: list[str],
) -> bool:
    """Return True if every token appears in at least one searchable field."""
    for token in tokens:
        found = False
        for field_name in fields:
            value = doc.get(field_name)
            if value is None:
                continue
            if token in str(value).lower():
                found = True
                break
        if not found:
            return False
    return True


def _doc_matches_filters(
    doc: dict[str, Any],
    filters: dict[str, Any],
) -> bool:
    """Return True if the document satisfies all filter conditions.

    Supported filter value types:
      - scalar (str, int, float, bool): exact match
      - list: document value must be in the list (OR semantics)
      - dict with operators: {"$gt": v, "$gte": v, "$lt": v, "$lte": v, "$ne": v}
    """
    for field_name, condition in filters.items():
        doc_value = doc.get(field_name)

        if isinstance(condition, dict):
            if not _apply_operator_filter(doc_value, condition):
                return False
        elif isinstance(condition, list):
            if doc_value not in condition:
                return False
        else:
            if doc_value != condition:
                return False

    return True


def _apply_operator_filter(doc_value: Any, operators: dict[str, Any]) -> bool:
    """Apply comparison operators against a document value."""
    for op, target in operators.items():
        if doc_value is None:
            return False
        if op == "$gt" and not (doc_value > target):
            return False
        if op == "$gte" and not (doc_value >= target):
            return False
        if op == "$lt" and not (doc_value < target):
            return False
        if op == "$lte" and not (doc_value <= target):
            return False
        if op == "$ne" and doc_value == target:
            return False
    return True
