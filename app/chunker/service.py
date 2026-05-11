from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chunker.markdown_chunk import (
    build_chunks_from_markdown,
    chunk_metadata_for_piece,
    estimate_token_count,
)
from app.config.settings import Settings
from app.db.enums import ChunkIndexStatus, ChunkStatus, IngestStatus, ParseStatus
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_parse_result import DocumentParseResult
from app.db.models.raw_document import RawDocument


log = logging.getLogger("contexthub.chunker")

CHUNKER_BATCH_LIMIT = 50


@dataclass(slots=True)
class ChunkerRunStats:
    pending_documents: int = 0
    processed: int = 0
    failed: int = 0
    chunks_created: int = 0


class ChunkerService:
    """Chunk worker: consume `chunk_status=PENDING`, split markdown, persist `document_chunk`."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def run_once(self) -> ChunkerRunStats:
        """
        Process one batch of pending chunk work.

        Policy:
        - Missing `document_parse_result` → chunk_status FAILED (cannot chunk).
        - Empty `markdown_text` (after strip) → FAILED (nothing to index meaningfully).
        - Existing `document_chunk` rows for this raw_document → reconcile chunk_status=DONE
          without inserting duplicates (orphan recovery).
        """
        _ = self._settings

        eligible_filters = (
            RawDocument.chunk_status == ChunkStatus.PENDING,
            RawDocument.parse_status == ParseStatus.DONE,
            RawDocument.ingest_status == IngestStatus.RECEIVED,
            RawDocument.excluded.is_(False),
        )
        pending_q = select(func.count()).select_from(RawDocument).where(*eligible_filters)
        pending = int(self._session.scalar(pending_q) or 0)
        log.info("pending chunk documents (parse=DONE, eligible)=%s", pending)

        waiting_parser = int(
            self._session.scalar(
                select(func.count())
                .select_from(RawDocument)
                .where(
                    RawDocument.chunk_status == ChunkStatus.PENDING,
                    RawDocument.parse_status != ParseStatus.DONE,
                    RawDocument.ingest_status == IngestStatus.RECEIVED,
                    RawDocument.excluded.is_(False),
                )
            )
            or 0
        )
        if waiting_parser:
            log.info(
                "documents waiting on parser (chunk=PENDING but parse!=DONE)=%s — run parser worker first",
                waiting_parser,
            )

        stats = ChunkerRunStats(pending_documents=pending, processed=0, failed=0, chunks_created=0)
        if pending == 0:
            return stats

        stmt = (
            select(RawDocument)
            .where(*eligible_filters)
            .order_by(RawDocument.created_at.asc())
            .limit(CHUNKER_BATCH_LIMIT)
        )
        documents = list(self._session.scalars(stmt).all())

        for doc in documents:
            existing_n = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.raw_document_id == doc.raw_document_id)
                )
                or 0
            )
            if existing_n > 0:
                log.warning(
                    "document_chunk rows already exist for raw_document_id=%s (n=%s); "
                    "marking chunk_status=DONE without duplicate inserts",
                    doc.raw_document_id,
                    existing_n,
                )
                doc.chunk_status = ChunkStatus.DONE
                continue

            pr = self._session.scalar(
                select(DocumentParseResult).where(DocumentParseResult.raw_document_id == doc.raw_document_id)
            )
            if pr is None:
                log.error(
                    "no document_parse_result for raw_document_id=%s; chunk_status=FAILED",
                    doc.raw_document_id,
                )
                doc.chunk_status = ChunkStatus.FAILED
                stats.failed += 1
                continue

            md = (pr.markdown_text or "").strip()
            if not md:
                log.error(
                    "empty markdown_text for raw_document_id=%s; chunk_status=FAILED",
                    doc.raw_document_id,
                )
                doc.chunk_status = ChunkStatus.FAILED
                stats.failed += 1
                continue

            pieces = build_chunks_from_markdown(md, fallback_filename=doc.original_filename)
            if not pieces:
                log.error(
                    "chunking produced no segments for raw_document_id=%s; chunk_status=FAILED",
                    doc.raw_document_id,
                )
                doc.chunk_status = ChunkStatus.FAILED
                stats.failed += 1
                continue

            meta = chunk_metadata_for_piece()
            for i, piece in enumerate(pieces, start=1):
                text = piece.text
                char_n = len(text)
                self._session.add(
                    DocumentChunk(
                        raw_document_id=doc.raw_document_id,
                        chunk_no=i,
                        section_title=piece.section_title,
                        page_no=piece.source_page,
                        heading_path=piece.heading_path,
                        chunk_text=text,
                        chunk_char_count=char_n,
                        chunk_token_estimate=estimate_token_count(text),
                        chunk_metadata_json=meta,
                        access_scope=doc.access_scope,
                        owner_id=doc.owner_id,
                        department_code=doc.department_code,
                        index_status=ChunkIndexStatus.PENDING,
                    )
                )
                stats.chunks_created += 1

            doc.chunk_status = ChunkStatus.DONE
            # index_status stays PENDING until indexer runs
            stats.processed += 1
            log.info(
                "chunked raw_document_id=%s chunks_created=%s chunk_status=DONE",
                doc.raw_document_id,
                len(pieces),
            )

        log.info(
            "chunker batch finished processed=%s failed=%s chunks_created=%s",
            stats.processed,
            stats.failed,
            stats.chunks_created,
        )
        return stats
