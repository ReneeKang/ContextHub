"""
Document discovery: group ``SearchHit`` rows by ``raw_document_id`` (no SearchClient contract change).

``top_k`` on the request is the chunk-level retrieval limit for ``SearchClient.search`` today;
structure allows a future split into ``top_k_chunks`` / ``top_k_documents`` without breaking callers.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat.retrieval_query import format_query_log_snippet, normalize_retrieval_query_pair
from app.chat.schemas import (
    DiscoverDocumentItem,
    DiscoverMatchedChunkItem,
    DiscoverRequest,
    DiscoverResponse,
)
from app.config.settings import Settings
from app.db.models.raw_document import RawDocument

log = logging.getLogger("contexthub.chat.discovery")

_PROJECT_SLUG_RE = re.compile(r"/projects/([^/]+)/", re.IGNORECASE)

# Per-document caps (MVP; design doc suggested 3–5 chunks in response)
_MAX_REPRESENTATIVE_SECTIONS = 3
_MAX_MATCHED_CHUNKS_PER_DOC = 4
_HIGHLIGHT_MAX_KEYS = 2
_HIGHLIGHT_MAX_FRAGMENTS_PER_KEY = 2
_HIGHLIGHT_MAX_CHARS_PER_FRAGMENT = 160
# OpenSearch body field; never expose in /discover (document discovery is metadata-only).
_HIGHLIGHT_EXCLUDED_KEYS = frozenset({"chunk_text"})


def infer_project_key(path: str) -> str | None:
    """
    If ``path`` (inbox or stored, forward slashes) contains ``/projects/{slug}/``, return ``slug``.
    Otherwise ``None``.
    """
    if not path:
        return None
    norm = path.replace("\\", "/")
    m = _PROJECT_SLUG_RE.search(norm)
    return m.group(1) if m else None


def _trim_highlights(raw: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
    """
    Trim highlight fragments for /discover only.

    Drops ``chunk_text`` (and case variants) so chunk body / body highlights never appear in the
    API or in any downstream serialization from this path. Metadata keys (e.g. ``section_title``,
    ``original_filename``) are kept, subject to caps.
    """
    if not raw:
        return None
    out: dict[str, list[str]] = {}
    used = 0
    for key, fragments in raw.items():
        if str(key).lower() in _HIGHLIGHT_EXCLUDED_KEYS:
            continue
        if used >= _HIGHLIGHT_MAX_KEYS:
            break
        if not isinstance(fragments, list):
            continue
        trimmed: list[str] = []
        for frag in fragments[:_HIGHLIGHT_MAX_FRAGMENTS_PER_KEY]:
            if not isinstance(frag, str):
                continue
            t = frag.strip()
            if len(t) > _HIGHLIGHT_MAX_CHARS_PER_FRAGMENT:
                t = t[:_HIGHLIGHT_MAX_CHARS_PER_FRAGMENT] + "…"
            if t:
                trimmed.append(t)
        if trimmed:
            out[str(key)] = trimmed
            used += 1
    return out or None


def _representative_sections(hits_sorted: list[SearchHit], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for h in hits_sorted:
        t = (h.section_title or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _load_raw_documents(session: Session, ids: list[UUID]) -> dict[UUID, RawDocument]:
    if not ids:
        return {}
    rows = list(session.scalars(select(RawDocument).where(RawDocument.raw_document_id.in_(ids))).all())
    return {r.raw_document_id: r for r in rows}


def run_discover(
    session: Session,
    settings: Settings,
    search: SearchClient,
    principal: PermissionPrincipal,
    body: DiscoverRequest,
) -> DiscoverResponse:
    """Chunk retrieval via ``SearchClient.search``, then document-level grouping (no LLM)."""
    original_q = body.question.strip()
    retrieval_q, norm_applied = normalize_retrieval_query_pair(body.question)
    top_k_chunks = body.top_k or 10

    t0 = time.perf_counter()
    hits = search.search(
        query=retrieval_q,
        top_k=top_k_chunks,
        principal=principal,
        index_name=settings.search_index_name,
    )
    retrieval_ms = int((time.perf_counter() - t0) * 1000)

    by_doc: dict[UUID, list[SearchHit]] = defaultdict(list)
    for h in hits:
        by_doc[h.raw_document_id].append(h)

    doc_ids = list(by_doc.keys())
    meta = _load_raw_documents(session, doc_ids)

    # Sort documents by top_score (max chunk score) descending
    def doc_top_score(doc_id: UUID) -> float:
        return max((x.score for x in by_doc[doc_id]), default=0.0)

    ordered_ids = sorted(doc_ids, key=doc_top_score, reverse=True)

    documents: list[DiscoverDocumentItem] = []
    top_scores_log: list[float] = []

    for rid in ordered_ids:
        doc_hits = by_doc[rid]
        doc_hits_by_score = sorted(doc_hits, key=lambda h: h.score, reverse=True)
        top_score = float(doc_hits_by_score[0].score) if doc_hits_by_score else 0.0
        top_scores_log.append(top_score)

        row = meta.get(rid)
        inbox_path = row.inbox_path if row is not None else ""
        stored_norm = (row.stored_path if row is not None else "").replace("\\", "/")
        inbox_norm = inbox_path.replace("\\", "/")
        path_display = inbox_path if inbox_path else (row.stored_path if row else "")
        pk = infer_project_key(inbox_norm) or infer_project_key(stored_norm)

        sections = _representative_sections(doc_hits_by_score, limit=_MAX_REPRESENTATIVE_SECTIONS)

        matched_chunks: list[DiscoverMatchedChunkItem] = []
        for h in doc_hits_by_score[:_MAX_MATCHED_CHUNKS_PER_DOC]:
            matched_chunks.append(
                DiscoverMatchedChunkItem(
                    chunk_id=h.chunk_id,
                    chunk_no=h.chunk_no,
                    section_title=h.section_title,
                    page_no=h.page_no,
                    score=float(h.score),
                    highlights=_trim_highlights(h.highlights),
                )
            )

        first = doc_hits_by_score[0]
        documents.append(
            DiscoverDocumentItem(
                raw_document_id=rid,
                original_filename=first.original_filename,
                path=path_display,
                project_key=pk,
                access_scope=first.access_scope,
                top_score=top_score,
                matched_chunk_count=len(doc_hits),
                representative_sections=sections,
                matched_chunks=matched_chunks,
            )
        )

    rec: dict[str, Any] = {
        "original_query": format_query_log_snippet(original_q, max_len=2000),
        "retrieval_query": format_query_log_snippet(retrieval_q, max_len=2000),
        "normalization_applied": norm_applied,
        "document_count": len(documents),
        "retrieved_document_ids": [str(i) for i in ordered_ids],
        "top_scores": top_scores_log,
        "retrieval_backend": settings.search_backend,
        "retrieval_latency_ms": retrieval_ms,
    }
    log.info("chat_discover %s", json.dumps(rec, ensure_ascii=False))

    return DiscoverResponse(
        original_query=original_q,
        retrieval_query=retrieval_q,
        normalization_applied=norm_applied,
        document_count=len(documents),
        documents=documents,
        search_backend=settings.search_backend,
        retrieval_latency_ms=retrieval_ms,
    )
