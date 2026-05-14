# Backend 구현 상태 (스냅샷)

설계 문서(`docs/architecture.md`, `docs/llm-gateway.md`, `docs/logging-audit.md` 등)와의 **대응 관계**를 기준으로, 현재 저장소의 **실제 코드** 상태를 요약한다.

---

## 1. Chat API

| 엔드포인트 | 역할 | 구현 위치 |
|-------------|------|-----------|
| `POST /api/v1/chat/query` | **Retrieval 전용** 검증: 권한 필터 검색 + 스텁 형태의 `answer` (LLM 미호출) | `app/chat/router.py`, `app/chat/service.py` |
| `POST /api/v1/chat/discover` | **문서 탐색 MVP**: 동일 `SearchClient.search`로 chunk 검색 후 `raw_document_id` 단위로 묶어 반환 (LLM 미호출, `chunk_text` 미포함) | `app/chat/router.py`, `app/chat/discovery_service.py` |
| `POST /api/v1/chat/generate` | **RAG generation MVP**: 동일 검색 계약으로 히트 조회 후 LLM 호출(또는 mock) | `app/chat/router.py`, `app/agents/nas_rag.py` |
| `GET /api/v1/chat/history/{session_id}` | 미구현 (501) | `app/chat/router.py` |

### `/query`와 `/generate`를 분리한 이유

두 엔드포인트는 **서로 다른 단계의 검증**을 담당한다.

| | `/query` | `/generate` |
|-|----------|-------------|
| 목적 | retrieval 계약·권한 필터 단독 검증 | 검색 + LLM 응답 end-to-end |
| LLM 호출 | 없음 | 있음 (`LLM_MOCK_MODE=false` 시) |
| 스텁 답변 | 고정 문자열 반환 | 실제 LLM 또는 mock 응답 |
| 사용 시점 | retrieval 품질 확인, DB/OpenSearch 연결 검증 | 실제 RAG 결과 확인 |

이 분리 덕분에 **LLM이 없어도 검색 파이프라인을 독립적으로 검증**할 수 있다.
`/query`가 올바른 청크를 반환하는지 확인한 후, `/generate`로 LLM 품질을 분리하여 측정한다.
`/discover`는 chunk 후보를 **문서 단위 후보 목록**으로만 돌려주며, 이 단계에서는 답변 생성·문서 선택 후 `/generate` 연동은 구현하지 않는다.

### 검색 계약 불변 원칙

`SearchClient`, `SearchHit`, `PermissionPrincipal` 인터페이스는 변경하지 않는다.
`/generate`는 `search.search(...)` 결과만 소비하고, 검색 엔진이 OpenSearch든 DB든 알지 못한다.

### retrieval_query / original_query 분리

요청 스키마(`app/chat/schemas.py`의 `ChatQueryRequest`)에서 받은 `question`은 두 용도로 분기한다.

```
question (원본, 사용자 입력)
  │
  ├─→ retrieval_query  ← normalize_retrieval_query() 적용
  │    └─ SearchClient.search(query=retrieval_query, ...)
  │
  └─→ original_query   ← 그대로 유지
       └─ LLM user 메시지에 포함 (프롬프트 조립)
```

**정규화를 검색에만 적용하고 LLM 프롬프트에는 원문을 넣는 이유:**
- 정규화된 검색어(`"방화벽 포트 오픈"`)를 LLM에게 넘기면 사용자 의도가 잘린다
- LLM은 `"방화벽 포트 오픈 설명해줘"`라는 자연어 질문 전체를 컨텍스트로 써야 더 나은 답변을 생성한다

### Retrieval Debug / Observability

**목적:** 운영·개발자가 “왜 이 문서/chunk가 검색되었는지”를 설명·재현할 수 있게 한다.

**구조화 로그 (항상):** `POST /api/v1/chat/query` 및 `POST /api/v1/chat/generate`의 검색 직후, `contexthub.chat.service` / `contexthub.agents.nas_rag` 로거로 한 줄 `retrieval_debug {…}` JSON이 출력된다. 필드에는 `original_query`, `retrieval_query`, `normalization_applied`, `retrieval_backend`, `retrieval_count`, `top_k`, `retrieved_chunk_ids`, `retrieved_document_ids`, `retrieval_scores`, `retrieval_filenames`, `retrieval_latency_ms`가 포함된다. **`chunk_text` 원문은 로그에 넣지 않는다** (메타만).

`POST /api/v1/chat/discover`는 검색 직후 `contexthub.chat.discovery` 로거로 `chat_discover {…}` 한 줄을 남긴다. 필드: `original_query`, `retrieval_query`, `normalization_applied`, `document_count`, `retrieved_document_ids`, `top_scores`, `retrieval_backend`, `retrieval_latency_ms`. 역시 **chunk 본문 로그 없음**.

**응답 `debug` (선택):** `ENABLE_RETRIEVAL_DEBUG=true`(기본 `false`)일 때만 응답 JSON에 `debug` 객체를 붙인다(`RetrievalDebugInfo`: 동일 메타 + `chunks` 배열; 역시 본문 없음). 운영에서는 끄고, 로컬·스테이징에서 Swagger로 원인 분석할 때 켠다.

**활용 예:** retrieval 품질·정규화 효과 분석, vector/hybrid 전환 전 BM25 기준선 검증, 운영 장애(0건·권한) 분석, hallucination과의 대조를 위한 **source 추적**, 감사 대응 시 “어떤 질의로 어떤 chunk_id가 매칭됐는지” 입증.

구현: `app/chat/retrieval_debug.py`, `Settings.enable_retrieval_debug`, `app/chat/schemas.py`의 `RetrievalDebugInfo`.

---

## 2. `app/llm` — LLM 게이트웨이 (MVP)

| 파일 | 설명 |
|------|------|
| `protocol.py` | `LLMMessage`, `LLMCompletionResult`, `LLMClient` Protocol (`complete` 동기 단일 진입점) |
| `mock.py` | `MockLLMClient` — 기본 개발용; 외부 HTTP 없음 |
| `openai_compat.py` | `OpenAICompatLLMClient` — `urllib`로 `{base}/chat/completions` POST. `normalize_openai_compat_base_url()`로 base URL 정규화 |
| `internal_chat.py` | `InternalChatLLMClient` — 사내 `POST {INTERNAL_CHAT_BASE_URL}{INTERNAL_CHAT_ENDPOINT}` (기본 `/chat`) |
| `internal_generate.py` | `InternalGenerateLLMClient` — 사내 `POST {INTERNAL_GENERATE_BASE_URL}{INTERNAL_GENERATE_ENDPOINT}` (기본 `/api/v1/generate`). `system_prompt` / `user_prompt` JSON |
| `backend.py` | `get_llm_client(settings)` — `LLM_MOCK_MODE` / `LLM_BACKEND`에 따라 클라이언트 선택 |

### ContextHub ↔ GPT generation API 구조

`internal_generate` 백엔드는 OpenAI-compatible API가 아닌 **사내 generation 전용 API**다.

```
ContextHub /generate
  │
  │ 1. SearchClient.search() → hits
  │ 2. PromptBuilder → system_prompt + user_prompt 문자열 조립
  │
  └─→ InternalGenerateLLMClient.complete()
        POST /api/v1/generate
        {
          "request_id":    "<uuid>",
          "model":         "gpt-oss-20b",
          "system_prompt": "...",    ← LLMMessage[role=system] 들을 빈 줄로 연결
          "user_prompt":   "...",    ← LLMMessage[role=user/assistant] 순서 유지
          "temperature":   0.1,
          "max_tokens":    2048
        }
        ↓
        { "answer": "...", "model": "...", "latency_ms": ... }
```

**generation 전용 API를 따로 둔 이유:**
- 사내 LLM 서비스는 OpenAI `/v1/chat/completions` 스펙 대신 단순화된 `system_prompt`/`user_prompt` JSON을 사용한다
- `messages[]` 배열 대신 두 개의 문자열 필드를 받으므로 별도 클라이언트가 필요하다
- `InternalGenerateLLMClient`가 `LLMMessage[]` → `system_prompt`/`user_prompt` 변환을 담당하여, `NasRagUsecase`는 메시지 포맷이 무엇인지 알 필요가 없다

### answer sanitizing 이유

`internal_generate` API 응답의 `answer` 필드에는 모델 내부 처리 흔적이 포함될 수 있다.

```python
# app/llm/internal_generate.py
sanitize_internal_generate_answer(raw_answer)
```

제거 대상:
- `assistantfinal` 이전 본문 (모델이 thinking 단계 출력을 포함하는 경우)
- `<analysis>...</analysis>` 등 인라인 XML 블록
- `<|...|>` 형태의 특수 토큰
- 헤더 줄 (`analysis:`, `reasoning:` 등)

**이 처리가 필요한 이유:**
- 사내 모델이 chain-of-thought 방식으로 동작하면 최종 답변 앞에 추론 과정이 섞여 나온다
- 사용자에게 추론 과정 원문을 그대로 보여주면 혼란이 발생한다
- `sanitize_internal_generate_answer`는 방어적으로 동작한다: 패턴이 없으면 원문 그대로 반환한다

---

## 3. `app/agents` — NAS RAG (MVP)

| 파일 | 설명 |
|------|------|
| `nas_rag.py` | `NAS_RAG_SYSTEM_PROMPT`, `build_nas_rag_user_prompt`, `_retrieve_hits_for_nas_rag`, `_sources_from_hits`, `run_nas_rag_generate`. 검색(권한 반영된 hits) → 프롬프트 조립 → LLM → **출처는 hits에서만 구성** (모델 출력 파싱 없음) |

**출처를 LLM 출력에서 파싱하지 않는 이유:**
- LLM이 출처 형식을 정확히 재현한다는 보장이 없다
- `hits` 객체에 이미 `raw_document_id`, `chunk_id`, `original_filename`, `section_title`, `page_no`가 있다
- 검색에 포함된 청크만 출처가 될 수 있으므로, hits 목록이 곧 정확한 출처 목록이다

**로깅 (운영 기준):**

| 로그 필드 | 기록 여부 |
|----------|----------|
| `original_query` (스니펫, 앞 80자) | ✅ |
| `retrieval_query` (스니펫) | ✅ |
| `normalization_applied` | ✅ |
| `retrieval_count` | ✅ |
| `retrieval_ms` | ✅ |
| `used_chunk_ids` | ✅ |
| `llm_model`, `llm_mock` | ✅ |
| `latency_ms` (총) | ✅ |
| `error_type`, `error_message` | ✅ (실패 시) |
| `chunk_text` 원문 | ❌ 절대 금지 |
| `question` 원문 전체 | ❌ 스니펫만 |
| `answer` 원문 | ❌ 절대 금지 |

`chunk_text`·`answer` 원문을 로그에 넣지 않는 이유는 `docs/logging-audit.md` 참조.
장애 분석 시 `used_chunk_ids`로 DB에서 직접 내용을 조회한다.

---

## 4. Query Normalization — 현재 상태와 한계

### 현재 구현 (`app/chat/retrieval_query.py`)

```python
normalize_retrieval_query(question: str) -> str
normalize_retrieval_query_pair(question: str) -> tuple[str, str]
#   returns (retrieval_query, original_query)
```

**현재 적용 규칙:**
- 접미 불용어 제거: `설명`, `알려줘`, `해줘`, `말해줘` 등
- `에 대해` / `에 대해서` 구문 제거
- 예: `"쿠베플로우에 대해 설명해줘"` → `"쿠베플로우"`
- 예: `"방화벽 포트 오픈 설명"` → `"방화벽 포트 오픈"`

### 현재 한계

**DB 검색 경로 (PostgreSQL `ILIKE`):**
- 공백 기준 AND 매칭이라 한글 조사 처리가 없다
- `"방화벽 포트 오픈 설명"`이 그대로 넘어가면 4토큰 AND 조건이 된다
- 본문에 `"방화벽 포트 오픈"`이 있어도 `"설명"` 매칭 실패 시 검색 누락

**OpenSearch 경로 (nori 분석기):**
- nori가 형태소 분석을 하므로 DB보다 훨씬 나으나, 불용어 처리 튜닝은 별도
- 현재 정규화는 OpenSearch보다 DB 경로의 한계를 보완하는 것이 주목적

**현재 정규화 방식의 근본 한계:**
- 규칙 기반이라 사전에 없는 표현은 처리 못 함
- 형태소 분석(KoNLPy, kss 등) 없음
- 동의어 확장 없음 (`K8s` ↔ `쿠버네티스`)
- 복합어 처리 없음 (`컨테이너오케스트레이션` → `컨테이너 오케스트레이션`)

### 보완 방향 (Phase 2)

| 항목 | 방향 |
|------|------|
| 형태소 분석 | KoNLPy 또는 kss 기반 토크나이저 도입 |
| 동의어 사전 | OpenSearch synonym filter + 사내 용어집 |
| 복합어 분리 | nori `decompound_mode: mixed` 튜닝 |
| 쿼리 확장 | LLM 기반 HyDE (가설 문서 생성 후 임베딩 검색) |

---

## 5. Retrieval 품질 — 현재 상태

### End-to-End 테스트 결과 (MVP 기준)

| 질의 유형 | 검색 결과 | 비고 |
|----------|----------|------|
| 단어 단독 (`"Kubeflow"`) | 정상 | 영문 단어는 정확 일치 |
| 단어 + 불용어 (`"Kubeflow 설명"`) | 정상 | 정규화 후 `"Kubeflow"` |
| 한글 복합어 (`"방화벽포트오픈"`) | 부분 실패 | DB 경로에서 단어 경계 문제 |
| 조사 포함 (`"쿠베플로우에 대해"`) | 정상 | `"에 대해"` 제거 처리됨 |
| 권한 필터 (PUBLIC) | 정상 | 권한 외 청크 미포함 확인 |
| 권한 필터 (DEPT) | 정상 (`test_department_codes` 기준) | 실 AD 연동 전 스텁 |
| 검색 결과 0건 | LLM 미호출, 안전 메시지 반환 | 정상 |

**현재 retrieval 품질 평가:**
- 영문 기술 용어 중심 질의: 양호
- 한글 자연어 질의: 규칙 기반 정규화 범위 내에서만 안정적
- 한글 복합어·조사 변형: OpenSearch 경로(nori)에서는 낫고, DB 경로에서는 취약

### scanner / parser / indexer 불변 원칙

retrieval 품질 개선을 위해 **scanner, parser, chunker, indexer를 수정하지 않는다.**

```
이미 완료된 파이프라인:
  scanner → parser → chunker → indexer → OpenSearch

개선 대상:
  retrieval_query.py (검색 전 쿼리 처리)
  search_client (검색 방식)
  agents/nas_rag.py (프롬프트 조립)
```

이 원칙의 이유:
- scanner/parser/indexer를 건드리면 기존 색인된 데이터 전체를 재처리해야 할 수 있다
- retrieval과 generation은 인덱스 데이터에 독립적으로 개선 가능하다
- 역할 분리 원칙: 색인 파이프라인이 안정화된 이후 retrieval 전략을 별도로 실험한다

---

## 6. `/api/v1/chat/generate` 사용법 (Swagger)

1. API 기동: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
2. `http://127.0.0.1:8000/docs` → **chat** → `POST /api/v1/chat/generate`
3. Request body는 **`POST /api/v1/chat/query`와 동일**하며, 스키마는 `app/chat/schemas.py`의 **`ChatQueryRequest`**. **필수 필드는 `question`** (문자열). 선택: `top_k`, `session_id`, `test_department_codes`.

```json
{
  "question": "Kubeflow 워크플로우",
  "top_k": 5,
  "session_id": null,
  "test_department_codes": null
}
```

`test_department_codes`는 생략하거나 DEPT 스텁 검증 시 `["infra"]`처럼 배열을 넣을 수 있다.

응답(`ChatGenerateResponse`): `answer`, `sources`, `search_backend`, `llm_model`, `llm_mock`, `retrieval_latency_ms`, `llm_latency_ms`, `total_latency_ms`.

---

## 7. Mock 모드 (기본)

| 환경 변수 | 기본 | 의미 |
|-----------|------|------|
| `LLM_MOCK_MODE` | `true` | `true`이면 항상 `MockLLMClient` (HTTP 미사용) |
| `LLM_BACKEND` | `mock` | `LLM_MOCK_MODE=false`일 때만 의미 |
| `LLM_MODEL` | `gpt-4o-mini` | mock이 아닌 경로에서 `complete(..., model=...)`에 전달 |

검색 결과 **0건**이면 LLM을 호출하지 않고 고정 안전 메시지를 반환한다.

---

## 8. LLM 백엔드 설정

### OpenAI-compatible

```env
LLM_MOCK_MODE=false
LLM_BACKEND=openai_compat
OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
OPENAI_COMPAT_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
OPENAI_COMPAT_TIMEOUT_SECONDS=120
```

`OPENAI_COMPAT_BASE_URL`: 스킴 + 호스트 + `/v1`까지. `/chat/completions`는 클라이언트가 붙인다.
`…/v1/chat/completions`까지 붙여 넣어도 `normalize_openai_compat_base_url()`이 정규화한다.

설정 누락 시 `get_llm_client`가 `RuntimeError`, 라우터가 **503**으로 매핑한다. LLM 호출 실패는 **502** (`NasRagLLMError`).

### 사내 `internal_chat` 백엔드

OpenAI-compatible `messages[]` 배열을 받는 사내 게이트웨이용.

```env
LLM_MOCK_MODE=false
LLM_BACKEND=internal_chat
INTERNAL_CHAT_BASE_URL=http://host:port
INTERNAL_CHAT_ENDPOINT=/chat
INTERNAL_CHAT_TIMEOUT_SECONDS=120
LLM_MODEL=gpt-4o-mini
# INTERNAL_CHAT_API_KEY=...
```

응답 파싱: `choices[0].message.content` 또는 최상위 `answer`/`message`/`content`/`text` 순서로 추출.

### 사내 `internal_generate` 백엔드

`system_prompt`/`user_prompt` 필드를 사용하는 generation 전용 API.

```env
LLM_MOCK_MODE=false
LLM_BACKEND=internal_generate
INTERNAL_GENERATE_BASE_URL=http://host:port
INTERNAL_GENERATE_ENDPOINT=/api/v1/generate
INTERNAL_GENERATE_TIMEOUT_SECONDS=120
LLM_MODEL=gpt-oss-20b
# INTERNAL_GENERATE_API_KEY=...
```

- **프롬프트 매핑**: `LLMMessage[role=system]` → `system_prompt` (복수면 빈 줄로 연결). `user`/`assistant` → `user_prompt` (assistant는 `[assistant]` 접두 블록).
- **응답**: `answer` 문자열만 `LLMCompletionResult.text`로 사용. `sanitize_internal_generate_answer`로 모델 내부 흔적 제거.

---

## 9. 현재 남은 과제

### 단기 (Phase 2)

| 과제 | 현황 | 방향 |
|------|------|------|
| Retrieval 정규화 고도화 | 규칙 기반, 한계 존재 | KoNLPy / nori 동의어 |
| Hybrid retrieval | 미구현 | BM25 + dense vector |
| Embedding 도입 | 미구현 | 임베딩 모델 + vector field |
| Reranking | 미구현 | cross-encoder 또는 LLM-as-judge |
| `trace_id` 상관관계 | 로그에 있으나 수집 미연동 | Loki / ELK 수집 |
| 감사 로그 저장소 분리 | stdout 출력 중 | 별도 감사 DB 또는 스토어 |

### 중기 (Phase 3)

| 과제 | 방향 |
|------|------|
| Streaming 응답 | LLMClient Protocol 확장 + SSE |
| 대화 이력 (`/history`) | 세션 저장소 설계 |
| AgentRouter | 에이전트 추가 시 라우팅 레이어 |
| AD/LDAP 권한 연동 | `PermissionPrincipal` 구성 시 디렉터리 조회 |
| Multi-agent | `AgentContext` 도입, 에이전트별 권한 위임 |

---

## 10. 운영·보안 로그 원칙 (현재 적용 기준)

현재 코드에서 지키는 원칙 (전체 설계는 `docs/logging-audit.md` 참조):

| 원칙 | 적용 현황 |
|------|----------|
| `chunk_text` 원문 로그 금지 | ✅ `nas_rag.py` 로그에 미포함 |
| `answer` 원문 로그 금지 | ✅ 미포함 |
| `question` 스니펫만 (앞 80자) | ✅ `original_query` 스니펫 |
| `retrieval_query` 기록 | ✅ 정규화 적용 여부 추적용 |
| `used_chunk_ids` 기록 | ✅ 장애 추적 기반 |
| `trace_id` 전파 | 부분 — 생성은 하나 전 계층 연결 미완성 |
| `anonymized_user_key` | 미적용 — `test_department_codes` 스텁 단계 |

장애 발생 시: `used_chunk_ids`로 DB에서 `document_chunk.chunk_text`를 직접 조회하여 내용 확인.

---

## 11. 관련 문서

- `docs/llm-gateway.md` — LLMClient 교체 전략, 운영 로그 필드 정의
- `docs/agent-architecture.md` — 장기 Agent 레이어 (현재는 단일 `nas_rag` 오케스트레이션)
- `docs/logging-audit.md` — Gateway 운영 로그 vs Agent 감사 로그 분리 설계
- `docs/retrieval-roadmap.md` — keyword → hybrid → vector retrieval 확장 방향
- `docs/prompt-strategy.md` — PromptBuilder 설계 및 금지 패턴

---

## 12. 자동 검증 (pytest)

```bash
pip install -e ".[dev]"
pytest -q
```

| 테스트 파일 | 검증 내용 |
|------------|----------|
| `tests/test_nas_rag_generation.py` | OpenAI base URL 정규화, 질의 로그 스니펫 길이, `get_llm_client` 타임아웃 주입, 검색 0건 시 LLM 미호출, 히트 시 소스 미러링·로그에 `chunk_text` 미포함, LLM 실패 시 `error_type`/`error_message` 로그 |
| `tests/test_retrieval_query_normalize.py` | `normalize_retrieval_query`/`normalize_retrieval_query_pair` 동작 검증, LLM 프롬프트에 원문 `question` 유지, `SearchClient.search`에 정규화 문자열 전달 확인 |
| `tests/test_swagger_equivalent_retrieval.py` | `httpx` 기반 `TestClient`로 `/chat/query`·`/chat/generate` 동일 JSON 호출; 질의 변형 4종이 동일 `search(query=…)`·동일 소스를 내는지, 로그 필드·LLM user 블록의 원문 `question` 유지 검증 |
| `tests/test_chat_routes_smoke.py` | OpenAPI에 `/api/v1/chat/query`·`/api/v1/chat/generate` 등록 여부 |

수동 Swagger 확인: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` 후 `/docs`에서 두 엔드포인트 모두 `question` 필드로 호출.
