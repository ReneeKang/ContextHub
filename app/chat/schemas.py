from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_serializer

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


class ChatGenerateRequest(ChatQueryRequest):
    """``POST /api/v1/chat/generate`` body: same as ``ChatQueryRequest`` plus optional document-scoped retrieval."""

    document_ids: list[UUID] | None = Field(
        default=None,
        max_length=50,
        description=(
            "When non-empty, only chunks whose ``raw_document_id`` is in this set are used for the LLM prompt "
            "(filter applied **after** permission-aware ``SearchClient.search``). Omit or null for full retrieval."
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


class RetrievalDebugChunkItem(BaseModel):
    """Chunk metadata for retrieval debug (no ``chunk_text``)."""

    chunk_id: UUID
    raw_document_id: UUID
    original_filename: str
    chunk_no: int
    section_title: str | None = None
    page_no: int | None = None
    score: float
    access_scope: str
    highlights: dict[str, list[str]] | None = None
    matched_fields: list[str] = Field(
        default_factory=list,
        description="OpenSearch highlight field keys present for this hit (sorted).",
    )
    highlight_terms: list[str] = Field(
        default_factory=list,
        description="Short tokens extracted from ``<em>...</em>`` spans inside highlight fragments.",
    )
    document_rank: int = Field(
        ge=1,
        description="Rank of this chunk's document by max chunk score among hits (1 = strongest).",
    )
    chunk_rank: int = Field(ge=1, description="1-based index of this chunk in the retrieval hit list.")


class GenerationContextChunkItem(BaseModel):
    """Truncated chunk body preview for ``/generate`` debug (LLM prompt context only)."""

    chunk_id: UUID
    raw_document_id: UUID
    original_filename: str
    chunk_no: int
    section_title: str | None = None
    score: float
    char_count: int = Field(ge=0, description="Full ``chunk_text`` length before preview truncation.")
    text_preview: str = Field(description="First ~300 characters of ``chunk_text`` (no full body).")
    included_in_prompt: bool = Field(
        default=True,
        description="True when this chunk was included in the LLM user prompt CONTEXT block.",
    )


class RetrievalDebugInfo(BaseModel):
    """Returned as ``debug`` when ``ENABLE_RETRIEVAL_DEBUG=true`` (dev / ops)."""

    original_query: str
    retrieval_query: str
    normalization_applied: bool
    backend: str = Field(description="Same as ``search_backend`` / ``retrieval_backend`` in logs.")
    retrieval_count: int
    top_k: int
    retrieval_latency_ms: int
    retrieved_chunk_ids: list[str]
    retrieved_document_ids: list[str]
    retrieval_scores: list[float]
    retrieval_filenames: list[str]
    chunks: list[RetrievalDebugChunkItem]
    generation_context_chunks: list[GenerationContextChunkItem] | None = Field(
        default=None,
        description="``/generate`` only: truncated previews of chunks sent to the LLM (when debug enabled).",
    )
    llm_system_message_char_count: int | None = Field(
        default=None,
        description="``/generate`` with hits: length of system message sent to the LLM (same as ``NAS_RAG_SYSTEM_PROMPT``).",
    )
    llm_user_message_char_count: int | None = Field(
        default=None,
        description="``/generate`` with hits: length of user message (output of ``build_nas_rag_user_prompt``).",
    )
    llm_user_message_preview: str | None = Field(
        default=None,
        description=(
            "QUESTION block + note that CONTEXT was attached; excerpt bodies are never included "
            "(use ``generation_context_chunks`` for truncated per-chunk text)."
        ),
    )

    @model_serializer(mode="wrap")
    def _serialize_omit_null_generation_context(self, serializer):
        data = serializer(self)
        if data.get("generation_context_chunks") is None:
            data.pop("generation_context_chunks", None)
        for k in (
            "llm_system_message_char_count",
            "llm_user_message_char_count",
            "llm_user_message_preview",
        ):
            if data.get(k) is None:
                data.pop(k, None)
        return data


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
    debug: RetrievalDebugInfo | None = Field(
        default=None,
        description="Present only when ENABLE_RETRIEVAL_DEBUG=true; omitted from JSON when null.",
    )

    @model_serializer(mode="wrap")
    def _serialize_omit_null_debug(self, serializer):
        data = serializer(self)
        if data.get("debug") is None:
            data.pop("debug", None)
        return data


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
    selected_document_ids: list[str] | None = Field(
        default=None,
        description="Echo of requested ``document_ids`` (UUID strings) when the client sent a non-empty list; null otherwise.",
    )
    filtered_retrieval_count: int = Field(
        default=0,
        ge=0,
        description="Chunk count after optional ``document_ids`` filter (what the LLM saw when invoked).",
    )
    debug: RetrievalDebugInfo | None = Field(
        default=None,
        description="Present only when ENABLE_RETRIEVAL_DEBUG=true; omitted from JSON when null.",
    )

    @model_serializer(mode="wrap")
    def _serialize_omit_null_debug(self, serializer):
        data = serializer(self)
        if data.get("debug") is None:
            data.pop("debug", None)
        return data


# --- Document discovery (POST /api/v1/chat/discover) ---


class DiscoverRequest(BaseModel):
    """Maximum distinct documents to return; chunk retrieval over-fetches before grouping."""

    question: str
    top_k: int | None = Field(default=10, ge=1, le=50)
    session_id: str | None = None
    test_department_codes: list[str] | None = Field(
        default=None,
        description="Same stub principal semantics as ``ChatQueryRequest.test_department_codes``.",
    )


class DiscoverMatchedChunkItem(BaseModel):
    chunk_id: UUID
    chunk_no: int
    section_title: str | None = None
    page_no: int | None = None
    score: float
    highlights: dict[str, list[str]] | None = Field(
        default=None,
        description="Optional trimmed highlight fragments (no full chunk body).",
    )


class DiscoverDocumentItem(BaseModel):
    raw_document_id: UUID
    original_filename: str
    path: str = Field(description="Preferred: ``inbox_path``; fallback stored path for display.")
    project_key: str | None = Field(description="From ``/projects/{slug}/`` in path when present.")
    access_scope: str
    top_score: float
    matched_chunk_count: int
    representative_sections: list[str] = Field(description="Deduped section titles, max 3.")
    matched_chunks: list[DiscoverMatchedChunkItem] = Field(
        description="Top chunks by score for this document (capped, no chunk_text).",
    )


class DiscoverResponse(BaseModel):
    original_query: str
    retrieval_query: str
    normalization_applied: bool
    document_count: int
    documents: list[DiscoverDocumentItem]
    search_backend: SearchBackendLiteral
    retrieval_latency_ms: int
