from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawDocumentScanState(Base):
    __tablename__ = "raw_document_scan_state"

    scan_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    file_path: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    file_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    mtime: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    stable: Mapped[bool] = mapped_column(default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False
    )
