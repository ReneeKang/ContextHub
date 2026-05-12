from __future__ import annotations

from app.llm.protocol import LLMCompletionResult, LLMMessage


class MockLLMClient:
    """Deterministic stub: summarizes that RAG context was supplied without echoing sources."""

    def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMCompletionResult:
        _ = max_tokens, temperature
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        preview = (last_user[:120] + "…") if len(last_user) > 120 else last_user
        text = (
            "[Mock LLM] 제공된 내부 문서 발췌를 바탕으로 답변을 생성했다고 가정한 스텁입니다.\n"
            f"사용자 질의 요약(앞부분): {preview!r}\n"
            "실제 응답은 `LLM_MOCK_MODE=false` 및 OpenAI-compatible 백엔드 설정 후 확인하세요."
        )
        return LLMCompletionResult(text=text, model="mock")
