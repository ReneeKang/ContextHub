"""Tests for retrieval-only query normalization."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.adapters.search_protocol import PermissionPrincipal, SearchHit
from app.agents.nas_rag import build_nas_rag_user_prompt
from app.chat.retrieval_query import normalize_retrieval_query, normalize_retrieval_query_pair


def test_normalize_pair_applied_false_when_unchanged() -> None:
    q, applied = normalize_retrieval_query_pair("방화벽 포트 오픈")
    assert q == "방화벽 포트 오픈"
    assert applied is False


def test_normalize_pair_applied_true_when_suffix_removed() -> None:
    q, applied = normalize_retrieval_query_pair("방화벽 포트 오픈 설명")
    assert q == "방화벽 포트 오픈"
    assert applied is True


def test_normalize_pair_suffix_haejwo() -> None:
    q, applied = normalize_retrieval_query_pair("포트 오픈 해줘")
    assert q == "포트 오픈"
    assert applied is True


def test_original_question_unchanged_in_llm_user_prompt() -> None:
    q = "방화벽 포트 오픈 설명"
    prompt = build_nas_rag_user_prompt(question=q, hits=[])
    assert f"QUESTION:\n{q}\n" in prompt


def test_normalize_strips_common_request_phrases() -> None:
    assert normalize_retrieval_query("LDAP 알려줘") == "LDAP"
    assert normalize_retrieval_query("정책 요약해줘") == "정책"


def test_normalize_fallback_when_only_stopwords() -> None:
    assert normalize_retrieval_query("설명") == "설명"


def test_fake_search_receives_normalized_query() -> None:
    """Integration-style: run_nas_rag passes normalized string into SearchClient.search."""
    from unittest.mock import MagicMock

    from app.agents import nas_rag
    from app.chat.schemas import ChatQueryRequest
    from app.config.settings import Settings

    captured: dict[str, str] = {}

    class _Cap:
        def search(self, *, query: str, top_k: int, principal: PermissionPrincipal, index_name: str):
            captured["query"] = query
            return []

        def index_chunk_document(self, **kwargs: object) -> None:
            raise AssertionError

        def delete_chunks_for_document(self, **kwargs: object) -> None:
            raise AssertionError

    settings = Settings(llm_mock_mode=True, search_backend="db")
    body = ChatQueryRequest(question="방화벽 포트 오픈 설명")
    nas_rag.run_nas_rag_generate(
        MagicMock(), settings, _Cap(), PermissionPrincipal(user_id="u", department_codes=()), body
    )
    assert captured["query"] == "방화벽 포트 오픈"


def test_prompt_still_has_original_after_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from app.agents import nas_rag
    from app.chat.schemas import ChatQueryRequest
    from app.config.settings import Settings
    from app.llm.protocol import LLMCompletionResult, LLMMessage

    q = "방화벽 포트 오픈 설명"
    hits = [
        SearchHit(
            chunk_id=uuid4(),
            raw_document_id=uuid4(),
            original_filename="f.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="body",
            access_scope="PUBLIC",
            score=1.0,
            highlights=None,
        )
    ]

    class _LLM:
        def complete(
            self,
            *,
            messages: list[LLMMessage],
            model: str,
            max_tokens: int = 1024,
            temperature: float = 0.2,
        ) -> LLMCompletionResult:
            user = next(m.content for m in messages if m.role == "user")
            assert f"QUESTION:\n{q}\n" in user
            return LLMCompletionResult(text="ok", model="mock")

    class _S:
        def search(self, **kwargs):
            return list(hits)

        def index_chunk_document(self, **kwargs):
            raise AssertionError

        def delete_chunks_for_document(self, **kwargs):
            raise AssertionError

    monkeypatch.setattr(nas_rag, "get_llm_client", lambda _s: _LLM())
    nas_rag.run_nas_rag_generate(
        MagicMock(),
        Settings(llm_mock_mode=True, search_backend="db"),
        _S(),
        PermissionPrincipal(user_id="u", department_codes=()),
        ChatQueryRequest(question=q),
    )
