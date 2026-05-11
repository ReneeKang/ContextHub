"""Minimal logging configuration for CLI (workers) and optional reuse by uvicorn."""

from __future__ import annotations

import logging
import sys

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure root logging once (idempotent).

    Development default: INFO to stderr with timestamp, level, logger name, message.
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.setLevel(level)
    root.addHandler(handler)

    # Reduce SQLAlchemy connection pool noise during normal operation
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _configured = True
