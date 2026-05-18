"""
Retrieval observability: structured logs (no ``chunk_text``) and optional API ``debug`` payload.

Logs are emitted on every ``/query`` and ``/generate`` retrieval path. Response ``debug`` is included
only when ``Settings.enable_retrieval_debug`` is true (default off for production).
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.adapters.search_protocol import SearchHit
from app.chat.schemas import (
    GenerationContextChunkItem,
    RetrievalDebugChunkItem,
    RetrievalDebugInfo,
)

_MAX_QUERY_LOG_LEN = 2000
GENERATION_CONTEXT_PREVIEW_MAX_CHARS = 300
# User message in /generate debug: question + framing only; CONTEXT excerpt bodies are never included.
LLM_USER_MESSAGE_DEBUG_PREVIEW_MAX_CHARS = 2000
_LLM_USER_CONTEXT_MARKER = "\nCONTEXT (numbered excerpts):\n"

# OpenSearch payload uses ``<em>`` / ``</em>`` (see ``opensearch_payload.build_search_body``).
_EM_RE = re.compile(r"<em>(.*?)</em>", re.IGNORECASE | re.DOTALL)
_HIGHLIGHT_TERM_SPLIT_RE = re.compile(r"[\s,.;:|/\\]+")


@dataclass(frozen=True, slots=True)
class RetrievalChunkRanking:
    """Per-hit ranking explanation (aligned with ``SearchClient.search`` result order)."""

    chunk_rank: int
    document_rank: int
    matched_fields: list[str]
    highlight_terms: list[str]


def matched_fields_from_highlights(highlights: dict[str, list[str]] | None) -> list[str]:
    """Stable-sorted OpenSearch highlight field names (keys of the highlight object)."""
    if not highlights:
        return []
    return sorted(highlights.keys())


def highlight_terms_from_highlights(
    highlights: dict[str, list[str]] | None,
    *,
    max_terms: int = 48,
    max_token_len: int = 64,
) -> list[str]:
    """
    Extract short tokens from ``<em>...</em>`` spans inside highlight fragments.

    Splits each span on common separators so comma-separated Korean phrases become separate terms.
    Does **not** return raw fragments (only tagged spans, length-capped).
    """
    if not highlights:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for fragments in highlights.values():
        if not isinstance(fragments, list):
            continue
        for frag in fragments:
            if not isinstance(frag, str):
                continue
            for m in _EM_RE.finditer(frag):
                inner = (m.group(1) or "").strip()
                if not inner:
                    continue
                for part in _HIGHLIGHT_TERM_SPLIT_RE.split(inner):
                    p = part.strip()
                    if not p:
                        continue
                    if len(p) > max_token_len:
                        p = p[:max_token_len]
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
                        if len(out) >= max_terms:
                            return out
    return out


def _document_ranks_by_top_score(hits: list[SearchHit]) -> dict[UUID, int]:
    """Rank documents by max chunk score among ``hits`` (1 = strongest document)."""
    best: dict[UUID, float] = defaultdict(float)
    for h in hits:
        uid = h.raw_document_id
        s = float(h.score)
        if s > best[uid]:
            best[uid] = s
    ordered = sorted(best.keys(), key=lambda u: (-best[u], str(u)))
    return {uid: i + 1 for i, uid in enumerate(ordered)}


def rank_hits_for_retrieval_debug(hits: list[SearchHit]) -> list[RetrievalChunkRanking]:
    """``chunk_rank`` = position in ``hits``; ``document_rank`` = rank of that chunk's doc by top score."""
    doc_ranks = _document_ranks_by_top_score(hits)
    out: list[RetrievalChunkRanking] = []
    for i, h in enumerate(hits, start=1):
        out.append(
            RetrievalChunkRanking(
                chunk_rank=i,
                document_rank=doc_ranks[h.raw_document_id],
                matched_fields=matched_fields_from_highlights(h.highlights),
                highlight_terms=highlight_terms_from_highlights(h.highlights),
            )
        )
    return out


def _chunk_ranking_for_log(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Safe log rows: scores + highlight-derived fields only (no raw highlight text blobs)."""
    ranked = rank_hits_for_retrieval_debug(hits)
    rows: list[dict[str, Any]] = []
    for h, r in zip(hits, ranked, strict=True):
        rows.append(
            {
                "chunk_id": str(h.chunk_id),
                "score": float(h.score),
                "matched_fields": r.matched_fields,
                "highlight_terms": r.highlight_terms,
                "document_rank": r.document_rank,
                "chunk_rank": r.chunk_rank,
            }
        )
    return rows


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
        "chunk_ranking": _chunk_ranking_for_log(hits),
    }


def chunk_text_preview(
    text: str | None,
    *,
    max_chars: int = GENERATION_CONTEXT_PREVIEW_MAX_CHARS,
) -> str:
    """Truncate chunk body for debug responses (never return full ``chunk_text``)."""
    if not text:
        return ""
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "…"


def build_generation_context_chunks(hits: list[SearchHit]) -> list[GenerationContextChunkItem]:
    """One preview row per hit included in the LLM user prompt CONTEXT block."""
    out: list[GenerationContextChunkItem] = []
    for h in hits:
        body = h.chunk_text or ""
        out.append(
            GenerationContextChunkItem(
                chunk_id=h.chunk_id,
                raw_document_id=h.raw_document_id,
                original_filename=h.original_filename,
                chunk_no=h.chunk_no,
                section_title=h.section_title,
                score=float(h.score),
                char_count=len(body),
                text_preview=chunk_text_preview(body),
                included_in_prompt=True,
            )
        )
    return out


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
    generation_context_chunks: list[GenerationContextChunkItem] | None = None,
    llm_system_message: str | None = None,
    llm_user_message: str | None = None,
) -> RetrievalDebugInfo:
    """
    Build the ``debug`` object for HTTP responses (when ``ENABLE_RETRIEVAL_DEBUG`` is on).

    Uses the same trace fields as logs plus a ``chunks`` list (metadata only, no ``chunk_text``).
    ``generation_context_chunks`` is set on ``/generate`` only (truncated prompt previews).
    When ``llm_user_message`` is set (hits path after ``build_nas_rag_user_prompt``), adds character counts
    and ``llm_user_message_preview``: the QUESTION block plus a placeholder line (CONTEXT excerpt bodies are never
    embedded in JSON; use ``generation_context_chunks`` for per-chunk previews).
    """
    ranked = rank_hits_for_retrieval_debug(hits)
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
            matched_fields=r.matched_fields,
            highlight_terms=r.highlight_terms,
            document_rank=r.document_rank,
            chunk_rank=r.chunk_rank,
        )
        for h, r in zip(hits, ranked, strict=True)
    ]
    sys_chars = len(llm_system_message) if llm_system_message is not None else None
    user_chars = len(llm_user_message) if llm_user_message is not None else None
    user_preview: str | None = None
    if llm_user_message is not None:
        if _LLM_USER_CONTEXT_MARKER in llm_user_message:
            head, _sep, tail = llm_user_message.partition(_LLM_USER_CONTEXT_MARKER)
            ctx_chars = len(tail)
            framed = (
                f"{head.rstrip()}\n"
                f"[… CONTEXT ({ctx_chars} chars of excerpts) omitted from debug JSON; "
                "see generation_context_chunks previews …]"
            )
            user_preview = chunk_text_preview(
                framed,
                max_chars=LLM_USER_MESSAGE_DEBUG_PREVIEW_MAX_CHARS,
            )
        else:
            user_preview = chunk_text_preview(
                llm_user_message,
                max_chars=LLM_USER_MESSAGE_DEBUG_PREVIEW_MAX_CHARS,
            )
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
        generation_context_chunks=generation_context_chunks,
        llm_system_message_char_count=sys_chars,
        llm_user_message_char_count=user_chars,
        llm_user_message_preview=user_preview,
    )
