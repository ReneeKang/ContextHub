# 로그 및 감사 설계

## 문서 목적

로그를 남기지 않는 것이 목표가 아니다.
**계층별로 남길 정보를 분리하는 것**이 목표다.

- LLM Gateway: 운영 지표 중심 (속도, 비용, 오류)
- RAG Agent: 추적 가능성 중심 (어떤 문서로 답했는가)

두 레이어는 서로 다른 목적으로 서로 다른 수신자를 위해 로그를 남긴다.

---

## 로그 계층 분리

```
┌─────────────────────────────────────────────┐
│  chat-api (HTTP 계층)                       │
│  - 요청/응답 메타: trace_id, status, latency │
│  - 인증 이벤트                               │
│  - 오류 코드                                 │
│  ❌ 질문 원문, 응답 원문 기록 금지            │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  NasRagUsecase (Agent / 업무 계층)          │
│  - 감사 로그: doc_id, chunk_id, citation_id │
│  - 검색 메타: top_k, score, backend         │
│  - 생성 상태: status, error_code            │
│  ❌ chunk_text, 질문 원문, LLM 응답 원문 금지 │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  LLMClient / LLM Gateway (인프라 계층)      │
│  - 운영 로그: 모델, 토큰 수, 지연, 오류      │
│  - 비용 추적 기반 지표                       │
│  ❌ prompt 전문, messages 내용, 응답 전문 금지 │
└─────────────────────────────────────────────┘
```

각 계층은 **자신이 생성한 정보만** 로그에 남긴다.
상위 계층이 내려준 내용(질문, 프롬프트, 청크)은 하위 계층이 로그하지 않는다.

---

# Part 1. LLM Gateway 운영 로그

## 목적

- LLM 인프라 성능 모니터링
- 비용 추적 (토큰 수 기반)
- 오류 분류 및 재시도 추적
- SLA 측정 (응답 시간, 가용성)

## 로그 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `trace_id` | string | ✅ | 요청 추적 ID, 전 계층 공유 |
| `service_name` | string | ✅ | 서비스명 (`contexthub`) |
| `agent_name` | string | ✅ | 에이전트명 (`nas_rag`) |
| `event` | string | ✅ | 로그 이벤트명 (`llm.generate.done`) |
| `model` | string | ✅ | 실제 사용된 모델 ID |
| `endpoint` | string | ✅ | LLM API 엔드포인트 (경로만, base_url 제외) |
| `temperature` | float | ✅ | 요청 temperature 값 |
| `max_tokens` | int | ✅ | 요청 max_tokens 값 |
| `input_token_count` | int | 조건부 | 입력 토큰 수 (모델이 제공 시) |
| `output_token_count` | int | 조건부 | 출력 토큰 수 (모델이 제공 시) |
| `latency_ms` | int | ✅ | 전체 호출 소요 시간 (ms) |
| `status` | string | ✅ | `success` \| `error` \| `timeout` |
| `status_code` | int | 조건부 | HTTP 상태 코드 (오류 시) |
| `error_code` | string | 조건부 | 내부 오류 분류 코드 |
| `is_timeout` | bool | ✅ | 타임아웃 여부 |
| `retry_count` | int | ✅ | 재시도 횟수 (0 = 첫 번째 성공) |
| `timestamp` | ISO8601 | ✅ | 이벤트 발생 시각 (UTC) |

## 절대 포함하지 않는 필드

| 금지 필드 | 이유 |
|-----------|------|
| `messages[].content` | system prompt + 사내 문서 내용 포함 |
| `question` / `user_query` | 사용자 민감 질문 원문 |
| `response_text` / `completion` | LLM이 생성한 응답 원문 |
| `chunk_text` | 사내 기밀 문서 내용 |
| `user_id` (실명) | 개인정보 (anonymized_user_key 사용) |
| `prompt` (전문) | 시스템 프롬프트 구조 노출 + 문서 내용 포함 |

## 예시 JSON 로그 (성공)

```json
{
  "trace_id": "a1b2c3d4e5f6",
  "service_name": "contexthub",
  "agent_name": "nas_rag",
  "event": "llm.generate.done",
  "model": "mistral-7b-instruct",
  "endpoint": "/v1/chat/completions",
  "temperature": 0.1,
  "max_tokens": 2048,
  "input_token_count": 1842,
  "output_token_count": 312,
  "latency_ms": 2341,
  "status": "success",
  "status_code": 200,
  "error_code": null,
  "is_timeout": false,
  "retry_count": 0,
  "timestamp": "2026-05-12T09:14:23.441Z"
}
```

## 예시 JSON 로그 (오류)

```json
{
  "trace_id": "f9e8d7c6b5a4",
  "service_name": "contexthub",
  "agent_name": "nas_rag",
  "event": "llm.generate.failed",
  "model": "mistral-7b-instruct",
  "endpoint": "/v1/chat/completions",
  "temperature": 0.1,
  "max_tokens": 2048,
  "input_token_count": null,
  "output_token_count": null,
  "latency_ms": 60012,
  "status": "timeout",
  "status_code": null,
  "error_code": "LLM_TIMEOUT",
  "is_timeout": true,
  "retry_count": 2,
  "timestamp": "2026-05-12T09:15:01.009Z"
}
```

---

# Part 2. RAG Agent 감사 로그

## 목적

- 운영 장애 추적: "왜 이 문서가 검색됐는가"
- 권한 감사: "누가 어떤 문서 범위에 접근했는가"
- 품질 모니터링: "어떤 문서가 자주 인용되는가"
- 재현 가능성: trace_id로 동일 상황 재구성

## 로그 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `trace_id` | string | ✅ | 요청 추적 ID |
| `agent_name` | string | ✅ | 에이전트명 (`nas_rag`) |
| `event` | string | ✅ | 로그 이벤트명 |
| `anonymized_user_key` | string | ✅ | 사용자 식별자 (해시 또는 내부 코드) |
| `access_scope_used` | string[] | ✅ | 검색에 적용된 권한 범위 목록 |
| `search_backend` | string | ✅ | `opensearch` \| `db` |
| `top_k_requested` | int | ✅ | 요청한 검색 결과 수 |
| `retrieved_count` | int | ✅ | 실제 반환된 청크 수 |
| `retrieved_doc_ids` | string[] | ✅ | 검색된 `raw_document_id` 목록 |
| `chunk_ids` | string[] | ✅ | 검색된 `chunk_id` 목록 |
| `included_chunk_ids` | string[] | ✅ | 프롬프트에 실제 포함된 청크 (토큰 초과로 잘린 경우 추적) |
| `citation_ids` | string[] | 조건부 | 응답 생성에 사용된 출처 청크 ID (후처리 추출 시) |
| `top_score` | float | 조건부 | 최고 검색 점수 |
| `prompt_token_estimate` | int | ✅ | 프롬프트 토큰 수 추정값 |
| `generation_status` | string | ✅ | `success` \| `empty_retrieval` \| `llm_error` \| `timeout` |
| `error_code` | string | 조건부 | 오류 분류 코드 |
| `question_len` | int | ✅ | 질문 문자 수 (원문 아님) |
| `answer_len` | int | 조건부 | 응답 문자 수 (원문 아님) |
| `created_at` | ISO8601 | ✅ | 이벤트 발생 시각 (UTC) |

## 예시 JSON 로그 (정상)

```json
{
  "trace_id": "a1b2c3d4e5f6",
  "agent_name": "nas_rag",
  "event": "rag.query.done",
  "anonymized_user_key": "u_7f3a91bc",
  "access_scope_used": ["PUBLIC", "DEPT:infra"],
  "search_backend": "opensearch",
  "top_k_requested": 5,
  "retrieved_count": 5,
  "retrieved_doc_ids": [
    "doc-uuid-0001",
    "doc-uuid-0002",
    "doc-uuid-0003"
  ],
  "chunk_ids": [
    "chunk-uuid-0011",
    "chunk-uuid-0012",
    "chunk-uuid-0021",
    "chunk-uuid-0031",
    "chunk-uuid-0032"
  ],
  "included_chunk_ids": [
    "chunk-uuid-0011",
    "chunk-uuid-0012",
    "chunk-uuid-0021"
  ],
  "citation_ids": [
    "chunk-uuid-0011",
    "chunk-uuid-0021"
  ],
  "top_score": 0.91,
  "prompt_token_estimate": 1842,
  "generation_status": "success",
  "error_code": null,
  "question_len": 28,
  "answer_len": 312,
  "created_at": "2026-05-12T09:14:25.881Z"
}
```

## 예시 JSON 로그 (검색 결과 없음)

```json
{
  "trace_id": "b3c4d5e6f7a8",
  "agent_name": "nas_rag",
  "event": "rag.query.done",
  "anonymized_user_key": "u_7f3a91bc",
  "access_scope_used": ["PUBLIC"],
  "search_backend": "opensearch",
  "top_k_requested": 5,
  "retrieved_count": 0,
  "retrieved_doc_ids": [],
  "chunk_ids": [],
  "included_chunk_ids": [],
  "citation_ids": [],
  "top_score": null,
  "prompt_token_estimate": 0,
  "generation_status": "empty_retrieval",
  "error_code": "NO_RESULTS",
  "question_len": 45,
  "answer_len": 0,
  "created_at": "2026-05-12T09:15:30.112Z"
}
```

---

# Part 3. 왜 prompt/chunk 전문 로그가 위험한가

## 위험 1: 로그 파일이 문서 저장소가 된다

사내 문서를 NAS에서 접근 제어하여 관리하더라도,
`chunk_text`가 로그에 포함되는 순간 **로그 시스템으로 우회 접근이 가능**해진다.

```
NAS 문서: 접근 제어 ✅
OpenSearch 인덱스: 권한 필터 ✅
로그 파일: 권한 없음 ❌ ← chunk_text가 여기 있으면 무의미
```

로그는 대부분 더 넓은 범위의 인원이 접근한다.
DevOps 팀이 로그를 볼 수 있다면, 그들은 법무·인사 문서에도 접근하게 된다.

## 위험 2: 로그는 오래 보관된다

청크 한 건이 로그에 들어가면 로그 보존 정책에 따라 수개월~수년간 남는다.
원본 문서를 삭제하거나 excluded 처리해도 **로그에서는 사라지지 않는다**.

```
운영자가 문서 exclude 처리 → OpenSearch에서 삭제 ✅
                           → 로그에서 삭제          ❌ 불가
```

## 위험 3: 보안 사고 시 피해 범위가 폭발적으로 커진다

로그 시스템이 침해되면 질문 원문 + 응답 원문 + 청크 원문이 모두 유출된다.
이것은 **단순 로그 유출이 아니라 전체 사내 문서 유출**이 된다.

## 위험 4: 사용자 행동 프로파일링이 가능해진다

`user_id + question 원문` 조합이 로그에 있으면
"누가 언제 무엇을 검색했는가"를 재구성할 수 있다.
이는 의도치 않은 개인정보 수집이 된다.

`anonymized_user_key`를 쓰는 이유가 여기에 있다.
`user_id` 직접 노출 없이 이상 패턴 감지는 가능하다.

## 위험 5: 시스템 프롬프트 구조가 노출된다

`messages[0].content` (system prompt)가 로그에 남으면
프롬프트 구조, 가이드라인, 에이전트 설계 의도가 외부에 노출된다.
공격자가 프롬프트를 알면 prompt injection 공격이 쉬워진다.

---

# Part 4. trace_id 기반 장애 분석 구조

원문 없이도 trace_id, doc_id, chunk_id만으로 장애를 재현할 수 있어야 한다.

## 장애 재현 흐름

```
운영자 신고: "비밀번호 규칙을 물었는데 이상한 답변을 받았다"

1. 사용자에게 trace_id 확인 (응답 헤더 또는 UI에 표시)

2. RAG Agent 감사 로그 조회:
   WHERE trace_id = 'a1b2c3d4e5f6'
   → retrieved_doc_ids: ["doc-uuid-0001", "doc-uuid-0002"]
   → included_chunk_ids: ["chunk-uuid-0011", "chunk-uuid-0012"]
   → generation_status: "success"

3. DB에서 청크 내용 직접 조회 (운영자 권한):
   SELECT chunk_text, section_title, page_no
   FROM document_chunk
   WHERE chunk_id IN ('chunk-uuid-0011', 'chunk-uuid-0012')

4. DB에서 문서 정보 조회:
   SELECT original_filename, stored_path, parse_status
   FROM raw_document
   WHERE raw_document_id IN ('doc-uuid-0001', 'doc-uuid-0002')

5. LLM Gateway 운영 로그 조회:
   WHERE trace_id = 'a1b2c3d4e5f6'
   → model: "mistral-7b-instruct"
   → input_token_count: 1842
   → latency_ms: 2341

재현 가능한 정보:
  - 어떤 문서의 어느 청크가 검색됐는가 (doc_id + chunk_id로 DB 직접 조회)
  - 어떤 모델이 얼마나 빠르게 응답했는가
  - 토큰 한도로 제외된 청크가 있는가 (included vs retrieved 비교)
  - 검색 점수가 낮았는가
```

## trace_id가 전 계층에 있어야 하는 이유

```
동일 trace_id로 조회 가능한 정보:

Gateway 로그: 모델, 토큰, 지연, 오류
Agent 감사 로그: doc_id, chunk_id, 권한 범위, 생성 상태
HTTP 로그: 상태 코드, 요청 크기, 응답 크기
(향후) DB 감사 로그: 청크 조회 이력

→ 원문 없이도 "무슨 일이 있었는가"를 재구성 가능
```

---

# Part 5. 원문 로그가 꼭 필요한 경우의 예외 정책

원문(질문, 응답, 청크)을 로그에 남겨야 하는 상황이 존재한다.

## 허용 사례

| 사례 | 조건 |
|------|------|
| LLM 품질 평가 데이터셋 수집 | 사용자 동의 + 별도 저장소 + 접근 제한 |
| 심각한 보안 사고 조사 | 보안팀 + 법무팀 승인 + 임시 보존 |
| 파서/청킹 품질 검증 | 내부 테스트 데이터, 익명화 처리 |
| 프롬프트 A/B 테스트 | 동의 + 별도 저장소 + 보존 기간 제한 |

## 예외 허용 조건 (5가지 모두 충족)

```
1. 별도 보안 저장소
   - 운영 로그 시스템과 분리된 저장소 사용
   - 접근 권한: 보안팀 + 데이터팀 (운영팀 제외)

2. 마스킹 처리
   - 개인정보(이름, 이메일, 전화번호) 자동 탐지 후 마스킹
   - 문서 내 개인정보도 마스킹 대상

3. 짧은 보존 기간
   - 최대 30일 (기본 운영 로그 보존 기간과 분리)
   - 목적 달성 즉시 삭제

4. 접근 권한 통제
   - 접근 시 사유 기재 필수
   - 접근 이력 자동 기록

5. 예외 감사 추적
   - 누가, 언제, 왜 원문 저장을 활성화했는지 기록
   - 별도 승인 워크플로 필요
```

## 예외 활성화 메커니즘

원문 저장은 기본 비활성화 상태여야 한다.

```python
# 원문 로그는 명시적 활성화 + 목적 지정이 필요
class Settings:
    enable_raw_log: bool = False          # 기본값: 비활성화
    raw_log_purpose: str = ""             # 활성화 시 목적 필수 기재
    raw_log_store_path: str = ""          # 별도 저장소 경로
    raw_log_retention_days: int = 7       # 최대 30일
```

설정 파일이 아닌 **환경 변수**로만 활성화 가능하게 하여,
코드 배포 없이는 원문 로그를 켤 수 없도록 한다.

---

# Part 6. 로그 보존 정책

| 로그 종류 | 보존 기간 | 저장소 | 접근 권한 |
|----------|----------|--------|----------|
| Gateway 운영 로그 | 90일 | 운영 로그 시스템 | 운영팀, DevOps |
| Agent 감사 로그 | 1년 | 감사 로그 시스템 (분리) | 보안팀, 감사팀 |
| HTTP 접근 로그 | 30일 | 운영 로그 시스템 | 운영팀 |
| 원문 예외 로그 | 최대 30일 | 보안 저장소 (별도) | 보안팀만 |

감사 로그는 운영 로그와 **물리적으로 분리된 저장소**에 보관한다.
운영팀이 감사 로그를 삭제하거나 수정할 수 없어야 한다.

---

# Part 7. MVP 최소 구현 범위

PoC 단계에서는 구조만 올바르게 잡는다.
수집 시스템 자체는 단순하게 유지한다.

| 항목 | MVP 구현 | 비고 |
|------|----------|------|
| `trace_id` 생성 및 전파 | ✅ | UUID, 전 계층 전달 |
| Gateway 운영 로그 (구조화 JSON) | ✅ | 파일 또는 stdout |
| Agent 감사 로그 (구조화 JSON) | ✅ | 파일 또는 stdout |
| `anonymized_user_key` | ✅ | SHA-256(user_id + salt) |
| doc_id / chunk_id 기록 | ✅ | 감사 로그 핵심 |
| 원문 로그 비활성화 (기본값) | ✅ | 설정값으로 제어 |
| 로그 수집 시스템 (ELK, Loki 등) | ❌ | Phase 2 |
| 감사 로그 전용 저장소 분리 | ❌ | Phase 2 |
| 개인정보 자동 마스킹 | ❌ | Phase 2 |
| 대시보드 / 알림 | ❌ | Phase 2 |
| 원문 예외 로그 워크플로 | ❌ | Phase 3 |

---

# Part 8. 향후 운영 환경 확장 로드맵

## Phase 2: 로그 인프라 구축

- 구조화 로그 수집 (Loki + Grafana 또는 ELK)
- Gateway 운영 로그 → 대시보드 (토큰 사용량, 지연, 오류율)
- Agent 감사 로그 → 별도 저장소 (운영 로그와 분리)
- 이상 감지 알림 (error_rate, timeout_rate 임계치)

## Phase 3: 보안 강화

- `anonymized_user_key` 역매핑 테이블 (보안팀 전용 접근)
- 감사 로그 무결성 검증 (hash chain 또는 서명)
- 원문 예외 로그 승인 워크플로
- 개인정보 자동 탐지·마스킹 파이프라인

## Phase 4: 품질 분석

- 자주 인용되는 문서/청크 순위 (`citation_ids` 집계)
- 검색 실패 패턴 분석 (`empty_retrieval` 빈도별 접근 권한 분포)
- 에이전트별 토큰 비용 비교
- `top_score` 분포로 청킹·인덱싱 품질 평가
