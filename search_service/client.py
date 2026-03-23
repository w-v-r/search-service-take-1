from __future__ import annotations

from search_service.exceptions import IndexAlreadyExistsError, IndexNotFoundError
from search_service.indexes.base import SearchIndex
from search_service.schemas.config import IndexConfig


class IndexManager:
    """Manages the lifecycle of search indexes owned by a SearchClient.

    Accessed via `client.indexes`. Provides create, get, delete, and list
    operations for SearchIndex instances.
    """

    def __init__(self) -> None:
        self._store: dict[str, SearchIndex] = {}

    def create(self, config: IndexConfig) -> SearchIndex:
        """Create a new search index from the given configuration.

        Args:
            config: IndexConfig defining the index identity, fields,
                adapter, and optional policy.

        Returns:
            A configured SearchIndex ready for search calls.

        Raises:
            IndexAlreadyExistsError: If an index with the same name exists.
        """
        if config.name in self._store:
            raise IndexAlreadyExistsError(config.name)

        index = SearchIndex(config)
        self._store[config.name] = index
        return index

    def get(self, name: str) -> SearchIndex:
        """Retrieve an existing index by name.

        Raises:
            IndexNotFoundError: If no index with the given name exists.
        """
        if name not in self._store:
            raise IndexNotFoundError(name)
        return self._store[name]

    def delete(self, name: str) -> None:
        """Delete an index by name.

        Raises:
            IndexNotFoundError: If no index with the given name exists.
        """
        if name not in self._store:
            raise IndexNotFoundError(name)
        del self._store[name]

    def list(self) -> list[SearchIndex]:
        """Return all registered indexes."""
        return list(self._store.values())

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        names = list(self._store.keys())
        return f"IndexManager(indexes={names})"


class SearchClient:
    """Entry point for the search service SDK.

    Follows the standard Client -> Index pattern used by comparable
    search SDKs (Pinecone, Typesense, Algolia, etc.). The client owns
    indexes directly -- there is no intermediate App layer.

    Usage::

        from search_service import SearchClient, IndexConfig

        client = SearchClient()
        index = client.indexes.create(IndexConfig(
            name="companies",
            schema=CompanyDocument,
            adapter=my_adapter,
            searchable_fields=["name", "description"],
            id_field="id",
        ))
        result = index.search("Telstra")
    """

    def __init__(self) -> None:
        self._indexes = IndexManager()

    @property
    def indexes(self) -> IndexManager:
        """Access the index manager for creating, retrieving, and managing indexes."""
        return self._indexes

    def __repr__(self) -> str:
        return f"SearchClient(indexes={len(self._indexes)})"
