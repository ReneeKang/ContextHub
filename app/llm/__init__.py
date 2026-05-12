"""LLM client protocol and pluggable backends (mock, OpenAI-compatible HTTP)."""

from app.llm.backend import get_llm_client
from app.llm.protocol import LLMClient, LLMCompletionResult, LLMMessage

__all__ = ["LLMClient", "LLMCompletionResult", "LLMMessage", "get_llm_client"]
