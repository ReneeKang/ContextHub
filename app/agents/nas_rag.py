from __future__ import annotations

import json
import logging
import time

from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat.retrieval_debug import (
    build_retrieval_debug_for_response,
    build_retrieval_debug_log_record,
    log_retrieval_debug,
)
from app.chat.retrieval_query import format_query_log_snippet, normalize_retrieval_query_pair
from app.chat.schemas import ChatGenerateResponse, ChatQueryRequest, ChatSourceItem
from app.config.settings import Settings
from app.llm.backend import get_llm_client
from app.llm.protocol import LLMMessage

log = logging.getLogger("contexthub.agents.nas_rag")

# --- Prompt building (module-level; NAS RAG PoC) ---

NAS_RAG_SYSTEM_PROMPT = (
    "You are an internal assistant for a Korean enterprise. "
    "The CONTEXT excerpts below are from internal documents **after permission filtering**; "
    "treat them as the only allowed factual ground for this request. "
    "Answer using **only** that CONTEXT; if it is insufficient, say so clearly in Korean and do not invent facts. "
    "Do not infer privileged information beyond what the excerpts support. "
    "Cite ideas by excerpt index (e.g. '발췌 1') when helpful. "
    "Respond in Korean unless the user explicitly asks otherwise."
)


def build_nas_rag_user_prompt(*, question: str, hits: list[SearchHit]) -> str:
    """Assemble user message: question + numbered excerpts (full chunk text for the model, not for logs)."""
    parts: list[str] = [f"QUESTION:\n{question}\n", "\nCONTEXT (numbered excerpts):\n"]
    for i, h in enumerate(hits, start=1):
        title = h.section_title or ""
        parts.append(
            f"--- excerpt {i} | file={h.original_filename} | chunk_no={h.chunk_no} | section_title={title!r}\n"
        )
        parts.append(h.chunk_text)
        parts.append("\n")
    parts.append(
        "\nUsing only the CONTEXT above, answer the QUESTION. "
        "If nothing in the context applies, state that you found no relevant internal text."
    )
    return "".join(parts)


ZERO_HIT_ANSWER_KO = (
    "검색된 내부 문서 발췌가 없어 답변을 생성하지 않았습니다. "
    "질문 표현을 바꾸거나, 권한 범위(PUBLIC/부서/개인 경로)와 색인 상태를 확인해 주세요."
)


class NasRagLLMError(Exception):
    """LLM HTTP or parse failure after retrieval succeeded."""


def _retrieve_hits_for_nas_rag(
    *,
    search: SearchClient,
    settings: Settings,
    principal: PermissionPrincipal,
    retrieval_query: str,
    top_k: int,
) -> tuple[list[SearchHit], int]:
    """Run permission-aware search; ``hits`` are exactly what ``SearchClient.search`` returns (already filtered)."""
    t0 = time.perf_counter()
    hits = search.search(
        query=retrieval_query,
        top_k=top_k,
        principal=principal,
        index_name=settings.search_index_name,
    )
    retrieval_ms = int((time.perf_counter() - t0) * 1000)
    return hits, retrieval_ms


def _sources_from_hits(hits: list[SearchHit]) -> list[ChatSourceItem]:
    return [
        ChatSourceItem(
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


def run_nas_rag_generate(
    session: Session,
    settings: Settings,
    search: SearchClient,
    principal: PermissionPrincipal,
    body: ChatQueryRequest,
) -> ChatGenerateResponse:
    """
    Permission-aware retrieval + optional LLM generation.

    Does not parse citations from model output; ``sources`` mirror retrieval hits.
    """
    _ = session
    t0 = time.perf_counter()
    original_q = body.question
    retrieval_q, norm_applied = normalize_retrieval_query_pair(original_q)
    top_k = body.top_k or 5
    hits, retrieval_ms = _retrieve_hits_for_nas_rag(
        search=search,
        settings=settings,
        principal=principal,
        retrieval_query=retrieval_q,
        top_k=top_k,
    )
    sources = _sources_from_hits(hits)
    rb = settings.search_backend
    rec = build_retrieval_debug_log_record(
        original_query=original_q,
        retrieval_query=retrieval_q,
        normalization_applied=norm_applied,
        retrieval_backend=rb,
        top_k=top_k,
        hits=hits,
        retrieval_latency_ms=retrieval_ms,
    )
    log_retrieval_debug(log, rec)
    dbg = (
        build_retrieval_debug_for_response(
            original_query=original_q,
            retrieval_query=retrieval_q,
            normalization_applied=norm_applied,
            retrieval_backend=rb,
            top_k=top_k,
            hits=hits,
            retrieval_latency_ms=retrieval_ms,
        )
        if settings.enable_retrieval_debug
        else None
    )

    if not hits:
        total_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "nas_rag_generate original_query=%r retrieval_query=%r normalization_applied=%s "
            "retrieval_count=0 retrieval_ms=%s used_chunk_ids=[] llm_model=%s llm_mock=%s latency_ms=%s",
            format_query_log_snippet(original_q),
            format_query_log_snippet(retrieval_q),
            norm_applied,
            retrieval_ms,
            None,
            False,
            total_ms,
        )
        return ChatGenerateResponse(
            answer=ZERO_HIT_ANSWER_KO,
            search_backend=settings.search_backend,
            sources=[],
            session_id=body.session_id,
            llm_model=None,
            llm_mock=False,
            retrieval_latency_ms=retrieval_ms,
            llm_latency_ms=None,
            total_latency_ms=total_ms,
            debug=dbg,
        )

    llm_mock = bool(settings.llm_mock_mode or settings.llm_backend == "mock")
    llm = get_llm_client(settings)
    user_content = build_nas_rag_user_prompt(question=body.question, hits=hits)
    messages = [
        LLMMessage(role="system", content=NAS_RAG_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_content),
    ]

    t_llm0 = time.perf_counter()
    try:
        result = llm.complete(
            messages=messages,
            model=settings.llm_model,
            max_tokens=1024,
            temperature=0.2,
        )
    except Exception as exc:
        err_msg = str(exc).replace("\n", " ")[:500]
        log.warning(
            "nas_rag_generate llm_failed error_type=%s error_message=%r original_query=%r retrieval_query=%r "
            "normalization_applied=%s retrieval_count=%s used_chunk_ids=%s retrieval_debug=%s",
            type(exc).__name__,
            err_msg,
            format_query_log_snippet(original_q),
            format_query_log_snippet(retrieval_q),
            norm_applied,
            len(hits),
            [str(h.chunk_id) for h in hits],
            json.dumps(rec, ensure_ascii=False),
        )
        raise NasRagLLMError("LLM generation failed") from exc
    t_llm1 = time.perf_counter()
    llm_ms = int((t_llm1 - t_llm0) * 1000)
    total_ms = int((time.perf_counter() - t0) * 1000)

    used_ids = [str(h.chunk_id) for h in hits]
    log.info(
        "nas_rag_generate original_query=%r retrieval_query=%r normalization_applied=%s retrieval_count=%s "
        "retrieval_ms=%s used_chunk_ids=%s llm_model=%s llm_mock=%s latency_ms=%s",
        format_query_log_snippet(original_q),
        format_query_log_snippet(retrieval_q),
        norm_applied,
        len(hits),
        retrieval_ms,
        used_ids,
        result.model,
        llm_mock,
        total_ms,
    )

    return ChatGenerateResponse(
        answer=result.text,
        search_backend=settings.search_backend,
        sources=sources,
        session_id=body.session_id,
        llm_model=result.model,
        llm_mock=llm_mock,
        retrieval_latency_ms=retrieval_ms,
        llm_latency_ms=llm_ms,
        total_latency_ms=total_ms,
        debug=dbg,
    )
