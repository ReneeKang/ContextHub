"""
OpenSearch-shaped `SearchClient` without network I/O.

Use for: validating payload/query structure, unit tests, and stepping-stone before `opensearch-py`.
Chat defaults to `DbChunkSearchClient`; set `SEARCH_BACKEND=opensearch_stub` to exercise this path (returns no hits until HTTP is wired).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.adapters.opensearch_payload import (
    build_delete_by_raw_document_query,
    build_keyword_search_body,
    validate_chunk_index_document,
)
from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.config.settings import Settings


log = logging.getLogger("contexthub.opensearch_stub")


class OpenSearchSearchClient(SearchClient):
    """
    Placeholder OpenSearch client: builds the same JSON structures a real client would send.

    - `index_chunk_document`: validates `document` keys; logs intended bulk index line (no POST).
    - `search`: builds `build_keyword_search_body`; logs query shape; returns [] (no cluster).
    - `delete_chunks_for_document`: logs delete-by-query body (no DELETE).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        body = build_keyword_search_body(
            query=query,
            top_k=top_k,
            principal_user_id=principal.user_id,
            department_codes=principal.department_codes,
        )
        log.info(
            "OpenSearch search (stub, no HTTP): index=%s base_url=%s query_body_keys=%s",
            index_name,
            self._settings.opensearch_base_url,
            list(body.keys()),
        )
        log.debug("OpenSearch search (stub) query body: %s", body)
        return []

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        validate_chunk_index_document(document)
        log.info(
            "OpenSearch index (stub, no HTTP): PUT /%s/_doc/%s fields=%s",
            index_name,
            doc_id,
            sorted(document.keys()),
        )
        log.debug("OpenSearch index (stub) document: %s", document)

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        body = build_delete_by_raw_document_query(str(raw_document_id))
        log.info(
            "OpenSearch delete-by-query (stub, no HTTP): POST /%s/_delete_by_query body=%s",
            index_name,
            body,
        )
