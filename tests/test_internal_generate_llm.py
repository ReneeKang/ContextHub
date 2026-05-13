"""Unit tests for internal /api/v1/generate LLM client (no real HTTP)."""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import Settings
from app.llm import backend as llm_backend
from app.llm.internal_generate import (
    InternalGenerateLLMClient,
    build_internal_generate_url,
    messages_to_internal_generate_body,
    parse_internal_generate_response,
    sanitize_internal_generate_answer,
)
from app.llm.protocol import LLMMessage


@pytest.mark.parametrize(
    ("base", "endpoint", "expected"),
    [
        (
            "http://106.245.249.226:7888",
            "/api/v1/generate",
            "http://106.245.249.226:7888/api/v1/generate",
        ),
        ("http://host:7888/", "/api/v1/generate", "http://host:7888/api/v1/generate"),
        ("http://host:7888", "api/v1/generate", "http://host:7888/api/v1/generate"),
    ],
)
def test_build_internal_generate_url(base: str, endpoint: str, expected: str) -> None:
    assert build_internal_generate_url(base, endpoint) == expected


def test_messages_to_internal_generate_body_nas_rag_shape() -> None:
    rid = str(uuid.uuid4())
    msgs = [
        LLMMessage(role="system", content="SYS"),
        LLMMessage(role="user", content="USER\nblock"),
    ]
    body = messages_to_internal_generate_body(
        request_id=rid,
        messages=msgs,
        model="gpt-oss-20b",
        max_tokens=1000,
        temperature=0.2,
    )
    assert body["request_id"] == rid
    assert body["model"] == "gpt-oss-20b"
    assert body["system_prompt"] == "SYS"
    assert body["user_prompt"] == "USER\nblock"
    assert body["max_tokens"] == 1000
    assert body["temperature"] == pytest.approx(0.2)


def test_messages_to_internal_generate_body_joins_multiple_system() -> None:
    rid = "00000000-0000-4000-8000-000000000001"
    msgs = [
        LLMMessage(role="system", content="A"),
        LLMMessage(role="system", content="B"),
        LLMMessage(role="user", content="Q"),
    ]
    body = messages_to_internal_generate_body(
        request_id=rid,
        messages=msgs,
        model="m",
        max_tokens=10,
        temperature=0.0,
    )
    assert body["system_prompt"] == "A\n\nB"
    assert body["user_prompt"] == "Q"


def test_parse_internal_generate_response_uses_answer_and_model() -> None:
    out = parse_internal_generate_response(
        {"answer": "  hi  ", "model": "gpt-oss-20b", "latency_ms": 99},
        fallback_model="fallback",
    )
    assert out.text == "hi"
    assert out.model == "gpt-oss-20b"


def test_sanitize_assistantfinal_and_analysis() -> None:
    raw = "analysis추론내용assistantfinal최종답변"
    assert sanitize_internal_generate_answer(raw) == "최종답변"


def test_sanitize_strips_think_tags() -> None:
    raw = "assistantfinal\u003cthink\u003ex\u003c/think\u003e최종"
    assert sanitize_internal_generate_answer(raw) == "최종"


def test_sanitize_drops_leading_analysis_lines() -> None:
    raw = "analysis: step1\nanalysis step2\nassistantfinal본문"
    assert sanitize_internal_generate_answer(raw) == "본문"


def test_sanitize_analysis_only_without_assistantfinal() -> None:
    assert sanitize_internal_generate_answer("analysis 요약\n실제답") == "실제답"


def test_parse_internal_generate_response_fallback_model() -> None:
    out = parse_internal_generate_response({"answer": "x"}, fallback_model="fb")
    assert out.model == "fb"


def test_parse_internal_generate_response_raises_without_answer() -> None:
    with pytest.raises(ValueError, match="answer"):
        parse_internal_generate_response({}, fallback_model="m")


def test_internal_generate_complete_posts_expected_url_and_json() -> None:
    captured: dict[str, str] = {}

    def _fake_urlopen(req, timeout=None):
        _ = timeout
        assert req.full_url == "http://example.com:7888/api/v1/generate"
        captured["data"] = req.data.decode("utf-8")
        return BytesIO(
            json.dumps({"answer": "done", "model": "gpt-oss-20b", "latency_ms": 1}).encode("utf-8")
        )

    client = InternalGenerateLLMClient(
        base_url="http://example.com:7888",
        endpoint="/api/v1/generate",
        timeout_s=30.0,
    )
    with patch("app.llm.internal_generate.urllib.request.urlopen", side_effect=_fake_urlopen):
        out = client.complete(
            messages=[
                LLMMessage(role="system", content="s"),
                LLMMessage(role="user", content="u"),
            ],
            model="gpt-oss-20b",
            max_tokens=1000,
            temperature=0.2,
        )
    assert out.text == "done"
    assert out.model == "gpt-oss-20b"
    payload = json.loads(captured["data"])
    assert payload["model"] == "gpt-oss-20b"
    assert payload["system_prompt"] == "s"
    assert payload["user_prompt"] == "u"
    uuid.UUID(payload["request_id"])  # valid uuid string


def test_get_llm_client_instantiates_internal_generate() -> None:
    with patch.object(llm_backend, "InternalGenerateLLMClient") as ctor:
        ctor.return_value = MagicMock()
        settings = Settings(
            llm_mock_mode=False,
            llm_backend="internal_generate",
            internal_generate_base_url="http://106.245.249.226:7888",
            internal_generate_endpoint="/api/v1/generate",
            internal_generate_timeout_seconds=55.0,
            internal_generate_api_key=None,
        )
        llm_backend.get_llm_client(settings)
        ctor.assert_called_once_with(
            base_url="http://106.245.249.226:7888",
            endpoint="/api/v1/generate",
            timeout_s=55.0,
            api_key=None,
        )
