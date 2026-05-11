from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.admin.schemas import (
    AdminDocumentDetailResponse,
    AdminDocumentListItem,
    AdminDocumentListResponse,
    AdminFailedDocumentItem,
    AdminFailedListResponse,
    AdminStatsResponse,
    ExcludeRequest,
    ExcludeResponse,
    IndexHistorySummary,
    ParseResultSummary,
    ReprocessRequest,
    ReprocessResponse,
)
from app.db.enums import (
    AccessScope,
    ChunkIndexStatus,
    ChunkStatus,
    DocumentIndexRecordStatus,
    DocumentPipelineIndexStatus,
    IngestStatus,
    ParseStatus,
)
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_index_status import DocumentIndexStatus
from app.db.models.document_parse_result import DocumentParseResult
from app.db.models.raw_document import RawDocument


def _enrich_list_aux_counts(
    session: Session, raw_ids: list[UUID]
) -> tuple[set[UUID], dict[UUID, int], dict[UUID, int]]:
    """Batch lookups: has parse_result, chunk counts, index_history counts."""
    if not raw_ids:
        return set(), {}, {}

    parse_ids = set(
        session.scalars(
            select(DocumentParseResult.raw_document_id).where(DocumentParseResult.raw_document_id.in_(raw_ids))
        ).all()
    )

    chunk_rows = session.execute(
        select(DocumentChunk.raw_document_id, func.count())
        .where(DocumentChunk.raw_document_id.in_(raw_ids))
        .group_by(DocumentChunk.raw_document_id)
    ).all()
    chunk_counts = {row[0]: int(row[1]) for row in chunk_rows}

    hist_rows = session.execute(
        select(DocumentChunk.raw_document_id, func.count(DocumentIndexStatus.index_status_id))
        .join(DocumentIndexStatus, DocumentIndexStatus.chunk_id == DocumentChunk.chunk_id)
        .where(DocumentChunk.raw_document_id.in_(raw_ids))
        .group_by(DocumentChunk.raw_document_id)
    ).all()
    hist_counts = {row[0]: int(row[1]) for row in hist_rows}

    return parse_ids, chunk_counts, hist_counts


def _index_history_summary(session: Session, raw_document_id: UUID) -> IndexHistorySummary:
    stmt = (
        select(
            func.count(DocumentIndexStatus.index_status_id),
            func.sum(case((DocumentIndexStatus.status == DocumentIndexRecordStatus.DONE, 1), else_=0)),
            func.sum(case((DocumentIndexStatus.status == DocumentIndexRecordStatus.FAILED, 1), else_=0)),
        )
        .select_from(DocumentIndexStatus)
        .join(DocumentChunk, DocumentIndexStatus.chunk_id == DocumentChunk.chunk_id)
        .where(DocumentChunk.raw_document_id == raw_document_id)
    )
    row = session.execute(stmt).one()
    total = int(row[0] or 0)
    done_n = int(row[1] or 0)
    failed_n = int(row[2] or 0)
    return IndexHistorySummary(total_records=total, done_records=done_n, failed_records=failed_n)


def _failure_reasons_for_document(
    doc: RawDocument,
    *,
    has_chunk_index_failed: bool,
) -> list[str]:
    reasons: list[str] = []
    if doc.parse_status == ParseStatus.FAILED:
        reasons.append("parse")
    if doc.chunk_status == ChunkStatus.FAILED:
        reasons.append("chunk")
    if doc.index_status == DocumentPipelineIndexStatus.FAILED:
        reasons.append("index")
    if has_chunk_index_failed:
        reasons.append("chunk_index")
    return reasons


def _failed_documents_filter(stage: str | None):
    chunk_index_failed_exists = exists(
        select(1)
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.raw_document_id == RawDocument.raw_document_id,
            DocumentChunk.index_status == ChunkIndexStatus.FAILED,
        )
    )

    any_failure = or_(
        RawDocument.parse_status == ParseStatus.FAILED,
        RawDocument.chunk_status == ChunkStatus.FAILED,
        RawDocument.index_status == DocumentPipelineIndexStatus.FAILED,
        chunk_index_failed_exists,
    )

    if stage == "parse":
        return RawDocument.parse_status == ParseStatus.FAILED
    if stage == "chunk":
        return RawDocument.chunk_status == ChunkStatus.FAILED
    if stage == "index":
        return or_(
            RawDocument.index_status == DocumentPipelineIndexStatus.FAILED,
            chunk_index_failed_exists,
        )
    return any_failure


class AdminService:
    """admin-api persistence operations (no worker orchestration)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_documents(
        self,
        *,
        page: int,
        per_page: int,
        ingest_status: IngestStatus | None,
        parse_status: ParseStatus | None,
        chunk_status: ChunkStatus | None,
        index_status: DocumentPipelineIndexStatus | None,
        access_scope: AccessScope | None,
    ) -> AdminDocumentListResponse:
        filters: list = []
        if ingest_status is not None:
            filters.append(RawDocument.ingest_status == ingest_status)
        if parse_status is not None:
            filters.append(RawDocument.parse_status == parse_status)
        if chunk_status is not None:
            filters.append(RawDocument.chunk_status == chunk_status)
        if index_status is not None:
            filters.append(RawDocument.index_status == index_status)
        if access_scope is not None:
            filters.append(RawDocument.access_scope == access_scope)

        stmt = select(RawDocument)
        count_stmt = select(func.count()).select_from(RawDocument)
        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total = int(self._session.scalar(count_stmt) or 0)

        rows = list(
            self._session.scalars(
                stmt.order_by(RawDocument.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            ).all()
        )

        ids = [r.raw_document_id for r in rows]
        parse_ids, chunk_counts, hist_counts = _enrich_list_aux_counts(self._session, ids)

        items = [
            AdminDocumentListItem(
                raw_document_id=r.raw_document_id,
                original_filename=r.original_filename,
                inbox_path=r.inbox_path,
                stored_path=r.stored_path,
                access_scope=r.access_scope.value,
                ingest_status=r.ingest_status.value,
                parse_status=r.parse_status.value,
                chunk_status=r.chunk_status.value,
                index_status=r.index_status.value,
                has_parse_result=r.raw_document_id in parse_ids,
                chunk_count=chunk_counts.get(r.raw_document_id, 0),
                index_history_count=hist_counts.get(r.raw_document_id, 0),
                created_at=r.created_at,
            )
            for r in rows
        ]
        return AdminDocumentListResponse(total=total, page=page, per_page=per_page, items=items)

    def get_document(self, raw_document_id: UUID) -> AdminDocumentDetailResponse | None:
        doc = self._session.get(RawDocument, raw_document_id)
        if doc is None:
            return None

        chunk_count = int(
            self._session.scalar(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.raw_document_id == raw_document_id)
            )
            or 0
        )
        indexed_chunk_count = int(
            self._session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.raw_document_id == raw_document_id,
                    DocumentChunk.index_status == ChunkIndexStatus.DONE,
                )
            )
            or 0
        )

        pr = self._session.scalar(
            select(DocumentParseResult).where(DocumentParseResult.raw_document_id == raw_document_id)
        )
        has_parse = pr is not None
        if pr is not None:
            md_len = len(pr.markdown_text or "")
            parse_summary = ParseResultSummary(
                exists=True,
                parser_name=pr.parser_name,
                parser_version=pr.parser_version,
                markdown_char_count=md_len,
                parsed_at=pr.parsed_at,
            )
        else:
            parse_summary = ParseResultSummary(exists=False)

        idx_hist = _index_history_summary(self._session, raw_document_id)

        return AdminDocumentDetailResponse(
            raw_document_id=doc.raw_document_id,
            original_filename=doc.original_filename,
            stored_path=doc.stored_path,
            inbox_path=doc.inbox_path,
            file_ext=doc.file_ext,
            file_size=doc.file_size,
            sha256_hash=doc.sha256_hash,
            access_scope=doc.access_scope.value,
            ingest_status=doc.ingest_status.value,
            parse_status=doc.parse_status.value,
            chunk_status=doc.chunk_status.value,
            index_status=doc.index_status.value,
            chunk_count=chunk_count,
            indexed_chunk_count=indexed_chunk_count,
            has_parse_result=has_parse,
            parse_result=parse_summary,
            index_history=idx_hist,
            excluded=doc.excluded,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    def list_failed(
        self,
        *,
        stage: str | None,
        page: int,
        per_page: int,
    ) -> AdminFailedListResponse:
        flt = _failed_documents_filter(stage)
        count_stmt = select(func.count()).select_from(RawDocument).where(flt)
        total = int(self._session.scalar(count_stmt) or 0)

        stmt = (
            select(RawDocument)
            .where(flt)
            .order_by(RawDocument.updated_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = list(self._session.scalars(stmt).all())

        ids = [r.raw_document_id for r in rows]
        chunk_failed_doc_ids: set[UUID] = set()
        if ids:
            chunk_failed_doc_ids = set(
                self._session.scalars(
                    select(DocumentChunk.raw_document_id)
                    .distinct()
                    .where(
                        DocumentChunk.raw_document_id.in_(ids),
                        DocumentChunk.index_status == ChunkIndexStatus.FAILED,
                    )
                ).all()
            )

        items = [
            AdminFailedDocumentItem(
                raw_document_id=r.raw_document_id,
                original_filename=r.original_filename,
                inbox_path=r.inbox_path,
                stored_path=r.stored_path,
                access_scope=r.access_scope.value,
                ingest_status=r.ingest_status.value,
                parse_status=r.parse_status.value,
                chunk_status=r.chunk_status.value,
                index_status=r.index_status.value,
                failure_reasons=_failure_reasons_for_document(
                    r,
                    has_chunk_index_failed=r.raw_document_id in chunk_failed_doc_ids,
                ),
                created_at=r.created_at,
            )
            for r in rows
        ]

        return AdminFailedListResponse(total=total, page=page, per_page=per_page, items=items)

    def reprocess(self, raw_document_id: UUID, body: ReprocessRequest) -> ReprocessResponse | None:
        _ = (raw_document_id, body)
        return None

    def exclude(self, raw_document_id: UUID, body: ExcludeRequest) -> ExcludeResponse | None:
        _ = (raw_document_id, body)
        return None

    def stats(self) -> AdminStatsResponse:
        return AdminStatsResponse(
            total_documents=0,
            ingest={"RECEIVED": 0, "DUPLICATE": 0, "FAILED": 0},
            parse={"PENDING": 0, "DONE": 0, "FAILED": 0},
            chunk={"PENDING": 0, "DONE": 0, "FAILED": 0},
            index={"PENDING": 0, "DONE": 0, "FAILED": 0},
        )
