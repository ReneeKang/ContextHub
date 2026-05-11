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
    """Search backend abstraction: OpenSearch today, PostgreSQL FTS / vector later."""

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        """Must apply permission filter inside the search backend (no post-filter of private hits)."""
        ...

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        """Index or replace one chunk document."""
        ...

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        """Used when admin excludes a document from search."""
        ...
