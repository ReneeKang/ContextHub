"""
**Development only:** drop the OpenSearch chunk index, recreate it with the same
body as ``opensearch_bootstrap``, and reset PostgreSQL indexing state so the
worker re-indexes chunks.

* **Do not use in production** — destructive to the OpenSearch index and DB index
  state for the configured ``SEARCH_INDEX_NAME``.
* Does **not** change search adapters, permission filters, or ``SearchClient`` wiring.

``document_index_status``: rows whose ``index_name`` matches ``SEARCH_INDEX_NAME``
are **deleted** so admin/history counts stay aligned with a fresh re-index (see README).

Run: ``python -m app.db.opensearch_reset_dev``

Requires ``OPENSEARCH_BASE_URL`` and ``DATABASE_URL`` (same as local dev stack).
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import delete, update

from app.adapters.opensearch_client import opensearch_client_from_settings
from app.adapters.opensearch_index_mapping import chunk_index_create_body
from app.config.settings import get_settings
from app.db.enums import ChunkIndexStatus, DocumentPipelineIndexStatus
from app.db.models.document_chunk import DocumentChunk
from app.db.models.document_index_status import DocumentIndexStatus
from app.db.models.raw_document import RawDocument
from app.db.session import get_session_factory

log = logging.getLogger("contexthub.opensearch_reset_dev")


def reset_dev_opensearch_and_db() -> None:
    settings = get_settings()
    index_name = settings.search_index_name

    raw_url = (settings.opensearch_base_url or "").strip()
    if not raw_url:
        raise SystemExit(
            "OPENSEARCH_BASE_URL is not set. Set it in .env (e.g. http://127.0.0.1:9201) "
            "before running this dev-only reset."
        )

    client = opensearch_client_from_settings(settings)

    if client.indices.exists(index=index_name):
        log.warning("DEV OpenSearch reset: deleting index %r", index_name)
        client.indices.delete(index=index_name)
    else:
        log.info("DEV OpenSearch reset: index %r did not exist (skip delete)", index_name)

    body = chunk_index_create_body()
    client.indices.create(index=index_name, body=body)
    log.info("DEV OpenSearch reset: created index %r (same body as opensearch_bootstrap)", index_name)

    factory = get_session_factory()
    session = factory()
    try:
        hist = session.execute(
            delete(DocumentIndexStatus).where(DocumentIndexStatus.index_name == index_name)
        )
        deleted_hist = hist.rowcount if hist.rowcount is not None else -1

        chunks = session.execute(
            update(DocumentChunk).values(index_status=ChunkIndexStatus.PENDING)
        )
        n_chunks = chunks.rowcount if chunks.rowcount is not None else -1

        docs = session.execute(
            update(RawDocument).values(index_status=DocumentPipelineIndexStatus.PENDING)
        )
        n_docs = docs.rowcount if docs.rowcount is not None else -1

        session.commit()
        log.info(
            "DEV DB reset: document_index_status deleted (index_name=%r) rows=%s; "
            "document_chunk -> PENDING rows=%s; raw_document -> PENDING rows=%s",
            index_name,
            deleted_hist,
            n_chunks,
            n_docs,
        )
    except Exception:
        session.rollback()
        log.exception(
            "DEV OpenSearch index was recreated but PostgreSQL reset failed — "
            "fix DB and re-run this script if needed."
        )
        raise
    finally:
        session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log.warning(
        "=== DEV-ONLY OpenSearch + DB index reset (%s) — not for production ===",
        __name__,
    )
    reset_dev_opensearch_and_db()
    log.info("OpenSearch dev reset finished. Run workers to re-index: python -m app.workers")


if __name__ == "__main__":
    main()
