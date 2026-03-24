"""Unit tests for MercuryModelProvider (mocked HTTP) and JSON parsing helpers.

Live API tests are opt-in: ``pytest -m integration`` with ``INCEPTION_API_KEY`` set.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIError

from search_service.models.mercury import (
    DEFAULT_MODEL,
    MercuryModelProvider,
    _parse_json_object,
    classification_from_parsed,
    extraction_from_parsed,
)
from search_service.schemas.enums import AmbiguityLevel


def test_parse_json_object_plain() -> None:
    d = _parse_json_object('{"query_type": "lookup", "confidence": 0.9}')
    assert d == {"query_type": "lookup", "confidence": 0.9}


def test_parse_json_object_fenced() -> None:
    text = '```json\n{"a": 1}\n```'
    d = _parse_json_object(text)
    assert d == {"a": 1}


def test_parse_json_object_balanced_fallback() -> None:
    text = 'Here is JSON:\n{"x": {"nested": true}}\n'
    d = _parse_json_object(text)
    assert d == {"x": {"nested": True}}


def test_parse_json_object_invalid() -> None:
    assert _parse_json_object("not json") is None


def test_classification_from_parsed() -> None:
    r = classification_from_parsed({"query_type": "search", "confidence": 1.5})
    assert r.query_type == "search"
    assert r.confidence == 1.0


def test_extraction_from_parsed() -> None:
    r = extraction_from_parsed({
        "entities": [{"value": "Acme", "entity_type": "company", "confidence": 0.8}],
        "filters": {"country": "AU"},
        "ambiguity": "low",
        "primary_subject": "Acme",
        "target_resource_type": "company",
        "possible_resource_types": ["company"],
        "missing_fields": [],
    })
    assert len(r.entities) == 1
    assert r.entities[0].value == "Acme"
    assert r.filters == {"country": "AU"}
    assert r.ambiguity == AmbiguityLevel.low


def _mock_openai_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )
    return client


def test_mercury_classify_query_mocked() -> None:
    payload = json.dumps({"query_type": "entity_lookup", "confidence": 0.85})
    mp = MercuryModelProvider(openai_client=_mock_openai_client(payload))
    assert mp.model_name == DEFAULT_MODEL
    r = mp.classify_query(
        "find Telstra",
        ["entity_lookup", "browse"],
    )
    assert r.query_type == "entity_lookup"
    assert r.confidence == pytest.approx(0.85)


def test_mercury_extract_entities_mocked() -> None:
    payload = json.dumps({
        "entities": [{"value": "Telstra", "entity_type": "company_name"}],
        "filters": {},
        "ambiguity": "medium",
        "primary_subject": "Telstra",
        "target_resource_type": None,
        "possible_resource_types": [],
        "missing_fields": ["country"],
    })
    mp = MercuryModelProvider(openai_client=_mock_openai_client(payload))
    r = mp.extract_entities(
        "Telstra stuff",
        entity_types=["company"],
        filterable_fields=["country"],
    )
    assert r.primary_subject == "Telstra"
    assert r.ambiguity == AmbiguityLevel.medium
    assert "country" in r.missing_fields


def test_mercury_classify_empty_expected_types() -> None:
    mp = MercuryModelProvider(openai_client=_mock_openai_client("ignored"))
    r = mp.classify_query("q", [])
    assert r.query_type is None


def test_mercury_api_error_returns_empty() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = APIError(
        message="fail",
        request=MagicMock(),
        body=None,
    )
    mp = MercuryModelProvider(openai_client=client)
    assert mp.classify_query("x", ["a"]).query_type is None
    assert mp.extract_entities("x").ambiguity == AmbiguityLevel.none


def test_mercury_malformed_json_returns_empty() -> None:
    mp = MercuryModelProvider(openai_client=_mock_openai_client("not json {}"))
    assert mp.classify_query("x", ["a"]).query_type is None


@pytest.mark.integration
def test_mercury_live_roundtrip() -> None:
    if not os.environ.get("INCEPTION_API_KEY"):
        pytest.skip("INCEPTION_API_KEY not set")
    mp = MercuryModelProvider()
    r = mp.classify_query(
        "show me companies in Australia",
        ["browse", "filter", "lookup"],
        example_queries=["list all companies"],
    )
    assert r.query_type in ("browse", "filter", "lookup", None)
    ex = mp.extract_entities(
        "companies in AU",
        entity_types=["company"],
        filterable_fields=["country"],
        canonical_filters={"country": ["AU", "US"]},
    )
    assert ex.ambiguity in list(AmbiguityLevel)
