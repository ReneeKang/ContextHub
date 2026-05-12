# Agent 아키텍처

## 문서 목적

현재 ContextHub는 NAS RAG Agent 하나를 구현한다.
이 문서는 **지금 구현해야 하는 최소 구조**와,
**나중에 agent를 추가할 때 어디에만 코드가 추가되는지**를 명확히 한다.

지금 당장 Orchestrator, AgentRouter, Tool Registry 같은 것은 만들지 않는다.

---

## 현재 상태와 목표

```
현재 완료:
  NAS ingestion → parse → chunk → index → OpenSearch retrieval → permission filtering

다음 단계 (이 문서의 범위):
  retrieval 결과 → prompt 조립 → LLM 호출 → 응답 후처리 → 사용자 반환
```

---

## 핵심 원칙

**SearchClient와 동일한 철학을 적용한다.**

`SearchClient`가 검색 엔진 구현체(OpenSearch, DB)를 추상화한 것처럼,
`LLMClient`는 LLM 구현체(vLLM, OpenAI, 사내 API)를 추상화한다.

Agent 레이어는 `SearchClient`와 `LLMClient`를 주입받아 사용한다.
어떤 검색 엔진을, 어떤 LLM을 쓰는지 Agent 레이어는 알 필요가 없다.

---

## 레이어 구조

```
chat-api (HTTP 진입점)
  │
  ▼
NasRagUsecase (usecase 레이어)          ← 비즈니스 흐름 조율
  │
  ├─ STEP 1: Retrieval
  │    SearchClient.search(query, permission_filter)
  │
  ├─ STEP 2: Prompt Assembly
  │    PromptBuilder.build(chunks, question, context)
  │
  ├─ STEP 3: Generation
  │    LLMClient.generate(prompt)       ← LLM Gateway 뒤에 숨김
  │
  └─ STEP 4: Postprocess
       SourceExtractor.extract(chunks, llm_response)
       응답 + 출처 목록 조합
```

각 단계는 독립된 모듈이다.
`NasRagUsecase`는 흐름을 조율하지만, 각 단계의 내부를 알지 않는다.

---

## 각 레이어 책임 범위

### chat-api (HTTP 진입점)

**책임:**
- HTTP 요청 수신 및 응답 반환
- 사용자 인증 토큰 검증
- `PermissionPrincipal` 구성
- `NasRagUsecase` 호출
- `trace_id` 생성 및 요청 로그 기록

**하지 않는 것:**
- 검색 로직
- 프롬프트 조립
- LLM 직접 호출

```python
@router.post("/query")
async def query(request: QueryRequest, principal: PermissionPrincipal = Depends(get_principal)):
    trace_id = uuid4().hex
    logger.info("chat.query.start", trace_id=trace_id, user_id=principal.user_id)

    result = await nas_rag_usecase.run(
        question=request.question,
        principal=principal,
        top_k=request.top_k,
        trace_id=trace_id,
    )

    logger.info("chat.query.done", trace_id=trace_id, chunk_count=len(result.sources))
    return result
```

---

### NasRagUsecase (usecase 레이어)

**책임:**
- 4단계 흐름(retrieval → assembly → generation → postprocess) 조율
- 각 단계 실패 처리 및 로그 기록
- 빈 검색 결과 처리 ("관련 문서를 찾을 수 없습니다" 응답)

**하지 않는 것:**
- 검색 쿼리 구성 (SearchClient에 위임)
- 프롬프트 문자열 직접 작성 (PromptBuilder에 위임)
- LLM API 직접 호출 (LLMClient에 위임)
- HTTP 관련 처리

```python
class NasRagUsecase:
    def __init__(
        self,
        search_client: SearchClient,
        llm_client: LLMClient,
        prompt_builder: PromptBuilder,
    ):
        self._search = search_client
        self._llm = llm_client
        self._prompt = prompt_builder

    async def run(
        self,
        question: str,
        principal: PermissionPrincipal,
        top_k: int,
        trace_id: str,
    ) -> ChatResult:
        # STEP 1: Retrieval
        permission_filter = build_permission_filter(principal)
        chunks = await self._search.search(question, permission_filter, top_k)

        if not chunks:
            return ChatResult.empty(trace_id)

        # STEP 2: Prompt Assembly
        prompt = self._prompt.build(chunks=chunks, question=question)

        # STEP 3: Generation
        llm_response = await self._llm.generate(prompt, trace_id=trace_id)

        # STEP 4: Postprocess
        sources = extract_sources(chunks)
        return ChatResult(answer=llm_response.text, sources=sources, trace_id=trace_id)
```

---

### Retrieval (Step 1)

**책임:**
- `SearchClient` 인터페이스를 통해 청크 검색
- 권한 필터는 `build_permission_filter(principal)` 에서 생성

**하지 않는 것:**
- 검색 결과를 재정렬하거나 필터링 (검색 엔진에 위임)
- LLM 응답을 참고한 재검색 (HyDE, Query Expansion은 Phase 2 이후)

---

### Prompt Assembly (Step 2)

**책임:**
- 검색된 청크를 LLM이 소비할 수 있는 컨텍스트 블록으로 조립
- 토큰 한도 내에서 청크 선택
- 프롬프트 템플릿 적용

**하지 않는 것:**
- 청크 내용을 수정하거나 요약
- LLM 호출

---

### Generation (Step 3)

**책임:**
- `LLMClient` 인터페이스를 통해 LLM에 프롬프트 전달
- `trace_id`를 LLM Gateway에 전달 (감사 연동)

**하지 않는 것:**
- 응답 파싱 또는 출처 추출
- 프롬프트 조립

---

### Postprocess (Step 4)

**책임:**
- LLM 응답 텍스트 정제 (불필요한 prefix/suffix 제거 등)
- 출처 청크 목록 구성 (파일명 + section_title + page_no)
- 최종 `ChatResult` 조합

**하지 않는 것:**
- LLM 재호출
- 검색 재시도

---

## trace_id / 감사 / 로깅 전략

> 상세 설계는 [logging-audit.md](logging-audit.md) 참조.
> 이 섹션은 Agent 계층에서 적용하는 규칙을 정리한다.

### 로그 계층 분리 원칙

Agent 계층은 두 종류의 로그를 생성한다.

| 로그 종류 | 생성 위치 | 목적 |
|----------|----------|------|
| RAG Agent 감사 로그 | `NasRagUsecase` | 추적 가능성: 어떤 문서로 답했는가 |
| LLM Gateway 운영 로그 | `LLMClient` 구현체 | 인프라: 속도·비용·오류 |

두 로그를 하나로 합치지 않는다. 수신자와 보존 정책이 다르다.

### trace_id 전파 경로

```
HTTP 요청 수신 (chat-api)
  → X-Trace-Id 헤더 확인 → 없으면 UUID 생성
  → NasRagUsecase.run(trace_id=...)
    → SearchClient.search(...)      [trace_id 전달, 검색엔진 헤더로]
    → LLMClient.generate(trace_id=...)  [LLM 서버 헤더로 전달]
  → 응답 헤더 X-Trace-Id 반환 (사용자가 장애 신고 시 참조)
```

### RAG Agent 감사 로그 이벤트

```python
# STEP 1: 검색 완료
logger.info("rag.retrieval.done",
    trace_id=trace_id,
    agent_name="nas_rag",
    anonymized_user_key=hash_user(principal.user_id),
    access_scope_used=principal.effective_scopes(),
    search_backend=search_backend_name,
    top_k_requested=top_k,
    retrieved_count=len(chunks),
    retrieved_doc_ids=[c.raw_document_id for c in chunks],
    chunk_ids=[c.chunk_id for c in chunks],
    top_score=chunks[0].score if chunks else None,
)

# STEP 2: 검색 결과 없음
logger.warning("rag.retrieval.empty",
    trace_id=trace_id,
    agent_name="nas_rag",
    anonymized_user_key=hash_user(principal.user_id),
    access_scope_used=principal.effective_scopes(),
    question_len=len(question),
)

# STEP 3: 프롬프트 조립 완료
logger.info("rag.prompt.built",
    trace_id=trace_id,
    agent_name="nas_rag",
    included_chunk_ids=prompt.included_chunk_ids,   # 토큰 초과로 잘린 경우 추적
    excluded_chunk_count=len(chunks) - len(prompt.included_chunk_ids),
    prompt_token_estimate=prompt.estimated_tokens,
)

# STEP 4: 생성 완료
logger.info("rag.query.done",
    trace_id=trace_id,
    agent_name="nas_rag",
    anonymized_user_key=hash_user(principal.user_id),
    retrieved_doc_ids=[c.raw_document_id for c in chunks],
    chunk_ids=[c.chunk_id for c in chunks],
    included_chunk_ids=prompt.included_chunk_ids,
    citation_ids=sources_to_ids(result.sources),
    generation_status="success",
    question_len=len(question),
    answer_len=len(result.answer),
)

# 오류
logger.error("rag.query.failed",
    trace_id=trace_id,
    agent_name="nas_rag",
    generation_status="llm_error",
    error_code=error.code,
)
```

### 절대 로그하지 않는 것

| 항목 | 위험 |
|------|------|
| `question` 원문 | 사용자 행동 프로파일링, 민감 질문 유출 |
| `chunk_text` 원문 | 로그가 사내 문서의 우회 접근 경로가 됨 |
| `prompt` 전문 | 시스템 프롬프트 구조 노출 + 문서 내용 포함 |
| `llm_response` 원문 | 문서 내용 재생산 유출 |
| `user_id` 실명 + `question` 조합 | 개인정보 수집 위반 |

**핵심**: 로그에서 `chunk_id`로 DB를 조회하면 내용을 확인할 수 있다.
로그 자체에 내용을 넣을 필요가 없다.

### 장애 분석은 ID로 한다

```
운영자가 "이상한 답변" 신고 수신
  → trace_id 확인 (응답에 포함)
  → 감사 로그: chunk_ids, included_chunk_ids, doc_ids 조회
  → DB: chunk_id로 실제 chunk_text 직접 조회 (권한 있는 운영자만)
  → Gateway 로그: trace_id로 모델·토큰·지연 확인
  → 원인 파악 완료 (로그에 원문 없어도 가능)
```

---

## 빈 검색 결과 처리

검색 결과가 없을 때 LLM을 호출하지 않는다.

```python
if not chunks:
    logger.warning("chat.retrieval.empty", trace_id=trace_id)
    return ChatResult(
        answer="관련 문서를 찾을 수 없습니다. 질문을 다르게 표현하거나 접근 가능한 문서를 확인해주세요.",
        sources=[],
        trace_id=trace_id,
    )
```

**이유:**
- LLM이 컨텍스트 없이 답변하면 hallucination 발생
- 빈 컨텍스트로 LLM을 호출하는 것은 비용 낭비
- "모른다"는 답이 틀린 답보다 낫다

---

## 현재 MVP에서 구현해야 하는 최소 범위

| 항목 | 구현 여부 |
|------|----------|
| `NasRagUsecase` 4단계 흐름 | ✅ 구현 |
| `LLMClient` 프로토콜 인터페이스 | ✅ 구현 |
| `PromptBuilder` 분리 | ✅ 구현 |
| `trace_id` 생성 및 전파 | ✅ 구현 |
| 빈 검색 결과 처리 | ✅ 구현 |
| 출처 목록 반환 | ✅ 구현 |
| HyDE / Query Expansion | ❌ Phase 2 |
| 대화 이력 기반 reranking | ❌ Phase 2 |
| Orchestrator / AgentRouter | ❌ Phase 3 |
| Tool Registry | ❌ Phase 3 |

---

## 절대 하지 말아야 할 것 (MVP)

| 패턴 | 이유 |
|------|------|
| LangGraph / CrewAI / AutoGen 도입 | 단일 에이전트에 과도한 프레임워크 오버헤드 |
| Usecase 내부에서 LLM 직접 import | LLMClient 추상화 파괴 |
| 검색 → LLM → 재검색 루프 | 단일 턴 RAG에서 불필요, 지연 증가 |
| 프롬프트 문자열을 usecase 안에 직접 작성 | 프롬프트 관리 불가, 재사용 불가 |
| 여러 에이전트를 한 파일에 구현 | 향후 분리 시 비용 급증 |
| HTTP 응답 구조를 LLM 응답에 맞춤 | LLM 교체 시 API 스펙 변경 발생 |

---

## 향후 멀티에이전트 확장 시 추가 위치

현재 구조에서 새 에이전트를 추가할 때 **추가되는 위치**:

```
app/
├─ chat/
│   ├─ usecases/
│   │   ├─ nas_rag_usecase.py      ← 현재 (NAS 문서 RAG)
│   │   ├─ log_analysis_usecase.py ← 추가 (로그 분석 Agent)
│   │   ├─ standards_usecase.py    ← 추가 (표준 검토 Agent)
│   │   └─ sql_data_usecase.py     ← 추가 (SQL/데이터 Agent)
│   ├─ router.py                   ← 추가: 요청을 어느 usecase로 보낼지 결정
│   └─ api.py                      ← chat-api HTTP 진입점 (거의 변경 없음)
```

**변경되지 않는 것:**
- `SearchClient` 인터페이스
- `LLMClient` 인터페이스
- `PermissionPrincipal` + `build_permission_filter()`
- `trace_id` 전파 방식
- 로깅 규칙

각 usecase는 독립적으로 자신의 retrieval 전략과 prompt를 갖는다.
공통 인프라(`SearchClient`, `LLMClient`, `PermissionPrincipal`)만 공유한다.

```
나중에 AgentRouter를 추가하더라도:

chat-api
  → AgentRouter.route(question, principal)
      → NasRagUsecase      (NAS 문서 질문)
      → LogAnalysisUsecase (로그 분석 질문)
      → SqlDataUsecase     (데이터 조회 질문)
```

`AgentRouter`는 라우팅만 한다.
각 Usecase의 내부 구조는 변경하지 않는다.
