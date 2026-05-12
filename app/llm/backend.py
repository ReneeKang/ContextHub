from __future__ import annotations

from app.config.settings import Settings
from app.llm.mock import MockLLMClient
from app.llm.openai_compat import OpenAICompatLLMClient
from app.llm.protocol import LLMClient


def get_llm_client(settings: Settings) -> LLMClient:
    """
    Select LLM implementation.

    * ``LLM_MOCK_MODE=true`` (default) → :class:`MockLLMClient` (ignores ``LLM_BACKEND`` for real HTTP).
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=mock`` → mock.
    * ``LLM_MOCK_MODE=false`` and ``LLM_BACKEND=openai_compat`` → HTTP client
      (requires ``OPENAI_COMPAT_BASE_URL`` and ``OPENAI_COMPAT_API_KEY``).
    """
    if settings.llm_mock_mode:
        return MockLLMClient()
    if settings.llm_backend == "mock":
        return MockLLMClient()
    base = (settings.openai_compat_base_url or "").strip()
    key = settings.openai_compat_api_key or ""
    if not base or not key:
        raise RuntimeError(
            "OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_API_KEY are required when "
            "LLM_MOCK_MODE=false and LLM_BACKEND=openai_compat"
        )
    return OpenAICompatLLMClient(
        base_url=base,
        api_key=key,
        timeout_s=settings.openai_compat_timeout_seconds,
    )
