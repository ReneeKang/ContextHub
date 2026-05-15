"""
Document discovery: over-fetch chunks, group by ``raw_document_id``, return document ``top_k``.

``DiscoverRequest.top_k`` is the **document** candidate limit. Chunk retrieval uses a larger
``chunk_fetch_size`` so one document cannot monopolize the chunk hit list before grouping.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import Any, Callable
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

# Per-document caps (design: 3–5 matched chunks in response)
_MAX_REPRESENTATIVE_SECTIONS = 3
_MAX_MATCHED_CHUNKS_PER_DOC = 5
_CHUNK_FETCH_SIZE_MULTIPLIER = 10
_CHUNK_FETCH_SIZE_MIN = 50
# Drop weak documents vs best hit unless they have metadata highlights.
_RELATIVE_SCORE_MIN_RATIO = 0.1


def chunk_fetch_size(document_top_k: int) -> int:
    """OpenSearch/SQL ``LIMIT`` for chunk hits before document grouping."""
    return max(document_top_k * _CHUNK_FETCH_SIZE_MULTIPLIER, _CHUNK_FETCH_SIZE_MIN)


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


def _document_has_metadata_highlight(doc_hits: list[SearchHit]) -> bool:
    """True when any chunk has non-body highlight fragments (filename, path, section, etc.)."""
    return any(_trim_highlights(h.highlights) for h in doc_hits)


def filter_document_candidates(
    ordered_ids: list[UUID],
    by_doc: dict[UUID, list[SearchHit]],
    *,
    doc_top_score: Callable[[UUID], float],
    min_relative_ratio: float = _RELATIVE_SCORE_MIN_RATIO,
) -> tuple[list[UUID], int]:
    """
    Drop documents with no metadata highlights and top_score far below the best hit.

    Keep when ``has_highlight`` OR ``top_score >= best_score * min_relative_ratio``.
    """
    if not ordered_ids:
        return [], 0

    best_score = max(doc_top_score(rid) for rid in ordered_ids)
    if best_score <= 0:
        return list(ordered_ids), 0

    threshold = best_score * min_relative_ratio
    kept: list[UUID] = []
    dropped = 0
    for rid in ordered_ids:
        top_score = doc_top_score(rid)
        has_highlight = _document_has_metadata_highlight(by_doc[rid])
        if has_highlight or top_score >= threshold:
            kept.append(rid)
        else:
            dropped += 1
    return kept, dropped


def run_discover(
    session: Session,
    settings: Settings,
    search: SearchClient,
    principal: PermissionPrincipal,
    body: DiscoverRequest,
) -> DiscoverResponse:
    """Over-fetch chunks, group by document, return up to ``top_k`` distinct documents (no LLM)."""
    original_q = body.question.strip()
    retrieval_q, norm_applied = normalize_retrieval_query_pair(body.question)
    top_k_documents = body.top_k or 10
    fetch_chunks = chunk_fetch_size(top_k_documents)

    t0 = time.perf_counter()
    hits = search.search(
        query=retrieval_q,
        top_k=fetch_chunks,
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

    ordered_all = sorted(doc_ids, key=doc_top_score, reverse=True)
    ordered_ids, dropped_documents_count = filter_document_candidates(
        ordered_all,
        by_doc,
        doc_top_score=doc_top_score,
    )
    ordered_ids = ordered_ids[:top_k_documents]

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
        "top_k_documents": top_k_documents,
        "chunk_fetch_size": fetch_chunks,
        "chunk_hits_fetched": len(hits),
        "documents_before_filter": len(ordered_all),
        "dropped_documents_count": dropped_documents_count,
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
