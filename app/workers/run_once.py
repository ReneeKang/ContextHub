"""
Run a single pass for one pipeline stage.

Orchestration here only sequences *independent* per-stage services; each service implements
at most its own DB-state transition (scanner/parser/chunker/indexer). No end-to-end pipeline
logic belongs in this module beyond calling those entrypoints in order for local dev.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.adapters.kordoc_stub import KordocStubParser
from app.adapters.search_stub import StubSearchClient
from app.chunker.service import ChunkerRunStats, ChunkerService
from app.config.settings import get_settings
from app.db.session import get_engine, get_session_factory
from app.indexer.service import IndexerRunStats, IndexerService
from app.parser.service import ParserRunStats, ParserService
from app.scanner.service import ScannerRunStats, ScannerService

log = logging.getLogger("contexthub.workers")


def verify_database_connection() -> None:
    """Execute a trivial query so connectivity failures surface before stage work."""
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("database connection ok")


def run_scanner_once() -> ScannerRunStats:
    settings = get_settings()
    factory = get_session_factory()
    session = factory()
    try:
        stats = ScannerService(session, settings).run_once()
        session.commit()
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_parser_once() -> ParserRunStats:
    settings = get_settings()
    factory = get_session_factory()
    session = factory()
    try:
        stats = ParserService(session, settings, parser=KordocStubParser()).run_once()
        session.commit()
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_chunker_once() -> ChunkerRunStats:
    settings = get_settings()
    factory = get_session_factory()
    session = factory()
    try:
        stats = ChunkerService(session, settings).run_once()
        session.commit()
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_indexer_once() -> IndexerRunStats:
    settings = get_settings()
    factory = get_session_factory()
    session = factory()
    try:
        stats = IndexerService(session, settings, search=StubSearchClient()).run_once()
        session.commit()
        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_dev_tick_sequential() -> None:
    """Development helper: invoke each worker once, each with its own DB transaction."""
    log.info("starting worker cycle")
    verify_database_connection()

    stages: list[tuple[str, Any]] = [
        ("scanner", run_scanner_once),
        ("parser", run_parser_once),
        ("chunker", run_chunker_once),
        ("indexer", run_indexer_once),
    ]

    for name, fn in stages:
        log.info("[%s] started", name)
        try:
            stats = fn()
        except Exception:
            log.exception("[%s] failed — worker cycle aborted (ERROR)", name)
            raise
        log.info("[%s] completed — %s (OK)", name, stats)

    log.info("worker cycle finished successfully (OK)")
