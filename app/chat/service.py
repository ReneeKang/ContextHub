from __future__ import annotations

from sqlalchemy.orm import Session

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat.schemas import ChatQueryRequest, ChatQueryResponse, ChatSourceItem
from app.config.settings import Settings


def _build_stub_answer(*, question: str, hits: list[SearchHit]) -> str:
    """Temporary answer until LLM is wired (`app.chat.service` / dedicated LLM client)."""
    if not hits:
        return (
            "검색 결과가 없습니다. (OpenSearch·LLM 미연동 PoC: DB `document_chunk` 검색만 사용합니다.)\n"
            "질문에 포함된 단어가 본문에 있는지, 또는 PUBLIC/부서/소유자 권한이 맞는지 확인해 보세요."
        )
    lines = [
        f"[임시 응답] 질문과 연관된 청크 {len(hits)}건을 찾았습니다. (실제 LLM은 아직 연결되지 않았습니다.)",
        "",
    ]
    for i, h in enumerate(hits, start=1):
        snippet = h.chunk_text[:280] + ("…" if len(h.chunk_text) > 280 else "")
        lines.append(f"{i}. `{h.original_filename}` 청크 #{h.chunk_no}: {snippet}")
    lines.append("")
    lines.append(f"(원 질문: {question[:200]}{'…' if len(question) > 200 else ''})")
    return "\n".join(lines)


class ChatService:
    """chat-api core: permission-aware search + LLM answer assembly."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        search: SearchClient,
        principal: PermissionPrincipal,
    ) -> None:
        self._session = session
        self._settings = settings
        self._search = search
        self._principal = principal

    def query(self, body: ChatQueryRequest) -> ChatQueryResponse:
        """
        DB-backed search (OpenSearch stand-in) with mandatory permission filter in SQL,
        then stub answer from chunk_text. Replace `self._search` with OpenSearch client later.
        """
        _ = self._session
        top_k = body.top_k or 5
        hits = self._search.search(
            query=body.question,
            top_k=top_k,
            principal=self._principal,
            index_name=self._settings.search_index_name,
        )
        sources = [
            ChatSourceItem(
                chunk_id=h.chunk_id,
                raw_document_id=h.raw_document_id,
                original_filename=h.original_filename,
                chunk_no=h.chunk_no,
                section_title=h.section_title,
                page_no=h.page_no,
                score=h.score,
                access_scope=h.access_scope,
            )
            for h in hits
        ]
        answer = _build_stub_answer(question=body.question, hits=hits)
        return ChatQueryResponse(answer=answer, sources=sources, session_id=body.session_id)
