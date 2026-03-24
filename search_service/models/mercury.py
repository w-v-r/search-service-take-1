"""Mercury 2 (Inception Labs) implementation of ModelProvider.

Uses the OpenAI-compatible API at https://api.inceptionlabs.ai/v1 with model
``mercury-2``. Set ``INCEPTION_API_KEY`` or pass ``api_key`` explicitly.

Classification and extraction prompts request a single JSON object; responses
are parsed leniently. API failures and malformed output yield empty or default
results rather than raising.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import APIError, OpenAI

from search_service.models.llm import ClassificationResult, ExtractionResult
from search_service.schemas.enums import AmbiguityLevel
from search_service.schemas.query import ExtractedEntity

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.inceptionlabs.ai/v1"
DEFAULT_MODEL = "mercury-2"
ENV_API_KEY = "INCEPTION_API_KEY"


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object from model output (strict decode, then balanced-brace fallback)."""
    raw = _strip_code_fence(text)
    if not raw:
        return None
    try:
        start = raw.index("{")
    except ValueError:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(raw[start:])
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    depth = 0
    for j in range(start, len(raw)):
        if raw[j] == "{":
            depth += 1
        elif raw[j] == "}":
            depth -= 1
            if depth == 0:
                chunk = raw[start : j + 1]
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _normalize_ambiguity(value: object) -> AmbiguityLevel:
    if isinstance(value, AmbiguityLevel):
        return value
    if not isinstance(value, str):
        return AmbiguityLevel.none
    v = value.strip().lower()
    for level in AmbiguityLevel:
        if level.value == v:
            return level
    return AmbiguityLevel.none


def _clamp_confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        try:
            f = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, f))


def _parse_entities(raw: object) -> list[ExtractedEntity]:
    if not isinstance(raw, list):
        return []
    out: list[ExtractedEntity] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        val = item.get("value")
        if not isinstance(val, str) or not val.strip():
            continue
        et = item.get("entity_type")
        fm = item.get("field_mapping")
        conf = item.get("confidence")
        try:
            out.append(
                ExtractedEntity(
                    value=val.strip(),
                    entity_type=et if isinstance(et, str) else None,
                    field_mapping=fm if isinstance(fm, str) else None,
                    confidence=_clamp_confidence(conf),
                )
            )
        except Exception:
            continue
    return out


def _parse_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def _parse_filters(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items()}


CLASSIFICATION_SYSTEM = (
    "You are a search query classifier. You must respond with a single JSON object only, "
    "no other text.\n"
    "The JSON must have exactly these keys:\n"
    '- "query_type": string, one of the allowed types listed in the user message, '
    "or null if none fit\n"
    '- "confidence": number between 0 and 1 indicating confidence in that choice\n'
    "Do not include markdown or code fences."
)


def _classification_user_prompt(
    query: str,
    expected_query_types: list[str],
    *,
    entity_types: list[str] | None,
    example_queries: list[str] | None,
) -> str:
    parts = [
        f"User query: {query!r}",
        f"Allowed query_type values (choose exactly one or use null): {json.dumps(expected_query_types)}",
    ]
    if entity_types:
        parts.append(f"Entity types in this index (context): {json.dumps(entity_types)}")
    if example_queries:
        parts.append(f"Example queries for this index: {json.dumps(example_queries)}")
    parts.append("Return only the JSON object.")
    return "\n\n".join(parts)


EXTRACTION_SYSTEM = (
    "You are a search assistant that extracts structured information from user queries.\n"
    "Respond with a single JSON object only, no markdown or code fences.\n"
    "\n"
    "Required shape:\n"
    "{\n"
    '  "entities": [ { "value": string, "entity_type": string or null, '
    '"field_mapping": string or null, "confidence": number or null } ],\n'
    '  "filters": { "<field_name>": <scalar value> },\n'
    '  "ambiguity": "none" | "low" | "medium" | "high",\n'
    '  "primary_subject": string or null,\n'
    '  "target_resource_type": string or null,\n'
    '  "possible_resource_types": [ string, ... ],\n'
    '  "missing_fields": [ string, ... ]\n'
    "}\n"
    "\n"
    "Use only filter field names from the filterable_fields list when proposing filters.\n"
    "Prefer canonical filter values when a canonical list is given for a field.\n"
    "If uncertain, set ambiguity higher and list missing_fields that would help."
)


def _extraction_user_prompt(
    query: str,
    *,
    entity_types: list[str] | None,
    filterable_fields: list[str] | None,
    canonical_filters: dict[str, list[str]] | None,
) -> str:
    parts = [f"User query: {query!r}"]
    if entity_types:
        parts.append(f"Entity types: {json.dumps(entity_types)}")
    if filterable_fields:
        parts.append(f"Filterable fields: {json.dumps(filterable_fields)}")
    if canonical_filters:
        parts.append(f"Canonical allowed values per field: {json.dumps(canonical_filters)}")
    parts.append("Return only the JSON object.")
    return "\n\n".join(parts)


def classification_from_parsed(data: dict[str, Any]) -> ClassificationResult:
    qt = data.get("query_type")
    query_type = qt.strip() if isinstance(qt, str) and qt.strip() else None
    return ClassificationResult(
        query_type=query_type,
        confidence=_clamp_confidence(data.get("confidence")),
    )


def extraction_from_parsed(data: dict[str, Any]) -> ExtractionResult:
    return ExtractionResult(
        entities=_parse_entities(data.get("entities")),
        filters=_parse_filters(data.get("filters")),
        ambiguity=_normalize_ambiguity(data.get("ambiguity")),
        primary_subject=data.get("primary_subject") if isinstance(data.get("primary_subject"), str) else None,
        target_resource_type=(
            data.get("target_resource_type")
            if isinstance(data.get("target_resource_type"), str)
            else None
        ),
        possible_resource_types=_parse_str_list(data.get("possible_resource_types")),
        missing_fields=_parse_str_list(data.get("missing_fields")),
    )


class MercuryModelProvider:
    """ModelProvider backed by Inception Labs Mercury 2 via OpenAI-compatible HTTP API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        max_retries: int = 2,
        openai_client: OpenAI | None = None,
    ) -> None:
        self._model = model
        if openai_client is not None:
            self._client = openai_client
        else:
            key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
            if not key:
                msg = (
                    f"MercuryModelProvider requires api_key=... or the {ENV_API_KEY} environment variable."
                )
                raise ValueError(msg)
            self._client = OpenAI(
                api_key=key,
                base_url=base_url or DEFAULT_BASE_URL,
                timeout=timeout,
                max_retries=max_retries,
            )

    @property
    def model_name(self) -> str:
        return self._model

    def _chat(self, system: str, user: str, *, max_tokens: int) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        choice = resp.choices[0].message
        content = choice.content if choice else None
        return content if isinstance(content, str) else ""

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        if not expected_query_types:
            return ClassificationResult()
        user = _classification_user_prompt(
            query,
            expected_query_types,
            entity_types=entity_types,
            example_queries=example_queries,
        )
        try:
            text = self._chat(CLASSIFICATION_SYSTEM, user, max_tokens=256)
        except (APIError, OSError) as e:
            logger.warning("Mercury classification request failed: %s", e)
            return ClassificationResult()
        data = _parse_json_object(text)
        if not data:
            logger.warning("Mercury classification returned unparseable output")
            return ClassificationResult()
        return classification_from_parsed(data)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        user = _extraction_user_prompt(
            query,
            entity_types=entity_types,
            filterable_fields=filterable_fields,
            canonical_filters=canonical_filters,
        )
        try:
            text = self._chat(EXTRACTION_SYSTEM, user, max_tokens=1024)
        except (APIError, OSError) as e:
            logger.warning("Mercury extraction request failed: %s", e)
            return ExtractionResult()
        data = _parse_json_object(text)
        if not data:
            logger.warning("Mercury extraction returned unparseable output")
            return ExtractionResult()
        return extraction_from_parsed(data)
