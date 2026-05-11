"""
PostgreSQL-backed chunk search for chat PoC (OpenSearch stand-in).

Applies the same permission shape as `docs/permission-policy.md` / OpenSearch filter:
PUBLIC OR (DEPT AND dept IN user departments) OR (PRIVATE AND owner_id = user_id).

Replace with OpenSearchSearchClient when wiring a real cluster; keep SearchClient protocol.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.db.enums import AccessScope, ChunkIndexStatus, IngestStatus
from app.db.models.document_chunk import DocumentChunk
from app.db.models.raw_document import RawDocument


log = logging.getLogger("contexthub.db_chunk_search")

_MAX_TERMS = 12


def _escape_ilike_pattern(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tokenize_question(q: str) -> list[str]:
    q = q.strip()
    if not q:
        return []
    parts = re.split(r"\s+", q)
    return [p for p in parts if len(p) >= 1][: _MAX_TERMS]


def _permission_filter(principal: PermissionPrincipal):
    """Rows the principal may read (SQL OR, evaluated in the database)."""
    public = DocumentChunk.access_scope == AccessScope.PUBLIC

    if principal.department_codes:
        dept = and_(
            DocumentChunk.access_scope == AccessScope.DEPT,
            DocumentChunk.department_code.in_(list(principal.department_codes)),
        )
    else:
        dept = false()

    private = and_(
        DocumentChunk.access_scope == AccessScope.PRIVATE,
        DocumentChunk.owner_id == principal.user_id,
    )
    return or_(public, dept, private)


class DbChunkSearchClient(SearchClient):
    """SearchClient implementation using document_chunk + raw_document (no OpenSearch)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        _ = index_name  # reserved for index routing when OpenSearch exists
        terms = _tokenize_question(query)
        if not terms:
            log.info("empty search query after tokenize; returning no hits")
            return []

        text_predicates = []
        for t in terms:
            pat = f"%{_escape_ilike_pattern(t)}%"
            text_predicates.append(
                or_(
                    DocumentChunk.chunk_text.ilike(pat, escape="\\"),
                    DocumentChunk.section_title.ilike(pat, escape="\\"),
                )
            )
        text_clause = and_(*text_predicates) if text_predicates else false()

        stmt = (
            select(DocumentChunk, RawDocument.original_filename)
            .join(RawDocument, DocumentChunk.raw_document_id == RawDocument.raw_document_id)
            .where(
                DocumentChunk.index_status == ChunkIndexStatus.DONE,
                RawDocument.excluded.is_(False),
                RawDocument.ingest_status == IngestStatus.RECEIVED,
                _permission_filter(principal),
                text_clause,
            )
            .order_by(DocumentChunk.created_at.asc())
            .limit(top_k)
        )

        rows = list(self._session.execute(stmt).all())
        hits: list[SearchHit] = []
        for chunk, original_filename in rows:
            hits.append(
                SearchHit(
                    chunk_id=chunk.chunk_id,
                    raw_document_id=chunk.raw_document_id,
                    original_filename=original_filename,
                    chunk_no=chunk.chunk_no,
                    section_title=chunk.section_title,
                    page_no=chunk.page_no,
                    chunk_text=chunk.chunk_text,
                    access_scope=chunk.access_scope.value,
                    score=1.0,
                )
            )
        log.info(
            "db chunk search query=%r principal_user=%s dept_codes=%s hits=%s",
            query[:200],
            principal.user_id,
            principal.department_codes,
            len(hits),
        )
        return hits

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        _ = (index_name, doc_id, document)
        raise NotImplementedError("DbChunkSearchClient is chat-read only; use indexer stub/OpenSearch adapter")

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        _ = (index_name, raw_document_id)
        raise NotImplementedError("DbChunkSearchClient is chat-read only; use indexer stub/OpenSearch adapter")
