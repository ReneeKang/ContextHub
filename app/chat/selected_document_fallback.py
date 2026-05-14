"""
Load indexed chunks for explicitly selected ``raw_document_id`` values (generate-only fallback).

Used when ``document_ids`` is set but keyword retrieval + filter yields no hits — e.g. pronoun-heavy
questions that do not match BM25 terms. Same permission and ingest/index gates as ``DbChunkSearchClient``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db_chunk_search import document_chunk_read_permission_predicate
from app.adapters.search_protocol import PermissionPrincipal, SearchHit
from app.db.enums import ChunkIndexStatus, IngestStatus
from app.db.models.document_chunk import DocumentChunk
from app.db.models.raw_document import RawDocument

# Slightly lower than search placeholder so logs can distinguish fallback hits if needed.
_FALLBACK_HIT_SCORE = 0.0


def load_chunks_for_selected_documents(
    session: Session,
    principal: PermissionPrincipal,
    document_ids: list[UUID],
    *,
    top_k: int,
) -> list[SearchHit]:
    """
    Return up to ``top_k`` chunks from the given documents, ordered by ``raw_document_id`` then ``chunk_no``.

    Documents the principal cannot read contribute no rows (same predicate as DB search).
    """
    if not document_ids or top_k < 1:
        return []
    ordered_ids = list(dict.fromkeys(document_ids))
    stmt = (
        select(DocumentChunk, RawDocument.original_filename)
        .join(RawDocument, DocumentChunk.raw_document_id == RawDocument.raw_document_id)
        .where(
            DocumentChunk.raw_document_id.in_(ordered_ids),
            DocumentChunk.index_status == ChunkIndexStatus.DONE,
            RawDocument.excluded.is_(False),
            RawDocument.ingest_status == IngestStatus.RECEIVED,
            document_chunk_read_permission_predicate(principal),
        )
        .order_by(DocumentChunk.raw_document_id.asc(), DocumentChunk.chunk_no.asc())
        .limit(top_k)
    )
    rows = list(session.execute(stmt).all())
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
                score=_FALLBACK_HIT_SCORE,
                highlights=None,
            )
        )
    return hits
