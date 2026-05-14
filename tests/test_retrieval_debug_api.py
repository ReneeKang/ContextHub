"""Retrieval debug: structured logs + optional ``debug`` in /query and /generate responses."""

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
from app.config.settings import Settings
from app.llm.protocol import LLMCompletionResult, LLMMessage
from app.main import app


def _hit() -> SearchHit:
    cid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    rid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    return SearchHit(
        chunk_id=cid,
        raw_document_id=rid,
        original_filename="doc.txt",
        chunk_no=1,
        section_title=None,
        page_no=None,
        chunk_text="SECRET_BODY",
        access_scope="PUBLIC",
        score=1.25,
        highlights=None,
    )


class _SearchOneHit(SearchClient):
    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        _ = query, top_k, principal, index_name
        return [_hit()]

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError


def _fake_db() -> Generator[MagicMock, None, None]:
    yield MagicMock()


@pytest.fixture
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.usefixtures("_clear_overrides")
def test_query_debug_disabled_omits_debug_key() -> None:
    search = _SearchOneHit()

    def _settings() -> Settings:
        return Settings(
            llm_mock_mode=True,
            search_backend="db",
            enable_retrieval_debug=False,
            database_url="postgresql+psycopg://x@127.0.0.1:5433/x",
        )

    app.dependency_overrides[chat_deps.get_db] = _fake_db
    app.dependency_overrides[chat_deps.get_search_client] = lambda: search
    app.dependency_overrides[chat_deps.get_settings_dep] = _settings

    client = TestClient(app)
    resp = client.post("/api/v1/chat/query", json={"question": "hello", "top_k": 3})
    assert resp.status_code == 200
    assert "debug" not in resp.json()


@pytest.mark.usefixtures("_clear_overrides")
def test_query_debug_enabled_includes_debug_and_log_has_retrieval_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    search = _SearchOneHit()

    def _settings() -> Settings:
        return Settings(
            llm_mock_mode=True,
            search_backend="db",
            enable_retrieval_debug=True,
            database_url="postgresql+psycopg://x@127.0.0.1:5433/x",
        )

    app.dependency_overrides[chat_deps.get_db] = _fake_db
    app.dependency_overrides[chat_deps.get_search_client] = lambda: search
    app.dependency_overrides[chat_deps.get_settings_dep] = _settings

    client = TestClient(app)
    resp = client.post("/api/v1/chat/query", json={"question": "hello world", "top_k": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert "debug" in data
    dbg = data["debug"]
    assert dbg["backend"] == "db"
    assert dbg["retrieval_query"] == "hello world"
    assert dbg["original_query"] == "hello world"
    assert dbg["top_k"] == 3
    assert dbg["retrieval_count"] == 1
    assert dbg["retrieved_chunk_ids"] == ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
    assert len(dbg["chunks"]) == 1
    assert dbg["chunks"][0]["chunk_no"] == 1
    assert "chunk_text" not in dbg["chunks"][0]

    rd = [r.getMessage() for r in caplog.records if r.getMessage().startswith("retrieval_debug ")]
    assert rd
    payload = json.loads(rd[-1].split("retrieval_debug ", 1)[1])
    assert payload["retrieval_backend"] == "db"
    assert payload["retrieval_count"] == 1
    assert "SECRET_BODY" not in rd[-1]


@pytest.mark.usefixtures("_clear_overrides")
def test_generate_debug_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    search = _SearchOneHit()

    def _settings() -> Settings:
        return Settings(
            llm_mock_mode=True,
            search_backend="db",
            enable_retrieval_debug=True,
            database_url="postgresql+psycopg://x@127.0.0.1:5433/x",
        )

    class _LLM:
        def complete(
            self,
            *,
            messages: list[LLMMessage],
            model: str,
            max_tokens: int = 1024,
            temperature: float = 0.2,
        ) -> LLMCompletionResult:
            return LLMCompletionResult(text="ok", model="mock")

    monkeypatch.setattr(nas_rag_mod, "get_llm_client", lambda _s: _LLM())

    app.dependency_overrides[chat_deps.get_db] = _fake_db
    app.dependency_overrides[chat_deps.get_search_client] = lambda: search
    app.dependency_overrides[chat_deps.get_settings_dep] = _settings

    client = TestClient(app)
    resp = client.post("/api/v1/chat/generate", json={"question": "q1", "top_k": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["debug"]["retrieval_query"] == "q1"
    assert data["debug"]["retrieval_count"] == 1
