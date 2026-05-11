from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import (
    AccessScope,
    ChunkStatus,
    DocumentPipelineIndexStatus,
    IngestStatus,
    ParseStatus,
    SourceType,
)


class RawDocument(Base):
    __tablename__ = "raw_document"

    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, native_enum=False, length=50),
        default=SourceType.NAS,
    )
    inbox_path: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_ext: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    access_scope: Mapped[AccessScope] = mapped_column(
        SAEnum(AccessScope, native_enum=False, length=20),
        nullable=False,
    )
    owner_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    ingest_status: Mapped[IngestStatus] = mapped_column(
        SAEnum(IngestStatus, native_enum=False, length=20),
        default=IngestStatus.RECEIVED,
    )
    parse_status: Mapped[ParseStatus] = mapped_column(
        SAEnum(ParseStatus, native_enum=False, length=20),
        default=ParseStatus.PENDING,
    )
    chunk_status: Mapped[ChunkStatus] = mapped_column(
        SAEnum(ChunkStatus, native_enum=False, length=20),
        default=ChunkStatus.PENDING,
    )
    index_status: Mapped[DocumentPipelineIndexStatus] = mapped_column(
        SAEnum(DocumentPipelineIndexStatus, native_enum=False, length=20),
        default=DocumentPipelineIndexStatus.PENDING,
    )

    duplicate_of_raw_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_document.raw_document_id"),
        nullable=True,
    )

    excluded: Mapped[bool] = mapped_column(default=False, nullable=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    duplicate_of: Mapped["RawDocument | None"] = relationship(
        "RawDocument",
        remote_side=[raw_document_id],
        foreign_keys=[duplicate_of_raw_document_id],
    )
    parse_result: Mapped["DocumentParseResult | None"] = relationship(
        "DocumentParseResult",
        back_populates="raw_document",
        uselist=False,
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="raw_document",
    )

    __table_args__ = (
        Index(
            "idx_raw_document_parse_status",
            "parse_status",
            postgresql_where=text("parse_status = 'PENDING'"),
        ),
        Index(
            "idx_raw_document_chunk_status",
            "chunk_status",
            postgresql_where=text("chunk_status = 'PENDING'"),
        ),
        Index(
            "idx_raw_document_index_status",
            "index_status",
            postgresql_where=text("index_status = 'PENDING'"),
        ),
        Index(
            "idx_raw_document_sha256",
            "sha256_hash",
            unique=True,
            postgresql_where=text("ingest_status = 'RECEIVED'"),
        ),
    )
