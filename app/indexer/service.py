from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.adapters.search_protocol import SearchClient
from app.config.settings import Settings
from app.db.enums import ChunkIndexStatus, DocumentIndexRecordStatus, DocumentPipelineIndexStatus, IngestStatus
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_index_status import DocumentIndexStatus
from app.db.models.raw_document import RawDocument


log = logging.getLogger("contexthub.indexer")

INDEXER_BATCH_LIMIT = 100


@dataclass(slots=True)
class IndexerRunStats:
    pending_chunks: int = 0
    processed: int = 0
    failed: int = 0


def _chunk_source_document(chunk: DocumentChunk, raw: RawDocument) -> dict[str, Any]:
    """Payload aligned with `docs/search-index.md` (stub/OpenSearch field names)."""
    created: datetime | None = chunk.created_at
    meta = chunk.chunk_metadata_json if isinstance(chunk.chunk_metadata_json, dict) else None
    tx = chunk.chunk_text or ""
    char_n = chunk.chunk_char_count if chunk.chunk_char_count else len(tx)
    tok_n = chunk.chunk_token_estimate
    if not tok_n and tx:
        tok_n = max(1, (len(tx) + 3) // 4)
    elif not tx:
        tok_n = 0
    return {
        "chunk_id": str(chunk.chunk_id),
        "raw_document_id": str(chunk.raw_document_id),
        "original_filename": raw.original_filename,
        "inbox_path": (raw.inbox_path or "").replace("\\", "/"),
        "file_ext": raw.file_ext,
        "chunk_no": chunk.chunk_no,
        "section_title": chunk.section_title,
        "heading_path": chunk.heading_path,
        "page_no": chunk.page_no,
        "chunk_text": chunk.chunk_text,
        "chunk_char_count": char_n,
        "chunk_token_estimate": int(tok_n or 0),
        "chunk_metadata_json": meta if meta is not None else {},
        "access_scope": chunk.access_scope.value,
        "owner_id": chunk.owner_id,
        "department_code": chunk.department_code,
        "created_at": created.isoformat() if created else None,
    }


def _sync_raw_document_aggregate_index_status(
    session: Session, raw_document_id: UUID
) -> DocumentPipelineIndexStatus | None:
    """
    Set raw_document.index_status from chunk-level index_status.

    Requires up-to-date DB rows for counts (caller should flush pending chunk updates first
    if session.autoflush is off — global session uses autoflush=True).
    """
    total = int(
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.raw_document_id == raw_document_id)
        )
        or 0
    )
    if total == 0:
        return None

    doc = session.get(RawDocument, raw_document_id)
    if doc is None:
        return None

    done_n = int(
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.raw_document_id == raw_document_id,
                DocumentChunk.index_status == ChunkIndexStatus.DONE,
            )
        )
        or 0
    )
    failed_n = int(
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.raw_document_id == raw_document_id,
                DocumentChunk.index_status == ChunkIndexStatus.FAILED,
            )
        )
        or 0
    )

    previous = doc.index_status
    if failed_n > 0:
        doc.index_status = DocumentPipelineIndexStatus.FAILED
    elif done_n == total:
        doc.index_status = DocumentPipelineIndexStatus.DONE
    else:
        doc.index_status = DocumentPipelineIndexStatus.PENDING

    log.info(
        "raw_document aggregate index_status raw_document_id=%s chunks_total=%s done=%s failed=%s "
        "previous=%s new=%s",
        raw_document_id,
        total,
        done_n,
        failed_n,
        previous.value,
        doc.index_status.value,
    )
    return doc.index_status


class IndexerService:
    """Index worker: consume pending chunk index rows, push to search backend."""

    def __init__(self, session: Session, settings: Settings, search: SearchClient) -> None:
        self._session = session
        self._settings = settings
        self._search = search

    def _reconcile_stale_raw_index_aggregates(self, *, limit: int = 500) -> int:
        """
        Fix raw_document.index_status left PENDING after chunk rows were already indexed
        (e.g. historical bug: aggregate COUNT ran before flush). Idempotent.
        """
        has_chunks = exists(
            select(1)
            .select_from(DocumentChunk)
            .where(DocumentChunk.raw_document_id == RawDocument.raw_document_id)
        )
        stmt = (
            select(RawDocument.raw_document_id)
            .where(
                RawDocument.index_status == DocumentPipelineIndexStatus.PENDING,
                RawDocument.ingest_status == IngestStatus.RECEIVED,
                RawDocument.excluded.is_(False),
                has_chunks,
            )
            .limit(limit)
        )
        ids = list(self._session.scalars(stmt).all())
        for rid in ids:
            _sync_raw_document_aggregate_index_status(self._session, rid)
        if ids:
            log.info("reconciled raw_document index aggregate for %s document(s) (no pending chunks)", len(ids))
        return len(ids)

    def run_once(self) -> IndexerRunStats:
        index_name = self._settings.search_index_name

        pending_q = (
            select(func.count())
            .select_from(DocumentChunk)
            .join(RawDocument, DocumentChunk.raw_document_id == RawDocument.raw_document_id)
            .where(
                DocumentChunk.index_status == ChunkIndexStatus.PENDING,
                RawDocument.excluded.is_(False),
                RawDocument.ingest_status == IngestStatus.RECEIVED,
            )
        )
        pending = int(self._session.scalar(pending_q) or 0)
        log.info("pending index chunks=%s", pending)

        stats = IndexerRunStats(pending_chunks=pending, processed=0, failed=0)
        if pending == 0:
            n = self._reconcile_stale_raw_index_aggregates()
            if n:
                self._session.flush()
            return stats

        stmt = (
            select(DocumentChunk, RawDocument)
            .join(RawDocument, DocumentChunk.raw_document_id == RawDocument.raw_document_id)
            .where(
                DocumentChunk.index_status == ChunkIndexStatus.PENDING,
                RawDocument.excluded.is_(False),
                RawDocument.ingest_status == IngestStatus.RECEIVED,
            )
            .order_by(DocumentChunk.created_at.asc())
            .limit(INDEXER_BATCH_LIMIT)
        )
        rows = list(self._session.execute(stmt).all())

        affected_raw_ids: set[UUID] = set()

        for chunk, raw in rows:
            doc_id = str(chunk.chunk_id)
            payload = _chunk_source_document(chunk, raw)
            try:
                self._search.index_chunk_document(
                    index_name=index_name,
                    doc_id=doc_id,
                    document=payload,
                )
            except Exception as exc:
                err_text = str(exc)[:8000]
                log.exception(
                    "index failed chunk_id=%s raw_document_id=%s",
                    chunk.chunk_id,
                    chunk.raw_document_id,
                )
                chunk.index_status = ChunkIndexStatus.FAILED
                self._session.add(
                    DocumentIndexStatus(
                        chunk_id=chunk.chunk_id,
                        index_name=index_name,
                        opensearch_doc_id=None,
                        status=DocumentIndexRecordStatus.FAILED,
                        error_message=err_text,
                    )
                )
                stats.failed += 1
                affected_raw_ids.add(chunk.raw_document_id)
                continue

            chunk.index_status = ChunkIndexStatus.DONE
            self._session.add(
                DocumentIndexStatus(
                    chunk_id=chunk.chunk_id,
                    index_name=index_name,
                    opensearch_doc_id=doc_id,
                    status=DocumentIndexRecordStatus.DONE,
                    error_message=None,
                )
            )
            stats.processed += 1
            affected_raw_ids.add(chunk.raw_document_id)
            log.info(
                "indexed chunk_id=%s raw_document_id=%s chunk_no=%s index=%s",
                chunk.chunk_id,
                chunk.raw_document_id,
                chunk.chunk_no,
                index_name,
            )

        # Ensure chunk/index row mutations are visible to aggregate COUNT queries
        self._session.flush()

        for rid in affected_raw_ids:
            _sync_raw_document_aggregate_index_status(self._session, rid)

        log.info(
            "indexer batch finished processed=%s failed=%s (stub SearchClient; no real OpenSearch)",
            stats.processed,
            stats.failed,
        )
        return stats
