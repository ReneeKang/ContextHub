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
| **PostgreSQL — `document_chunk`** | 검색 준비 단위 저장소 (Silver) | `chunk_text`, `section_title`, `heading_path`, `page_no`, 권한 메타(복사본), `index_status` |
| **OpenSearch — `contexthub_chunks`** | 서비스 검색용 projection (Gold) | DB `document_chunk`에서 파생된 색인 문서, nori/BM25 + boost 필드 + 권한 필터 필드 |
| **LLM 백엔드** | (저장소 아님) Stateless Generation Engine | 상태 없음. `messages` + context chunks를 받아 `answer`만 반환 |

저장소 흐름을 도식화하면 다음과 같다.

```
NAS 원본 파일
   │
   ▼ (Source/Ingestion 영역)
PostgreSQL raw_document
   │
   ▼ (Document Transformation 영역)
PostgreSQL document_parse_result
   │
   ▼ (Search Preparation 영역)          ← chunk 단위 재구성 / metadata 생성
PostgreSQL document_chunk  ──────────────────────────────────┐
   │                                                         │ (selected-document DB fallback)
   ▼ (Search Serving Index 영역)                            │
OpenSearch contexthub_chunks  [future: Vector DB]            │
   │                                                         │
   └──────────────────────┬──────────────────────────────────┘
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

#### 파싱 핵심 구조 요소

파서가 생성하는 `blocks_json` / `metadata_json`에는 다음 구조 요소들이 포함된다.
이 요소들의 추출 품질이 이후 chunk metadata의 정확도와 검색 품질의 상한선을 결정한다.

| 구조 요소 | 역할 | chunk metadata / 검색 품질 영향 |
|-----------|------|----------------------------------|
| **OCR** | 이미지·스캔 PDF의 텍스트를 추출한다. 레이아웃 인식 수준에 따라 텍스트 순서와 표 경계가 달라진다. | OCR 오류는 `chunk_text`에 그대로 전파되어 BM25 토큰 매칭률을 낮춘다. OCR 품질이 검색 리콜(recall)의 하한선이다. |
| **page** | 원본 문서의 페이지 번호 또는 페이지 경계 정보. | `page_no` 필드로 chunk에 기록된다. 멀티 페이지 문서에서 chunk 위치를 특정하는 유일한 좌표이며, 소스 뷰어(미래)에서 원본 위치 추적에 쓰인다. |
| **heading** | 마크다운 `#` / docx 스타일 / PDF 폰트 크기 기반 제목 감지. | `heading_path`(예: `§1 > §1.2 > §1.2.1`)로 chunk에 기록된다. BM25 boost 필드로서 질의 키워드와 제목이 일치할 때 가중치를 받는다. heading 추출이 부정확하면 `heading_path`가 무너지고 boost 효과가 사라진다. |
| **section** | heading으로 구분된 문서 내 의미 단위. | `section_title` 필드로 chunk에 기록된다. chunking policy에서 section 경계를 청크 분리 기준으로 삼을 수 있다. section이 잘못 분리되면 하나의 의미 단위가 여러 청크에 쪼개져 검색 정밀도(precision)가 낮아진다. |
| **layout** | 문단·열·박스 구조 등 공간적 배치 정보. | 다단 레이아웃에서 텍스트 읽기 순서가 뒤섞이는 것을 방지한다. layout 인식 실패 시 `chunk_text`에 무관한 텍스트가 섞여 BM25 노이즈가 증가한다. |
| **table** | 행/열 구조를 가진 데이터 영역 감지. | 표를 일반 텍스트로 직렬화하면 행·열 관계가 소실된다. table-aware chunking(후보)에서는 표를 별도 청크로 처리하거나 요약 텍스트로 변환해 검색 가능성을 높인다. 현재는 markdown 표 형식으로 직렬화. |

### 2.3 Search Preparation 영역

| 항목 | 내용 |
|------|------|
| **목적** | 변환된 문서를 검색 가능한 chunk와 metadata로 재구성한다. |
| **입력 데이터** | `document_parse_result.markdown_text` / structured text / parser metadata (`metadata_json`) + `raw_document` 권한 메타 |
| **출력 데이터** | `document_chunk` 레코드 (`chunk_text`, `section_title`, `heading_path`, `page_no`, `sheet_name`, 권한 메타 복사본, `index_status=PENDING`), `raw_document.chunk_status=DONE\|FAILED` |
| **저장소** | (in) `document_parse_result`, `raw_document` (out) PostgreSQL `document_chunk` |
| **내부 workflow task** | `chunker` — chunking policy 적용, section_title / heading_path / page_no / sheet_name 등 chunk metadata 생성, 권한 메타 복사, metadata enrichment, (후보) table-aware chunking, (후보) embedding input text 생성 |
| **다음 영역 인터페이스** | `document_chunk.index_status = PENDING` — Search Serving Index 영역이 이를 픽업한다 |

> **Silver 레이어**: `document_chunk`는 원본 문서의 모든 검색 단위를 구조화된 형태로 보관하는
> Source of Truth다. OpenSearch가 날아가도 이 레이어에서 완전 재생성이 가능하다.

### 2.4 Search Serving Index 영역

| 항목 | 내용 |
|------|------|
| **목적** | 서비스 검색을 위한 search projection을 생성·유지한다. |
| **입력 데이터** | `document_chunk` (index_status=PENDING) + chunk metadata |
| **출력 데이터** | OpenSearch `contexthub_chunks` 색인 문서, `document_chunk.index_status=DONE\|FAILED`. (future) Vector DB index |
| **저장소** | (in) PostgreSQL `document_chunk` (out) OpenSearch `contexthub_chunks`, (future) Vector DB |
| **내부 workflow task** | `indexer` — OpenSearch mapping 관리 (BM25/nori analyzer 설정, keyword 필드), filename/path/section_title/heading_path boost 적용, bulk upsert (chunk_id 기준 멱등), soft delete 반영, alias switch 기반 무중단 reindex, (future) vector index loading |
| **다음 영역 인터페이스** | 권한 필드(`access_scope`, `owner_id`, `department_code`)가 채워진 색인 문서가 OpenSearch에서 조회 가능한 상태 |

> **Gold 레이어**: OpenSearch는 `document_chunk`로부터 파생된 검색 최적화 projection이다.
> 매핑 변경·analyzer 교체·boost 튜닝이 이 레이어 안에서만 일어나며,
> 언제든 `document_chunk` 기반 전체 재색인으로 복구 가능하다.

### 2.5 Serving / RAG Application 영역

| 항목 | 내용 |
|------|------|
| **목적** | 사용자 질의를 받아 권한 필터·검색·문서 선택·컨텍스트 조립·LLM 호출까지 수행하고 최종 답변을 반환한다. |
| **입력 데이터** | 사용자 질의, `PermissionPrincipal`, (선택 시) `document_ids` |
| **출력 데이터** | `DocumentCandidate[]` (discover) 또는 `answer + sources[] + debug{}` (generate) |
| **저장소** | (in) OpenSearch `contexthub_chunks` 또는 DB `document_chunk` (selected-document fallback) (out) 응답 JSON (영속 저장소 없음) |
| **내부 workflow task** | `query` (검색만) · `discover` (검색 + 문서 그룹핑 + post-processing) · `generate` (검색 + 컨텍스트 조립 + LLM 호출 + selected-document fallback) |
| **다음 영역 인터페이스** | HTTP API (`/api/v1/chat/query`, `/discover`, `/generate`) — POC UI 또는 외부 호출자가 소비 |

### 2.6 Observability / Governance 영역

| 항목 | 내용 |
|------|------|
| **목적** | 위 모든 영역을 가로질러 **상태 가시성·품질 진단·권한 enforcement·감사**를 제공한다. |
| **입력 데이터** | 단계별 상태 컬럼, retrieval 메타(`matched_fields`, `highlight_terms`, `document_rank`, `chunk_rank`, `score`, `retrieval_latency_ms`), LLM 호출 메타, 권한 정보 |
| **출력 데이터** | 구조화 로그, 응답 내 `debug{}` 객체, 운영용 reprocess API 응답, (계획) 감사 로그 |
| **저장소** | (cross-cutting) 로그 시스템 + 응답 페이로드. 권한 모델은 `raw_document` → `document_chunk` → OpenSearch 색인 문서로 전파된 access 필드를 참조 |
| **내부 workflow task** | retrieval debug 직렬화 (`app/chat/retrieval_debug.py`), 단계별 상태 컬럼 갱신, `/admin/documents/{id}/reprocess`, `PermissionPrincipal` 산출 및 쿼리 필터 enforcement |
| **다음 영역 인터페이스** | (1) 운영자 쪽: 로그/대시보드/관리 API (2) 다른 영역 쪽: 쿼리에 주입되는 **Retrieval Filter Interface**, 즉 `PermissionPrincipal` → backend별 filter 절 |

### 2.7 영역 경계 원칙

- **chat-api는 파서 종류를 모른다.** 파서 교체는 Document Transformation 영역 안에서만.
- **chat-api는 검색 백엔드 종류를 모른다.** `SearchClient` 인터페이스 뒤에 DB / OpenSearch가 숨는다.
- **LLM 호출자는 백엔드 종류를 모른다.** `LLMClient.complete`만 본다.
- **권한은 Governance가 책임진다.** Serving 영역은 `PermissionPrincipal`만 신뢰하고 backend별 필터 변환은 어댑터가 한다.
- **Search Preparation과 Search Serving Index는 분리된다.** chunking 정책 변경은 Search Preparation 안에서, analyzer·boost·mapping 변경은 Search Serving Index 안에서. 두 영역을 동시에 바꾸면 한 PR에서 묶어서 관리한다.

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
| **chunker** | Search Preparation | `raw_document.chunk_status=PENDING` 픽업 → markdown → 청크 분리 + metadata 생성 + 권한 메타 복사 → `chunk_status=DONE\|FAILED` | `document_chunk` rows (각 row `index_status=PENDING`) |
| **indexer** | Search Serving Index | `document_chunk.index_status=PENDING` 픽업 → OpenSearch bulk upsert → `index_status=DONE\|FAILED` | OpenSearch projection 갱신 |

### 3.2 서빙 측 workflow task

| Workflow task | 소속 영역 | 입력 | 산출물 |
|---------------|-----------|------|--------|
| **discover** | Serving/RAG Application | `{ question, top_k, principal }` | `DocumentCandidate[]` (문서 단위, 본문 제외) |
| **generate** | Serving/RAG Application | `{ question, document_ids, principal }` | `answer + sources[] + debug{}` |

`discover`는 내부적으로 `chunk_fetch_size = max(top_k × 10, 50)` over-fetch → `raw_document_id` 그룹핑
→ 상대 점수 + highlight 후처리 필터를 거친다.
`generate`는 권한 필터 검색 + `document_ids` 한정 → 히트 0 시 selected-document DB fallback →
`build_nas_rag_user_prompt` → `LLMClient.complete` 흐름이다.

### 3.3 검색 품질 튜닝 사이클

이 사이클은 Search Preparation 영역과 Search Serving Index 영역에 **걸쳐** 있다.
한 변수만 건드리면 다른 변수에서 회귀가 발생하므로 항상 묶어서 관리한다.

```
   ┌── chunking policy (크기/오버랩/heading 보존)           ← Search Preparation
   │
   ▼
   chunk metadata (section_title, heading_path, page_no, access_scope, …)
   │
   ▼
   OpenSearch mapping (nori 분석기, keyword 필드, boost 대상 필드)  ← Search Serving Index
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

#### chunking policy가 바뀌면 BM25 score가 바뀌는 이유

BM25는 "문서 내 용어 빈도 / 문서 길이" 비율로 점수를 계산한다. chunk가 검색에서의 "문서"다.

- **청크가 크면**: 한 청크에 여러 토픽의 용어가 섞이고 문서 길이가 길어진다. BM25는 긴 문서에 패널티를 주므로(IDF × TF/문서길이) 특정 키워드의 score가 희석된다.
- **청크가 작으면**: 키워드 집중도는 높아지지만, 문맥이 잘려 질의와 연관된 청크가 분산된다. 동일 의미 단위가 여러 청크로 쪼개지면 각 청크의 score가 낮아져 top-k에서 탈락한다.
- **heading 보존 여부**: heading 텍스트를 청크에 포함시키면 해당 용어가 chunk_text 안에 존재하므로 BM25 매칭 기회가 늘어난다. 제거하면 heading_path boost만으로만 검색할 수 있다.
- **오버랩**: 오버랩이 있으면 동일 텍스트가 여러 청크에 등장해 score 중복이 생긴다. 문서 그룹핑(discover) 단계에서 중복 제거를 고려해야 한다.

chunking policy를 바꾸면 **모든 문서를 다시 chunk → index**해야 하며, 바뀐 평균 청크 길이에 맞춰 boost 가중치도 재조정해야 한다.

#### metadata field가 바뀌면 검색 결과가 바뀌는 이유

OpenSearch는 `multi_match` 쿼리로 여러 필드를 동시에 검색하고, 필드별 boost를 곱한 값을 최종 score에 반영한다. 따라서:

- **필드가 추가되면**: 새 필드가 매칭에 참여해 score 분포가 바뀐다. 기존 튜닝된 top-k 경계가 움직인다.
- **필드가 삭제되면**: 그 필드에만 있던 용어는 더 이상 매칭되지 않는다. recall이 떨어진다.
- **필드 값이 변경되면**: 예를 들어 `section_title`을 더 정확하게 추출하면 boost가 올바른 청크에 집중되어 precision이 올라간다. 반대로 오염된 값이 들어가면 노이즈가 증가한다.
- **필드 analyzer가 바뀌면**: 동일 텍스트라도 토크나이제이션 결과가 달라져 매칭 여부 자체가 바뀐다.

metadata field 변경은 항상 **전체 재색인**을 동반한다. 스키마 변경 없이 OpenSearch 문서만 업데이트하면 기존 문서와 신규 문서의 필드 구조가 불일치한다.

#### heading_path, section_title, filename, path가 검색에 쓰이는 방식

```
질의: "연차 사용 기준"

multi_match 대상 필드:
  chunk_text          (boost 1.0)  ← 본문 텍스트
  section_title       (boost 3.0)  ← 해당 청크가 속한 절의 제목
  heading_path        (boost 2.0)  ← 상위 제목 계층 전체 (§1 > §1.2 > ...)
  filename            (boost 2.0)  ← 파일명 (예: "연차휴가_규정.pdf")
  path                (boost 1.5)  ← 폴더 경로 (예: "인사팀/규정집/...")
```

- `section_title`과 `heading_path`는 **문서 내 위치 신호**다. chunk_text에 키워드가 없어도 제목 계층에 키워드가 있으면 검색된다. 예: "연차 사용 기준"이라는 절 아래에 구체적인 규정만 있는 청크는 chunk_text에 "연차"가 없어도 `section_title` boost로 상위 순위를 받는다.
- `filename`과 `path`는 **문서 출처 신호**다. 파일명에 핵심 키워드가 있는 경우 — 예: "연차휴가_규정.pdf" — 해당 파일의 모든 청크가 boost를 받는다. 이 효과는 discover 단계의 문서 그룹핑과 결합해 "올바른 문서"를 상위로 끌어올리는 데 기여한다.
- `heading_path`는 계층 전체 경로를 하나의 문자열로 저장하므로 상위 제목 키워드도 매칭된다. `section_title`은 현재 절 제목만이므로 두 필드는 상호 보완 관계다.

#### chunk_text만으로 검색하면 안 되는 이유

chunk_text 단독 검색은 다음 한계를 가진다.

1. **제목 없는 본문 청크**: 규정·지침 문서에서 실제 내용은 "1. 목적에 의거하여 …"처럼 본문에만 있고 핵심 키워드는 절 제목에 있다. chunk_text만 보면 해당 청크가 "연차 규정"에 관한 것인지 알 수 없다.
2. **파일명 신호 손실**: "급여명세서_양식.xlsx" 파일의 청크에는 "급여명세서"라는 단어가 본문에 없을 수 있다. filename boost 없이는 이 파일을 찾을 수 없다.
3. **동음이의어 분산**: 동일 개념이 다른 표현으로 청크마다 흩어져 있을 때, heading_path가 상위 개념 키워드를 모아 주는 역할을 한다.
4. **짧은 청크의 BM25 불안정성**: 작은 청크는 TF가 1~2에 불과해 score 변동이 크다. 제목 필드 boost는 score를 안정시키는 앵커 역할을 한다.
5. **권한 필터 외의 랭킹 신호 부재**: 동일 권한 범위에서 여러 문서가 매칭될 때, 파일명·경로가 없으면 어느 문서가 더 "관련 있는 출처"인지 구분할 수 없다.

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
이 섹션의 모든 작업은 **Search Serving Index 영역** 안에서 일어난다.

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
[Search Preparation] document_chunk에 권한 메타 복사 (스냅샷, 일관성 보장)
       │
       ▼
[Search Serving Index] OpenSearch 색인 문서에도 동일 필드 매핑 (검색 필터 키)
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
| Search Preparation | markdown 기반 청크 분리, chunk metadata 생성, 권한 메타 복사 | `app/chunker/service.py` |
| Search Serving Index | DB / OpenSearch 양쪽 indexer 백엔드 | `app/indexer/service.py`, `app/adapters/opensearch_*` |
| Search Serving Index | OpenSearch 매핑 (nori + keyword + boost 필드) | `app/adapters/opensearch_index_mapping.py` |
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
| **Search Serving Index (Reindex 운영)** | dev: 인덱스 drop + 전체 재색인 스크립트 | 운영용 alias 기반 무중단 전환 전략 미구현 |
| **Source/Ingestion · Transformation (Reprocess 운영)** | API 단건 호출은 가능 | 일괄 reprocess UI / FAILED 자동 분류 / 재시도 정책 없음 |
| **Search Serving Index (Indexer batch)** | `INDEXER_BATCH_SIZE` 환경변수 노출 | 동적 조정·실패 시 batch 분할·백프레셔 없음 |
| **Observability (Generation 가시성)** | `llm_user_message_char_count`, `generation_context_chunks` preview 노출 | LLM latency / token usage / cost 메트릭 없음 |

### 7.3 미구현 (⛔ Not yet)

| 영역 | 메모 |
|------|------|
| **Governance: 실제 인증** | JWT/세션 → `PermissionPrincipal` 변환 |
| **Observability: 감사 로그** | 누가 어떤 문서를 조회/생성했는지 추적 |
| **Source/Ingestion: File change detection** | 파일 갱신·삭제 감지 (현재는 신규 파일만 안정 처리) |
| **Search Preparation: table-aware chunking** | 표를 별도 청크 또는 요약 텍스트로 처리 |
| **Search Preparation: embedding input 생성** | vector 검색을 위한 정제 텍스트 생성 |
| **Search Serving Index: Vector / Hybrid search** | 임베딩 색인 + BM25 ⊕ vector ranking |
| **Search Serving Index: Reranker** | cross-encoder 기반 query-doc 재정렬 |
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
| **Layer (영역)** | 저장소 경계 · 책임 경계 · 인터페이스 경계를 모두 가진 큰 단위. 본 문서의 6개 영역(Source/Ingestion, Document Transformation, Search Preparation, Search Serving Index, Serving/RAG Application, Observability/Governance)이 여기에 해당한다. |
| **Workflow task** | 한 Layer 내부에서 돌아가는 실행 단위. 상태 컬럼으로 트리거되고 다음 task에 신호를 넘긴다. 예: scanner, parser, chunker, indexer, discover, generate. Layer가 아니다. |
| **Interface** | 한 Layer가 다음 Layer에 데이터/제어를 넘기는 계약. 보통 DB의 상태 컬럼(예: `parse_status=PENDING`), HTTP API, 또는 어댑터 인터페이스(`SearchClient`, `LLMClient`)의 형태를 띤다. |
| **Source of Truth** | 데이터의 권위 있는 원본. ContextHub에서는 PostgreSQL의 `raw_document` / `document_parse_result` / `document_chunk` 가 해당한다. 분쟁 시 이쪽 값이 이긴다. |
| **Projection** | Source of Truth로부터 파생된, 다른 목적(주로 검색)으로 최적화된 사본. ContextHub에서는 OpenSearch `contexthub_chunks`가 projection이다. 잃어버려도 DB로부터 재생성 가능하다. |
| **Silver / Gold** | 데이터 성숙도 비유. `document_chunk`(Silver)는 구조화된 검색 준비 단위로 Source of Truth. OpenSearch(Gold)는 서비스 최적화 projection. |
| **Reindex** | 기존 projection을 새 매핑/새 분석 설정으로 다시 만드는 작업. 운영에서는 새 인덱스 생성 + alias switch로 한다. |
| **Alias switch** | 검색 클라이언트가 보는 논리 이름(alias)을 새 물리 인덱스로 원자적으로 전환하는 방식. 무중단 reindex의 핵심. |
| **Soft delete** | 물리 삭제 대신 `excluded=true` 같은 마크로 논리적 삭제만 수행하는 패턴. DB에는 이력이 남고, projection(OpenSearch)에서는 해당 문서를 제거한다. |
| **Metadata enrichment** | 원본 데이터에 검색·권한·정렬용 메타데이터(예: section_title, heading_path, access_scope)를 부착해 검색 품질·필터 능력을 강화하는 과정. Search Preparation 영역에서 주로 일어난다. |

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
