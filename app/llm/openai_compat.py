from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any

from app.llm.protocol import LLMCompletionResult, LLMMessage

log = logging.getLogger("contexthub.llm.openai_compat")


def normalize_openai_compat_base_url(raw: str) -> str:
    """
    Strip whitespace/trailing slashes. If the user pasted a full ``…/chat/completions`` URL,
    strip that suffix so we append ``/chat/completions`` exactly once.

    Expected shape: ``https://host/v1`` (OpenAI) or any provider base that ends before ``/chat/completions``).
    """
    u = raw.strip().rstrip("/")
    suffix = "/chat/completions"
    if u.lower().endswith(suffix):
        u = u[: -len(suffix)].rstrip("/")
    return u


class OpenAICompatLLMClient:
    """
    Sync POST to ``{base_url}/chat/completions`` (OpenAI-compatible JSON).

    ``base_url`` should be like ``https://api.openai.com/v1`` (no trailing slash required).
    """

    def __init__(self, *, base_url: str, api_key: str | None = None, timeout_s: float = 120.0) -> None:
        self._base = normalize_openai_compat_base_url(base_url)
        self._api_key = (api_key or "").strip()
        self._timeout_s = timeout_s

    def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMCompletionResult:
        url = f"{self._base}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        body = json.dumps(payload).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8")
        except socket.timeout as exc:
            log.warning(
                "openai_compat timeout error_type=socket.timeout error_message=%s url=%s timeout_s=%s",
                str(exc)[:300],
                url,
                self._timeout_s,
            )
            raise
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            log.warning(
                "openai_compat HTTP error error_type=HTTPError error_message=%s status=%s url=%s body_prefix=%r",
                str(exc)[:300],
                exc.code,
                url,
                detail[:200],
            )
            raise
        except urllib.error.URLError as exc:
            log.warning(
                "openai_compat URL error error_type=URLError error_message=%s url=%s",
                str(exc)[:300],
                url,
            )
            raise

        data = json.loads(raw)
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("openai_compat: empty choices in response")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise ValueError("openai_compat: missing string message.content")
        used_model = data.get("model") or model
        if not isinstance(used_model, str):
            used_model = model
        return LLMCompletionResult(text=content.strip(), model=used_model)
