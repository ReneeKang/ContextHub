from __future__ import annotations

import json
import logging
import time
from uuid import UUID

from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat.retrieval_debug import (
    build_generation_context_chunks,
    build_retrieval_debug_for_response,
    build_retrieval_debug_log_record,
    log_retrieval_debug,
)
from app.chat.retrieval_query import format_query_log_snippet, normalize_retrieval_query_pair
from app.chat.schemas import ChatGenerateResponse, ChatQueryRequest, ChatSourceItem
from app.chat.selected_document_fallback import load_chunks_for_selected_documents
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
    "When citing evidence, use only a short marker like (발췌 N); keep source marks minimal. "
    "Respond in Korean unless the user explicitly asks otherwise.\n\n"
    "Default answer format (conservative — avoids truncation from over-long replies):\n"
    "- Prefer a **short bullet summary** (plain lines or Markdown `-` bullets). Do **not** default to tabular layouts.\n"
    "- **Unless the user explicitly asks you to present results as a table** (e.g. asks to lay them out in table form), "
    "do **not** write **Markdown pipe tables** (`| ... |`) or ASCII table grids.\n"
    "  (Korean reminder: 사용자가 '표로 정리해 달라'고 **명시**하지 않는 한 Markdown 표를 만들지 말 것.)\n"
    "- **Do not cram many deliverables or list items into one bullet** (no long comma chains or mini-catalogs inside a single `-` line). "
    "Split only when it stays within the bullet budget below; otherwise merge into **representative categories**.\n"
    "  (Korean reminder: **한 bullet 안에** 산출물·항목을 길게 나열하지 말 것.)\n"
    "- **Default body: at most 5 bullets** (not counting the closing summary lines). **Each bullet: 1–2 sentences only.**\n"
    "  (Korean reminder: 기본 답변은 **최대 5개 bullet**, **각 bullet은 1~2문장**만.)\n"
    "- For **deliverable / inventory-style** context, **do not enumerate every line item**; summarize **representative categories** only.\n"
    "  (Korean reminder: 산출물·목록형 문서는 **모든 항목을 나열하지 말고 대표 범주만** 요약할 것.)\n"
    "- If a **full detailed list** would be useful, add one short Korean line telling the user they may **ask again** for that depth "
    "(e.g. that a detailed 산출물 목록 is available on re-request).\n"
    "  (예: '상세 산출물 목록이 필요하면 다시 요청해 주세요.')\n"
    "- **Always** end the answer with **one or two closing sentences** that restate the bottom line (no new facts beyond the context).\n"
    "  (Korean reminder: 답변 마지막은 반드시 **한두 문장**으로 핵심을 다시 요약해 마무리할 것.)\n"
    "- Skip exhaustive inventories unless the user explicitly asks for full detail.\n"
    "- Keep the body concise; prefer quality over completeness in a single turn."
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
        "If nothing in the context applies, state that you found no relevant internal text. "
        "Prefer bullets over tables unless the user explicitly requested a table; "
        "use at most 5 body bullets (1–2 sentences each), do not pack many items into one bullet; "
        "keep the answer short enough to finish without truncation."
    )
    return "".join(parts)


ZERO_HIT_ANSWER_KO = (
    "검색된 내부 문서 발췌가 없어 답변을 생성하지 않았습니다. "
    "질문 표현을 바꾸거나, 권한 범위(PUBLIC/부서/개인 경로)와 색인 상태를 확인해 주세요."
)

FILTERED_EMPTY_ANSWER_KO = (
    "선택한 문서에 해당하는 검색 결과가 없어 답변을 생성하지 않았습니다. "
    "다른 문서를 선택하거나 질문을 조정해 주세요."
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


def _normalized_document_ids(body: ChatQueryRequest) -> list[UUID] | None:
    """``document_ids`` on ``ChatGenerateRequest`` only; absent or empty → no filter."""
    raw = getattr(body, "document_ids", None)
    if not raw:
        return None
    return list(raw)


def _apply_document_filter(hits: list[SearchHit], document_ids: list[UUID] | None) -> list[SearchHit]:
    if not document_ids:
        return hits
    allow = frozenset(document_ids)
    return [h for h in hits if h.raw_document_id in allow]


def _selected_document_ids_echo(document_ids: list[UUID] | None) -> list[str] | None:
    if not document_ids:
        return None
    return [str(u) for u in document_ids]


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

    Does not parse citations from model output; ``sources`` mirror retrieval hits
    (after optional ``document_ids`` filter when ``body`` is a :class:`~app.chat.schemas.ChatGenerateRequest`).
    When ``document_ids`` is set and filtered retrieval is empty, loads early chunks from PostgreSQL
    (same permission rules as DB search) so pronoun-style questions still receive context.
    """
    t0 = time.perf_counter()
    original_q = body.question
    retrieval_q, norm_applied = normalize_retrieval_query_pair(original_q)
    top_k = body.top_k or 5
    doc_ids = _normalized_document_ids(body)
    selected_echo = _selected_document_ids_echo(doc_ids)

    raw_hits, retrieval_ms = _retrieve_hits_for_nas_rag(
        search=search,
        settings=settings,
        principal=principal,
        retrieval_query=retrieval_q,
        top_k=top_k,
    )
    hits = _apply_document_filter(raw_hits, doc_ids)
    used_selected_document_fallback = False
    fallback_context_limit: int | None = None
    if doc_ids and not hits:
        fb_limit = min(top_k, settings.selected_document_context_chunks)
        fallback_context_limit = fb_limit
        fb = load_chunks_for_selected_documents(
            session, principal, doc_ids, top_k=fb_limit
        )
        if fb:
            hits = fb
            used_selected_document_fallback = True

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
    if used_selected_document_fallback:
        extra: dict[str, object] = {"selected_document_fallback_used": True}
        if fallback_context_limit is not None:
            extra["selected_document_context_chunk_limit"] = fallback_context_limit
        rec = {**rec, **extra}
    log_retrieval_debug(log, rec)
    dbg = None
    if settings.enable_retrieval_debug:
        dbg = build_retrieval_debug_for_response(
            original_query=original_q,
            retrieval_query=retrieval_q,
            normalization_applied=norm_applied,
            retrieval_backend=rb,
            top_k=top_k,
            hits=hits,
            retrieval_latency_ms=retrieval_ms,
            generation_context_chunks=build_generation_context_chunks(hits) if hits else [],
        )

    if not hits:
        total_ms = int((time.perf_counter() - t0) * 1000)
        answer = FILTERED_EMPTY_ANSWER_KO if doc_ids else ZERO_HIT_ANSWER_KO
        log.info(
            "nas_rag_generate original_query=%r retrieval_query=%r normalization_applied=%s "
            "retrieval_count=%s raw_retrieval_count=%s document_filter=%s selected_doc_fallback=%s "
            "retrieval_ms=%s used_chunk_ids=[] llm_model=%s llm_mock=%s latency_ms=%s",
            format_query_log_snippet(original_q),
            format_query_log_snippet(retrieval_q),
            norm_applied,
            len(hits),
            len(raw_hits),
            bool(doc_ids),
            used_selected_document_fallback,
            retrieval_ms,
            None,
            False,
            total_ms,
        )
        return ChatGenerateResponse(
            answer=answer,
            search_backend=settings.search_backend,
            sources=[],
            session_id=body.session_id,
            llm_model=None,
            llm_mock=False,
            retrieval_latency_ms=retrieval_ms,
            llm_latency_ms=None,
            total_latency_ms=total_ms,
            selected_document_ids=selected_echo,
            filtered_retrieval_count=len(hits),
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
            max_tokens=settings.rag_llm_max_tokens,
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
        "raw_retrieval_count=%s document_filter=%s selected_doc_fallback=%s retrieval_ms=%s "
        "used_chunk_ids=%s llm_model=%s llm_mock=%s latency_ms=%s",
        format_query_log_snippet(original_q),
        format_query_log_snippet(retrieval_q),
        norm_applied,
        len(hits),
        len(raw_hits),
        bool(doc_ids),
        used_selected_document_fallback,
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
        selected_document_ids=selected_echo,
        filtered_retrieval_count=len(hits),
        debug=dbg,
    )
