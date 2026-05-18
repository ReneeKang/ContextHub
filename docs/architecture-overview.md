# ContextHub RAG MVP — Architecture Overview (운영 확장 관점)

## 문서 목적

`docs/architecture.md`가 구현 시점의 컴포넌트 구조도를 기술한다면,
이 문서는 **운영 확장 관점**에서 현재 MVP의 영역(Layer) 책임·데이터 저장소 흐름·
처리 흐름(workflow task)·설계 원칙·구현 상태를 한눈에 정리한 스냅샷이다.

- "지금 어디까지 와 있는가"
- "다음 한 사이클은 무엇인가"
- "어디를 키워야 운영형 시스템이 되는가"

이 세 질문에 답하는 것이 목표다.
세부 구현 변천사는 `docs/rag-troubleshooting-and-lessons.md`,
현재 진행 상황의 디테일은 `docs/backend-status.md`를 함께 참고한다.

> **용어 주의**: 본 문서에서 **Layer(영역)** 는 저장소 경계 · 책임 경계 · 인터페이스 경계가
> 있는 큰 단위에만 사용한다. scanner / parser / chunker / indexer / discover / generate는
> 각 영역 내부에서 돌아가는 **workflow task**이지 layer가 아니다. 용어 정의는 문서 끝의
> §8 용어 정리를 참고한다.

---

## 1. 데이터 저장소 기준 흐름

ContextHub의 데이터는 다음 저장소 사이를 단방향으로 흐른다.
저장소를 기준으로 보면 각 영역(Layer)이 어떤 데이터를 받고 어떤 데이터를 남기는지가
가장 명확해진다.

| 저장소 | 역할 | 저장 내용 |
|--------|------|-----------|
| **NAS / `local_nas/chatbot_docs`** | 원본 파일의 물리 저장소 | 원본 파일(txt/pdf/docx/xlsx/hwp/hwpx), 폴더 구조로 access scope 표현 |
| **PostgreSQL — `raw_document`** | 수집 메타·상태·권한의 Source of Truth | 파일 경로, sha256, `ingest_status`, `parse_status`, `chunk_status`, `access_scope`, `owner_id`, `department_code` |
| **PostgreSQL — `document_parse_result`** | 파싱 결과 저장소 | `markdown_text`, `blocks_json`, parser metadata (`metadata_json`) |
| **PostgreSQL — `document_chunk`** | 검색 준비 단위 저장소 | `chunk_text`, `section_title`, `heading_path`, `page_no`, 권한 메타(복사본), `index_status` |
| **OpenSearch — `contexthub_chunks`** | 서비스 검색용 projection | DB `document_chunk`에서 파생된 색인 문서, nori/BM25 + boost 필드 + 권한 필터 필드 |
| **LLM 백엔드** | (저장소 아님) Stateless Generation Engine | 상태 없음. `messages` + context chunks를 받아 `answer`만 반환 |

저장소 흐름을 도식화하면 다음과 같다.

```
NAS 원본 파일
   │
   ▼ (Source/Ingestion 영역)
PostgreSQL raw_document  ──┐
   │                       │
   ▼ (Document Transformation 영역)
PostgreSQL document_parse_result
   │
   ▼ (Search Index Preparation 영역)
PostgreSQL document_chunk  ──►  OpenSearch contexthub_chunks (projection)
   │                                          │
   └──────────────┬───────────────────────────┘
                  ▼ (Serving/RAG Application 영역)
            검색 → 문서 그룹핑 → 선택 → 컨텍스트 조립 → LLM 호출
                  │
                  ▼
            answer + sources[]

(Observability/Governance 영역은 위 모든 흐름의 메타데이터·상태·권한·로그를 가로지른다)
```

핵심 관찰: 저장소 간 전환은 **DB의 상태 컬럼으로 느슨하게 결합**되어 있다.
한 단계가 실패해도 다음 단계가 멈추지 않고, 운영자는 `ingest_status` / `parse_status` /
`chunk_status` / `index_status`만 보고 어디서 막혔는지 추적할 수 있다.

---

## 2. 영역(Layer)별 책임

각 Layer는 저장소 경계 · 책임 경계 · 인터페이스 경계를 가진다.
Layer 내부에서 돌아가는 세부 작업은 **workflow task**라고 부르며 §3에서 다룬다.

### 2.1 Source / Ingestion 영역

| 항목 | 내용 |
|------|------|
| **목적** | 외부 원본 파일을 시스템 내부의 신뢰 가능한 메타데이터로 끌어들인다. 권한(access scope)을 부여한다. |
| **입력 데이터** | NAS 폴더 구조 + 원본 파일(byte stream) |
| **출력 데이터** | `raw_document` 레코드 (파일 식별자, sha256, 경로, access_scope, owner_id, department_code, `ingest_status`) |
| **저장소** | (in) NAS `local_nas/chatbot_docs/{public\|dept/{code}\|private/{uid}}` (out) PostgreSQL `raw_document`, `raw_document_scan_state` |
| **내부 workflow task** | `scanner` (주기 폴링·mtime/size 안정화 판단·sha256 중복 감지·access_scope 태깅) |
| **다음 영역 인터페이스** | `raw_document.parse_status = PENDING` 상태 행 — Document Transformation 영역이 이를 폴링·픽업한다 |

### 2.2 Document Transformation 영역

| 항목 | 내용 |
|------|------|
| **목적** | 임의 포맷의 원본을 통일된 markdown 표현으로 변환한다. |
| **입력 데이터** | `raw_document` (parse_status=PENDING) + NAS 원본 파일 |
| **출력 데이터** | `document_parse_result` (markdown_text, blocks_json, metadata_json) + `raw_document.parse_status=DONE\|FAILED` + `parse_error_message` |
| **저장소** | (in) `raw_document`, NAS (out) PostgreSQL `document_parse_result` |
| **내부 workflow task** | `parser` workflow — `RoutingParser`가 확장자별 어댑터(`PlainTextParser`, `PdfPypdfParser`, `DocxParser`, `XlsxOpenpyxlParser`, `KordocCliParser`)에 위임 |
| **다음 영역 인터페이스** | `raw_document.chunk_status = PENDING` + `document_parse_result.markdown_text` 가 준비된 행 |

### 2.3 Search Index Preparation 영역

| 항목 | 내용 |
|------|------|
| **목적** | markdown 텍스트를 검색 가능한 단위로 분해하고, 권한·검색 메타를 enrichment해 검색 backend에 투영(projection)한다. |
| **입력 데이터** | `document_parse_result.markdown_text` + `raw_document`의 권한 메타 |
| **출력 데이터** | `document_chunk` 레코드 + OpenSearch `contexthub_chunks` 색인 문서 + `index_status=DONE\|FAILED` |
| **저장소** | (in) `document_parse_result`, `raw_document` (out) PostgreSQL `document_chunk`, OpenSearch `contexthub_chunks` |
| **내부 workflow task** | `chunker` (markdown → 의미 단위 청크 분리, 권한 메타 복사) → `indexer` (DB ready 전환 또는 OpenSearch bulk upsert) |
| **다음 영역 인터페이스** | 권한 필드(`access_scope`, `owner_id`, `department_code`)가 채워진 청크가 DB / OpenSearch 양쪽에서 조회 가능한 상태 |

> ⚠️ **chunking / indexing / search 품질**은 별도 영역이 아니라 이 영역 **내부의
> 반복 튜닝 사이클**이다. 자세한 내용은 §3.3을 참고한다.

### 2.4 Serving / RAG Application 영역

| 항목 | 내용 |
|------|------|
| **목적** | 사용자 질의를 받아 권한 필터·검색·문서 선택·컨텍스트 조립·LLM 호출까지 수행하고 최종 답변을 반환한다. |
| **입력 데이터** | 사용자 질의, `PermissionPrincipal`, (선택 시) `document_ids` |
| **출력 데이터** | `DocumentCandidate[]` (discover) 또는 `answer + sources[] + debug{}` (generate) |
| **저장소** | (in) OpenSearch `contexthub_chunks` 또는 DB `document_chunk` (out) 응답 JSON (영속 저장소 없음) |
| **내부 workflow task** | `query` (검색만) · `discover` (검색 + 문서 그룹핑 + post-processing) · `generate` (검색 + 컨텍스트 조립 + LLM 호출 + selected-document fallback) |
| **다음 영역 인터페이스** | HTTP API (`/api/v1/chat/query`, `/discover`, `/generate`) — POC UI 또는 외부 호출자가 소비 |

### 2.5 Observability / Governance 영역

| 항목 | 내용 |
|------|------|
| **목적** | 위 모든 영역을 가로질러 **상태 가시성·품질 진단·권한 enforcement·감사**를 제공한다. |
| **입력 데이터** | 단계별 상태 컬럼, retrieval 메타(`matched_fields`, `highlight_terms`, `document_rank`, `chunk_rank`, `score`, `retrieval_latency_ms`), LLM 호출 메타, 권한 정보 |
| **출력 데이터** | 구조화 로그, 응답 내 `debug{}` 객체, 운영용 reprocess API 응답, (계획) 감사 로그 |
| **저장소** | (cross-cutting) 로그 시스템 + 응답 페이로드. 권한 모델은 `raw_document` → `document_chunk` → OpenSearch 색인 문서로 전파된 access 필드를 참조 |
| **내부 workflow task** | retrieval debug 직렬화 (`app/chat/retrieval_debug.py`), 단계별 상태 컬럼 갱신, `/admin/documents/{id}/reprocess`, `PermissionPrincipal` 산출 및 쿼리 필터 enforcement |
| **다음 영역 인터페이스** | (1) 운영자 쪽: 로그/대시보드/관리 API (2) 다른 영역 쪽: 쿼리에 주입되는 **Retrieval Filter Interface**, 즉 `PermissionPrincipal` → backend별 filter 절 |

### 2.6 영역 경계 원칙

- **chat-api는 파서 종류를 모른다.** 파서 교체는 Document Transformation 영역 안에서만.
- **chat-api는 검색 백엔드 종류를 모른다.** `SearchClient` 인터페이스 뒤에 DB / OpenSearch가 숨는다.
- **LLM 호출자는 백엔드 종류를 모른다.** `LLMClient.complete`만 본다.
- **권한은 Governance가 책임진다.** Serving 영역은 `PermissionPrincipal`만 신뢰하고 backend별 필터 변환은 어댑터가 한다.

영역 경계가 흐려지면 운영 중 교체 비용이 폭증한다. 현재는 이 경계가 비교적 깔끔하게 유지되고 있다.

---

## 3. 처리 흐름 (Workflow Tasks)

아래 항목들은 모두 **layer가 아니라 workflow task**다. 각 task가 어느 영역에 속하는지,
어떤 상태 컬럼으로 다음 task에 신호를 넘기는지가 운영 추적의 핵심이다.

### 3.1 데이터 입력 측 workflow task

| Workflow task | 소속 영역 | 트리거 / 상태 신호 | 산출물 |
|---------------|-----------|--------------------|--------|
| **scanner** | Source/Ingestion | 주기 폴링 + mtime/size 안정화 + sha256 중복 감지 → `raw_document.ingest_status=RECEIVED\|DUPLICATE\|FAILED` | `raw_document` 신규/갱신 행 |
| **parser** | Document Transformation | `raw_document.parse_status=PENDING` 픽업 → `RoutingParser`로 어댑터 분기 → `parse_status=DONE\|FAILED` | `document_parse_result` + (실패 시) `parse_error_message` |
| **chunker** | Search Index Preparation | `raw_document.chunk_status=PENDING` 픽업 → markdown → 청크 분리 + 권한 메타 복사 → `chunk_status=DONE\|FAILED` | `document_chunk` rows (각 row `index_status=PENDING`) |
| **indexer** | Search Index Preparation | `document_chunk.index_status=PENDING` 픽업 → DB ready 전환 또는 OpenSearch bulk → `index_status=DONE\|FAILED` | OpenSearch projection 갱신 |

### 3.2 서빙 측 workflow task

| Workflow task | 소속 영역 | 입력 | 산출물 |
|---------------|-----------|------|--------|
| **discover** | Serving/RAG Application | `{ question, top_k, principal }` | `DocumentCandidate[]` (문서 단위, 본문 제외) |
| **generate** | Serving/RAG Application | `{ question, document_ids, principal }` | `answer + sources[] + debug{}` |

`discover`는 내부적으로 `chunk_fetch_size = max(top_k × 10, 50)` over-fetch → `raw_document_id` 그룹핑
→ 상대 점수 + highlight 후처리 필터를 거친다.
`generate`는 권한 필터 검색 + `document_ids` 한정 → 히트 0 시 selected-document DB fallback →
`build_nas_rag_user_prompt` → `LLMClient.complete` 흐름이다.

### 3.3 검색 품질 개선 사이클 (Search Index Preparation 영역 내부)

이 사이클은 별개 layer가 아니라 **하나의 영역 내부에서 서로 영향을 주는 튜닝 변수들**이다.
한 변수만 건드리면 다른 변수에서 회귀가 발생하므로 항상 묶어서 관리한다.

```
   ┌── chunking policy (크기/오버랩/heading 보존)
   │
   ▼
   chunk metadata (section_title, heading_path, page_no, access_scope, …)
   │
   ▼
   OpenSearch mapping (nori 분석기, keyword 필드, boost 대상 필드)
   │
   ▼
   BM25 / nori 토크나이제이션
   │
   ▼
   metadata boost (title/section/heading 가중)
   │
   ▼
   filtering / ranking (권한 필터 + 상대 점수 + highlight 후처리)
   │
   ▼
   reranking (계획: cross-encoder)
   │
   └─► (피드백) chunking policy로 되돌아옴
```

운영 원칙: **한 사이클의 변경은 한 PR에서 묶어서**.
mapping을 바꾸면 indexing을 다시 돌려야 하고, chunking을 바꾸면 mapping의 boost 가중치가 무의미해질 수 있다.

### 3.4 운영용 workflow task

- `POST /admin/documents/{id}/reprocess` — 특정 stage(parse / chunk / index)를 `PENDING`으로 리셋
- (개발 전용) `opensearch_reset_dev` — 인덱스 drop 후 전체 재색인. **운영 환경에서는 사용 금지.**

---

## 4. 주요 설계 원칙

### 4.1 Postgres는 Source of Truth

`raw_document` / `document_parse_result` / `document_chunk`가 진실의 출처다.
OpenSearch는 언제든 재생성 가능한 **search projection**이다.
인덱스 매핑이 바뀌면 DB 기반 전체 재색인으로 복구한다 (운영은 alias switch로, §5 참고).

### 4.2 OpenSearch는 Search Projection

OpenSearch에 들어간 값은 모두 DB에서 파생된다.
"OpenSearch에는 있는데 DB에는 없는" 상태는 발생하지 않는다.
이 원칙 덕분에 매핑 변경·alias 전환·인덱스 분리 같은 운영 변경이 데이터 손실 없이 가능하다.

### 4.3 LLM은 Stateless Generation Engine

ContextHub의 LLM은 메모리·세션·툴콜을 갖지 않는다.
입력: `messages` + context chunks. 출력: `answer` 문자열.
대화 상태는 클라이언트(POC UI 또는 미래의 호출자)가 들고 있다.
이 덕분에 mock ↔ openai_compat ↔ internal_* 교체가 무중단으로 이뤄진다.

### 4.4 Parser는 Adapter 구조

`RoutingParser`가 확장자별로 분기해 동일한 `ParseResult` 인터페이스를 반환한다.
- txt/md → `PlainTextParser`
- pdf → `PdfPypdfParser`
- docx → `DocxParser`
- xlsx → `XlsxOpenpyxlParser`
- hwp/hwpx → `KordocCliParser`

새 포맷 추가의 영향 범위는 **parser 패키지 하나**로 제한된다.

### 4.5 Retrieval과 Generation은 분리

`/query`(retrieval only) / `/discover`(retrieval + document grouping) / `/generate`(retrieval + LLM).
"검색 품질이 나쁜가, LLM 품질이 나쁜가"를 격리해서 진단할 수 있다.
이 분리는 운영 중 품질 회귀를 디버깅할 때 가장 자주 사용된다.

### 4.6 Debug / Observability는 품질 개선의 필수 요소

`matched_fields`, `highlight_terms`, `document_rank`, `chunk_rank`, `score`,
`retrieval_latency_ms`가 응답·로그에 노출된다.
"왜 이 문서가 나왔는가"를 설명할 수 없으면 boost 튜닝은 감(感)이 된다.

---

## 5. 인덱스 라이프사이클 (Index Loading / Reindex / Delete 전략)

OpenSearch는 projection이므로, 인덱스 운영은 **DB 상태를 기준으로 한 재생성/동기화** 관점에서 본다.

### 5.1 신규 문서 추가

- scanner → parser → chunker → indexer를 따라 `document_chunk` row 생성 시 `index_status=PENDING`.
- indexer가 `_id = chunk_id` 기준으로 **upsert**한다. 동일 chunk_id 재인덱스는 멱등(idempotent).

### 5.2 변경 문서 감지

- 파일 갱신이 감지되면(향후 §6.2 작업) 신규 sha256으로 새 `raw_document` 행을 발급한다.
- 정책: **versioning** 또는 **reprocess**
  - versioning: 기존 raw_document를 supersede 마크로 두고 새 row가 살아 있는 버전을 가진다. 검색은 살아있는 버전만 노출.
  - reprocess: 동일 `raw_document_id`에 대해 parse / chunk / index를 다시 돌린다 (`reprocess` API 사용).
- 변경 detection이 없는 현재 MVP에서는 사실상 수동 reprocess로만 변경이 반영된다.

### 5.3 삭제 문서

- **Soft delete** 원칙: `raw_document.excluded=true` 마크 → `document_chunk` 후속 처리 → OpenSearch에서는 해당 `_id`들을 명시적으로 `delete`로 반영.
- DB에서 row를 물리 삭제하지 않는 이유: 감사·복구·디버깅을 위해 이력이 필요.

### 5.4 전체 재색인 (Reindex)

운영 환경에서는 **기존 인덱스 drop 방식을 사용하지 않는다.** 다음과 같이 한다.

1. 새 인덱스 `contexthub_chunks_v{n+1}` 를 새 매핑으로 생성.
2. DB `document_chunk` 전체를 새 인덱스로 bulk 색인.
3. 색인 완료 검증 (count, sampling 쿼리).
4. **Alias `contexthub_chunks` 를 v{n} → v{n+1}로 swap.**
5. v{n} 인덱스는 일정 기간 유지 후 회수.

이 방식은 매핑 변경 중에도 검색 다운타임이 0이다.

### 5.5 개발 환경 전용: `opensearch_reset_dev`

- 인덱스를 drop하고 DB 기반으로 한 번에 재색인하는 **개발 전용** 스크립트.
- 검색 다운타임이 발생하므로 **운영 환경에서는 절대 사용하지 않는다.**

---

## 6. 권한 모델 (Governance 영역과 Retrieval Filter Interface)

권한은 UI 라벨이 아니라 데이터 파이프라인 전 구간에 흐르는 메타데이터다.

### 6.1 권한 전파 흐름

```
[Ingestion] 폴더 경로에서 access_scope / owner_id / department_code 추출
       │       (public / dept/{code} / private/{uid})
       ▼
raw_document.access_scope = …            (Source of Truth)
       │
       ▼
[Chunking] document_chunk에 권한 메타 복사 (스냅샷, 일관성 보장)
       │
       ▼
[Indexing] OpenSearch 색인 문서에도 동일 필드 매핑 (검색 필터 키)
       │
       ▼
[Serving] PermissionPrincipal 기반 query filter 절 주입
          (DB backend / OpenSearch backend 양쪽 동일 의미로 변환)
```

### 6.2 Retrieval Filter Interface

- Serving 영역은 `PermissionPrincipal` (user_id + department_codes 등)만 안다.
- 각 검색 backend 어댑터(`app/adapters/db_chunk_search.py`, `app/adapters/opensearch_payload.py`)가 principal을 backend의 필터 표현(SQL where / OpenSearch bool filter)으로 번역한다.
- 이 변환 경계가 **Retrieval Filter Interface**다. 새 backend가 들어와도 이 인터페이스만 구현하면 권한이 자동 적용된다.

### 6.3 현재 한계: Trust Boundary

권한 enforcement 자체는 양쪽 backend에 들어가 있지만, **trust boundary가 닫혀 있지 않다.**

- 실제 사용자 인증(JWT/세션)이 연결되어 있지 않다.
- `PermissionPrincipal`은 현재 요청 바디의 `test_department_codes`에서 만들어지는 stub이다.
- `user_id`는 `"stub-user"` 하드코딩.
- 결과적으로 **클라이언트가 자신의 권한을 임의 선언 가능**한 상태다.

즉, "내부 필터링 로직은 살아 있는데 외부 신뢰 입구가 비어 있다"가 현재의 정확한 상태다.
이 부분은 §7.1에서 다룬다.

---

## 7. 현재 구현 상태

### 7.1 완료 (✅ Done)

| 영역 | 항목 | 위치 |
|------|------|------|
| Source/Ingestion | NAS 스캐너, 파일 안정화, sha256 중복 감지 | `app/scanner/service.py` |
| Source/Ingestion | access_scope/owner_id/department_code 경로 추출 | `app/scanner/permissions.py` |
| Document Transformation | RoutingParser + txt/md/pdf/docx/xlsx/hwp/hwpx | `app/parser/`, `app/adapters/parser_*` |
| Document Transformation | `parse_error_message` 기록 | `raw_document` |
| Search Index Preparation | markdown 기반 청크 분리, 권한 메타 복사 | `app/chunker/service.py` |
| Search Index Preparation | DB / OpenSearch 양쪽 indexer 백엔드 | `app/indexer/service.py`, `app/adapters/opensearch_*` |
| Search Index Preparation | OpenSearch 매핑 (nori + keyword + boost 필드) | `app/adapters/opensearch_index_mapping.py` |
| Serving/RAG | `/query`, `/discover`, `/generate` 분리 엔드포인트 | `app/chat/router.py` |
| Serving/RAG | chunk over-fetch + 문서 그룹핑 | `app/chat/discovery_service.py` |
| Serving/RAG | 상대점수 + highlight 기반 post-processing 필터 | 동상 |
| Serving/RAG | NAS RAG 프롬프트 조립 | `app/agents/nas_rag.py` |
| Serving/RAG | selected-document DB fallback | `app/chat/selected_document_fallback.py` |
| Serving/RAG | LLM: mock / openai_compat 실연동 (Bearer 옵션, timeout) | `app/llm/backend.py`, `app/llm/openai_compat.py` |
| Governance | 권한 필터 메커니즘 (DB + OpenSearch 양쪽) | `app/adapters/db_chunk_search.py`, `app/adapters/opensearch_payload.py` |
| Observability | 구조화 retrieval 로그 + `debug` 객체 노출 | `app/chat/retrieval_debug.py` |
| Observability | 단계별 상태 컬럼 (ingest/parse/chunk/index_status) | `raw_document`, `document_chunk` |
| Observability | reprocess API (stage 단위 PENDING 리셋) | `/admin/documents/{id}/reprocess` |
| UI | POC UI: discover → 선택 → generate 흐름, debug 패널, IME 처리 | `app/static/`, `main.js`, `render.js` |
| Quality | NFC normalization (scanner/parser/indexer/query 전 구간) | §23 lessons |

### 7.2 부분 완료 (🟡 Partial)

| 영역 | 현재 상태 | 부족한 부분 |
|------|-----------|-------------|
| **Governance (Access control)** | 권한 필터는 양쪽 백엔드에 들어가 있음 | `PermissionPrincipal`이 요청 바디(`test_department_codes`)의 stub. 인증 토큰/세션 연동 없음. trust boundary 미완성 |
| **Search Index Preparation (Reindex 운영)** | dev: 인덱스 drop + 전체 재색인 스크립트 | 운영용 alias 기반 무중단 전환 전략 미구현 |
| **Source/Ingestion · Transformation (Reprocess 운영)** | API 단건 호출은 가능 | 일괄 reprocess UI / FAILED 자동 분류 / 재시도 정책 없음 |
| **Search Index Preparation (Indexer batch)** | `INDEXER_BATCH_SIZE` 환경변수 노출 | 동적 조정·실패 시 batch 분할·백프레셔 없음 |
| **Observability (Generation 가시성)** | `llm_user_message_char_count`, `generation_context_chunks` preview 노출 | LLM latency / token usage / cost 메트릭 없음 |

### 7.3 미구현 (⛔ Not yet)

| 영역 | 메모 |
|------|------|
| **Governance: 실제 인증** | JWT/세션 → `PermissionPrincipal` 변환 |
| **Observability: 감사 로그** | 누가 어떤 문서를 조회/생성했는지 추적 |
| **Source/Ingestion: File change detection** | 파일 갱신·삭제 감지 (현재는 신규 파일만 안정 처리) |
| **Search Index Preparation: Vector / Hybrid search** | 임베딩 색인 + BM25 ⊕ vector ranking |
| **Search Index Preparation: Reranker** | cross-encoder 기반 query-doc 재정렬 |
| **Serving/RAG: Document-scoped chat** | 선택 문서 내 멀티턴 대화·후속 질의 |
| **Serving/RAG: Source viewer** | chunk → 원본 파일 위치(page/line) 시각화 |
| **Observability: Monitoring** | latency/throughput/error rate 대시보드, 알림 |
| **Serving/RAG: Streaming** | `/generate` SSE 스트리밍 응답 |
| **Serving/RAG: LLM 안정성** | 재시도·서킷 브레이커·모델 폴백 |

---

## 8. 용어 정리

본 문서에서 사용하는 용어는 정확하게 다음 의미로 쓴다.

| 용어 | 정의 |
|------|------|
| **Layer (영역)** | 저장소 경계 · 책임 경계 · 인터페이스 경계를 모두 가진 큰 단위. 본 문서의 5개 영역(Source/Ingestion, Document Transformation, Search Index Preparation, Serving/RAG Application, Observability/Governance)이 여기에 해당한다. |
| **Workflow task** | 한 Layer 내부에서 돌아가는 실행 단위. 상태 컬럼으로 트리거되고 다음 task에 신호를 넘긴다. 예: scanner, parser, chunker, indexer, discover, generate. Layer가 아니다. |
| **Interface** | 한 Layer가 다음 Layer에 데이터/제어를 넘기는 계약. 보통 DB의 상태 컬럼(예: `parse_status=PENDING`), HTTP API, 또는 어댑터 인터페이스(`SearchClient`, `LLMClient`)의 형태를 띤다. |
| **Source of Truth** | 데이터의 권위 있는 원본. ContextHub에서는 PostgreSQL의 `raw_document` / `document_parse_result` / `document_chunk` 가 해당한다. 분쟁 시 이쪽 값이 이긴다. |
| **Projection** | Source of Truth로부터 파생된, 다른 목적(주로 검색)으로 최적화된 사본. ContextHub에서는 OpenSearch `contexthub_chunks`가 projection이다. 잃어버려도 DB로부터 재생성 가능하다. |
| **Reindex** | 기존 projection을 새 매핑/새 분석 설정으로 다시 만드는 작업. 운영에서는 새 인덱스 생성 + alias switch로 한다. |
| **Alias switch** | 검색 클라이언트가 보는 논리 이름(alias)을 새 물리 인덱스로 원자적으로 전환하는 방식. 무중단 reindex의 핵심. |
| **Soft delete** | 물리 삭제 대신 `excluded=true` 같은 마크로 논리적 삭제만 수행하는 패턴. DB에는 이력이 남고, projection(OpenSearch)에서는 해당 문서를 제거한다. |
| **Metadata enrichment** | 원본 데이터에 검색·권한·정렬용 메타데이터(예: section_title, heading_path, access_scope)를 부착해 검색 품질·필터 능력을 강화하는 과정. Search Index Preparation 영역에서 주로 일어난다. |

---

## 관련 문서

- `docs/architecture.md` — 컴포넌트 구조도, DB 간접 연동 원칙
- `docs/backend-status.md` — 현재 구현 상태 스냅샷 (디테일)
- `docs/db-schema.md` — 테이블·상태 컬럼 정의
- `docs/search-index.md` — OpenSearch 매핑 + 권한 필터 쿼리
- `docs/document-discovery.md` — discover 분리 철학, post-processing
- `docs/parser-kordoc.md` — parser adapter 구조와 kordoc 호출 경계
- `docs/document-versioning.md` — 문서 버전 관리 전략
- `docs/rag-troubleshooting-and-lessons.md` — 구축 운영 일지 (§1~§23)
