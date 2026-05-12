from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMCompletionResult:
    text: str
    model: str


@runtime_checkable
class LLMClient(Protocol):
    """
    Minimal chat-completions style surface (sync, no streaming).

    Implementations (:class:`app.llm.mock.MockLLMClient`, :class:`app.llm.openai_compat.OpenAICompatLLMClient`)
    must accept the same keyword arguments and return :class:`LLMCompletionResult`.
    HTTP backends should POST to ``{normalized_base}/chat/completions`` (see ``normalize_openai_compat_base_url``).
    """

    def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMCompletionResult:
        """Return assistant text; implementations must not log full user context verbatim at INFO."""
        ...
