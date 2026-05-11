from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.parser_protocol import ParseRequest, ParserClient
from app.config.settings import Settings
from app.db.enums import IngestStatus, ParseStatus
from app.db.models.document_parse_result import DocumentParseResult
from app.db.models.raw_document import RawDocument


log = logging.getLogger("contexthub.parser")

# Single-transaction batch size (PoC); tune when adding heavy files.
PARSER_BATCH_LIMIT = 50


@dataclass(slots=True)
class ParserRunStats:
    pending_documents: int = 0
    processed: int = 0
    failed: int = 0


class ParserService:
    """Parse worker: consume `parse_status=PENDING`, call parser adapter, persist parse results."""

    def __init__(self, session: Session, settings: Settings, parser: ParserClient) -> None:
        self._session = session
        self._settings = settings
        self._parser = parser

    def run_once(self) -> ParserRunStats:
        pending_q = select(func.count()).select_from(RawDocument).where(
            RawDocument.parse_status == ParseStatus.PENDING,
            RawDocument.ingest_status == IngestStatus.RECEIVED,
            RawDocument.excluded.is_(False),
        )
        pending = int(self._session.scalar(pending_q) or 0)
        log.info("pending parse documents=%s", pending)

        stats = ParserRunStats(pending_documents=pending, processed=0, failed=0)
        if pending == 0:
            return stats

        stmt = (
            select(RawDocument)
            .where(
                RawDocument.parse_status == ParseStatus.PENDING,
                RawDocument.ingest_status == IngestStatus.RECEIVED,
                RawDocument.excluded.is_(False),
            )
            .order_by(RawDocument.created_at.asc())
            .limit(PARSER_BATCH_LIMIT)
        )
        documents = list(self._session.scalars(stmt).all())

        for doc in documents:
            existing = self._session.scalar(
                select(DocumentParseResult).where(DocumentParseResult.raw_document_id == doc.raw_document_id)
            )
            if existing is not None:
                log.warning(
                    "parse_result already exists for raw_document_id=%s; marking DONE without re-parse",
                    doc.raw_document_id,
                )
                doc.parse_status = ParseStatus.DONE
                continue

            path = Path(doc.stored_path)
            try:
                file_bytes = path.read_bytes()
            except OSError:
                log.exception("failed to read file for raw_document_id=%s path=%s", doc.raw_document_id, path)
                doc.parse_status = ParseStatus.FAILED
                stats.failed += 1
                continue

            mime_raw, _ = mimetypes.guess_type(doc.original_filename or "")
            mime_type = mime_raw.lower() if mime_raw else None
            request = ParseRequest(
                file_bytes=file_bytes,
                file_ext=doc.file_ext,
                original_filename=doc.original_filename,
                mime_type=mime_type,
            )
            try:
                result = self._parser.parse(request)
            except Exception:
                log.exception("parser raised for raw_document_id=%s", doc.raw_document_id)
                doc.parse_status = ParseStatus.FAILED
                stats.failed += 1
                continue

            self._session.add(
                DocumentParseResult(
                    raw_document_id=doc.raw_document_id,
                    parser_name=result.parser_name or self._settings.parser_name,
                    parser_version=result.parser_version or self._settings.parser_version,
                    markdown_text=result.markdown_text,
                    blocks_json=result.blocks_json,
                    metadata_json=result.metadata_json,
                    page_count=result.page_count,
                )
            )
            doc.parse_status = ParseStatus.DONE
            # chunk_status / index_status unchanged per design (chunk stays PENDING)
            stats.processed += 1
            log.info(
                "parsed raw_document_id=%s parser=%s version=%s markdown_chars=%s",
                doc.raw_document_id,
                result.parser_name or self._settings.parser_name,
                result.parser_version or self._settings.parser_version,
                len(result.markdown_text),
            )

        log.info(
            "parser batch finished processed=%s failed=%s (remaining pending on next run if batch limited)",
            stats.processed,
            stats.failed,
        )
        return stats
