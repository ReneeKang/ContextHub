"""
Swagger-equivalent HTTP checks: same JSON body as /docs Try it out.

Uses FastAPI TestClient + dependency overrides (no live DB/OpenSearch).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.agents import nas_rag as nas_rag_mod
from app.chat import deps as chat_deps
from app.llm.protocol import LLMCompletionResult, LLMMessage
from app.main import app


def _fixed_hit() -> SearchHit:
    cid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    rid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    return SearchHit(
        chunk_id=cid,
        raw_document_id=rid,
        original_filename="firewall-doc.txt",
        chunk_no=1,
        section_title="포트",
        page_no=1,
        chunk_text="방화벽 포트 오픈 절차",
        access_scope="PUBLIC",
        score=1.0,
        highlights=None,
    )


class _RecordingSearchClient(SearchClient):
    """Returns hits only when retrieval query equals normalized ``방화벽 포트 오픈``."""

    def __init__(self) -> None:
        self.search_queries: list[str] = []

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        _ = top_k, principal, index_name
        self.search_queries.append(query)
        if query == "방화벽 포트 오픈":
            return [_fixed_hit()]
        return []

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError


_VARIANTS = (
    "방화벽 포트 오픈",
    "방화벽 포트 오픈 설명",
    "방화벽 포트 오픈 알려줘",
    "방화벽 포트 오픈 해줘",
)


@pytest.fixture
def swagger_client() -> Generator[tuple[TestClient, _RecordingSearchClient], None, None]:
    search = _RecordingSearchClient()

    def _fake_db() -> Generator[MagicMock, None, None]:
        yield MagicMock()

    app.dependency_overrides[chat_deps.get_db] = _fake_db
    app.dependency_overrides[chat_deps.get_search_client] = lambda: search

    client = TestClient(app)
    try:
        yield client, search
    finally:
        app.dependency_overrides.clear()


def test_chat_query_variants_same_documents_and_log_fields(
    swagger_client: tuple[TestClient, _RecordingSearchClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, search = swagger_client
    caplog.set_level(logging.INFO)

    expected_chunk = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    for q in _VARIANTS:
        resp = client.post("/api/v1/chat/query", json={"question": q, "top_k": 5})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["chunk_id"] == expected_chunk

    assert search.search_queries == ["방화벽 포트 오픈"] * len(_VARIANTS)

    svc_logs = [r.getMessage() for r in caplog.records if r.name == "contexthub.chat.service"]
    chat_query_logs = [m for m in svc_logs if m.startswith("chat_query")]
    assert len(chat_query_logs) >= len(_VARIANTS)
    for msg in chat_query_logs[-len(_VARIANTS) :]:
        assert "original_query=" in msg
        assert "retrieval_query=" in msg
        assert "normalization_applied=" in msg
        assert "retrieval_count=" in msg

    rd_logs = [m for m in svc_logs if m.startswith("retrieval_debug ")]
    assert len(rd_logs) >= len(_VARIANTS)
    for msg in rd_logs[-len(_VARIANTS) :]:
        payload = json.loads(msg[len("retrieval_debug ") :])
        assert payload["retrieval_query"] == "방화벽 포트 오픈"
        assert payload["retrieval_backend"] in ("db", "opensearch", "opensearch_stub")
        assert "retrieval_latency_ms" in payload


def test_chat_generate_variants_same_documents_logs_and_prompt_uses_original(
    swagger_client: tuple[TestClient, _RecordingSearchClient],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, search = swagger_client
    caplog.set_level(logging.INFO)

    captured_user_contents: list[str] = []

    class _CapLLM:
        def complete(
            self,
            *,
            messages: list[LLMMessage],
            model: str,
            max_tokens: int = 1024,
            temperature: float = 0.2,
        ) -> LLMCompletionResult:
            user = next(m.content for m in messages if m.role == "user")
            captured_user_contents.append(user)
            return LLMCompletionResult(text="ok", model="mock")

    monkeypatch.setattr(nas_rag_mod, "get_llm_client", lambda _s: _CapLLM())

    expected_chunk = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    for q in _VARIANTS:
        resp = client.post("/api/v1/chat/generate", json={"question": q, "top_k": 5})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["chunk_id"] == expected_chunk

    assert search.search_queries == ["방화벽 포트 오픈"] * len(_VARIANTS)

    for q, user in zip(_VARIANTS, captured_user_contents, strict=True):
        assert f"QUESTION:\n{q}\n" in user

    rag_logs = [r.getMessage() for r in caplog.records if r.name == "contexthub.agents.nas_rag"]
    gen_logs = [m for m in rag_logs if "nas_rag_generate" in m]
    assert len(gen_logs) >= len(_VARIANTS)
    for msg in gen_logs[-len(_VARIANTS) :]:
        assert "original_query=" in msg
        assert "retrieval_query=" in msg
        assert "normalization_applied=" in msg
        assert "retrieval_count=" in msg

    rd_logs = [m for m in rag_logs if m.startswith("retrieval_debug ")]
    assert len(rd_logs) >= len(_VARIANTS)
    for msg in rd_logs[-len(_VARIANTS) :]:
        payload = json.loads(msg[len("retrieval_debug ") :])
        assert payload["retrieval_query"] == "방화벽 포트 오픈"
