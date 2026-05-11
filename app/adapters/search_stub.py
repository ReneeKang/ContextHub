from __future__ import annotations

from typing import Any
from uuid import UUID

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit


class StubSearchClient(SearchClient):
    """No-op / empty search and index operations for local skeleton runs."""

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        _ = (query, top_k, principal, index_name)
        return []

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        _ = (index_name, doc_id, document)
        # TODO: OpenSearch index API

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        _ = (index_name, raw_document_id)
        # TODO: delete-by-query on raw_document_id
