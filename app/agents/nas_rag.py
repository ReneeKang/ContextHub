from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
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
    body: ChatQueryRequest,
) -> tuple[list[SearchHit], int]:
    """Run permission-aware search; ``hits`` are exactly what ``SearchClient.search`` returns (already filtered)."""
    t0 = time.perf_counter()
    hits = search.search(
        query=body.question,
        top_k=body.top_k or 5,
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


def _query_log_snippet(question: str, max_len: int = 400) -> str:
    q = question.replace("\n", " ").strip()
    if len(q) <= max_len:
        return q
    return q[:max_len] + "…"


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
    hits, retrieval_ms = _retrieve_hits_for_nas_rag(
        search=search, settings=settings, principal=principal, body=body
    )
    sources = _sources_from_hits(hits)

    if not hits:
        total_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "nas_rag_generate query=%r retrieval_count=0 retrieval_ms=%s used_chunk_ids=[] "
            "llm_model=%s llm_mock=%s latency_ms=%s",
            _query_log_snippet(body.question),
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
            "nas_rag_generate llm_failed error_type=%s error_message=%r query=%r retrieval_count=%s used_chunk_ids=%s",
            type(exc).__name__,
            err_msg,
            _query_log_snippet(body.question),
            len(hits),
            [str(h.chunk_id) for h in hits],
        )
        raise NasRagLLMError("LLM generation failed") from exc
    t_llm1 = time.perf_counter()
    llm_ms = int((t_llm1 - t_llm0) * 1000)
    total_ms = int((time.perf_counter() - t0) * 1000)

    used_ids = [str(h.chunk_id) for h in hits]
    log.info(
        "nas_rag_generate query=%r retrieval_count=%s retrieval_ms=%s used_chunk_ids=%s "
        "llm_model=%s llm_mock=%s latency_ms=%s",
        _query_log_snippet(body.question),
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
    )
