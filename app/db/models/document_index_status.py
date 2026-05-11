from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import DocumentIndexRecordStatus


class DocumentIndexStatus(Base):
    __tablename__ = "document_index_status"

    index_status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunk.chunk_id"),
        nullable=False,
    )

    index_name: Mapped[str] = mapped_column(String(100), nullable=False)
    opensearch_doc_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[DocumentIndexRecordStatus] = mapped_column(
        SAEnum(DocumentIndexRecordStatus, native_enum=False, length=20),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )

    chunk: Mapped[object] = relationship("DocumentChunk", back_populates="index_records")

    __table_args__ = (Index("idx_doc_index_status_chunk", "chunk_id"),)
