from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentParseResult(Base):
    __tablename__ = "document_parse_result"

    parse_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_document.raw_document_id"),
        nullable=False,
        unique=True,
    )

    parser_name: Mapped[str] = mapped_column(String(100), default="kordoc", nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)

    markdown_text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON tree: keep runtime typing loose for SQLAlchemy annotation parsing.
    blocks_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    page_count: Mapped[int | None] = mapped_column(nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )

    raw_document: Mapped[object] = relationship("RawDocument", back_populates="parse_result")
