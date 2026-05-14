"""Unit tests for NAS RAG generation (no DB, no HTTP)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.adapters.search_protocol import PermissionPrincipal, SearchHit
from app.agents import nas_rag
from app.chat.schemas import ChatGenerateRequest, ChatQueryRequest
from app.config.settings import Settings
from app.llm.protocol import LLMCompletionResult, LLMMessage


class _FakeSearchClient:
    """Minimal stand-in: only ``search`` is used by ``run_nas_rag_generate``."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        _ = query, top_k, principal, index_name
        return list(self._hits)

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError("not used in nas_rag")

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError("not used in nas_rag")


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMCompletionResult:
        _ = messages, model, max_tokens, temperature
        self.calls += 1
        return LLMCompletionResult(text="synthetic-answer", model="mock")


def test_query_log_snippet_truncates_long_question() -> None:
    from app.chat.retrieval_query import format_query_log_snippet

    long_q = "x" * 500
    s = format_query_log_snippet(long_q, max_len=400)
    assert len(s) == 401  # 400 + ellipsis
    assert s.endswith("…")
    assert "x" * 400 in s


def test_normalize_openai_compat_strips_duplicate_chat_completions() -> None:
    from app.llm.openai_compat import normalize_openai_compat_base_url

    assert normalize_openai_compat_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
    assert (
        normalize_openai_compat_base_url("https://api.openai.com/v1/chat/completions")
        == "https://api.openai.com/v1"
    )
    assert normalize_openai_compat_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"


def test_zero_hits_does_not_call_get_llm_client(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    def _boom(_settings: Settings) -> object:
        raise AssertionError("get_llm_client must not run when retrieval is empty")

    monkeypatch.setattr(nas_rag, "get_llm_client", _boom)
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatQueryRequest(question="hello")
    principal = PermissionPrincipal(user_id="stub-user", department_codes=())
    session = MagicMock()
    out = nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient([]), principal, body)
    assert "검색된 내부 문서 발췌가 없어" in out.answer
    assert out.sources == []
    assert out.llm_latency_ms is None
    assert out.filtered_retrieval_count == 0
    assert out.selected_document_ids is None
    assert "SECRET_CHUNK" not in caplog.text


def test_hits_invoke_llm_and_sources_mirror_hits(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    cid = uuid4()
    rid = uuid4()
    hits = [
        SearchHit(
            chunk_id=cid,
            raw_document_id=rid,
            original_filename="doc.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="SECRET_CHUNK_BODY_XYZ",
            access_scope="PUBLIC",
            score=1.0,
            highlights=None,
        )
    ]
    rec = _RecordingLLM()
    monkeypatch.setattr(nas_rag, "get_llm_client", lambda _s: rec)
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatQueryRequest(question="q")
    principal = PermissionPrincipal(user_id="stub-user", department_codes=())
    session = MagicMock()
    out = nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient(hits), principal, body)
    assert rec.calls == 1
    assert out.answer == "synthetic-answer"
    assert len(out.sources) == 1
    assert out.sources[0].chunk_id == cid
    assert out.sources[0].raw_document_id == rid
    assert out.filtered_retrieval_count == 1
    assert out.selected_document_ids is None
    assert "SECRET_CHUNK_BODY_XYZ" not in caplog.text


def test_get_llm_client_passes_timeout_to_openai_compat() -> None:
    from unittest.mock import MagicMock, patch

    from app.llm import backend as llm_backend

    with patch.object(llm_backend, "OpenAICompatLLMClient") as ctor:
        ctor.return_value = MagicMock()
        settings = Settings(
            llm_mock_mode=False,
            llm_backend="openai_compat",
            openai_compat_base_url="https://api.openai.com/v1",
            openai_compat_api_key="secret-key",
            openai_compat_timeout_seconds=42.5,
            llm_model="gpt-test",
        )
        llm_backend.get_llm_client(settings)
        ctor.assert_called_once_with(base_url="https://api.openai.com/v1", api_key="secret-key", timeout_s=42.5)


def test_llm_failure_logs_error_type_and_message(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    hits = [
        SearchHit(
            chunk_id=uuid4(),
            raw_document_id=uuid4(),
            original_filename="a.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="SECRET",
            access_scope="PUBLIC",
            score=1.0,
            highlights=None,
        )
    ]

    class _Boom:
        def complete(
            self,
            *,
            messages: list[LLMMessage],
            model: str,
            max_tokens: int = 1024,
            temperature: float = 0.2,
        ) -> LLMCompletionResult:
            _ = messages, model, max_tokens, temperature
            raise ValueError("upstream failure")

    monkeypatch.setattr(nas_rag, "get_llm_client", lambda _s: _Boom())
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatQueryRequest(question="x")
    principal = PermissionPrincipal(user_id="u", department_codes=())
    session = MagicMock()
    with pytest.raises(nas_rag.NasRagLLMError):
        nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient(hits), principal, body)
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "error_type=ValueError" in joined
    assert "error_message=" in joined
    assert "SECRET" not in joined


def test_document_ids_filters_prompt_and_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    rid_a = uuid4()
    rid_b = uuid4()
    cid_a = uuid4()
    cid_b = uuid4()
    hits = [
        SearchHit(
            chunk_id=cid_a,
            raw_document_id=rid_a,
            original_filename="a.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="DOC_A_ONLY",
            access_scope="PUBLIC",
            score=1.0,
            highlights=None,
        ),
        SearchHit(
            chunk_id=cid_b,
            raw_document_id=rid_b,
            original_filename="b.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="DOC_B_ONLY",
            access_scope="PUBLIC",
            score=2.0,
            highlights=None,
        ),
    ]
    captured: list[list[LLMMessage]] = []

    class _Cap:
        def complete(
            self,
            *,
            messages: list[LLMMessage],
            model: str,
            max_tokens: int = 1024,
            temperature: float = 0.2,
        ) -> LLMCompletionResult:
            captured.append(messages)
            return LLMCompletionResult(text="ok", model="m")

    monkeypatch.setattr(nas_rag, "get_llm_client", lambda _s: _Cap())
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatGenerateRequest(question="q", document_ids=[rid_b])
    principal = PermissionPrincipal(user_id="stub-user", department_codes=())
    session = MagicMock()
    out = nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient(hits), principal, body)
    assert len(out.sources) == 1
    assert out.sources[0].raw_document_id == rid_b
    assert out.filtered_retrieval_count == 1
    assert out.selected_document_ids == [str(rid_b)]
    user_content = captured[0][1].content
    assert "DOC_B_ONLY" in user_content
    assert "DOC_A_ONLY" not in user_content


def test_document_ids_no_match_after_search_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_settings: Settings) -> object:
        raise AssertionError("LLM must not run when document filter removes all chunks")

    monkeypatch.setattr(nas_rag, "get_llm_client", _boom)
    rid_in_index = uuid4()
    rid_requested = uuid4()
    hits = [
        SearchHit(
            chunk_id=uuid4(),
            raw_document_id=rid_in_index,
            original_filename="x.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="BODY",
            access_scope="PUBLIC",
            score=1.0,
            highlights=None,
        )
    ]
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatGenerateRequest(question="q", document_ids=[rid_requested])
    principal = PermissionPrincipal(user_id="stub-user", department_codes=())
    session = MagicMock()
    out = nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient(hits), principal, body)
    assert "선택한 문서" in out.answer
    assert out.sources == []
    assert out.filtered_retrieval_count == 0
    assert out.selected_document_ids == [str(rid_requested)]


def test_document_ids_empty_search_still_zero_hit_not_filtered_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_settings: Settings) -> object:
        raise AssertionError("get_llm_client must not run")

    monkeypatch.setattr(nas_rag, "get_llm_client", _boom)
    rid = uuid4()
    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatGenerateRequest(question="q", document_ids=[rid])
    principal = PermissionPrincipal(user_id="stub-user", department_codes=())
    session = MagicMock()
    out = nas_rag.run_nas_rag_generate(session, settings, _FakeSearchClient([]), principal, body)
    assert "검색된 내부 문서 발췌가 없어" in out.answer
    assert out.filtered_retrieval_count == 0
    assert out.selected_document_ids == [str(rid)]
