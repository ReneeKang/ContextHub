from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.config.settings import SearchBackendLiteral


class ChatQueryRequest(BaseModel):
    question: str
    top_k: int | None = Field(default=5, ge=1, le=50)
    session_id: str | None = None

    # --- development / Swagger only (not production auth) ---
    test_department_codes: list[str] | None = Field(
        default=None,
        description=(
            "[DEV/TEST ONLY] If non-empty, used as stub principal `department_codes` for this request "
            "so DEPT-scoped chunks can be searched without code changes. Omitted = empty tuple (no DEPT access). "
            "Remove or ignore when Bearer/session auth replaces the stub."
        ),
    )


class ChatSourceItem(BaseModel):
    chunk_id: UUID
    raw_document_id: UUID
    original_filename: str
    chunk_no: int
    section_title: str | None = None
    page_no: int | None = None
    score: float = Field(
        ...,
        description="OpenSearch: `_score` (BM25). DB backend: placeholder `1.0` (no ranking).",
    )
    access_scope: str
    highlights: dict[str, list[str]] | None = Field(
        default=None,
        description="OpenSearch highlight fragments per field when enabled; omitted/null for DB or stub.",
    )


class ChatQueryResponse(BaseModel):
    answer: str
    search_backend: SearchBackendLiteral = Field(
        description=(
            "Retrieval backend for this request: `db` = PostgreSQL ILIKE; "
            "`opensearch_stub` = query validation only (no hits); `opensearch` = HTTP cluster (BM25, optional highlights)."
        ),
    )
    sources: list[ChatSourceItem]
    session_id: str | None = None


class ChatGenerateResponse(BaseModel):
    """RAG generation: same retrieval contract as ``/query``; ``sources`` are always from hits, not model parsing."""

    answer: str
    search_backend: SearchBackendLiteral
    sources: list[ChatSourceItem]
    session_id: str | None = None
    llm_model: str | None = Field(default=None, description="Model id reported by the LLM client (null when LLM skipped).")
    llm_mock: bool = Field(
        description="True when mock client or mock backend path was used. False when LLM was skipped (zero hits) or a live OpenAI-compatible client answered.",
    )
    retrieval_latency_ms: int
    llm_latency_ms: int | None = Field(default=None, description="Null when LLM was not invoked (e.g. zero hits).")
    total_latency_ms: int
