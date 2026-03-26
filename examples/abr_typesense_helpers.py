from __future__ import annotations

import csv
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import typesense
from pydantic import BaseModel

from search_service import (
    ClassificationResult,
    ExtractionResult,
    IndexConfig,
    InteractionMode,
    QueryAnalyzer,
    SearchClient,
    SearchPolicy,
)
from search_service.adapters import TypesenseAdapter, create_collection_if_missing
from search_service.schemas.config import ConfidenceThresholds
from search_service.schemas.enums import AmbiguityLevel

SEARCHABLE_FIELDS = [
    "entity_name",
    "main_name",
    "legal_full_name",
    "trading_names",
    "business_names",
    "other_names",
    "all_other_entity_names",
]

FILTERABLE_FIELDS = [
    "abn_status",
    "entity_type_text",
    "entity_type_ind",
    "entity_name_type",
    "state",
    "postcode",
    "gst_status",
    "dgr_status",
    "replaced",
]

DISPLAY_FIELDS = [
    "abn",
    "entity_name",
    "main_name",
    "entity_type_text",
    "abn_status",
    "state",
    "postcode",
    "gst_status",
    "trading_names",
    "business_names",
]

CANONICAL_STATES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"]
STATUS_SYNONYMS = {
    "active": "ACT",
    "cancelled": "CAN",
    "canceled": "CAN",
    "inactive": "CAN",
}
GST_SYNONYMS = {
    "gst registered": "ACT",
    "registered for gst": "ACT",
    "gst active": "ACT",
    "gst cancelled": "CAN",
    "gst canceled": "CAN",
    "not gst registered": "NON",
    "non gst": "NON",
}
DGR_SYNONYMS = {
    "dgr": "ACT",
    "deductible gift recipient": "ACT",
}
ENTITY_TYPE_SYNONYMS = {
    "private company": "Australian Private Company",
    "public company": "Australian Public Company",
    "sole trader": "Individual/Sole Trader",
    "individual": "Individual/Sole Trader",
    "family partnership": "Family Partnership",
    "other partnership": "Other Partnership",
    "partnership": "Other Partnership",
    "smsf": "ATO Regulated Self-Managed Superannuation Fund",
    "self-managed super fund": "ATO Regulated Self-Managed Superannuation Fund",
    "discretionary trust": "Discretionary Trading Trust",
    "unit trust": "Fixed Unit Trust",
}


class AbrBusinessRecord(BaseModel):
    id: str
    abn: str
    entity_name: str
    main_name: str | None = None
    legal_full_name: str | None = None
    entity_type_ind: str | None = None
    entity_type_text: str | None = None
    entity_name_type: str | None = None
    state: str | None = None
    postcode: str | None = None
    abn_status: str | None = None
    gst_status: str | None = None
    dgr_status: str | None = None
    trading_names: str | None = None
    business_names: str | None = None
    other_names: str | None = None
    all_other_entity_names: str | None = None
    replaced: str | None = None
    record_last_updated_date: str | None = None
    source_file: str | None = None


class AbrNotebookProvider:
    @property
    def model_name(self) -> str:
        return "demo/abr-notebook-provider"

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(query_type="entity_lookup", confidence=0.9)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        q = query.lower().strip()
        filters: dict[str, Any] = {}
        postcode_match = re.search(r"\b(\d{4})\b", q)

        for state in CANONICAL_STATES:
            if f" {state.lower()} " in f" {q} ":
                filters["state"] = state
                break

        if postcode_match is not None:
            filters["postcode"] = postcode_match.group(1)

        for phrase, status_code in STATUS_SYNONYMS.items():
            if phrase in q:
                filters["abn_status"] = status_code
                break

        for phrase, gst_code in GST_SYNONYMS.items():
            if phrase in q:
                filters["gst_status"] = gst_code
                break

        for phrase, dgr_code in DGR_SYNONYMS.items():
            if phrase in q:
                filters["dgr_status"] = dgr_code
                break

        for phrase, entity_type in ENTITY_TYPE_SYNONYMS.items():
            if phrase in q:
                filters["entity_type_text"] = entity_type
                break

        if q == "telstra" or q.startswith("ambiguous "):
            cleaned = query.replace("ambiguous", "", 1).strip() or "Telstra"
            return ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                primary_subject=cleaned,
                target_resource_type="company",
                missing_fields=["state"],
            )

        return ExtractionResult(
            ambiguity=AmbiguityLevel.none,
            primary_subject=query.strip() or "business record",
            filters=filters,
            target_resource_type="company",
        )


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def normalize_abr_row(row: dict[str, Any]) -> dict[str, str] | None:
    abn = clean_value(row.get("abn"))
    if abn is None:
        return None

    best_name = (
        clean_value(row.get("entity_name"))
        or clean_value(row.get("main_name"))
        or clean_value(row.get("legal_full_name"))
    )
    if best_name is None:
        return None

    return {
        "id": abn,
        "abn": abn,
        "entity_name": best_name,
        "main_name": clean_value(row.get("main_name")) or best_name,
        "legal_full_name": clean_value(row.get("legal_full_name")) or "",
        "entity_type_ind": clean_value(row.get("entity_type_ind")) or "",
        "entity_type_text": clean_value(row.get("entity_type_text")) or "",
        "entity_name_type": clean_value(row.get("entity_name_type")) or "",
        "state": clean_value(row.get("state")) or "",
        "postcode": clean_value(row.get("postcode")) or "",
        "abn_status": clean_value(row.get("abn_status")) or "",
        "gst_status": clean_value(row.get("gst_status")) or "",
        "dgr_status": clean_value(row.get("dgr_status")) or "",
        "trading_names": clean_value(row.get("trading_names")) or "",
        "business_names": clean_value(row.get("business_names")) or "",
        "other_names": clean_value(row.get("other_names")) or "",
        "all_other_entity_names": clean_value(row.get("all_other_entity_names")) or "",
        "replaced": clean_value(row.get("replaced")) or "",
        "record_last_updated_date": clean_value(row.get("record_last_updated_date")) or "",
        "source_file": clean_value(row.get("source_file")) or "",
    }


def abr_csv_metadata(csv_path: Path) -> dict[str, Any]:
    """Cheap metadata only: file size and header row. Does not scan the full CSV."""
    stat = csv_path.stat()
    size_bytes = stat.st_size
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline()
    reader = csv.reader([first_line])
    headers = next(reader)
    return {
        "path": str(csv_path.resolve()),
        "size_bytes": size_bytes,
        "size_gb": round(size_bytes / (1024**3), 3),
        "headers": headers,
    }


def iter_abr_documents(
    csv_path: Path,
    *,
    limit: int | None = None,
    max_rows_to_scan: int | None = None,
) -> Iterator[dict[str, str]]:
    """Stream normalized ABR rows. Stops after ``limit`` valid documents or ``max_rows_to_scan`` raw rows.

    Use ``max_rows_to_scan`` for previews so a pathological file cannot force an unbounded scan.
    """
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        yielded = 0
        scanned = 0
        for row in reader:
            scanned += 1
            if max_rows_to_scan is not None and scanned > max_rows_to_scan:
                return
            document = normalize_abr_row(row)
            if document is None:
                continue
            yield document
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def preview_abr_documents(
    csv_path: Path,
    *,
    limit: int = 3,
    max_rows_to_scan: int = 500_000,
) -> list[dict[str, str]]:
    """Return up to ``limit`` valid documents without scanning the entire file."""
    return list(iter_abr_documents(csv_path, limit=limit, max_rows_to_scan=max_rows_to_scan))


def build_typesense_client(
    *,
    host: str = "localhost",
    port: int = 8108,
    api_key: str = "search-service-dev",
    protocol: str = "http",
) -> typesense.Client:
    return typesense.Client(
        {
            "nodes": [{"host": host, "port": str(port), "protocol": protocol}],
            "api_key": api_key,
            "connection_timeout_seconds": 10,
        }
    )


def wait_for_typesense(
    *,
    host: str = "localhost",
    port: int = 8108,
    protocol: str = "http",
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> None:
    health_url = f"{protocol}://{host}:{port}/health"
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
        time.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Typesense did not become ready in time. "
        f"Waited {timeout_seconds} seconds for {health_url}. Last error: {last_error}"
    )


def ensure_typesense_container(
    *,
    container_name: str = "search-service-typesense",
    host_port: int = 8108,
    api_key: str = "search-service-dev",
    image: str = "typesense/typesense:30.1",
    data_dir: Path | None = None,
) -> None:
    resolved_data_dir = (data_dir or Path(".typesense-data")).resolve()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)

    existing = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{container_name}$",
            "--format",
            "{{.Names}}\t{{.Status}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode != 0:
        message = existing.stderr.strip() or existing.stdout.strip() or "unknown Docker error"
        raise RuntimeError(
            "Docker is installed but is not currently available. "
            f"Start Docker Desktop or your local Docker daemon, then retry. Details: {message}"
        )

    for line in existing.stdout.splitlines():
        if not line.strip():
            continue
        name, _, status = line.partition("\t")
        if name != container_name:
            continue
        if status.startswith("Up "):
            return
        subprocess.run(["docker", "start", container_name], check=True)
        return

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{host_port}:8108",
            "-v",
            f"{resolved_data_dir}:/data",
            image,
            "--data-dir",
            "/data",
            "--api-key",
            api_key,
            "--enable-cors",
        ],
        check=True,
    )


def build_abr_typesense_config(
    adapter: TypesenseAdapter,
    *,
    interaction_mode: InteractionMode = InteractionMode.aitl,
    index_name: str = "abr_entities",
) -> IndexConfig:
    return IndexConfig(
        name=index_name,
        document_schema=AbrBusinessRecord,
        adapter=adapter,
        searchable_fields=SEARCHABLE_FIELDS,
        filterable_fields=FILTERABLE_FIELDS,
        display_fields=DISPLAY_FIELDS,
        id_field="id",
        entity_types=["company"],
        expected_query_types=["entity_lookup", "filter_search"],
        default_interaction_mode=interaction_mode,
        policy=SearchPolicy(
            max_iterations=3,
            max_branches=2,
            canonical_filters={
                "state": CANONICAL_STATES,
                "abn_status": ["ACT", "CAN"],
                "gst_status": ["ACT", "CAN", "NON"],
                "dgr_status": ["ACT"],
                "entity_type_text": list(ENTITY_TYPE_SYNONYMS.values()),
            },
            example_queries=[
                "QBE NSW active",
                "private company in VIC",
                "sole trader in QLD",
                "gst registered business in 2000",
            ],
            confidence_thresholds=ConfidenceThresholds(stop=0.72, escalate=0.28),
        ),
    )


def recreate_collection(client: typesense.Client, collection_name: str) -> None:
    if collection_name not in client.collections:
        return
    client.collections[collection_name].delete()


def get_collection_document_count(client: typesense.Client, collection_name: str) -> int:
    if collection_name not in client.collections:
        return 0
    metadata = client.collections[collection_name].retrieve()
    return int(metadata.get("num_documents") or 0)


def _flush_import_batch(
    collection: Any,
    batch: list[dict[str, str]],
) -> tuple[int, list[dict[str, Any]]]:
    if not batch:
        return 0, []

    responses = collection.documents.import_(batch, {"action": "upsert"})
    imported = 0
    failures: list[dict[str, Any]] = []
    for response in responses:
        success = response.get("success")
        was_successful = success is True or str(success).lower() == "true"
        if was_successful:
            imported += 1
            continue
        failures.append(response)
    return imported, failures


def import_abr_documents_to_typesense(
    client: typesense.Client,
    collection_name: str,
    csv_path: Path,
    *,
    limit: int | None = None,
    batch_size: int = 5_000,
) -> dict[str, Any]:
    collection = client.collections[collection_name]
    batch: list[dict[str, str]] = []
    imported = 0
    failed = 0
    sample_failures: list[dict[str, Any]] = []

    for document in iter_abr_documents(csv_path, limit=limit):
        batch.append(document)
        if len(batch) < batch_size:
            continue

        batch_imported, batch_failures = _flush_import_batch(collection, batch)
        imported += batch_imported
        failed += len(batch_failures)
        if batch_failures and len(sample_failures) < 3:
            sample_failures.extend(batch_failures[: 3 - len(sample_failures)])
        batch = []

    if batch:
        batch_imported, batch_failures = _flush_import_batch(collection, batch)
        imported += batch_imported
        failed += len(batch_failures)
        if batch_failures and len(sample_failures) < 3:
            sample_failures.extend(batch_failures[: 3 - len(sample_failures)])

    return {
        "imported": imported,
        "failed": failed,
        "limit": limit,
        "batch_size": batch_size,
        "sample_failures": sample_failures,
    }


def build_abr_typesense_index(
    *,
    csv_path: Path,
    host: str = "localhost",
    port: int = 8108,
    api_key: str = "search-service-dev",
    protocol: str = "http",
    interaction_mode: InteractionMode = InteractionMode.aitl,
    index_name: str = "abr_entities",
    ensure_collection: bool = True,
    reindex: bool = False,
    import_limit: int | None = None,
    allow_full_import: bool = False,
    batch_size: int = 5_000,
    with_demo_analyzer: bool = True,
) -> tuple[SearchClient, Any, typesense.Client, dict[str, Any] | None]:
    if import_limit is None and not allow_full_import:
        raise ValueError(
            "import_limit is None (full file import) but allow_full_import is False. "
            "Set allow_full_import=True only when you intend to read the entire CSV. "
            "For experiments, set import_limit to a positive integer (for example 25_000)."
        )
    wait_for_typesense(host=host, port=port, protocol=protocol)
    ts_client = build_typesense_client(
        host=host,
        port=port,
        api_key=api_key,
        protocol=protocol,
    )
    adapter = TypesenseAdapter(ts_client, index_name, SEARCHABLE_FIELDS)
    config = build_abr_typesense_config(
        adapter,
        interaction_mode=interaction_mode,
        index_name=index_name,
    )

    import_summary = None
    if ensure_collection:
        if reindex:
            recreate_collection(ts_client, index_name)
        create_collection_if_missing(ts_client, config)
        if reindex or get_collection_document_count(ts_client, index_name) == 0:
            import_summary = import_abr_documents_to_typesense(
                ts_client,
                index_name,
                csv_path,
                limit=import_limit,
                batch_size=batch_size,
            )

    client = SearchClient()
    analyzer = QueryAnalyzer(AbrNotebookProvider()) if with_demo_analyzer else None
    index = client.indexes.create(config, analyzer=analyzer)
    return client, index, ts_client, import_summary
