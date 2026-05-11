from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.admin.deps import get_db
from app.admin.schemas import (
    AdminDocumentDetailResponse,
    AdminDocumentListResponse,
    AdminFailedListResponse,
    AdminStatsResponse,
    ExcludeRequest,
    ExcludeResponse,
    ReprocessRequest,
    ReprocessResponse,
)
from app.admin.service import AdminService
from app.db.enums import (
    AccessScope,
    ChunkStatus,
    DocumentPipelineIndexStatus,
    IngestStatus,
    ParseStatus,
)

router = APIRouter()


@router.get("/documents/failed", response_model=AdminFailedListResponse)
def get_failed_documents(
    stage: Literal["parse", "chunk", "index"] | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    size: int | None = Query(default=None, ge=1, le=200, description="Alias for per_page (page size)"),
    db: Session = Depends(get_db),
) -> AdminFailedListResponse:
    limit = size if size is not None else per_page
    return AdminService(db).list_failed(stage=stage, page=page, per_page=limit)


@router.get("/documents", response_model=AdminDocumentListResponse)
def list_documents(
    ingest_status: IngestStatus | None = None,
    parse_status: ParseStatus | None = None,
    chunk_status: ChunkStatus | None = None,
    index_status: DocumentPipelineIndexStatus | None = None,
    access_scope: AccessScope | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    size: int | None = Query(default=None, ge=1, le=200, description="Alias for per_page (page size)"),
    db: Session = Depends(get_db),
) -> AdminDocumentListResponse:
    limit = size if size is not None else per_page
    return AdminService(db).list_documents(
        page=page,
        per_page=limit,
        ingest_status=ingest_status,
        parse_status=parse_status,
        chunk_status=chunk_status,
        index_status=index_status,
        access_scope=access_scope,
    )


@router.get("/documents/{raw_document_id}", response_model=AdminDocumentDetailResponse)
def get_document(raw_document_id: UUID, db: Session = Depends(get_db)) -> AdminDocumentDetailResponse:
    item = AdminService(db).get_document(raw_document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
    return item


@router.post("/documents/{raw_document_id}/reprocess", response_model=ReprocessResponse)
def reprocess_document(
    raw_document_id: UUID,
    body: ReprocessRequest,
    db: Session = Depends(get_db),
) -> ReprocessResponse:
    result = AdminService(db).reprocess(raw_document_id, body)
    if result is None:
        raise HTTPException(status_code=501, detail="Not implemented in PoC skeleton")
    return result


@router.post("/documents/{raw_document_id}/exclude", response_model=ExcludeResponse)
def exclude_document(
    raw_document_id: UUID,
    body: ExcludeRequest,
    db: Session = Depends(get_db),
) -> ExcludeResponse:
    result = AdminService(db).exclude(raw_document_id, body)
    if result is None:
        raise HTTPException(status_code=501, detail="Not implemented in PoC skeleton")
    return result


@router.get("/stats", response_model=AdminStatsResponse)
def get_stats(db: Session = Depends(get_db)) -> AdminStatsResponse:
    return AdminService(db).stats()
