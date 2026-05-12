# Backend 구현 상태 (스냅샷)

설계 문서(`docs/architecture.md`, `docs/llm-gateway.md`, `docs/logging-audit.md` 등)와의 **대응 관계**를 기준으로, 현재 저장소의 **실제 코드** 상태를 요약한다.

---

## 1. Chat API

| 엔드포인트 | 역할 | 구현 위치 |
|-------------|------|-----------|
| `POST /api/v1/chat/query` | **Retrieval 전용** 검증: 권한 필터 검색 + 스텁 형태의 `answer` (LLM 미호출) | `app/chat/router.py`, `app/chat/service.py` |
| `POST /api/v1/chat/generate` | **RAG generation MVP**: 동일 검색 계약으로 히트 조회 후 LLM 호출(또는 mock) | `app/chat/router.py`, `app/agents/nas_rag.py` |
| `GET /api/v1/chat/history/{session_id}` | 미구현 (501) | `app/chat/router.py` |

요청 스키마는 `app/chat/schemas.py`의 `ChatQueryRequest`(`question` 등). **검색에 넘기는 문자열**만 `app/chat/retrieval_query.py`의 `normalize_retrieval_query` / `normalize_retrieval_query_pair`로 가볍게 정규화한다 (`/query`·`/generate` 공통; 구현은 `retrieval_query.py`).

검색 계약(`SearchClient`, `SearchHit`, `PermissionPrincipal`)은 **변경하지 않는다**는 전제로 `/generate`가 `search.search(...)` 결과만 사용한다.

### Keyword retrieval 품질 (MVP)

- **현상**: PostgreSQL 경로는 공백으로만 토큰을 나눈 뒤 AND 매칭한다. 한글에서 `"방화벽 포트 오픈 설명"`처럼 **붙여 쓴** 질의는 한 토큰이 되어, 본문에 `"방화벽 포트 오픈"`만 있어도 `"…설명"`까지 연속 일치가 없으면 미스가 난다.
- **조치**: `app/chat/retrieval_query.py`에서 **검색 전용** 문자열만 정규화(접미·토큰 단위 불용어 제거: `설명`, `알려줘`, `해줘` 등). **원본 `question`**은 `/query` 스텁 답변·`/generate` LLM user 블록에 그대로 둔다.
- **로그**: `original_query`, `retrieval_query`, `normalization_applied`, `retrieval_count` (`contexthub.chat.service`, `contexthub.agents.nas_rag`).
- **Swagger 동등 검증**: `tests/test_swagger_equivalent_retrieval.py` — `TestClient`로 `POST /api/v1/chat/query`·`/generate`에 동일 스키마 JSON을 보내, 네 가지 질의 변형이 **동일 `SearchClient.search(query=…)`**와 동일 소스를 내는지 확인한다. dev 의존성에 `httpx` 필요.

---

## 2. `app/llm` — LLM 게이트웨이 (MVP)

| 파일 | 설명 |
|------|------|
| `protocol.py` | `LLMMessage`, `LLMCompletionResult`, `LLMClient` Protocol (`complete` 동기 단일 진입점). |
| `mock.py` | `MockLLMClient` — 기본 개발용; 외부 HTTP 없음. |
| `openai_compat.py` | `OpenAICompatLLMClient` — `urllib`로 `{base}/chat/completions` POST. `normalize_openai_compat_base_url()`로 base URL 정규화(잘못 붙여넣은 `/chat/completions` 접미사 제거). |
| `backend.py` | `get_llm_client(settings)` — `LLM_MOCK_MODE` / `LLM_BACKEND`에 따라 mock vs HTTP 클라이언트 선택, 타임아웃·API 키·base URL은 `Settings`에서 주입. |

OpenAI 예시: `OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1` → 요청 URL은 **`https://api.openai.com/v1/chat/completions`** 한 번만 붙는다.  
`…/v1/chat/completions`까지 붙여 넣은 경우에도 정규화 후 동일하게 동작한다.

---

## 3. `app/agents` — NAS RAG (MVP)

| 파일 | 설명 |
|------|------|
| `nas_rag.py` | `NAS_RAG_SYSTEM_PROMPT`, `build_nas_rag_user_prompt`, `_retrieve_hits_for_nas_rag`, `_sources_from_hits`, `run_nas_rag_generate`. 검색(권한 반영된 `hits`) → 프롬프트 조립 → LLM → **`sources`는 히트에서만 구성**(모델 출력 파싱 없음). 검색 문자열은 `normalize_retrieval_query` / `normalize_retrieval_query_pair`로만 정규화하고, LLM user 메시지의 질문 문장은 **원본 `question`** 그대로다. |

로깅(성공/실패): HTTP 요청의 **`question`** 값은 로그에 **`original_query`**·**`retrieval_query`**(각각 스니펫), **`normalization_applied`**(정규화로 검색 문자열이 달라졌는지), **`retrieval_count`** 등을 남긴다. `retrieval_ms`, `used_chunk_ids`, `llm_model`, `llm_mock`, `latency_ms`(총), 실패 시 `error_type`·`error_message`를 남긴다. **`chunk_text` 원문은 로그에 넣지 않는다.**

---

## 4. `/api/v1/chat/generate` 사용법 (Swagger)

1. API 기동: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
2. `http://127.0.0.1:8000/docs` → **chat** → `POST /api/v1/chat/generate`
3. Request body는 **`POST /api/v1/chat/query`와 동일**하며, 스키마는 `app/chat/schemas.py`의 **`ChatQueryRequest`**이다. **필수 필드는 `question`**(문자열)이다. 선택: `top_k`, `session_id`, `test_department_codes`.

Swagger / Try it out 예시(JSON):

```json
{
  "question": "Kubeflow 워크플로우",
  "top_k": 5,
  "session_id": null,
  "test_department_codes": null
}
```

`test_department_codes`는 생략하거나, DEPT 스텁 검증 시 `["infra"]`처럼 배열을 넣을 수 있다.

응답은 `app/chat/schemas.py`의 **`ChatGenerateResponse`**: `answer`, `sources`, `search_backend`, `llm_model`, `llm_mock`, `retrieval_latency_ms`, `llm_latency_ms`, `total_latency_ms`.

---

## 5. Mock 모드 (기본)

| 환경 변수 | 기본 | 의미 |
|-----------|------|------|
| `LLM_MOCK_MODE` | `true` | `true`이면 **항상** `MockLLMClient` (HTTP 미사용). |
| `LLM_BACKEND` | `mock` | `LLM_MOCK_MODE=false`일 때만 의미; `mock`이면 mock 클라이언트. |
| `LLM_MODEL` | `gpt-4o-mini` | mock이 아닌 OpenAI-compatible 경로에서 `complete(..., model=...)`에 전달. |

검색 결과 **0건**이면 LLM을 호출하지 않고 고정 안전 메시지를 반환한다.

---

## 6. OpenAI-compatible 설정

`.env` 예시:

```env
LLM_MOCK_MODE=false
LLM_BACKEND=openai_compat
OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
OPENAI_COMPAT_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
OPENAI_COMPAT_TIMEOUT_SECONDS=120
```

- `OPENAI_COMPAT_BASE_URL`: **스킴 + 호스트 + `/v1`까지** (또는 사내 게이트웨이가 요구하는 동일 패턴). `/chat/completions`는 클라이언트가 붙인다.
- `OPENAI_COMPAT_TIMEOUT_SECONDS`: `urllib.request.urlopen` 타임아웃(초).

설정 누락 시 `get_llm_client`는 `RuntimeError`를 던지고, 라우터는 **503**으로 매핑한다. LLM 호출 실패는 **502** (`NasRagLLMError`).

---

## 7. 현재 MVP 한계

- **스트리밍 / async 전환 / AgentRouter / LangChain·LlamaIndex 없음.**
- **재시도·회로 차단·요청별 trace_id**는 미구현.
- **대화 이력 저장·세션 관리** 없음 (`/history` 501).
- Mock 응답은 스텁 문자열이며, **실제 요약 품질 검증**은 `LLM_MOCK_MODE=false` + 실 API에서 수행해야 한다.
- `test_department_codes` 등 **스텁 principal**은 개발용; 운영 인증·감사 로그 정책은 별도 설계 필요 (`docs/logging-audit.md`).

---

## 8. 다음 단계 (설계 대비)

1. **실 LLM 품질**: 프롬프트·토큰 상한·출처 표기 UX (`docs/prompt-strategy.md`).
2. **LLMClient** 확장: 도구 호출·구조화 출력은 Protocol 확장 시 하위 호환 유의.
3. **관측**: `trace_id` 상관관계, 민감정보 마스킹 정책을 운영 기준에 맞게 강화.
4. **테스트**: 단위 테스트(`tests/`)는 LLM·RAG 경로만 커버; DB/OpenSearch 통합은 별도 픽스처·CI에서 수행.

---

## 9. 관련 문서

- `docs/llm-gateway.md` — LLMClient 교체 전략
- `docs/agent-architecture.md` — 장기 Agent 레이어 (현 코드는 단일 `nas_rag` 오케스트레이션)
- `docs/logging-audit.md` — 로그 vs 감사

---

## 10. 자동 검증 (pytest)

```bash
pip install -e ".[dev]"
pytest -q
```

`tests/test_nas_rag_generation.py` — OpenAI base URL 정규화, 질의 로그 스니펫 길이, `get_llm_client` 타임아웃 주입, 검색 0건 시 LLM 미호출, 히트 시 소스 미러링·로그에 `chunk_text` 미포함, LLM 실패 시 `error_type` / `error_message` 로그.

`tests/test_retrieval_query_normalize.py` — `normalize_retrieval_query` / `normalize_retrieval_query_pair`(예: ``방화벽 포트 오픈 설명``→``방화벽 포트 오픈``, `normalization_applied`), LLM 프롬프트에 원문 `question` 유지, `SearchClient.search`에 정규화 문자열 전달.

`tests/test_swagger_equivalent_retrieval.py` — `httpx` 기반 `TestClient`로 Swagger와 동일 JSON으로 `/chat/query`·`/chat/generate` 호출; 질의 변형 4종이 동일 `search(query=…)`·동일 소스를 내는지, 로그 필드·LLM user 블록의 원문 `question`을 검증.

`tests/test_chat_routes_smoke.py` — OpenAPI에 `/api/v1/chat/query`·`/api/v1/chat/generate` 등록 여부.

수동으로 Swagger를 확인할 때는 `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` 후 `/docs`에서 `POST /api/v1/chat/query`와 `POST /api/v1/chat/generate`를 각각 호출하면 된다. 두 엔드포인트 모두 요청 body의 질의 문자열 필드명은 **`question`**(`app/chat/schemas.py`의 `ChatQueryRequest`)이다.
