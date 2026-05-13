"""
Corporate internal ``POST …/api/v1/generate`` JSON API (not OpenAI chat/completions).

Maps :class:`LLMMessage` list to ``system_prompt`` / ``user_prompt`` and POSTs
``request_id``, ``model``, ``temperature``, ``max_tokens``. Response ``answer`` is passed through
:func:`sanitize_internal_generate_answer` then mapped to :class:`LLMCompletionResult` ``text``;
``model`` from JSON when present.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
import urllib.error
import urllib.request
from typing import Any, Final

from app.llm.protocol import LLMCompletionResult, LLMMessage

log = logging.getLogger("contexthub.llm.internal_generate")

_ASSISTANT_FINAL_MARK: Final[str] = "assistantfinal"
# Paired thinking blocks (non-greedy); tag names vary by upstream stack.
_THINK_BLOCK_PATTERNS: Final[tuple[str, ...]] = (
    r"(?is)<think>.*?</think>",
)


def sanitize_internal_generate_answer(text: str) -> str:
    """
    Strip channel-style noise from corporate ``generate`` responses.

    * If ``assistantfinal`` appears (any case), keep only the text **after** the last occurrence.
    * Drop leading lines that start with ``analysis`` (case-insensitive).
    * Remove thinking/channel markers and trim / collapse horizontal spaces.
    """
    s = text.strip()
    if not s:
        return s
    lower = s.lower()
    pos = lower.rfind(_ASSISTANT_FINAL_MARK)
    if pos != -1:
        tail = s[pos + len(_ASSISTANT_FINAL_MARK) :].strip()
        if tail:
            s = tail
    lines = s.splitlines()
    while lines and lines[0].strip() and lines[0].strip().lower().startswith("analysis"):
        lines.pop(0)
    s = "\n".join(lines).strip()
    for pat in _THINK_BLOCK_PATTERNS:
        s = re.sub(pat, "", s)
    s = re.sub(r"<\|[^|]+\|>", "", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def build_internal_generate_url(base_url: str, endpoint: str) -> str:
    """Join base (scheme+host+port) and path endpoint (default ``/api/v1/generate``)."""
    b = base_url.strip().rstrip("/")
    ep = endpoint.strip()
    if not ep:
        ep = "/api/v1/generate"
    if not ep.startswith("/"):
        ep = "/" + ep
    return b + ep


def messages_to_internal_generate_body(
    *,
    request_id: str,
    messages: list[LLMMessage],
    model: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """
    Map ``LLMMessage`` list to the gateway JSON body.

    * ``system`` roles → ``system_prompt`` (joined with blank lines).
    * ``user`` / ``assistant`` (in order) → ``user_prompt`` (user text as-is; assistant prefixed).
    """
    system_parts = [m.content for m in messages if m.role == "system"]
    user_blocks: list[str] = []
    for m in messages:
        if m.role == "user":
            user_blocks.append(m.content)
        elif m.role == "assistant":
            user_blocks.append(f"[assistant]\n{m.content}")
    system_prompt = "\n\n".join(system_parts).strip()
    user_prompt = "\n\n".join(user_blocks).strip()
    return {
        "request_id": request_id,
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def parse_internal_generate_response(data: dict[str, Any], *, fallback_model: str) -> LLMCompletionResult:
    """Use ``answer`` only for assistant text; ``model`` from JSON when a non-empty string."""
    raw = data.get("answer")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("internal_generate: missing or empty string field 'answer'")
    cleaned = sanitize_internal_generate_answer(raw)
    if not cleaned:
        cleaned = raw.strip()
    if not cleaned:
        raise ValueError("internal_generate: empty answer after sanitize")
    used = data.get("model")
    model_out = fallback_model
    if isinstance(used, str) and used.strip():
        model_out = used.strip()
    return LLMCompletionResult(text=cleaned, model=model_out)


class InternalGenerateLLMClient:
    """Sync POST to ``{INTERNAL_GENERATE_BASE_URL}{INTERNAL_GENERATE_ENDPOINT}``."""

    def __init__(
        self,
        *,
        base_url: str,
        endpoint: str = "/api/v1/generate",
        timeout_s: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self._url = build_internal_generate_url(base_url, endpoint)
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
        request_id = str(uuid.uuid4())
        payload = messages_to_internal_generate_body(
            request_id=request_id,
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
                "internal_generate HTTP error status=%s url=%s body_prefix=%r",
                exc.code,
                self._url,
                detail[:400],
            )
            raise
        except urllib.error.URLError as exc:
            log.warning("internal_generate URL error url=%s err=%s", self._url, str(exc)[:400])
            raise

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("internal_generate: response JSON must be an object")
        return parse_internal_generate_response(data, fallback_model=model)
