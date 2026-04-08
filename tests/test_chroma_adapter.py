"""Unit tests for the Chroma adapter: filter translation, both search modes, and hit normalization.

All tests use a Chroma ``EphemeralClient`` with a stub embedding function so no
model files are downloaded and the test suite runs fully offline.
"""

from __future__ import annotations

import uuid

import chromadb
import pytest
from chromadb.api.types import Documents, Embeddings
from chromadb.utils.embedding_functions import EmbeddingFunction
from pydantic import BaseModel

from search_service.adapters.base import BackendSearchRequest, SearchAdapter
from search_service.adapters.chroma import (
    ChromaAdapter,
    _where_document_from_query,
    filters_to_chroma_where,
)
from search_service.schemas.config import IndexConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _StubEF(EmbeddingFunction):
    """Deterministic stub embedding function — avoids any model download."""

    def __init__(self) -> None:
        pass

    def name(self) -> str:
        return "stub_ef"

    def get_config(self) -> dict:  # type: ignore[override]
        return {}

    def __call__(self, input: Documents) -> Embeddings:
        return [[float(i) for i in range(4)] for _ in input]


_DOCS = [
    {
        "id": "1",
        "name": "Acme Corp",
        "country": "AU",
        "revenue": 5000,
        "document": "Acme Corp Australian company",
    },
    {
        "id": "2",
        "name": "Globex",
        "country": "US",
        "revenue": 8000,
        "document": "Globex United States firm",
    },
    {
        "id": "3",
        "name": "Initech",
        "country": "AU",
        "revenue": 2000,
        "document": "Initech Australian startup",
    },
]


def _make_collection(name: str | None = None) -> chromadb.Collection:
    """Create a fresh EphemeralClient collection pre-populated with _DOCS.

    A unique name is generated per call so tests do not collide even when
    running against the same Chroma process state.
    """
    col_name = name or f"companies_{uuid.uuid4().hex}"
    client = chromadb.EphemeralClient()
    col = client.create_collection(col_name, embedding_function=_StubEF())
    col.add(
        ids=[d["id"] for d in _DOCS],
        documents=[d["document"] for d in _DOCS],
        metadatas=[{k: v for k, v in d.items() if k not in ("id", "document")} for d in _DOCS],
    )
    return col


def _make_adapter(
    mode: str = "vector",
    document_field: str | None = None,
) -> ChromaAdapter:
    col = _make_collection()
    return ChromaAdapter(
        collection=col,
        searchable_fields=["name"],
        id_field="id",
        mode=mode,  # type: ignore[arg-type]
        document_field=document_field,
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_is_search_adapter(self) -> None:
        adapter = _make_adapter()
        assert isinstance(adapter, SearchAdapter)


# ---------------------------------------------------------------------------
# filters_to_chroma_where
# ---------------------------------------------------------------------------


class TestFiltersToChromaWhere:
    def test_empty_returns_none(self) -> None:
        assert filters_to_chroma_where({}) is None

    def test_scalar_string(self) -> None:
        result = filters_to_chroma_where({"country": "AU"})
        assert result == {"country": {"$eq": "AU"}}

    def test_scalar_int(self) -> None:
        result = filters_to_chroma_where({"revenue": 5000})
        assert result == {"revenue": {"$eq": 5000}}

    def test_scalar_bool(self) -> None:
        result = filters_to_chroma_where({"active": True})
        assert result == {"active": {"$eq": True}}

    def test_list_becomes_in(self) -> None:
        result = filters_to_chroma_where({"country": ["AU", "US"]})
        assert result == {"country": {"$in": ["AU", "US"]}}

    def test_empty_list_skipped(self) -> None:
        result = filters_to_chroma_where({"country": []})
        assert result is None

    def test_gt_operator(self) -> None:
        result = filters_to_chroma_where({"revenue": {"$gt": 1000}})
        assert result == {"revenue": {"$gt": 1000}}

    def test_gte_operator(self) -> None:
        result = filters_to_chroma_where({"revenue": {"$gte": 5000}})
        assert result == {"revenue": {"$gte": 5000}}

    def test_lt_operator(self) -> None:
        result = filters_to_chroma_where({"revenue": {"$lt": 3000}})
        assert result == {"revenue": {"$lt": 3000}}

    def test_lte_operator(self) -> None:
        result = filters_to_chroma_where({"revenue": {"$lte": 8000}})
        assert result == {"revenue": {"$lte": 8000}}

    def test_ne_operator(self) -> None:
        result = filters_to_chroma_where({"country": {"$ne": "US"}})
        assert result == {"country": {"$ne": "US"}}

    def test_multiple_fields_wrapped_in_and(self) -> None:
        result = filters_to_chroma_where({"country": "AU", "revenue": {"$gt": 1000}})
        assert result is not None
        assert "$and" in result
        conditions = result["$and"]
        assert {"country": {"$eq": "AU"}} in conditions
        assert {"revenue": {"$gt": 1000}} in conditions

    def test_single_field_not_wrapped(self) -> None:
        result = filters_to_chroma_where({"country": "AU"})
        assert "$and" not in (result or {})

    def test_unknown_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown filter operator"):
            filters_to_chroma_where({"revenue": {"$gt": 1, "$bogus": 2}})

    def test_empty_operator_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty operator dict"):
            filters_to_chroma_where({"revenue": {}})


# ---------------------------------------------------------------------------
# _where_document_from_query
# ---------------------------------------------------------------------------


class TestWhereDocumentFromQuery:
    def test_empty_query_returns_none(self) -> None:
        assert _where_document_from_query("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _where_document_from_query("   ") is None

    def test_single_token(self) -> None:
        assert _where_document_from_query("hello") == {"$contains": "hello"}

    def test_multi_token_ands(self) -> None:
        result = _where_document_from_query("hello world")
        assert result == {"$and": [{"$contains": "hello"}, {"$contains": "world"}]}


# ---------------------------------------------------------------------------
# ChromaAdapter — vector mode
# ---------------------------------------------------------------------------


class TestVectorMode:
    def test_returns_hits(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        assert len(response.hits) > 0

    def test_hit_has_id_field(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        for hit in response.hits:
            assert "id" in hit

    def test_hit_includes_metadata(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        assert any("country" in hit for hit in response.hits)

    def test_document_field_populated_when_set(self) -> None:
        adapter = _make_adapter(mode="vector", document_field="document")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        assert all("document" in hit for hit in response.hits)

    def test_total_count_is_collection_size(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="anything"))
        assert response.total_count == 3

    def test_limit_respected(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="company", limit=2))
        assert len(response.hits) <= 2

    def test_offset_slices_results(self) -> None:
        adapter = _make_adapter(mode="vector")
        all_results = adapter.search(BackendSearchRequest(query="company", limit=3))
        offset_results = adapter.search(BackendSearchRequest(query="company", limit=3, offset=1))
        assert len(offset_results.hits) <= len(all_results.hits)

    def test_metadata_filter_applied(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(
            BackendSearchRequest(query="company", filters={"country": "AU"})
        )
        for hit in response.hits:
            assert hit.get("country") == "AU"

    def test_empty_query_returns_all(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="", limit=10))
        assert len(response.hits) == 3

    def test_query_time_ms_present(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        assert response.query_time_ms is not None
        assert response.query_time_ms >= 0

    def test_raw_response_has_mode(self) -> None:
        adapter = _make_adapter(mode="vector")
        response = adapter.search(BackendSearchRequest(query="Acme"))
        assert response.raw_response.get("mode") in ("vector", "vector_empty_query")


# ---------------------------------------------------------------------------
# ChromaAdapter — full_text mode
# ---------------------------------------------------------------------------


class TestFullTextMode:
    def test_returns_hits_for_matching_query(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="Australian"))
        assert len(response.hits) > 0
        for hit in response.hits:
            assert hit.get("country") == "AU"

    def test_empty_query_returns_all(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="", limit=10))
        assert len(response.hits) == 3

    def test_no_match_returns_empty(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="nonexistentxyz"))
        assert response.hits == []

    def test_total_count_exact_without_content_query(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="", limit=10))
        assert response.total_count == 3

    def test_total_count_with_metadata_filter_exact(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(
            BackendSearchRequest(query="", filters={"country": "AU"}, limit=10)
        )
        assert response.total_count == 2

    def test_total_count_with_content_query_is_page_size(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="Australian", limit=10))
        assert response.total_count == len(response.hits)

    def test_metadata_filter_applied(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(
            BackendSearchRequest(query="", filters={"country": "US"}, limit=10)
        )
        assert len(response.hits) == 1
        assert response.hits[0].get("country") == "US"

    def test_list_filter(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(
            BackendSearchRequest(query="", filters={"country": ["AU", "US"]}, limit=10)
        )
        assert len(response.hits) == 3

    def test_gt_filter(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(
            BackendSearchRequest(query="", filters={"revenue": {"$gt": 4000}}, limit=10)
        )
        ids = {hit["id"] for hit in response.hits}
        assert ids == {"1", "2"}  # revenue 5000 and 8000

    def test_limit_offset_pagination(self) -> None:
        adapter = _make_adapter(mode="full_text")
        page1 = adapter.search(BackendSearchRequest(query="", limit=2, offset=0))
        page2 = adapter.search(BackendSearchRequest(query="", limit=2, offset=2))
        ids_page1 = {hit["id"] for hit in page1.hits}
        ids_page2 = {hit["id"] for hit in page2.hits}
        # Pages should not overlap
        assert ids_page1.isdisjoint(ids_page2)
        assert len(page1.hits) == 2
        assert len(page2.hits) == 1

    def test_id_field_present(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query="", limit=10))
        for hit in response.hits:
            assert "id" in hit

    def test_document_field_populated_when_set(self) -> None:
        adapter = _make_adapter(mode="full_text", document_field="document")
        response = adapter.search(BackendSearchRequest(query="", limit=10))
        assert all("document" in hit for hit in response.hits)

    def test_raw_response_has_mode(self) -> None:
        adapter = _make_adapter(mode="full_text")
        response = adapter.search(BackendSearchRequest(query=""))
        assert response.raw_response.get("mode") == "full_text"

    def test_multi_token_query_requires_all_tokens(self) -> None:
        adapter = _make_adapter(mode="full_text")
        # "Australian startup" should match only Initech (id=3)
        response = adapter.search(BackendSearchRequest(query="Australian startup", limit=10))
        assert len(response.hits) == 1
        assert response.hits[0]["id"] == "3"


# ---------------------------------------------------------------------------
# Integration with IndexConfig
# ---------------------------------------------------------------------------


class _CompanyDoc(BaseModel):
    id: str
    name: str
    country: str
    revenue: int


class TestIndexConfigIntegration:
    def test_chromaadapter_works_with_index_config(self) -> None:
        adapter = _make_adapter(mode="full_text")
        config = IndexConfig(
            name="companies",
            document_schema=_CompanyDoc,
            adapter=adapter,
            searchable_fields=["name"],
            id_field="id",
            filterable_fields=["country"],
        )
        assert config.adapter is adapter

    def test_search_protocol_satisfied(self) -> None:
        """ChromaAdapter satisfies the SearchAdapter protocol used by the executor."""
        adapter = _make_adapter(mode="vector")
        assert isinstance(adapter, SearchAdapter)
        response = adapter.search(BackendSearchRequest(query="test"))
        assert hasattr(response, "hits")
        assert hasattr(response, "total_count")
