from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.nas_rag import NasRagLLMError, run_nas_rag_generate
from app.chat.deps import get_db, get_search_client, get_settings_dep, resolve_stub_principal_for_chat
from app.chat.schemas import ChatGenerateResponse, ChatQueryRequest, ChatQueryResponse
from app.chat.service import ChatService
from app.config.settings import Settings

router = APIRouter()


@router.post("/query", response_model=ChatQueryResponse)
def post_chat_query(
    body: ChatQueryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    search=Depends(get_search_client),
) -> ChatQueryResponse:
    principal = resolve_stub_principal_for_chat(body)
    service = ChatService(db, settings, search, principal)
    return service.query(body)


@router.post("/generate", response_model=ChatGenerateResponse)
def post_chat_generate(
    body: ChatQueryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    search=Depends(get_search_client),
) -> ChatGenerateResponse:
    """Retrieval + LLM answer (mock by default). ``/query`` remains retrieval-only with stub text."""
    principal = resolve_stub_principal_for_chat(body)
    try:
        return run_nas_rag_generate(db, settings, search, principal, body)
    except NasRagLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/history/{session_id}")
def get_chat_history(session_id: str) -> None:
    _ = session_id
    raise HTTPException(status_code=501, detail="Not implemented in PoC skeleton")
