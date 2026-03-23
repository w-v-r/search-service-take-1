from __future__ import annotations

from search_service.adapters.base import BackendSearchRequest, BackendSearchResponse, SearchAdapter
from search_service.adapters.in_memory import InMemoryAdapter

SAMPLE_DOCS = [
    {"id": "1", "name": "Telstra Corporation", "country": "AU", "status": "active", "revenue": 20_000},
    {"id": "2", "name": "Optus Networks", "country": "AU", "status": "active", "revenue": 8_000},
    {"id": "3", "name": "Vodafone Australia", "country": "AU", "status": "inactive", "revenue": 5_000},
    {"id": "4", "name": "British Telecom", "country": "UK", "status": "active", "revenue": 25_000},
    {"id": "5", "name": "AT&T Inc", "country": "US", "status": "active", "revenue": 170_000},
    {"id": "6", "name": "Verizon Communications", "country": "US", "status": "active", "revenue": 130_000},
]


def _make_adapter() -> InMemoryAdapter:
    return InMemoryAdapter(
        documents=SAMPLE_DOCS,
        searchable_fields=["name"],
    )


# --- Protocol conformance ---


class TestProtocolConformance:
    def test_is_search_adapter(self) -> None:
        adapter = _make_adapter()
        assert isinstance(adapter, SearchAdapter)

    def test_search_returns_backend_search_response(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telstra"))
        assert isinstance(response, BackendSearchResponse)


# --- Keyword matching ---


class TestKeywordMatching:
    def test_single_token_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telstra"))
        assert response.total_count == 1
        assert response.hits[0]["id"] == "1"

    def test_case_insensitive(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="telstra"))
        assert response.total_count == 1

    def test_substring_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telecom"))
        assert response.total_count == 1
        assert response.hits[0]["name"] == "British Telecom"

    def test_multi_token_all_must_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Vodafone Australia"))
        assert response.total_count == 1
        assert response.hits[0]["id"] == "3"

    def test_multi_token_partial_no_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Vodafone UK"))
        assert response.total_count == 0

    def test_empty_query_returns_all(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query=""))
        assert response.total_count == len(SAMPLE_DOCS)

    def test_whitespace_query_returns_all(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="   "))
        assert response.total_count == len(SAMPLE_DOCS)

    def test_no_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Nonexistent"))
        assert response.total_count == 0
        assert response.hits == []

    def test_custom_fields_override(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="AU", fields=["country"]))
        assert response.total_count == 3

    def test_custom_fields_no_match_in_wrong_field(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="inactive", fields=["name"]))
        assert response.total_count == 0


# --- Filter matching ---


class TestFilterMatching:
    def test_exact_string_filter(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", filters={"country": "AU"}))
        assert response.total_count == 3
        assert all(h["country"] == "AU" for h in response.hits)

    def test_exact_filter_combined_with_keyword(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Networks", filters={"country": "AU"}))
        assert response.total_count == 1
        assert response.hits[0]["name"] == "Optus Networks"

    def test_list_filter_or_semantics(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", filters={"country": ["AU", "UK"]}))
        assert response.total_count == 4

    def test_multiple_filters_all_must_match(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(
            BackendSearchRequest(query="", filters={"country": "AU", "status": "active"})
        )
        assert response.total_count == 2
        assert all(h["country"] == "AU" and h["status"] == "active" for h in response.hits)

    def test_gt_operator(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", filters={"revenue": {"$gt": 100_000}}))
        assert response.total_count == 2
        assert {h["id"] for h in response.hits} == {"5", "6"}

    def test_lte_operator(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", filters={"revenue": {"$lte": 8_000}}))
        assert response.total_count == 2
        assert {h["id"] for h in response.hits} == {"2", "3"}

    def test_ne_operator(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", filters={"status": {"$ne": "active"}}))
        assert response.total_count == 1
        assert response.hits[0]["id"] == "3"

    def test_combined_operators(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(
            BackendSearchRequest(query="", filters={"revenue": {"$gte": 5_000, "$lt": 25_000}})
        )
        assert response.total_count == 3
        assert {h["id"] for h in response.hits} == {"1", "2", "3"}

    def test_filter_on_missing_field_excludes_doc(self) -> None:
        adapter = InMemoryAdapter(
            documents=[{"id": "1", "name": "Foo"}, {"id": "2", "name": "Bar", "tag": "x"}],
            searchable_fields=["name"],
        )
        response = adapter.search(BackendSearchRequest(query="", filters={"tag": "x"}))
        assert response.total_count == 1
        assert response.hits[0]["id"] == "2"


# --- Pagination ---


class TestPagination:
    def test_limit(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", limit=2))
        assert len(response.hits) == 2
        assert response.total_count == len(SAMPLE_DOCS)

    def test_offset(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", limit=2, offset=4))
        assert len(response.hits) == 2
        assert response.total_count == len(SAMPLE_DOCS)

    def test_offset_beyond_results(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="", offset=100))
        assert len(response.hits) == 0
        assert response.total_count == len(SAMPLE_DOCS)


# --- Response shape ---


class TestResponseShape:
    def test_query_time_ms_is_set(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telstra"))
        assert response.query_time_ms is not None
        assert response.query_time_ms >= 0

    def test_raw_response_metadata(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telstra"))
        assert "matched_before_filters" in response.raw_response
        assert "matched_after_filters" in response.raw_response

    def test_hits_are_full_documents(self) -> None:
        adapter = _make_adapter()
        response = adapter.search(BackendSearchRequest(query="Telstra"))
        hit = response.hits[0]
        assert hit["id"] == "1"
        assert hit["name"] == "Telstra Corporation"
        assert hit["country"] == "AU"


# --- Document management ---


class TestDocumentManagement:
    def test_add_documents(self) -> None:
        adapter = InMemoryAdapter(searchable_fields=["name"])
        adapter.add_documents([{"id": "1", "name": "Foo"}])
        assert len(adapter.documents) == 1

        adapter.add_documents([{"id": "2", "name": "Bar"}])
        assert len(adapter.documents) == 2

    def test_clear(self) -> None:
        adapter = _make_adapter()
        adapter.clear()
        response = adapter.search(BackendSearchRequest(query=""))
        assert response.total_count == 0

    def test_empty_adapter(self) -> None:
        adapter = InMemoryAdapter()
        response = adapter.search(BackendSearchRequest(query="anything"))
        assert response.total_count == 0
        assert response.hits == []
