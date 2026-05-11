from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import AccessScope, ChunkIndexStatus


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_document.raw_document_id"),
        nullable=False,
    )

    chunk_no: Mapped[int] = mapped_column(nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Logical source page (e.g. PDF); mirrors index `page_no` / search filters.
    page_no: Mapped[int | None] = mapped_column(nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_char_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("0"))
    chunk_token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("0"))
    chunk_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    access_scope: Mapped[AccessScope] = mapped_column(
        SAEnum(AccessScope, native_enum=False, length=20),
        nullable=False,
    )
    owner_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    index_status: Mapped[ChunkIndexStatus] = mapped_column(
        SAEnum(ChunkIndexStatus, native_enum=False, length=20),
        default=ChunkIndexStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )

    raw_document: Mapped[object] = relationship("RawDocument", back_populates="chunks")
    index_records: Mapped[list[object]] = relationship(
        "DocumentIndexStatus",
        back_populates="chunk",
    )

    __table_args__ = (
        Index("idx_document_chunk_raw_doc", "raw_document_id"),
        Index(
            "idx_document_chunk_idx_status",
            "index_status",
            postgresql_where=text("index_status = 'PENDING'"),
        ),
    )
