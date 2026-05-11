from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    question: str
    top_k: int | None = Field(default=5, ge=1, le=50)
    session_id: str | None = None


class ChatSourceItem(BaseModel):
    chunk_id: UUID
    raw_document_id: UUID
    original_filename: str
    chunk_no: int
    section_title: str | None = None
    page_no: int | None = None
    score: float
    access_scope: str


class ChatQueryResponse(BaseModel):
    answer: str
    sources: list[ChatSourceItem]
    session_id: str | None = None
