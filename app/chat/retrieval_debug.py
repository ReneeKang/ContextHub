"""
Retrieval observability: structured logs (no ``chunk_text``) and optional API ``debug`` payload.

Logs are emitted on every ``/query`` and ``/generate`` retrieval path. Response ``debug`` is included
only when ``Settings.enable_retrieval_debug`` is true (default off for production).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.adapters.search_protocol import SearchHit
from app.chat.schemas import RetrievalDebugChunkItem, RetrievalDebugInfo

_MAX_QUERY_LOG_LEN = 2000


def _truncate_query(q: str, *, max_len: int = _MAX_QUERY_LOG_LEN) -> str:
    t = q.strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def build_retrieval_debug_log_record(
    *,
    original_query: str,
    retrieval_query: str,
    normalization_applied: bool,
    retrieval_backend: str,
    top_k: int,
    hits: list[SearchHit],
    retrieval_latency_ms: int,
) -> dict[str, Any]:
    """Flat dict for one-line JSON logging (no chunk bodies)."""
    return {
        "original_query": _truncate_query(original_query),
        "retrieval_query": _truncate_query(retrieval_query),
        "normalization_applied": normalization_applied,
        "retrieval_backend": retrieval_backend,
        "retrieval_count": len(hits),
        "top_k": top_k,
        "retrieved_chunk_ids": [str(h.chunk_id) for h in hits],
        "retrieved_document_ids": [str(h.raw_document_id) for h in hits],
        "retrieval_scores": [float(h.score) for h in hits],
        "retrieval_filenames": [h.original_filename for h in hits],
        "retrieval_latency_ms": retrieval_latency_ms,
    }


def log_retrieval_debug(logger: logging.Logger, record: dict[str, Any]) -> None:
    """Single INFO line with JSON object (grep-friendly)."""
    logger.info("retrieval_debug %s", json.dumps(record, ensure_ascii=False))


def build_retrieval_debug_for_response(
    *,
    original_query: str,
    retrieval_query: str,
    normalization_applied: bool,
    retrieval_backend: str,
    top_k: int,
    hits: list[SearchHit],
    retrieval_latency_ms: int,
) -> RetrievalDebugInfo:
    """
    Build the ``debug`` object for HTTP responses (when ``ENABLE_RETRIEVAL_DEBUG`` is on).

    Uses the same trace fields as logs plus a ``chunks`` list (metadata only, no ``chunk_text``).
    """
    chunks = [
        RetrievalDebugChunkItem(
            chunk_id=h.chunk_id,
            raw_document_id=h.raw_document_id,
            original_filename=h.original_filename,
            chunk_no=h.chunk_no,
            section_title=h.section_title,
            page_no=h.page_no,
            score=h.score,
            access_scope=h.access_scope,
            highlights=h.highlights,
        )
        for h in hits
    ]
    return RetrievalDebugInfo(
        original_query=original_query.strip(),
        retrieval_query=retrieval_query.strip(),
        normalization_applied=normalization_applied,
        backend=retrieval_backend,
        retrieval_count=len(hits),
        top_k=top_k,
        retrieval_latency_ms=retrieval_latency_ms,
        retrieved_chunk_ids=[str(h.chunk_id) for h in hits],
        retrieved_document_ids=[str(h.raw_document_id) for h in hits],
        retrieval_scores=[float(h.score) for h in hits],
        retrieval_filenames=[h.original_filename for h in hits],
        chunks=chunks,
    )
