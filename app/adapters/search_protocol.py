"""
Search abstraction for **indexer** (write) and **chat** (read).

Implementations
---------------
* `DbChunkSearchClient` — PostgreSQL `document_chunk` + SQL permission filter (current chat default).
* `StubSearchClient` — no-op search; minimal index/delete (worker default unless `SEARCH_BACKEND` changes).
* `OpenSearchSearchClient` — `opensearch_stub.py`: validates payloads / builds query JSON; **no HTTP** until wired.

OpenSearch wiring (later)
-------------------------
* Add `opensearch-py` (or HTTP) dependency; inject base URL + auth from `Settings`.
* Indexer: replace `StubSearchClient` with HTTP client implementing the same `SearchClient` protocol.
* Chat: set `SEARCH_BACKEND` to the HTTP-backed client name when ready; keep `build_permission_filter_clause`
  from `opensearch_payload.py` aligned with SQL in `DbChunkSearchClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: UUID
    raw_document_id: UUID
    original_filename: str
    chunk_no: int
    section_title: str | None
    page_no: int | None
    chunk_text: str
    access_scope: str
    score: float


@dataclass(frozen=True, slots=True)
class PermissionPrincipal:
    """User-derived principal for query-time filter construction (server-side only)."""

    user_id: str
    department_codes: tuple[str, ...]


@runtime_checkable
class SearchClient(Protocol):
    """
    Pluggable search backend.

    Required for pipeline + chat:
    * **search** — chat RAG retrieval; MUST embed permission logic (OpenSearch `filter` or SQL `WHERE`).
    * **index_chunk_document** — indexer upsert; `_id` should equal `chunk_id` string per `docs/search-index.md`.
    * **delete_chunks_for_document** — admin exclude; delete-by-query on `raw_document_id` keyword field.
    """

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        """Return ranked hits; never widen results beyond `principal` (no post-filter of private rows)."""
        ...

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        """Upsert one chunk document (bulk line or `_doc` API). `document` keys: see `opensearch_payload.REQUIRED_CHUNK_INDEX_FIELDS`."""
        ...

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        """Remove all chunks for a document (admin exclude)."""
        ...
