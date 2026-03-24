"""Search Service SDK -- LLM-powered search orchestration with iterative search and ambiguity handling."""

from search_service.adapters.base import BackendSearchRequest, BackendSearchResponse, SearchAdapter
from search_service.adapters.in_memory import InMemoryAdapter
from search_service.client import SearchClient
from search_service.exceptions import (
    AdapterError,
    ConfigurationError,
    IndexAlreadyExistsError,
    IndexNotFoundError,
    SearchExecutionError,
    SearchServiceError,
    TraceNotFoundError,
)
from search_service.indexes.base import SearchIndex
from search_service.models.llm import ClassificationResult, ExtractionResult, ModelProvider
from search_service.models.mercury import MercuryModelProvider
from search_service.orchestration.analyzer import QueryAnalyzer
from search_service.schemas.config import ConfidenceThresholds, IndexConfig, SearchPolicy
from search_service.schemas.enums import (
    AmbiguityLevel,
    BranchKind,
    InteractionMode,
    SearchStatus,
    TraceStepType,
)
from search_service.schemas.followup import Candidate, FollowUpRequest
from search_service.schemas.query import ExtractedEntity, QueryAnalysis
from search_service.schemas.result import BranchResult, SearchResultEnvelope, SearchResultItem
from search_service.schemas.trace import SearchTrace, TraceStep
from search_service.telemetry.tracer import Tracer

__all__ = [
    # Client & Index
    "SearchClient",
    "SearchIndex",
    # Configuration
    "IndexConfig",
    "SearchPolicy",
    "ConfidenceThresholds",
    # Enums
    "AmbiguityLevel",
    "BranchKind",
    "InteractionMode",
    "SearchStatus",
    "TraceStepType",
    # Query
    "ExtractedEntity",
    "QueryAnalysis",
    # Results
    "BranchResult",
    "Candidate",
    "FollowUpRequest",
    "SearchResultEnvelope",
    "SearchResultItem",
    # Trace
    "SearchTrace",
    "TraceStep",
    # Adapter
    "BackendSearchRequest",
    "BackendSearchResponse",
    "InMemoryAdapter",
    "SearchAdapter",
    # Models
    "ClassificationResult",
    "ExtractionResult",
    "MercuryModelProvider",
    "ModelProvider",
    # Orchestration
    "QueryAnalyzer",
    # Telemetry
    "Tracer",
    # Exceptions
    "AdapterError",
    "ConfigurationError",
    "IndexAlreadyExistsError",
    "IndexNotFoundError",
    "SearchExecutionError",
    "SearchServiceError",
    "TraceNotFoundError",
]
