"""Unit tests for internal /chat LLM client (no real HTTP)."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import Settings
from app.llm import backend as llm_backend
from app.llm.internal_chat import (
    InternalChatLLMClient,
    build_internal_chat_request_body,
    build_internal_chat_url,
    extract_internal_chat_answer,
)
from app.llm.protocol import LLMMessage


@pytest.mark.parametrize(
    ("base", "endpoint", "expected"),
    [
        ("http://106.245.249.226:7888", "/chat", "http://106.245.249.226:7888/chat"),
        ("http://host:7888/", "/chat", "http://host:7888/chat"),
        ("http://host:7888", "chat", "http://host:7888/chat"),
    ],
)
def test_build_internal_chat_url(base: str, endpoint: str, expected: str) -> None:
    assert build_internal_chat_url(base, endpoint) == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "  hello  "},
        {"response": "ok"},
        {"content": "plain"},
        {"message": "top-level string"},
        {"message": {"content": "nested"}},
        {"choices": [{"message": {"content": "from-openai-shape"}}]},
        {"data": {"answer": "wrapped"}},
    ],
)
def test_extract_internal_chat_answer_variants(payload: dict) -> None:
    text = extract_internal_chat_answer(payload)
    assert text and len(text) >= 2
    assert "[Mock" not in text


def test_extract_internal_chat_answer_raises_on_empty() -> None:
    with pytest.raises(ValueError, match="could not extract"):
        extract_internal_chat_answer({})


def test_build_internal_chat_request_body_shapes() -> None:
    msgs = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="hi"),
    ]
    body = build_internal_chat_request_body(messages=msgs, model="m1", max_tokens=64, temperature=0.1)
    assert body["model"] == "m1"
    assert body["max_tokens"] == 64
    assert body["temperature"] == pytest.approx(0.1)
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def test_internal_chat_complete_posts_json_and_parses_answer() -> None:
    captured: dict[str, bytes] = {}

    def _fake_urlopen(req, timeout=None):
        _ = timeout
        assert req.full_url == "http://example.com:7888/chat"
        assert req.method == "POST"
        captured["data"] = req.data
        return BytesIO(json.dumps({"answer": "model-reply", "model": "corp-1"}).encode("utf-8"))

    client = InternalChatLLMClient(
        base_url="http://example.com:7888",
        endpoint="/chat",
        timeout_s=30.0,
        api_key=None,
    )
    with patch("app.llm.internal_chat.urllib.request.urlopen", side_effect=_fake_urlopen):
        out = client.complete(
            messages=[LLMMessage(role="user", content="q")],
            model="gpt-test",
            max_tokens=100,
            temperature=0.5,
        )
    assert out.text == "model-reply"
    assert out.model == "corp-1"
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["messages"] == [{"role": "user", "content": "q"}]
    assert payload["model"] == "gpt-test"


def test_internal_chat_complete_sends_bearer_when_api_key_set() -> None:
    headers_captured: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"answer": "x"}).encode("utf-8")

    def _fake_urlopen(req, timeout=None):
        _ = timeout
        headers_captured.update({k: v for k, v in req.header_items()})
        return _Resp()

    client = InternalChatLLMClient(
        base_url="http://example.com",
        endpoint="/chat",
        api_key="secret-token",
    )
    with patch("app.llm.internal_chat.urllib.request.urlopen", side_effect=_fake_urlopen):
        client.complete(messages=[LLMMessage(role="user", content="a")], model="m")
    assert headers_captured.get("Authorization") == "Bearer secret-token"


def test_get_llm_client_instantiates_internal_chat() -> None:
    with patch.object(llm_backend, "InternalChatLLMClient") as ctor:
        ctor.return_value = MagicMock()
        settings = Settings(
            llm_mock_mode=False,
            llm_backend="internal_chat",
            internal_chat_base_url="http://106.245.249.226:7888",
            internal_chat_endpoint="/chat",
            internal_chat_timeout_seconds=99.0,
            internal_chat_api_key=" k ",
        )
        llm_backend.get_llm_client(settings)
        ctor.assert_called_once_with(
            base_url="http://106.245.249.226:7888",
            endpoint="/chat",
            timeout_s=99.0,
            api_key="k",
        )
