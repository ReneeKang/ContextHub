"""
DEV-ONLY, PostgreSQL-only schema patches.

This is **not** a production migration system and **not** a substitute for Alembic.
Use only in local / dev databases when `Base.metadata.create_all()` has already run
and you need additive columns without dropping data.

Safe properties:
- Uses `ADD COLUMN IF NOT EXISTS` (no destructive DDL).
- Skips work when columns already exist (PostgreSQL treats IF NOT EXISTS as no-op).
- Logs each step; on failure, logs which statement label failed then re-raises.

Run: ``python -m app.db.dev_migrations``
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import text

from app.db.session import get_engine

log = logging.getLogger("contexthub.dev_migrations")

# (label for logs, SQL) — PostgreSQL syntax only.
_RAW_DOCUMENT_PATCHES: tuple[tuple[str, str], ...] = (
    (
        "raw_document.parse_error_message",
        "ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS parse_error_message TEXT",
    ),
)

_DOCUMENT_CHUNK_PATCHES: tuple[tuple[str, str], ...] = (
    (
        "document_chunk.heading_path",
        "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS heading_path TEXT",
    ),
    (
        "document_chunk.chunk_char_count",
        "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_char_count INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "document_chunk.chunk_token_estimate",
        "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_token_estimate INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "document_chunk.chunk_metadata_json",
        "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_metadata_json JSONB",
    ),
)


def apply_raw_document_dev_columns() -> None:
    """Apply additive `raw_document` columns; idempotent on PostgreSQL."""
    engine = get_engine()
    for label, ddl in _RAW_DOCUMENT_PATCHES:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            log.info("dev migration ok: %s", label)
        except Exception:
            log.exception("dev migration FAILED on step: %s — ddl=%r", label, ddl)
            raise


def apply_document_chunk_dev_columns() -> None:
    """Apply additive `document_chunk` columns; idempotent on PostgreSQL."""
    engine = get_engine()
    for label, ddl in _DOCUMENT_CHUNK_PATCHES:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            log.info("dev migration ok: %s", label)
        except Exception:
            log.exception("dev migration FAILED on step: %s — ddl=%r", label, ddl)
            raise


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log.warning(
        "Running DEV-ONLY migrations (PostgreSQL). Do not use this as a production migration path."
    )
    apply_raw_document_dev_columns()
    apply_document_chunk_dev_columns()
    log.info("dev migrations finished successfully.")


if __name__ == "__main__":
    main()
