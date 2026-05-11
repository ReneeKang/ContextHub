"""
DEV / local: create the chunk index on OpenSearch if it does not exist.

* **Not** a production migration tool (no Alembic); safe to re-run (skips when index exists).
* Uses the same mapping as ``app.adapters.opensearch_index_mapping.chunk_index_create_body``.
* Requires ``OPENSEARCH_BASE_URL`` and a reachable cluster (e.g. ``docker compose up``).

Run: ``python -m app.db.opensearch_bootstrap``
"""

from __future__ import annotations

import logging
import sys

from app.adapters.opensearch_client import opensearch_client_from_settings
from app.adapters.opensearch_index_mapping import chunk_index_create_body
from app.config.settings import get_settings

log = logging.getLogger("contexthub.opensearch_bootstrap")


def ensure_chunk_index() -> None:
    settings = get_settings()
    client = opensearch_client_from_settings(settings)
    name = settings.search_index_name
    if client.indices.exists(index=name):
        log.info("OpenSearch index already exists, skip create: %r", name)
        return
    body = chunk_index_create_body()
    client.indices.create(index=name, body=body)
    log.info("OpenSearch index created: %r", name)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log.warning("OpenSearch bootstrap (dev): creating index if missing — not for production lifecycle.")
    ensure_chunk_index()
    log.info("OpenSearch bootstrap finished.")


if __name__ == "__main__":
    main()
