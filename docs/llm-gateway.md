# LLM Gateway

## 문서 목적

`LLMClient`가 왜 필요하고, 어떤 구조를 갖추어야 하며,
MVP에서 어디까지 구현해야 하는지를 정의한다.

`SearchClient`가 검색 엔진 구현체를 추상화한 것과 동일한 철학을 적용한다.

---

## 왜 LLM Gateway 레이어를 분리해야 하는가

### 이유 1: LLM 구현체를 교체할 수 있어야 한다

운영 환경에서 LLM은 바뀔 수 있다.

| 상황 | LLM 교체 |
|------|----------|
| 초기 PoC | OpenAI API 또는 사내 임시 API |
| 운영 전환 | 사내 vLLM 클러스터 |
| 성능 비교 | vLLM (A) vs vLLM (B) 모델 A/B 테스트 |
| 비용 최적화 | 작은 질문은 경량 모델, 복잡한 질문은 대형 모델 |

`Usecase`가 LLM API를 직접 호출하면, 교체할 때 모든 Usecase를 수정해야 한다.
`LLMClient` 인터페이스 뒤에 구현체를 숨기면, `LLMClient` 구현체만 교체하면 된다.

### 이유 2: OpenAI-compatible 구조를 표준 인터페이스로 활용한다

vLLM, LM Studio, Ollama, LocalAI, Azure OpenAI는
모두 OpenAI Chat Completions API와 호환되는 엔드포인트를 제공한다.

```
POST /v1/chat/completions
{
  "model": "...",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user",   "content": "..."}
  ]
}
```

이 형태를 `LLMClient`의 내부 구현으로 쓰면,
**엔드포인트 URL과 모델명만 바꿔서 다른 백엔드로 전환**할 수 있다.

Usecase는 이 사실을 알 필요가 없다.

### 이유 3: 공통 관심사를 한 곳에서 처리한다

LLM 호출에 공통적으로 필요한 것들을 Gateway에서 처리한다.

| 관심사 | Gateway에서 처리 |
|--------|-----------------|
| 재시도 (retry) | 네트워크 오류 시 최대 N회 재시도 |
| 타임아웃 | 응답 없음 시 N초 후 오류 반환 |
| 지연 시간 측정 | `latency_ms` 로그 (내용 없이) |
| 오류 분류 | 네트워크 오류 vs 모델 오류 vs 컨텐츠 거부 |
| `trace_id` 헤더 전달 | LLM 서비스 내부 추적 연동 |
| **운영 로그** | 토큰·속도·오류만. prompt/응답 원문 절대 제외 |

이것들을 각 Usecase에서 개별 구현하면 중복과 불일치가 발생한다.

### 이유 4: 미래의 멀티에이전트에서 비용·사용량 추적이 가능해야 한다

에이전트가 여러 개가 되면 "어떤 에이전트가 얼마나 토큰을 썼는가"를 추적해야 한다.
이 집계 지점은 `LLMClient` 구현체 안이 유일하게 적합하다.
`agent_name`을 `generate()` 호출 시 전달하면, Gateway 로그에서 에이전트별 집계가 가능하다.

---

## LLMClient 인터페이스

`SearchClient`와 동일한 방식으로 정의한다.

```python
# app/adapters/llm_protocol.py

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str     # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str | None = None       # None이면 Gateway 기본값 사용
    max_tokens: int = 2048
    temperature: float = 0.1       # RAG 응답은 낮은 temperature 권장


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None       # 사용 토큰 수 (모델이 제공하면)
    output_tokens: int | None
    latency_ms: int


class LLMClient(ABC):

    @abstractmethod
    async def generate(
        self,
        request: LLMRequest,
        trace_id: str,
    ) -> LLMResponse:
        ...
```

**인터페이스 설계 원칙:**
- `messages` 리스트를 받는다. 단일 문자열 프롬프트가 아니다.
  이유: system prompt 분리가 LLM 품질에 중요하다. 단일 문자열은 이 분리를 강제하지 못한다.
- `trace_id`는 항상 전달한다. Gateway 내부에서 로그와 LLM 서비스 헤더로 사용한다.
- `LLMResponse.text`만 Usecase가 사용한다. 토큰 수·모델명은 Gateway가 로그한다.

---

## 구현체

### OpenAICompatibleLLMClient (기본 구현)

OpenAI API 형식을 사용하는 모든 백엔드(OpenAI, vLLM, Ollama 등)에 공통으로 사용.

```python
# app/adapters/llm_openai_compat.py

import httpx
from .llm_protocol import LLMClient, LLMRequest, LLMResponse


class OpenAICompatibleLLMClient(LLMClient):

    def __init__(self, base_url: str, api_key: str, default_model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model

    async def generate(self, request: LLMRequest, trace_id: str) -> LLMResponse:
        model = request.model or self._default_model
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Trace-Id": trace_id,          # LLM 서비스 내부 추적용
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        latency_ms = int((time.monotonic() - start) * 1000)
        data = resp.json()
        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        # 운영 로그: 메트릭만 기록. prompt/응답 원문은 절대 포함하지 않는다.
        logger.info(
            "llm.generate.done",
            trace_id=trace_id,
            service_name="contexthub",
            agent_name=request.agent_name,   # Usecase가 주입, 에이전트별 집계용
            model=model,
            endpoint="/v1/chat/completions",
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            input_token_count=usage.get("prompt_tokens"),
            output_token_count=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            status="success",
            status_code=200,
            error_code=None,
            is_timeout=False,
            retry_count=0,
        )

        return LLMResponse(
            text=choice,
            model=model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
        )
```

### StubLLMClient (테스트·로컬 개발용)

실제 LLM 없이 파이프라인 전체를 실행할 수 있어야 한다.
`SearchClient`의 `DbChunkSearchClient`와 동일한 역할.

```python
# app/adapters/llm_stub.py

class StubLLMClient(LLMClient):
    async def generate(self, request: LLMRequest, trace_id: str) -> LLMResponse:
        logger.info("llm.stub.generate", trace_id=trace_id, message_count=len(request.messages))
        return LLMResponse(
            text="[STUB] LLM 응답입니다. 실제 LLM 연결 후 교체됩니다.",
            model="stub",
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
        )
```

### 구현체 선택

`SearchClient`의 `search_backend` 설정과 동일한 방식으로 구현체를 선택한다.

```python
# app/config/settings.py

class Settings:
    llm_backend: str = "stub"       # "stub" | "openai_compat"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_default_model: str = ""
```

```python
# app/adapters/llm_backend.py

def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_backend == "openai_compat":
        return OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            default_model=settings.llm_default_model,
        )
    return StubLLMClient()
```

---

## vLLM/OpenAI-compatible 구조를 Gateway 뒤에 숨겨야 하는 이유

vLLM은 OpenAI API와 호환되지만, 모든 구현이 동일하지 않다.

| 항목 | OpenAI | vLLM | Ollama |
|------|--------|------|--------|
| 스트리밍 | SSE | SSE | SSE |
| `usage` 필드 | 항상 있음 | 버전에 따라 없음 | 없을 수 있음 |
| 커스텀 파라미터 | 없음 | `repetition_penalty` 등 | `num_ctx` 등 |
| 인증 | API Key | API Key 또는 없음 | 없음 |
| 오류 코드 | 표준 | 다를 수 있음 | 다를 수 있음 |

이 차이를 `OpenAICompatibleLLMClient` 내부에서 흡수한다.
Usecase가 이 차이를 알면 안 된다.

**sLLM 교체 시나리오:**

```
개발 환경: StubLLMClient (HTTP 없음)
로컬 테스트: Ollama + OpenAICompatibleLLMClient (llm_base_url=localhost:11434)
스테이징: vLLM 내부 서버 + OpenAICompatibleLLMClient
운영: 사내 vLLM 클러스터 + OpenAICompatibleLLMClient
```

**Usecase 코드 변경: 없음. `.env` 또는 설정값만 변경.**

---

## 재시도 및 오류 처리 정책

```python
# Gateway 내부 재시도 정책 (MVP)

MAX_RETRY = 2
RETRY_WAIT_SEC = [1, 3]   # 1초, 3초
TIMEOUT_SEC = 60

재시도 대상:
  - httpx.TimeoutException
  - httpx.ConnectError
  - HTTP 502, 503

재시도 안 하는 것:
  - HTTP 400 (잘못된 요청, 재시도해도 동일)
  - HTTP 401 (인증 실패)
  - HTTP 429 (Rate Limit, 별도 처리 필요)
  - HTTP 500 (모델 오류)
```

---

## LLM Gateway 운영 로그 정책

> 전체 로그 설계는 [logging-audit.md](logging-audit.md) 참조.
> 이 섹션은 Gateway 구현체가 지켜야 하는 규칙을 정리한다.

### 남길 수 있는 필드

```
trace_id, service_name, agent_name, event,
model, endpoint, temperature, max_tokens,
input_token_count, output_token_count, latency_ms,
status, status_code, error_code, is_timeout, retry_count
```

### 절대 남기지 않는 필드

```
messages[*].content   → system prompt + 사내 문서 내용
request.messages      → 위와 동일
response_text         → LLM 생성 응답 원문
prompt (전문)         → 시스템 프롬프트 구조 + 문서 내용
user_question         → 사용자 민감 질문 원문
chunk_text            → 사내 기밀 문서 내용
```

**원칙**: 로그는 "무슨 일이 있었는가"를 설명하는 메타정보만 담는다.
"무슨 내용이었는가"는 DB에서 chunk_id로 조회한다.

### 오류 시 추가 로그

```python
logger.error(
    "llm.generate.failed",
    trace_id=trace_id,
    service_name="contexthub",
    agent_name=request.agent_name,
    model=model,
    endpoint="/v1/chat/completions",
    latency_ms=latency_ms,
    status="timeout",          # "timeout" | "http_error" | "connection_error"
    status_code=None,          # HTTP 응답이 없었으면 None
    error_code="LLM_TIMEOUT",  # 내부 오류 코드
    is_timeout=True,
    retry_count=2,             # 재시도 후 최종 실패
)
```

---

## 절대 하지 않는 것

| 항목 | 이유 |
|------|------|
| Gateway에서 프롬프트를 수정하거나 조립 | 프롬프트 책임은 PromptBuilder |
| Gateway에서 검색 결과를 처리 | 검색 책임은 SearchClient |
| `request.messages`의 `content`를 로그에 기록 | 사내 문서 내용이 로그에 영구 기록됨 |
| LLM 응답 `text`를 로그에 기록 | 문서 내용 재생산 유출 |
| Usecase에서 httpx / openai SDK 직접 import | LLMClient 추상화 파괴 |
| 하나의 LLMClient에 여러 LLM 라우팅 로직 | AgentRouter 역할 침범 |
| 토큰 수 없을 때 로그 자체를 생략 | 모델이 usage를 안 줘도 다른 필드는 기록해야 함 |

---

## 모듈 위치

```
app/
└─ adapters/
    ├─ llm_protocol.py         # LLMClient ABC, LLMRequest, LLMResponse
    ├─ llm_openai_compat.py    # OpenAI-compatible 구현체
    ├─ llm_stub.py             # 테스트용 스텁
    └─ llm_backend.py          # 설정 기반 구현체 선택
```

---

## MVP 구현 체크리스트

| 항목 | 상태 |
|------|------|
| `LLMClient` ABC 정의 | ✅ |
| `LLMRequest` / `LLMResponse` 데이터클래스 | ✅ |
| `StubLLMClient` 구현 | ✅ |
| `OpenAICompatibleLLMClient` 구현 | ✅ |
| `llm_backend` 설정 기반 선택 | ✅ |
| `trace_id` 헤더 전달 | ✅ |
| 운영 로그 (메타정보만, 원문 제외) | ✅ |
| 재시도 (최대 2회, 오류 로그 포함) | ✅ |
| `agent_name` 로그 필드 (에이전트별 집계 기반) | ✅ |
| 스트리밍(Streaming) 응답 | ❌ Phase 2 |
| Rate Limit 처리 | ❌ Phase 2 |
| 멀티 모델 라우팅 | ❌ Phase 3 |
| 토큰 사용량 집계 DB 저장 | ❌ Phase 3 |
| 로그 수집 시스템 연동 (ELK, Loki) | ❌ Phase 2 |

> 로그 필드 전체 정의 및 감사 로그 설계: [logging-audit.md](logging-audit.md)
