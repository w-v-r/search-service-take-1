"""Chroma backend adapter: filter translation, vector search, and full-text search.

ChromaDB stores each record as a single document string (used for embedding and
``$contains`` matching) plus a metadata dict. When building an index for this
adapter, the recommended pattern is:

- Store all structured fields in Chroma ``metadatas`` using the same names as
  your Pydantic ``document_schema``.
- Store the text you want to embed / search in Chroma ``documents`` (e.g., a
  concatenation of ``name`` and ``description``).
- If you want the adapter to copy the Chroma ``document`` string back into a
  specific schema field on retrieval, pass ``document_field="<field_name>"``.

Two retrieval modes are available, selected per ``ChromaAdapter`` instance:

``"vector"``
    Calls ``collection.query(query_texts=[query], ...)`` — the collection's
    embedding function converts the query to a vector and returns nearest
    neighbours ranked by similarity. Good for semantic / fuzzy queries.

``"full_text"``
    Calls ``collection.get(where_document=..., ...)`` — whitespace tokens in the
    query become ``$contains`` clauses ANDed together (substring match, **case-
    sensitive**, unlike ``InMemoryAdapter``). Good for exact-string lookups.

Both modes honour the same ``filters`` dict contract as ``InMemoryAdapter`` and
``TypesenseAdapter`` (scalar, list, and ``$gt``/``$gte``/``$lt``/``$lte``/
``$ne`` dict operators), translated into Chroma ``where`` metadata filters.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from search_service.adapters.base import BackendSearchRequest, BackendSearchResponse

try:
    from chromadb.api.models.Collection import Collection as ChromaCollection
except ImportError as _err:  # pragma: no cover
    raise ImportError(
        "chromadb is required for ChromaAdapter. "
        "Install it with: pip install 'search-harness[chroma]'"
    ) from _err


# ---------------------------------------------------------------------------
# Filter translation (orchestration dict -> Chroma where clause)
# ---------------------------------------------------------------------------

_PASSTHROUGH_OPERATORS = {"$gt", "$gte", "$lt", "$lte", "$ne"}


def filters_to_chroma_where(filters: dict[str, Any]) -> dict[str, Any] | None:
    """Translate orchestration filter dicts into a Chroma ``where`` clause.

    Supports the same shapes as :class:`~search_service.adapters.in_memory.InMemoryAdapter`:

    - Scalar: exact match — translated to ``{"field": {"$eq": value}}``.
    - ``list``: OR match — translated to ``{"field": {"$in": [a, b]}}``.
    - ``dict`` with ``$gt`` / ``$gte`` / ``$lt`` / ``$lte`` / ``$ne`` — passed
      through directly as Chroma natively supports these operators.

    Multiple top-level keys are combined with ``$and``.

    Raises:
        ValueError: If a dict-shaped condition uses unsupported operator keys,
            or is an empty dict.
    """
    if not filters:
        return None

    conditions: list[dict[str, Any]] = []

    for field, condition in filters.items():
        if isinstance(condition, dict):
            if not condition:
                raise ValueError(
                    f"Empty operator dict for filter field {field!r} is not supported."
                )
            unknown = [k for k in condition if k not in _PASSTHROUGH_OPERATORS]
            if unknown:
                raise ValueError(
                    f"Unknown filter operator key(s) for field {field!r}: {unknown}. "
                    f"Supported keys: {sorted(_PASSTHROUGH_OPERATORS)}."
                )
            conditions.append({field: condition})
        elif isinstance(condition, list):
            if not condition:
                continue
            conditions.append({field: {"$in": condition}})
        else:
            conditions.append({field: {"$eq": condition}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


# ---------------------------------------------------------------------------
# Full-text: build where_document from a query string
# ---------------------------------------------------------------------------


def _where_document_from_query(query: str) -> dict[str, Any] | None:
    """Build a Chroma ``where_document`` clause from a query string.

    Each whitespace-delimited token becomes a ``$contains`` condition; all
    tokens must be present (``$and`` semantics), mirroring how
    :class:`~search_service.adapters.in_memory.InMemoryAdapter` handles
    multi-token queries.

    Returns ``None`` for empty queries so that ``collection.get`` returns all
    documents (filter-only search), matching the "empty query matches all"
    contract used throughout the harness.

    Note: Chroma's ``$contains`` is **case-sensitive**, unlike
    ``InMemoryAdapter``'s case-insensitive substring matching.
    """
    tokens = query.split()
    if not tokens:
        return None
    if len(tokens) == 1:
        return {"$contains": tokens[0]}
    return {"$and": [{"$contains": t} for t in tokens]}


# ---------------------------------------------------------------------------
# Hit normalization
# ---------------------------------------------------------------------------


def _row_to_hit(
    id_: str,
    metadata: dict[str, Any] | None,
    document: str | None,
    id_field: str,
    document_field: str | None,
) -> dict[str, Any]:
    """Merge a Chroma row (id + metadata + document) into a flat hit dict."""
    hit: dict[str, Any] = dict(metadata or {})
    hit[id_field] = id_
    if document_field is not None and document is not None:
        hit[document_field] = document
    return hit


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ChromaAdapter:
    """Chroma implementation of :class:`~search_service.adapters.base.SearchAdapter`.

    Parameters
    ----------
    collection:
        A configured ``chromadb.Collection`` instance. The collection must
        already exist and be populated before calling ``search``.
    searchable_fields:
        Field names from the index schema used for display and
        :class:`~search_service.adapters.base.BackendSearchRequest` routing.
        Not used for query routing inside this adapter (Chroma embeds the
        ``document`` string directly).
    id_field:
        Name of the primary key field in your schema. Chroma ``ids`` are mapped
        to this key in every returned hit dict.
    mode:
        ``"vector"`` (default) — semantic nearest-neighbour search using the
        collection's embedding function.
        ``"full_text"`` — document substring search via Chroma's
        ``where_document`` / ``$contains`` (case-sensitive).
    document_field:
        If set, the Chroma ``document`` string is copied into this key in every
        returned hit dict. Useful when your schema has a field that mirrors the
        text you stored in Chroma's ``document``.
    """

    def __init__(
        self,
        collection: ChromaCollection,
        searchable_fields: list[str],
        id_field: str,
        mode: Literal["vector", "full_text"] = "vector",
        document_field: str | None = None,
    ) -> None:
        self._collection = collection
        self._searchable_fields = list(searchable_fields)
        self._id_field = id_field
        self._mode: Literal["vector", "full_text"] = mode
        self._document_field = document_field

    @property
    def collection(self) -> ChromaCollection:
        return self._collection

    @property
    def mode(self) -> Literal["vector", "full_text"]:
        return self._mode

    def search(self, request: BackendSearchRequest) -> BackendSearchResponse:
        """Route to the correct retrieval strategy based on ``mode``."""
        if self._mode == "vector":
            return self._vector_search(request)
        return self._full_text_search(request)

    # ------------------------------------------------------------------
    # Vector mode
    # ------------------------------------------------------------------

    def _vector_search(self, request: BackendSearchRequest) -> BackendSearchResponse:
        """Semantic search via ``collection.query``.

        Uses the collection's embedding function to embed ``request.query``,
        fetches ``offset + limit`` nearest neighbours, then slices from
        ``offset``. Metadata filters are applied as a Chroma ``where`` clause.

        For empty queries, falls back to ``collection.get`` (returns documents
        in insertion order, subject to filters).

        ``total_count`` is set to ``collection.count()`` — the total number of
        records in the collection — because vector search ranks *all* documents
        and there is no meaningful "total matching" count to report.
        """
        start = time.perf_counter()
        where = filters_to_chroma_where(request.filters)

        if not request.query.strip():
            return self._get_all(request, start=start, mode_label="vector_empty_query")

        n_results = request.offset + request.limit
        query_kwargs: dict[str, Any] = {
            "query_texts": [request.query],
            "n_results": n_results,
            "include": ["metadatas", "documents"],
        }
        if where:
            query_kwargs["where"] = where

        result = self._collection.query(**query_kwargs)

        # Chroma returns one list per query; we send exactly one query text.
        ids: list[str] = result["ids"][0]
        metadatas: list[dict[str, Any] | None] = (result.get("metadatas") or [[]])[0]
        documents: list[str | None] = (result.get("documents") or [[]])[0]

        ids = ids[request.offset :]
        metadatas = metadatas[request.offset :]
        documents = documents[request.offset :]

        hits = [
            _row_to_hit(id_, meta, doc, self._id_field, self._document_field)
            for id_, meta, doc in zip(ids, metadatas, documents)
        ]

        elapsed_ms = (time.perf_counter() - start) * 1000
        return BackendSearchResponse(
            hits=hits,
            total_count=self._collection.count(),
            query_time_ms=round(elapsed_ms, 3),
            raw_response={
                "mode": "vector",
                "n_results_requested": n_results,
                "collection": self._collection.name,
            },
        )

    # ------------------------------------------------------------------
    # Full-text mode
    # ------------------------------------------------------------------

    def _full_text_search(self, request: BackendSearchRequest) -> BackendSearchResponse:
        """Substring search via ``collection.get`` and ``where_document``.

        Translates whitespace-delimited tokens into ``$contains`` conditions
        (ANDed). Metadata filters are applied via ``where``. Pagination is
        handled through Chroma's native ``limit`` / ``offset`` on ``get``.

        ``total_count`` accuracy:

        - No query and no filters: exact, from ``collection.count()``.
        - Metadata filters only (no content query): exact, from a lightweight
          ``get(..., include=[])`` count call.
        - Content query (``where_document`` involved): set to ``len(hits)``
          (i.e., the returned page size). An exact count would require a second
          full-scan call, which is deferred to a future version.
        """
        start = time.perf_counter()
        where = filters_to_chroma_where(request.filters)
        where_doc = _where_document_from_query(request.query)

        get_kwargs: dict[str, Any] = {
            "limit": request.limit,
            "offset": request.offset,
            "include": ["metadatas", "documents"],
        }
        if where:
            get_kwargs["where"] = where
        if where_doc:
            get_kwargs["where_document"] = where_doc

        result = self._collection.get(**get_kwargs)

        ids: list[str] = result["ids"]
        metadatas: list[dict[str, Any] | None] = result.get("metadatas") or [None] * len(ids)
        documents: list[str | None] = result.get("documents") or [None] * len(ids)

        hits = [
            _row_to_hit(id_, meta, doc, self._id_field, self._document_field)
            for id_, meta, doc in zip(ids, metadatas, documents)
        ]

        total_count = self._compute_full_text_total(where, where_doc, fallback=len(hits))

        elapsed_ms = (time.perf_counter() - start) * 1000
        return BackendSearchResponse(
            hits=hits,
            total_count=total_count,
            query_time_ms=round(elapsed_ms, 3),
            raw_response={
                "mode": "full_text",
                "has_where_document": where_doc is not None,
                "collection": self._collection.name,
            },
        )

    def _compute_full_text_total(
        self,
        where: dict[str, Any] | None,
        where_doc: dict[str, Any] | None,
        *,
        fallback: int,
    ) -> int:
        """Compute total matching count for full-text mode.

        Uses a lightweight ``include=[]`` get call when only metadata filters
        are present. Falls back to ``fallback`` (page size) when
        ``where_document`` is involved, because an accurate count would require
        a full content-scan call.
        """
        if where_doc is not None:
            return fallback
        if where is None:
            return self._collection.count()
        count_result = self._collection.get(where=where, include=[])
        return len(count_result["ids"])

    # ------------------------------------------------------------------
    # Shared helper for empty-query vector fallback
    # ------------------------------------------------------------------

    def _get_all(
        self,
        request: BackendSearchRequest,
        *,
        start: float,
        mode_label: str,
    ) -> BackendSearchResponse:
        """Fallback for empty queries: return documents in insertion order."""
        where = filters_to_chroma_where(request.filters)
        get_kwargs: dict[str, Any] = {
            "limit": request.limit,
            "offset": request.offset,
            "include": ["metadatas", "documents"],
        }
        if where:
            get_kwargs["where"] = where

        result = self._collection.get(**get_kwargs)
        ids: list[str] = result["ids"]
        metadatas: list[dict[str, Any] | None] = result.get("metadatas") or [None] * len(ids)
        documents: list[str | None] = result.get("documents") or [None] * len(ids)

        hits = [
            _row_to_hit(id_, meta, doc, self._id_field, self._document_field)
            for id_, meta, doc in zip(ids, metadatas, documents)
        ]

        total_count = self._compute_full_text_total(where, None, fallback=len(hits))
        elapsed_ms = (time.perf_counter() - start) * 1000

        return BackendSearchResponse(
            hits=hits,
            total_count=total_count,
            query_time_ms=round(elapsed_ms, 3),
            raw_response={"mode": mode_label, "collection": self._collection.name},
        )
