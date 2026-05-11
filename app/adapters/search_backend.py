"""
Select `SearchClient` implementation from `Settings.search_backend`.

* **db** (default): chat uses PostgreSQL; indexer uses in-memory stub for index/delete (no cluster).
* **opensearch_stub**: no HTTP; validates payloads and logs query shapes.
* **opensearch**: HTTP ``OpenSearchHttpClient`` for chat + indexer (keyword search; permission in query filter).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.db_chunk_search import DbChunkSearchClient
from app.adapters.opensearch_client import OpenSearchHttpClient
from app.adapters.opensearch_stub import OpenSearchSearchClient
from app.adapters.search_protocol import SearchClient
from app.adapters.search_stub import StubSearchClient
from app.config.settings import Settings


def search_client_for_chat(session: Session, settings: Settings) -> SearchClient:
    """Chat RAG retrieval: DB SQL by default; real OpenSearch when ``SEARCH_BACKEND=opensearch``."""
    if settings.search_backend == "opensearch":
        return OpenSearchHttpClient(settings)
    if settings.search_backend == "opensearch_stub":
        return OpenSearchSearchClient(settings)
    return DbChunkSearchClient(session)


def search_client_for_indexer(settings: Settings) -> SearchClient:
    """Indexer writes: stub by default; OpenSearch HTTP when ``SEARCH_BACKEND=opensearch``."""
    if settings.search_backend == "opensearch":
        return OpenSearchHttpClient(settings)
    if settings.search_backend == "opensearch_stub":
        return OpenSearchSearchClient(settings)
    return StubSearchClient()
