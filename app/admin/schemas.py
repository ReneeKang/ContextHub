from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AdminDocumentListItem(BaseModel):
    raw_document_id: UUID
    original_filename: str
    """Official inbox-relative path (design: inbox_path)."""
    inbox_path: str
    """Absolute NAS path as stored at ingest."""
    stored_path: str
    access_scope: str
    ingest_status: str
    parse_status: str
    chunk_status: str
    index_status: str
    has_parse_result: bool = Field(description="Whether document_parse_result exists")
    chunk_count: int = Field(description="Number of document_chunk rows")
    index_history_count: int = Field(
        description="Rows in document_index_status for chunks of this document"
    )
    created_at: datetime


class AdminDocumentListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[AdminDocumentListItem]


class ParseResultSummary(BaseModel):
    exists: bool
    parser_name: str | None = None
    parser_version: str | None = None
    markdown_char_count: int | None = None
    parsed_at: datetime | None = None


class IndexHistorySummary(BaseModel):
    """Aggregate over document_index_status rows linked via document_chunk."""

    total_records: int
    done_records: int
    failed_records: int


class AdminDocumentDetailResponse(BaseModel):
    raw_document_id: UUID
    original_filename: str
    stored_path: str
    inbox_path: str
    file_ext: str
    file_size: int
    sha256_hash: str
    access_scope: str
    ingest_status: str
    parse_status: str
    chunk_status: str
    index_status: str
    chunk_count: int
    indexed_chunk_count: int
    has_parse_result: bool
    parse_result: ParseResultSummary | None = None
    index_history: IndexHistorySummary | None = None
    excluded: bool
    created_at: datetime
    updated_at: datetime


class AdminFailedDocumentItem(BaseModel):
    raw_document_id: UUID
    original_filename: str
    inbox_path: str
    stored_path: str
    access_scope: str
    ingest_status: str
    parse_status: str
    chunk_status: str
    index_status: str
    failure_reasons: list[str] = Field(
        description="Which stages are FAILED (parse / chunk / index_doc / chunk_index)"
    )
    created_at: datetime


class AdminFailedListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[AdminFailedDocumentItem]


class ReprocessRequest(BaseModel):
    stage: Literal["parse", "chunk", "index"]


class ReprocessResponse(BaseModel):
    raw_document_id: UUID
    stage: str
    result: str


class ExcludeRequest(BaseModel):
    reason: str


class ExcludeResponse(BaseModel):
    raw_document_id: UUID
    excluded: bool


class AdminStatsResponse(BaseModel):
    total_documents: int
    ingest: dict[str, int]
    parse: dict[str, int]
    chunk: dict[str, int]
    index: dict[str, int]
