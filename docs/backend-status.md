# Backend 구현 상태 (스냅샷)

설계 문서(`docs/architecture.md`, `docs/llm-gateway.md`, `docs/logging-audit.md` 등)와의 **대응 관계**를 기준으로, 현재 저장소의 **실제 코드** 상태를 요약한다.

---

## 0. 현재 진행 단계 (2026-05)

| 단계 | 상태 | 비고 |
|------|------|------|
| Ingestion / xlsx·kordoc parser 확장 | ✅ (코드) | FAILED 문서는 수동 reprocess 필요 |
| OpenSearch filename/path boost | ✅ | 매핑 변경 시 재색인 |
| **Discover retrieval post-processing** | ✅ | chunk over-fetch → document grouping → 상대 점수·highlight 필터 (`discovery_service.py`) |
| POC discover → select → generate 연결 | ✅ | `app/static/poc/` |
| **Generate quality validation** | 🔄 **진행 중** | 선택 문서·sources·debug·답변 근거 일치 여부 운영 검증 |
| Generate multi-document context 균형 | ⏳ 후보 | 선택 N건이어도 chunk `top_k`가 한 문서에 치우칠 수 있음 |

**다음 작업:** POC/Swagger에서 `과업대비표` 시나리오로 문서 1건·3건 선택 후 `/generate` 검증. `.env`에 `ENABLE_RETRIEVAL_DEBUG=true` 권장(로컬).

---

## 1. Chat API

| 엔드포인트 | 역할 | 구현 위치 |
|-------------|------|-----------|
| `POST /api/v1/chat/query` | **Retrieval 전용** 검증: 권한 필터 검색 + 스텁 형태의 `answer` (LLM 미호출) | `app/chat/router.py`, `app/chat/service.py` |
| `POST /api/v1/chat/discover` | **문서 탐색 MVP**: chunk over-fetch → `raw_document_id` 그룹핑 → document `top_k` → **Search Post-processing**(상대 점수·highlight 필터). LLM 미호출, `chunk_text` 미포함 | `app/chat/router.py`, `app/chat/discovery_service.py` |
| `POST /api/v1/chat/generate` | **RAG generation MVP**: 권한 반영 `SearchClient.search` → (선택) `document_ids`로 `raw_document_id` 필터 → 히트가 없으면 **선택 문서 chunk DB fallback**(동일 권한·색인 조건) → 프롬프트·LLM. 응답에 `selected_document_ids`, `filtered_retrieval_count` 포함 | `app/chat/router.py`, `app/agents/nas_rag.py`, `app/chat/selected_document_fallback.py`, `app/chat/schemas.py` (`ChatGenerateRequest`) |
| `GET /api/v1/chat/history/{session_id}` | 미구현 (501) | `app/chat/router.py` |

### POC UI (Vanilla)

| 경로 | 설명 |
|------|------|
| `GET /`, `GET /poc` | 브라우저 POC (**3열 레이아웃**: 사이드바 · 검색/후보/답변 · 선택·출처·debug). `discover` → 문서 선택 → `generate` + `document_ids`. 정적 파일: `app/static/poc/`. |
| `/static/poc/*` | `index.html`, `css/style.css`, `js/*.js` (ES modules). |

로컬 실행: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` 후 `http://127.0.0.1:8000/poc` (또는 `/`). 상세 레이아웃은 `docs/poc-ui-design.md`.

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
`/discover`는 chunk 후보를 **문서 단위 후보 목록**으로 돌려준 뒤, 사용자가 `raw_document_id`를 고르면 **`POST /api/v1/chat/generate`**에 `document_ids`로 넘겨 해당 문서의 검색 히트만으로 답변을 생성할 수 있다(자동 파이프라인 없음; 클라이언트가 두 API를 순서대로 호출).

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

**구조화 로그 (항상):** `POST /api/v1/chat/query` 및 `POST /api/v1/chat/generate`의 검색 직후, `contexthub.chat.service` / `contexthub.agents.nas_rag` 로거로 한 줄 `retrieval_debug {…}` JSON이 출력된다. 필드에는 `original_query`, `retrieval_query`, `normalization_applied`, `retrieval_backend`, `retrieval_count`, `top_k`, `retrieved_chunk_ids`, `retrieved_document_ids`, `retrieval_scores`, `retrieval_filenames`, `retrieval_latency_ms`가 포함된다. **`chunk_text` 원문은 로그에 넣지 않는다** (메타만). `/generate`에서 `document_ids`를 쓴 경우 `retrieval_count` 등은 **문서 필터 적용 후** 실제로 사용된 히트 기준이다.

`POST /api/v1/chat/discover`는 검색 직후 `contexthub.chat.discovery` 로거로 `chat_discover {…}` 한 줄을 남긴다. 필드: `original_query`, `retrieval_query`, `normalization_applied`, `document_count`, `retrieved_document_ids`, `top_scores`, `retrieval_backend`, `retrieval_latency_ms`. 역시 **chunk 본문 로그 없음**.

**응답 `debug` (선택):** `ENABLE_RETRIEVAL_DEBUG=true`(기본 `false`)일 때만 응답 JSON에 `debug` 객체를 붙인다(`RetrievalDebugInfo`: 동일 메타 + `chunks` 배열; 역시 전체 본문 없음). **`POST /generate`만** `debug.generation_context_chunks`에 LLM 프롬프트에 넣은 chunk의 `text_preview`(약 300자)를 추가한다. POC 우측 Retrieval debug 패널에서 확인.

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
3. Request body는 **`ChatGenerateRequest`** (`ChatQueryRequest` 필드 + 선택 `document_ids`). **`question`** 필수. 선택: `top_k`, `session_id`, `test_department_codes`, **`document_ids`** (`raw_document_id` UUID 배열; 생략 시 전체 검색 히트로 생성).

```json
{
  "question": "Kubeflow 워크플로우",
  "top_k": 5,
  "session_id": null,
  "test_department_codes": null,
  "document_ids": ["f44d094c-4fa3-42b3-aa15-a01c125c9400"]
}
```

`document_ids`는 `/discover` 응답의 문서를 고른 뒤 Swagger에서 붙이는 용도다. 권한 필터를 통과한 검색 결과에 없는 ID만 넘기면 히트가 비고 LLM은 호출되지 않는다.

`test_department_codes`는 생략하거나 DEPT 스텁 검증 시 `["infra"]`처럼 배열을 넣을 수 있다.

응답(`ChatGenerateResponse`): `answer`, `sources`, `search_backend`, `llm_model`, `llm_mock`, `retrieval_latency_ms`, `llm_latency_ms`, `total_latency_ms`, **`selected_document_ids`**(요청에 `document_ids`가 있었을 때 UUID 문자열 목록), **`filtered_retrieval_count`**(문서 필터 후 실제 사용 청크 수).

**흐름 예:** `POST /discover`로 후보 문서·`raw_document_id` 확인 → 사용자 선택 → `POST /generate`에 동일 질의(또는 후속 질의)와 `document_ids`를 넣어 해당 문서 근거만으로 답변.

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

## 11. POC UI 구현 상태

UI는 백엔드 API 계약을 변경하지 않는다. `/discover` → 문서 선택 → `/generate(document_ids)` 흐름을 시각화하는 역할만 한다.

### 현재 구현 단계: Connected POC UI — API Wiring 완료

| 구성 요소 | 상태 |
|----------|------|
| FastAPI StaticFiles + `/poc` 라우트 | ✅ 완료 |
| 3-panel 레이아웃 (사이드바·중앙·우측) | ✅ 완료 |
| `POST /api/v1/chat/discover` 연결 | ✅ 완료 |
| `POST /api/v1/chat/generate` 연결 | ✅ 완료 |
| discover 응답 → 문서 카드 렌더링 | ✅ 완료 |
| `raw_document_id` 기준 체크박스 선택 관리 | ✅ 완료 |
| 선택 `document_ids` → generate 전달 | ✅ 완료 |
| generate 응답 → 답변·출처·debug 렌더링 | ✅ 완료 |
| phase 상태 전환 (DISCOVERING → DISCOVERED → GENERATING → ANSWERED) | ✅ 완료 |
| EMPTY (빈 결과) 처리 | ✅ 완료 |
| /discover 오류 → 후보 영역 오류 표시 | ✅ 완료 |
| /generate 오류 → 선택 상태 유지 + 답변 영역 오류 표시 | ✅ 완료 |
| top_k / test_department_codes → API 요청 반영 | ✅ 완료 |
| mock 데이터 제거 | ✅ 완료 |

### 파일별 역할

| 파일 | 역할 |
|------|------|
| `api.js` | fetch 처리, FastAPI detail 에러 파싱, discover 빈 결과 판별 |
| `state.js` | phase 관리, selectedDocumentIds Set, canStartDiscover / canStartGenerate 판단 |
| `main.js` | 버튼/입력 이벤트 처리, API 호출 흐름 제어, phase 전환 |
| `render.js` | API 응답 기반 DOM 렌더링, progress 단계 표시, 문서 카드·선택 패널·답변·출처·debug 표시 |

### 접속 및 사용

```
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
→ http://127.0.0.1:8000/poc
```

실제 색인 데이터가 있어야 검색 결과가 반환된다. LLM 연결은 `.env`의 `LLM_BACKEND` 설정에 따른다.

### 현재 검증 필요 항목

| 항목 | 확인 방법 |
|------|---------|
| **Generate 품질 (1건·3건 선택)** | `과업대비표` discover → A01 선택 → generate: `selected_document_ids`, `sources`, `answer` 일치 |
| **Generate context 치우침** | 문서 3건 선택 시 `sources`/`debug.chunks`가 선택 문서 전부에서 오는지 (한 문서 청크만 나오면 `top_k`·fetch 정책 검토) |
| `/discover` 빈 결과 처리 | 색인 없는 질문으로 EMPTY 상태 진입 확인 |
| `/generate` 실패 시 선택 상태 유지 | LLM 오류 시 문서 카드 선택 유지 확인 |
| `test_department_codes` 필터 적용 | 부서 설정 후 DEPT 문서 포함 여부 확인 |
| `top_k` 적용 여부 | discover `top_k`=문서 수, generate `top_k`=청크 수 (UI Advanced) |
| `sources` / `debug` 표시 여부 | `ENABLE_RETRIEVAL_DEBUG=true` 환경에서 debug 패널·`chunk_rank`/`document_rank`/`matched_fields`/`highlight_terms` |
| `document_ids` 매핑 정확성 | 브라우저 `console.debug` `[POC] /api/v1/chat/generate payload` vs 응답 `selected_document_ids` |

### 다음 개선 후보

| 항목 | 설명 |
|------|------|
| Retrieval Debug UI 가독성 개선 | matched_fields, highlight_terms, document_rank 테이블 정리 |
| 문서 카드 점수 시각화 개선 | score 바 색상 + top_score 수치 동시 표시 |
| 선택 문서 미리보기 강화 | 우측 패널에 representative_sections 표시 |
| Progress 단계별 소요 시간 표시 | 각 단계 완료 시각 표시 |
| POC 테스트 시나리오 문서화 | 시나리오 A/B/C를 재현 가능한 절차로 정리 |

---

## 12. 관련 문서

- `docs/llm-gateway.md` — LLMClient 교체 전략, 운영 로그 필드 정의
- `docs/agent-architecture.md` — 장기 Agent 레이어 (현재는 단일 `nas_rag` 오케스트레이션)
- `docs/logging-audit.md` — Gateway 운영 로그 vs Agent 감사 로그 분리 설계
- `docs/retrieval-roadmap.md` — keyword → hybrid → vector retrieval 확장 방향
- `docs/prompt-strategy.md` — PromptBuilder 설계 및 금지 패턴
- `docs/poc-ui-design.md` — POC UI 설계 기준 문서 (API Wiring 완료, 검증 항목 및 개선 후보 포함)
- `docs/rag-troubleshooting-and-lessons.md` — 운영형 RAG 구축 트러블슈팅 기록 (발생 순서 기반 21개 이슈, ingestion→retrieval→generation 레이어별 원인·해결·교훈, 체크리스트)

---

## 13. 자동 검증 (pytest)

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
