from __future__ import annotations

from app.config.settings import Settings
from app.llm.internal_chat import InternalChatLLMClient
from app.llm.internal_generate import InternalGenerateLLMClient
from app.llm.mock import MockLLMClient
from app.llm.openai_compat import OpenAICompatLLMClient
from app.llm.protocol import LLMClient


def get_llm_client(settings: Settings) -> LLMClient:
    """
    Select LLM implementation.

    * ``LLM_MOCK_MODE=true`` (default) → :class:`MockLLMClient` (ignores ``LLM_BACKEND`` for real HTTP).
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=mock`` → mock.
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=internal_chat`` → :class:`InternalChatLLMClient`
      (requires ``INTERNAL_CHAT_BASE_URL``).
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=internal_generate`` → :class:`InternalGenerateLLMClient`
      (requires ``INTERNAL_GENERATE_BASE_URL``).
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=openai_compat`` → :class:`OpenAICompatLLMClient`
      (requires ``OPENAI_COMPAT_BASE_URL``; ``OPENAI_COMPAT_API_KEY`` optional — omit ``Authorization`` when unset/empty for local vLLM).
    """
    if settings.llm_mock_mode:
        return MockLLMClient()
    if settings.llm_backend == "mock":
        return MockLLMClient()
    if settings.llm_backend == "internal_chat":
        base = (settings.internal_chat_base_url or "").strip()
        if not base:
            raise RuntimeError(
                "INTERNAL_CHAT_BASE_URL is required when LLM_MOCK_MODE=false and LLM_BACKEND=internal_chat"
            )
        ep = (settings.internal_chat_endpoint or "/chat").strip() or "/chat"
        return InternalChatLLMClient(
            base_url=base,
            endpoint=ep,
            timeout_s=settings.internal_chat_timeout_seconds,
            api_key=(settings.internal_chat_api_key or "").strip() or None,
        )
    if settings.llm_backend == "internal_generate":
        base = (settings.internal_generate_base_url or "").strip()
        if not base:
            raise RuntimeError(
                "INTERNAL_GENERATE_BASE_URL is required when LLM_MOCK_MODE=false and LLM_BACKEND=internal_generate"
            )
        ep = (settings.internal_generate_endpoint or "/api/v1/generate").strip() or "/api/v1/generate"
        return InternalGenerateLLMClient(
            base_url=base,
            endpoint=ep,
            timeout_s=settings.internal_generate_timeout_seconds,
            api_key=(settings.internal_generate_api_key or "").strip() or None,
        )
    if settings.llm_backend == "openai_compat":
        base = (settings.openai_compat_base_url or "").strip()
        if not base:
            raise RuntimeError(
                "OPENAI_COMPAT_BASE_URL is required when LLM_MOCK_MODE=false and LLM_BACKEND=openai_compat"
            )
        key = (settings.openai_compat_api_key or "").strip() or None
        return OpenAICompatLLMClient(
            base_url=base,
            api_key=key,
            timeout_s=settings.openai_compat_timeout_seconds,
        )
    raise RuntimeError(f"Unsupported LLM_BACKEND: {settings.llm_backend!r}")
