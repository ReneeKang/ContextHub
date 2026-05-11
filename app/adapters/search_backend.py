"""
Select `SearchClient` implementation from `Settings.search_backend`.

* **db** (default): chat uses PostgreSQL; indexer uses in-memory stub for index/delete (no cluster).
* **opensearch_stub**: chat returns no hits but logs OpenSearch query shape; indexer validates index payloads and logs (no HTTP).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.db_chunk_search import DbChunkSearchClient
from app.adapters.opensearch_stub import OpenSearchSearchClient
from app.adapters.search_protocol import SearchClient
from app.adapters.search_stub import StubSearchClient
from app.config.settings import Settings


def search_client_for_chat(session: Session, settings: Settings) -> SearchClient:
    """Chat RAG retrieval: DB SQL search by default; OpenSearch-shaped stub for integration tests."""
    if settings.search_backend == "opensearch_stub":
        return OpenSearchSearchClient(settings)
    return DbChunkSearchClient(session)


def search_client_for_indexer(settings: Settings) -> SearchClient:
    """Indexer writes: lightweight stub by default; OpenSearch-shaped stub validates payload + logs."""
    if settings.search_backend == "opensearch_stub":
        return OpenSearchSearchClient(settings)
    return StubSearchClient()
