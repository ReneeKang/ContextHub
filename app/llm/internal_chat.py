"""
Corporate internal ``/chat`` HTTP backend (not OpenAI ``/v1/chat/completions``).

POST ``{INTERNAL_CHAT_BASE_URL}{INTERNAL_CHAT_ENDPOINT}`` (default endpoint ``/chat``)
with a JSON body derived from :class:`LLMMessage` list. Response text is parsed from
several common shapes (OpenAI-like ``choices``, or top-level ``answer`` / ``message`` / ``content``).

If the live API contract differs, adjust :func:`build_internal_chat_request_body` /
:func:`extract_internal_chat_answer` to match the OpenAPI spec of the gateway.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.llm.protocol import LLMCompletionResult, LLMMessage

log = logging.getLogger("contexthub.llm.internal_chat")


def build_internal_chat_url(base_url: str, endpoint: str) -> str:
    """Join base (scheme+host+port, optional path) and path endpoint (leading ``/`` recommended)."""
    b = base_url.strip().rstrip("/")
    ep = endpoint.strip()
    if not ep:
        ep = "/chat"
    if not ep.startswith("/"):
        ep = "/" + ep
    return b + ep


def build_internal_chat_request_body(
    *,
    messages: list[LLMMessage],
    model: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """
    Map ContextHub ``LLMMessage`` list to the internal chat JSON body.

    Default shape matches many internal gateways (OpenAI-like ``messages`` array).
    """
    return {
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def extract_internal_chat_answer(data: dict[str, Any], *, _depth: int = 0) -> str:
    """
    Extract assistant plain text from a JSON object. Tries several layouts without
    echoing debug noise into the returned string.
    """
    if _depth > 6:
        raise ValueError("internal_chat: response nesting too deep")

    # OpenAI-compatible: choices[0].message.content
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            msg = c0.get("message")
            if isinstance(msg, dict):
                c = msg.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()
            # some stacks put content on choice root
            c2 = c0.get("content") or c0.get("text")
            if isinstance(c2, str) and c2.strip():
                return c2.strip()

    # Top-level string fields (common internal APIs)
    for key in ("answer", "response", "text", "output", "content"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    msg = data.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    if isinstance(msg, dict):
        inner = msg.get("content") or msg.get("text") or msg.get("answer")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()

    # Nested data / result wrappers
    for wrap in ("data", "result", "payload"):
        inner = data.get(wrap)
        if isinstance(inner, dict):
            try:
                return extract_internal_chat_answer(inner, _depth=_depth + 1)
            except ValueError:
                continue

    raise ValueError("internal_chat: could not extract answer text from JSON response")


class InternalChatLLMClient:
    """Sync POST to ``{base}{endpoint}`` (default ``/chat``); optional Bearer API key."""

    def __init__(
        self,
        *,
        base_url: str,
        endpoint: str = "/chat",
        timeout_s: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self._url = build_internal_chat_url(base_url, endpoint)
        self._timeout_s = timeout_s
        self._api_key = (api_key or "").strip() or None

    def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMCompletionResult:
        payload = build_internal_chat_request_body(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = urllib.request.Request(self._url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            log.warning(
                "internal_chat HTTP error status=%s url=%s body_prefix=%r",
                exc.code,
                self._url,
                detail[:400],
            )
            raise
        except urllib.error.URLError as exc:
            log.warning("internal_chat URL error url=%s err=%s", self._url, str(exc)[:400])
            raise

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("internal_chat: response JSON must be an object")
        text = extract_internal_chat_answer(data)
        used = data.get("model")
        used_model = model if not isinstance(used, str) or not used.strip() else used.strip()
        return LLMCompletionResult(text=text, model=used_model)
