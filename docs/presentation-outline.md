# ContextHub 발표자료 목차 및 스크립트 초안

## 메타 정보

| 항목 | 내용 |
|------|------|
| **발표 제목** | 사내 문서 RAG 시스템 구축 — NAS 문서 챗봇에서 멀티소스 플랫폼으로 |
| **부제** | 설계 원칙·구현 경험·운영 교훈 |
| **대상 청중** | 개발팀, 기획자, 운영자 |
| **예상 시간** | 40~50분 (Q&A 포함 60분) |
| **핵심 메시지 3줄** | (1) "검색 안 됨"의 원인은 retrieval이 아니라 ingestion 누락일 수 있다. (2) chunk 검색과 document 후보 검색은 다른 문제다. (3) LLM 답변 품질은 프롬프트가 아니라 context 품질에 좌우된다. |

---

## 발표 구성 (슬라이드 순서)

```
[0]   표지
[1]   핵심 메시지 한 장
[2]   큰 그림 — 무엇을 만들었나
[3]   아키텍처 개요 — 6개 영역
[4]   저장소 기준 데이터 흐름
[5]   Bronze / Silver / Gold
[6]   Postgres Source of Truth
[7]   OpenSearch Search Projection
[8]   LLM Stateless Generation Engine
[9]   구현 진행 순서 — 어떻게 만들었나

      ── 트러블슈팅 사례 ──
[10A] 테마 1: 파이프라인이 막혔다      (Document Transformation / Ingestion 영역)
[10B] 테마 2: 색인이 약하다            (Search Serving Index 영역)
[10C] 테마 3: 검색 후보가 이상하다     (Serving/RAG Application — discover 단계)
[10D] 테마 4: 답변 근거를 모른다       (Serving/RAG Application — generate + Observability)
[10E] 테마 5: 권한은 작동하지만 신뢰가 없다  (Observability/Governance 영역)
[10F] 테마 6: 환경 차이가 조용히 품질을 망친다  (cross-cutting)

[11]  핵심 교훈 3가지
[12]  검색 품질 튜닝 사이클
[13]  현재 구현 상태
[14]  남은 과제
[15]  다음 한 사이클 목표
[16]  마무리 — 운영형 RAG 구축 교훈
```

---

## [0] 표지

**발표 제목**: 사내 문서 RAG 시스템 구축
**부제**: NAS 문서 챗봇에서 멀티소스·멀티에이전트 플랫폼으로

---

## [1] 핵심 메시지

> **"RAG는 검색 엔진과 LLM을 붙이는 것이 아니라,
> 데이터 파이프라인 전체를 신뢰 가능하게 만드는 작업이다."**

이 발표에서 반복해서 확인하게 되는 핵심 교훈 3가지:

| # | 교훈 | 관련 영역 |
|---|------|-----------|
| **1** | "검색이 안 된다"의 원인은 retrieval이 아니라 **ingestion 누락**일 수 있다 | Source/Ingestion, Document Transformation |
| **2** | **chunk 검색**과 **document 후보 검색**은 다른 문제다 | Search Serving Index, Serving/RAG |
| **3** | LLM 답변 품질은 프롬프트가 아니라 **context 품질**에 좌우된다 | Search Preparation, Serving/RAG |

---

## [2] 큰 그림 — 무엇을 만들었나

### 출발점: NAS 문서 챗봇

```
사용자: "과업대비표 어디 있어요?"
챗봇:   "인사팀/프로젝트/ID_A01_과업대비표.xlsx 를 참고하세요. 핵심 내용은 ..."
```

- 사내 NAS에 쌓인 문서(PDF, DOCX, XLSX, HWP, TXT)를 자연어로 검색
- 권한(부서, 공개/비공개)에 따라 검색 범위 자동 제한
- 답변에 출처 문서 링크 포함

### 지향점: 멀티소스·멀티에이전트 플랫폼

```
현재 (MVP)                       미래 (플랫폼)
─────────────────────────────    ────────────────────────────────────────
NAS 문서 한 종류                 NAS + DB + API + 웹 크롤링 + 실시간 이벤트
단일 RAG 에이전트                도메인별 전문 에이전트 + 라우터
BM25 검색                        BM25 + 벡터 하이브리드 + Reranker
Mock/OpenAI-compat LLM           사내 LLM 게이트웨이 (완전 통합)
```

---

## [3] 아키텍처 개요 — 6개 영역

> **용어 원칙**: scanner / parser / chunker / indexer / discover / generate는 **workflow task**이지 layer가 아니다.
> 영역(Layer)은 저장소 경계 · 책임 경계 · 인터페이스 경계를 모두 가진 단위에만 사용한다.

| 영역 | 한 줄 책임 | 저장소 (in → out) |
|------|-----------|-------------------|
| **Source/Ingestion** | 원본 파일을 신뢰 가능한 메타데이터로 등록. 권한 부여 | NAS → PostgreSQL `raw_document` |
| **Document Transformation** | 임의 포맷 → 통일된 markdown | `raw_document` → `document_parse_result` |
| **Search Preparation** | markdown → 검색 단위 chunk + metadata 생성 | `document_parse_result` → `document_chunk` |
| **Search Serving Index** | chunk → 서비스 검색용 projection 생성·관리 | `document_chunk` → OpenSearch |
| **Serving/RAG Application** | 질의 → 검색 → LLM → 답변 | OpenSearch → 응답 JSON |
| **Observability/Governance** | 상태·권한·품질 가시성 (전 영역 cross-cutting) | 로그·debug 객체·상태 컬럼 |

```
NAS 원본 파일
   │
   ▼ Source/Ingestion
PostgreSQL raw_document
   │
   ▼ Document Transformation
PostgreSQL document_parse_result
   │
   ▼ Search Preparation                ← chunk 재구성 / metadata 생성
PostgreSQL document_chunk
   │
   ▼ Search Serving Index              ← 검색 projection 관리
OpenSearch contexthub_chunks
   │
   ▼ Serving/RAG Application
answer + sources[] + debug{}
```

---

## [4] 저장소 기준 데이터 흐름

### 영역 간 연결은 DB 상태 컬럼으로

각 영역은 "느슨한 결합"으로 연결된다. HTTP나 메시지 큐가 아니라 **DB 상태 컬럼**이 신호다.

```
ingest_status = RECEIVED   → Document Transformation이 픽업
parse_status  = DONE       → Search Preparation이 픽업
chunk_status  = DONE       → Search Serving Index가 픽업
index_status  = DONE       → Serving에서 조회 가능
```

### 이 구조의 운영 이점

- 한 단계가 실패해도 다음 단계가 멈추지 않는다
- "왜 이 문서가 검색 안 되지?"를 상태 컬럼 4개만 보면 추적 가능
- worker 재시작·reprocess가 멱등(idempotent)하다

### 검색 안 될 때 진단 순서

```
1. raw_document에 행이 있는가?       (scanner workflow task 통과 여부)
2. parse_status = DONE 인가?         (parser workflow task 통과 여부)
3. document_chunk에 행이 있는가?     (chunker workflow task 통과 여부)
4. index_status = DONE 인가?         (indexer workflow task 통과 여부)
5. OpenSearch에 실제 문서가 있는가?  (색인 확인)
─────────────────────────────────
6. 위 5단계가 모두 정상일 때만 검색 쿼리 품질을 본다
```

---

## [5] Bronze / Silver / Gold — 저장소 성숙도

| 단계 | 저장소 | 역할 | 특성 |
|------|--------|------|------|
| **Bronze** | NAS `local_nas/` | 원본 파일 물리 저장소 | 불변. 임의 포맷. 폴더 구조로 접근 권한 표현 |
| **Silver** | PostgreSQL `document_chunk` | 검색 단위로 구조화된 Source of Truth | metadata enrichment 완료. 권한 복사 완료. 재생성 기준점 |
| **Gold** | OpenSearch `contexthub_chunks` | 서비스 검색 최적화 projection | nori 분석기, BM25, boost 적용. 언제든 Silver로부터 재생성 가능 |

> **핵심 원칙**: Gold가 날아가도 Silver로부터 전체 재색인 가능.
> Silver가 있는 한 데이터는 절대 소실되지 않는다.

---

## [6] Postgres — Source of Truth

3개 테이블이 모든 데이터의 권위 있는 원본이다.

```
raw_document          — 파일 식별자, 권한, 상태 컬럼 4개
document_parse_result — markdown_text, blocks_json, parser metadata
document_chunk        — chunk_text, section_title, heading_path, page_no,
                        권한 메타 복사본, index_status
```

- OpenSearch에 있는 모든 값은 이 3개 테이블에서 파생된다
- "OpenSearch에는 있는데 DB에는 없는" 상태는 존재하지 않는다
- 매핑 변경·인덱스 교체·장애 복구는 항상 DB 기반 재생성으로 처리한다

---

## [7] OpenSearch — Search Projection

OpenSearch는 `document_chunk`로부터 생성된 검색 최적화 사본이다.

### 매핑 핵심

```
multi_match fields:
  chunk_text          boost 1.0   ← 본문
  section_title       boost 3.0   ← 절 제목
  heading_path        boost 2.0   ← 상위 제목 계층
  original_filename   boost 4.0   ← 파일명 (사내 검색의 핵심 단서)
  inbox_path          boost 1.5   ← 폴더 경로
```

### chunk_text만으로 검색하면 안 되는 이유

- 담당자는 파일명·폴더명으로 문서를 기억한다 (`filename` boost 없으면 탈락)
- 핵심 키워드가 section_title에만 있고 본문에는 없는 경우가 많다
- 짧은 chunk는 BM25 score 자체가 불안정하다 → 제목 boost가 앵커 역할

### 무중단 Reindex 전략

```
기존 (개발): 인덱스 drop → 서비스 중단 발생
운영 목표:   새 인덱스 생성 → 전체 재색인 → alias switch → 이전 인덱스 회수
```

---

## [8] LLM — Stateless Generation Engine

ContextHub의 LLM은 메모리·세션·툴콜이 없다.

```
입력: messages[] + context chunks (검색 결과)
출력: answer 문자열
```

- `LLMClient.complete` 단일 인터페이스 뒤에 mock / OpenAI-compat / 사내 generate API가 숨는다
- 대화 상태는 클라이언트(POC UI)가 들고 있다
- 검색 결과 0건이면 LLM을 호출하지 않는다 (불필요한 hallucination 방지)

### LLM 인터페이스를 하나로 추상화하는 이유

```
MockLLMClient          ← 개발 초기, 외부 HTTP 없이 파이프라인 검증
    ↓ (코드 변경 없이 교체)
OpenAICompatLLMClient  ← openai API / vLLM / 호환 게이트웨이
    ↓ (코드 변경 없이 교체)
InternalGenerateLLMClient  ← 사내 system_prompt/user_prompt 전용 API
```

`NasRagUsecase`는 `LLMClient.complete`만 호출한다. 백엔드가 무엇인지 알지 못한다.

### 출처를 LLM 출력에서 파싱하지 않는 이유

```
❌ "답변에 출처를 [1], [2] 형식으로 표시해라"  → LLM이 형식을 틀리면 파싱 실패
✅ 검색 hits 객체에서 직접 sources[] 구성      → 검색에 포함된 chunk만 출처가 됨
```

---

## [9] 구현 진행 순서

### 원칙: 가장 단순한 포맷으로 파이프라인 전체를 먼저 연결한다

한 번에 완성된 시스템을 만들려다 "어디서 막혔는지" 모르는 상황이 생긴다.
txt 한 줄로 전체 흐름을 먼저 검증하고, 포맷과 기능을 순차적으로 확장했다.

| 단계 | 작업 | 핵심 결정 |
|------|------|-----------|
| **1. 인프라** | Docker Compose (PostgreSQL + OpenSearch), NAS 마운트 | WSL2, vm.max_map_count 설정 |
| **2. scanner** | NAS 폴더 스캔, sha256 중복 감지, access_scope 추출 | 파일 안정화(stabilization) 개념 도입 |
| **3. txt/md 최소 MVP** | txt → parse → chunk → index → discover 전체 흐름 연결 | "가장 단순한 포맷으로 전체를 먼저" |
| **4. parser adapter** | RoutingParser 구조, ParseResult 인터페이스 | 파서 교체 범위를 parser 패키지 안으로 제한 |
| **5. PDF / DOCX parser** | pypdf, python-docx 기반 어댑터 | 빈 결과 = FAILED (DONE으로 오인 금지) |
| **6. xlsx / hwp parser** | openpyxl, kordoc CLI + reprocess 절차 정비 | 포맷 누락 = 검색 누락. parser 추가 후 기존 FAILED는 수동 reprocess |
| **7. chunk** | markdown heading 기반 분리, 권한 메타 복사 | section_title / heading_path / page_no metadata 생성 |
| **8. index** | OpenSearch bulk upsert, 매핑 설계 | chunk_id 기준 멱등 upsert |
| **9. filename/path boost** | OpenSearch 매핑에 파일명·경로 full-text 필드 추가 | 매핑 변경 → 전체 재색인 필요 학습 |
| **10. discover** | chunk over-fetch → raw_document_id 그룹핑 → top_k 문서 | chunk top-k ≠ document top-k 분리 |
| **11. generate** | 권한 필터 검색 + document_ids 한정 + DB fallback | retrieval 0건 시 LLM 미호출 |
| **12. search post-processing** | 상대 점수 + highlight 후처리 필터 | precision vs recall 트레이드오프 인식 |
| **13. generation observability** | `generation_context_chunks` preview + `debug` 객체 | "왜 이런 답변인가" 추적 가능 |
| **14. POC UI** | discover → 선택 → generate 흐름, debug 패널, IME 처리 | compositionstart/end 패턴 |
| **15. LLM 실연동** | OpenAI-compat 백엔드, 사내 generate API | mock ↔ 실 LLM 무중단 전환 |
| **16. NFC normalization** | 전 구간(scanner/parser/indexer/query) NFC 적용 | macOS NFD vs Windows NFC 파일명 불일치 |

---

## [10A] 트러블슈팅 테마 1: 파이프라인이 막혔다

> **관련 영역**: Source/Ingestion, Document Transformation

### 사례 1: "검색이 안 됩니다" — 실제 원인은 ingestion 누락

**증상**: `"과업대비표"` 검색 결과 0건. 관련 PDF는 잘 검색됨. 처음에는 검색 품질 문제로 오인했다.

**진단**:
```sql
SELECT original_filename, parse_status, parse_error_message
FROM raw_document WHERE original_filename LIKE '%과업대비표%';
-- 결과: parse_status = 'FAILED', 'Unsupported document type: xlsx'
```

**원인**: xlsx parser가 없었다. 파일은 scanner workflow task에 잡혀 `raw_document`에 등록됐지만, parser workflow task에서 막혀 chunk도 index도 0이었다.

**조치**: `XlsxOpenpyxlParser` adapter 추가 (openpyxl 기반, 시트별 markdown 표 변환).

**실무 교훈**: "검색 품질 문제처럼 보여도 실제 원인이 ingestion 누락인 경우가 많다." 상태 컬럼 4개를 먼저 확인하는 습관이 시간을 아낀다.

---

### 사례 6: xlsx parser 추가 후에도 기존 FAILED 문서는 자동 복구되지 않는다

**증상**: xlsx parser를 추가했는데도 기존 xlsx 파일이 계속 검색되지 않았다. 새로 반입한 xlsx는 정상 검색됨.

**원인**: parser workflow task는 `parse_status = 'PENDING'`인 문서만 처리한다. 이미 `FAILED`로 기록된 문서는 자동 재시도하지 않는다. 이것은 **의도된 설계**다 — 자동 재시도를 허용하면 파서 버그가 있을 때 무한 루프가 발생한다.

**조치**: 운영자가 원인을 확인하고 명시적으로 reprocess를 트리거해야 한다.

```
parser 업그레이드 표준 절차:
1. 새 parser adapter 코드 배포
2. 의존성 재설치 확인 (pip install -e ".[dev]")
3. 새 파일 1개로 parser 동작 확인
4. FAILED 문서 목록 조회 (parse_error_message 원인 필터)
5. 해당 포맷 문서 reprocess → parse_status = PENDING 리셋
6. parser workflow task 실행 → 상태 확인
7. chunk_status / index_status 연쇄 재처리 확인
```

관련 API: `POST /admin/documents/{id}/reprocess?stage=parse`

**실무 교훈**: "parser를 개선하거나 교체한 뒤에는 기존 FAILED 문서를 재처리하는 운영 절차가 별도로 필요하다." FAILED는 자동으로 해소되지 않는다. 운영자가 명시적으로 개입해야 한다.

---

## [10B] 트러블슈팅 테마 2: 색인이 약하다

> **관련 영역**: Search Serving Index

### 사례 2: 파일명·경로로 검색이 안 된다

**증상**: `"ID_A01_과업대비표"` (파일명 그대로) 검색 시 결과 0건. 파일명을 아는 사용자가 검색했는데 결과가 안 나왔다.

**원인**: 초기 OpenSearch 매핑에서 `original_filename`, `inbox_path`가 `keyword` 타입(필터 전용)이었고 full-text 검색 대상이 아니었다.

사내 문서 검색 패턴을 관찰한 결과:
- 담당자가 파일명을 알고 있는 경우: "ID_A01" 또는 "과업대비표" 검색
- 프로젝트 경로를 알고 있는 경우: "sanrim-platform 문서" 검색
- 이 두 패턴 모두 `chunk_text` 기반 BM25로는 잘 안 됐다

**조치**: `original_filename`, `inbox_path`를 `text (nori)` 타입으로 변경 + `multi_match`에 boost 추가. **매핑 변경 → 전체 재색인** 필요.

**실무 교훈**: "사내 문서 RAG에서 파일명과 폴더 경로는 본문보다 강한 검색 단서다." 처음 매핑 설계 시 메타 필드를 빼면 나중에 재색인 비용을 치른다.

---

### 사례 12: indexer batch 환경 차이와 stub vs 실제 OpenSearch

**증상**: 로컬 개발 환경에서 indexer workflow task가 느리거나 중간에 멈췄다. 전체 재색인 후 색인 건수가 예상보다 적었다.

**원인**: 두 가지 요인이 겹쳤다.

첫째, **`INDEXER_BATCH_SIZE` 환경 차이**: Docker Desktop(Windows/macOS)에서 메모리 제한이 있어 큰 batch size로 OpenSearch에 bulk 요청을 보내면 OOM이나 timeout이 발생했다.

둘째, **stub SearchClient vs 실제 OpenSearch 동작 차이**: 단위 테스트에서 stub `SearchClient`를 쓰면 응답이 즉시 나오지만, 실제 OpenSearch는 인덱스 refresh 주기(기본 1초)가 있어 색인 직후 바로 검색되지 않는다. "색인은 됐는데 검색 결과가 안 나온다"는 증상이 환경마다 달리 나타났다.

**조치**:
- 개발 환경에서는 `INDEXER_BATCH_SIZE`를 낮게(50~100) 설정
- indexer 완료 후 테스트 전에 OpenSearch `/_refresh` 명시 호출 (또는 충분한 대기)
- stub과 실제 backend의 동작 차이를 문서화

**실무 교훈**: "운영 환경 차이는 검색 품질 이전에 색인 상태 자체에 영향을 준다." 환경 변수 하나가 전체 색인 완료 여부를 바꿀 수 있다. `INDEXER_BATCH_SIZE`와 OpenSearch refresh 동작을 환경별로 명시적으로 관리해야 한다.

---

## [10C] 트러블슈팅 테마 3: 검색 후보가 이상하다

> **관련 영역**: Serving/RAG Application — discover 단계

### 사례 3 + 7: chunk 독점과 document-level recall 개선

**증상**: `top_k=5` 요청인데 응답 문서가 1개, `matched_chunk_count=5`. 관련 문서가 여러 개 있는데 사용자에게 후보 1개만 제시됐다.

**원인**:

```
top_k = 5 요청
  → OpenSearch: hits size = 5
  → 상위 5개 chunk가 전부 같은 문서에서 나옴
  → raw_document_id 기준 groupBy
  → 결과: 문서 1개, matched_chunk_count = 5
```

한 문서에서 관련 chunk가 많으면 그 문서가 chunk를 독점하고, 다른 문서의 chunk는 top-5 밖으로 밀려나 아예 후보에 등장하지 않았다. 이것은 **chunk precision**(개별 chunk 관련성)과 **document recall**(다양한 문서 포함)의 구조적 충돌이다.

**두 관점의 차이**:

| 관점 | 질문 | OpenSearch에서 다루는 단위 |
|------|------|--------------------------|
| Chunk Precision | 가져온 chunk들이 질문과 얼마나 관련 있는가? | chunk 개별 BM25 score |
| Document Recall | 관련 문서들이 빠지지 않고 후보에 포함됐는가? | raw_document_id 기준 다양성 |

OpenSearch는 chunk 단위로 검색한다. 사용자에게 보여줄 "문서 후보"는 별도로 만들어야 한다.

**조치**: chunk fetch와 document 반환을 분리했다.

```python
# 이전: top_k가 chunk size로 직접 사용됨
chunk_hits = opensearch.search(query, size=body.top_k)

# 이후: 두 층 분리
top_k_documents  = body.top_k                      # 사용자에게 보여줄 문서 수
chunk_fetch_size = max(top_k_documents * 10, 50)   # 넉넉하게 가져올 chunk 수

chunk_hits = opensearch.search(query, size=chunk_fetch_size)
# → raw_document_id 기준 그룹핑
# → 문서당 matched_chunks 최대 5개로 제한
# → top_k_documents 개 문서 반환
```

**실무 교훈**: "top_k(문서 수)와 내부 chunk_fetch_size는 분리된 개념이다." 사용자에게 5개 문서를 보여주려면 OpenSearch에서 50개 chunk를 가져와야 할 수 있다.

---

### 사례 8: low-quality candidate filtering — recall 개선 이후 저품질 후보 유입

**증상**: `chunk_fetch_size`를 늘리자 document recall은 좋아졌지만, 관련 없는 문서(`top_score ≈ 1.0`, `highlight = null`)도 후보에 섞였다. 반면 실제 관련 문서의 score는 100 이상이었다.

**원인**:

```
[1] Retrieval (OpenSearch)
      chunk_fetch_size만큼 상위 chunk hit 수집
           ↓
[2] Search Post-processing (애플리케이션)
      raw_document_id 그룹핑
      → document top_k 제한
      → 저품질 문서 필터 ← 이 단계가 없으면 tail chunk도 후보로 나온다
```

recall을 올리면 tail chunk(약한 BM25 매칭)도 fetch window에 들어온다.

**조치**: `app/chat/discovery_service.py`에 문서 후보 필터를 추가했다.

| 조건 | 의미 |
|------|------|
| `has_highlight` | `matched_chunks` 중 메타데이터 highlight 존재 |
| `relative_score_ok` | `top_score >= best_score × 0.1` (상대 비율) |

둘 다 아니면 제외. 예: `best_score ≈ 122`, 저품질 문서 `top_score ≈ 1.0` → 비율 ~0.8% + highlight 없음 → drop.

고정 `min_score`를 쓰지 않는 이유: 질의와 인덱스마다 점수 스케일이 달라 고정값 튜닝이 쉽게 깨진다. **상대 점수 + highlight** 조합이 더 안전하다.

**실무 교훈**: precision과 recall은 서로 상충한다. 사용자가 직접 문서를 선택하는 UI에서는 recall이 더 중요하지만(나쁜 후보는 선택 안 하면 되므로), 컨텍스트에 자동으로 넣는 generate에서는 precision이 더 중요하다. 두 단계가 다른 정책을 써야 하는 이유다.

---

## [10D] 트러블슈팅 테마 4: 답변 근거를 모른다

> **관련 영역**: Serving/RAG Application — generate 단계, Observability/Governance

### 사례 9: generation_context_chunks observability — "왜 이런 답변인가"

**증상**: `/generate` 응답으로 답변과 출처는 나왔지만, "왜 이 답변이 생성됐는지"를 추적할 수 없었다. LLM에 실제로 어떤 chunk가 context로 들어갔는지 알 방법이 없었다.

**원인**: 초기 구현에서 retrieval debug는 "어떤 chunk가 검색됐는가"를 노출했지만, "그 chunk 중 어떤 것이 실제로 LLM prompt에 포함됐는가"는 별도로 노출하지 않았다. 선택 문서 수가 늘수록 "context가 한 문서에 치우치는 문제"도 이 observability 없이는 진단할 수 없었다.

**조치**: `ENABLE_RETRIEVAL_DEBUG=true`일 때 `/generate` 응답에 `debug.generation_context_chunks`를 추가했다.

```json
"debug": {
  "generation_context_chunks": [
    {
      "chunk_id": "...",
      "raw_document_id": "...",
      "original_filename": "ID_A01_과업대비표.xlsx",
      "section_title": "1. 과업 개요",
      "text_preview": "본 과업은...",     ← 약 300자 발췌
      "chunk_rank": 1
    }
  ],
  "llm_user_message_char_count": 3420,
  "llm_user_message_preview": "QUESTION: ...\n[CONTEXT 발췌는 generation_context_chunks 참고]"
}
```

POC UI의 debug 패널에서 "LLM이 실제로 본 context가 무엇인가"를 브라우저에서 직접 확인할 수 있게 됐다.

**활용 사례**:
- 문서 3건을 선택했는데 sources가 1건에만 몰려 있다 → `generation_context_chunks`로 fetch 치우침 확인
- 답변이 헤딩만 있고 실질적 내용이 없다 → context에 heading-only chunk가 들어간 것 확인 → chunking 재검토
- LLM이 "관련 정보를 찾을 수 없습니다"라고 답한다 → context가 실제로 관련 내용을 담고 있는지 확인

**실무 교훈**: "LLM 답변 품질은 프롬프트 설계만의 문제가 아니다." context 품질이 나쁘면 아무리 좋은 프롬프트도 한계가 있다. generation_context_chunks debug가 없으면 LLM을 의심할지 retrieval을 의심할지 알 수 없다.

---

### 사례 10: Mock LLM → OpenAI-compatible 실연동

**증상**: retrieval, sources, debug까지 모두 붙여 놨는데 `/generate`의 `answer`가 항상 고정 문자열이었다. "RAG가 동작한다"고 말할 수 없었다.

**원인**: 기본이 `MockLLMClient`였다. mock은 외부 HTTP 없이 개발 파이프라인을 검증하는 용도이므로, 실제 LLM 품질은 알 수 없는 상태였다.

**조치**:

```
LLM_MOCK_MODE=false
LLM_BACKEND=openai_compat
OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1   (또는 사내 vLLM 주소)
OPENAI_COMPAT_API_KEY=sk-...                        (인증이 없으면 생략)
LLM_MODEL=gpt-4o-mini
```

`OpenAICompatLLMClient`가 `POST {base}/chat/completions`로 실제 요청을 보낸다. `LLMClient.complete` 인터페이스는 동일하므로 `NasRagUsecase` 코드는 변경하지 않았다.

**API 키 생략 시**: `OPENAI_COMPAT_API_KEY`를 비우면 `Authorization` 헤더를 보내지 않는다. 로컬 vLLM 등 인증 없는 서버에 유용하다.

**사내 LLM 구조**:
```
사내 generate API (system_prompt / user_prompt 전용 포맷)
  → InternalGenerateLLMClient가 messages[] → system_prompt/user_prompt 변환 담당
  → NasRagUsecase는 포맷이 무엇인지 알지 못한다
```

**실무 교훈**: "retrieval 검증은 mock으로, generation 검증은 실 LLM으로 분리한다." mock을 켠 상태에서 retrieval 품질을 먼저 확인하고, mock을 끄면 LLM 품질만 달라지므로 두 레이어를 격리해 디버깅할 수 있다.

---

## [10E] 트러블슈팅 테마 5: 권한은 작동하지만 신뢰가 없다

> **관련 영역**: Observability/Governance

### 사례 11: access_scope 전파 구조와 trust boundary 한계

**권한 전파 구조는 완성됐다**:

```
[Ingestion] 폴더 경로 → access_scope / owner_id / department_code 추출
     ↓
raw_document.access_scope = "public" | "dept/{code}" | "private/{uid}"
     ↓
[Search Preparation] document_chunk에 권한 메타 복사 (스냅샷)
     ↓
[Search Serving Index] OpenSearch 색인 문서에도 동일 필드 매핑
     ↓
[Serving] PermissionPrincipal 기반 query filter 절 주입
          DB backend: SQL WHERE
          OpenSearch backend: bool filter
```

권한 enforcement 로직 자체는 DB 검색과 OpenSearch 검색 **양쪽에 모두** 들어가 있다.

**그러나 trust boundary가 닫혀 있지 않다**:

```
현재 상태:
  PermissionPrincipal = 요청 바디의 test_department_codes에서 생성
  user_id = "stub-user" 하드코딩
  → 클라이언트가 자신의 권한을 임의로 선언 가능

즉:
  "내부 필터링 로직은 살아 있는데
   외부 신뢰 입구가 비어 있다"
```

**조치 방향**:

```
미완성 → 목표:
  요청 바디 stub  →  JWT/세션 토큰 검증 → PermissionPrincipal 구성
  stub-user       →  AD/LDAP 디렉터리 조회 기반 실 user_id
```

**실무 교훈**: "권한은 파이프라인 전 구간에 흐른다. 하지만 입구가 신뢰되지 않으면 전체 설계가 의미 없다." 권한 로직을 다 만들어 놓고 인증 연결을 마지막으로 미루면 결국 운영 직전에 가장 어려운 작업이 남는다. trust boundary 완성은 운영 배포 전 필수 조건이다.

---

## [10F] 트러블슈팅 테마 6: 환경 차이가 조용히 품질을 망친다

> **관련 영역**: cross-cutting (전 영역)

### 사례 4: 한글 IME 입력 깨짐

**증상**: 질문 입력창에 "안녕"을 입력하면 "ㅇㅏㄴㄴㅕㅇ"로 자모가 분리됐다. 영어는 정상이었다.

**원인**: `input` 이벤트 핸들러에서 상태 갱신 후 DOM을 다시 렌더링했다. 한글은 IME 조합 단계(ㅇ → 아 → 안)가 있어, 이 중간에 DOM이 다시 그려지면 조합 중이던 문자가 확정되고 자모가 분리됐다.

**조치**: `compositionstart` / `compositionend` 이벤트로 조합 중 렌더링 지연.

```javascript
let isComposing = false;
input.addEventListener('compositionstart', () => { isComposing = true; });
input.addEventListener('compositionend',   () => { isComposing = false; handleInputChange(input.value); });
input.addEventListener('input', (e) => { if (!isComposing) handleInputChange(e.target.value); });
```

**실무 교훈**: CJK 서비스의 기본 요건이다. React `onChange`는 내부적으로 처리해주지만, Vanilla JS에서는 직접 구현해야 한다. "RAG 검색 품질 이전에 질문 입력 자체가 안정적이어야 한다."

---

### 사례 5: macOS 파일명 NFC/NFD 불일치

**증상**: Windows에서는 `"과업대비표"` 검색 시 `ID_A01_과업대비표.xlsx`가 정상 검색됐다. macOS에서는 동일 코드·동일 매핑인데 검색 결과 0건이었다.

```sql
-- macOS에서 색인한 데이터
SELECT original_filename FROM raw_document
WHERE original_filename LIKE '%과업대비표%';
-- 0 rows  ← 조합 글자를 못 찾음

SELECT original_filename FROM raw_document
WHERE original_filename LIKE '%A01%';
-- ID_A01_과업대비표.xlsx  ← 영문은 잡힘
```

**원인**: macOS(HFS+/APFS)는 파일명을 NFD(자모 분리)로 반환한다. Windows는 NFC(조합형). 같은 글자라도 코드 포인트가 달라 `ILIKE` 매칭이 어긋났다. scanner workflow task가 NFD 상태 그대로 DB에 저장했고, indexer가 그 값을 OpenSearch에 그대로 올렸다. `original_filename` boost(사례 2에서 공들여 설계한)가 NFC/NFD 불일치로 실질적으로 무력화됐다.

**조치**: 전 구간에 NFC 정규화 적용. NFC normalize는 멱등이므로 이미 NFC인 입력에도 안전하다.

```
scanner    → raw_document 저장 시 NFC
parser     → markdown_text, section_title, heading_path 저장 시 NFC
indexer    → OpenSearch 페이로드 NFC
query path → /discover, /query, /generate의 question을 retrieval 직전에 NFC
```

**실무 교훈**: "RAG retrieval 품질 문제를 진단할 때, tokenizer/BM25/boost 튜닝 전에 metadata가 같은 normalization 형태인지부터 확인해야 한다." 코드포인트 단위 불일치는 분석기로 복구할 수 없다. 파이프라인 전체에 일관되게 적용해야 하며 한 군데라도 빠지면 재현된다.

---

## [11] 핵심 교훈 3가지

이 발표에서 반복해서 등장하는 패턴을 3가지로 압축하면:

---

### 교훈 1: "검색이 안 된다"의 원인은 retrieval이 아니라 ingestion 누락일 수 있다

```
사용자 신고: "과업대비표 검색이 안 됩니다"
              ↓
  개발자 반응 A (잘못): 프롬프트 수정, LLM 교체, boost 튜닝 시도
  개발자 반응 B (옳음): 상태 컬럼 확인
              ↓
  parse_status = FAILED
  parse_error_message = 'Unsupported document type: xlsx'
              ↓
  원인: xlsx parser 없음. 검색 품질이 아니라 색인 자체가 없었다.
```

**진단 프로토콜을 먼저 확립한다**:
```
ingest_status → parse_status → chunk 존재 여부 → index_status → OpenSearch 확인
위 5단계가 모두 정상일 때만 검색 쿼리 품질을 본다
```

연관 사례: 사례 1 (ingestion 누락), 사례 6 (FAILED 재처리), 사례 12 (batch 환경 차이)

---

### 교훈 2: chunk 검색과 document 후보 검색은 다른 문제다

```
OpenSearch가 하는 일:        chunk 단위로 BM25 검색 → top-K chunk 반환
사용자에게 보여줄 것:        document 단위 후보 목록
                               ↑
                               이 변환이 없으면 chunk 독점이 생긴다
```

**두 단계가 필요하다**:

```
[1] OpenSearch retrieval
    chunk_fetch_size = max(top_k_documents × 10, 50)으로 넉넉하게

[2] Search Post-processing (애플리케이션)
    raw_document_id 기준 그룹핑
    → 저품질 문서 필터 (상대 점수 + highlight)
    → 문서 단위 top_k 컷오프
    → document candidate 반환
```

`top_k=5`로 요청해도 내부에서는 `chunk_fetch_size=50`으로 가져온다. 이 불일치를 시스템이 내부에서 처리해야 한다.

연관 사례: 사례 3+7 (chunk 독점 → document recall), 사례 8 (low-quality filtering)

---

### 교훈 3: LLM 답변 품질은 프롬프트가 아니라 context 품질에 좌우된다

```
증상: "답변이 엉뚱하다"
       ↓
진단 A: LLM 프롬프트를 수정한다  ← 잘못된 접근일 수 있다
진단 B: generation_context_chunks를 확인한다
       ↓
  context에 heading-only chunk만 있다          → chunking 재검토
  context가 한 문서 chunk에 치우쳐 있다         → fetch 정책 재검토
  context는 좋은데 LLM 답변이 나쁘다           → 이때만 프롬프트/모델 검토
```

**LLM이 이상한 게 아니라 retrieval/context가 문제일 수 있다**:

| 현상 | 실제 원인 | 해결 방향 |
|------|-----------|-----------|
| 답변이 엉뚱하다 | 관련 없는 chunk가 context에 들어감 | retrieval 튜닝 |
| 답변이 불완전하다 | heading-only chunk, 표 구조 소실 | chunking policy 재검토 |
| 출처가 맞지 않는다 | LLM 출력 파싱 의존 | hits 객체에서 직접 sources 구성 |
| 잘 되는데 갑자기 나빠진다 | context chunk 수/질 변화 | generation_context_chunks debug 확인 |

`/query`(retrieval only)로 retrieval을 먼저 검증하고, `LLM_MOCK_MODE=false`로 전환해야 generation 품질만 변수로 남는다.

연관 사례: 사례 9 (generation_context_chunks), 사례 10 (mock → 실연동)

---

## [12] 검색 품질 튜닝 사이클

이 사이클은 Search Preparation 영역과 Search Serving Index 영역에 **걸쳐** 있다. 한 변수만 건드리면 다른 변수에서 회귀가 발생하므로 항상 묶어서 관리한다.

```
chunking policy (크기/오버랩/heading 보존)          ← Search Preparation
      │
      ▼
chunk metadata (section_title, heading_path, page_no, ...)
      │
      ▼
OpenSearch mapping (nori 분석기, keyword, boost 대상)  ← Search Serving Index
      │
      ▼
BM25 / nori 토크나이제이션
      │
      ▼
metadata boost (파일명 / 절 제목 / heading 계층 가중)
      │
      ▼
Search Post-processing (권한 필터 + 상대 점수 + highlight 필터)
      │
      └─► (피드백) chunking policy로 되돌아옴
```

### 튜닝 원칙

- **chunking을 바꾸면 BM25 score가 바뀐다**: chunk 크기가 BM25 "문서 길이"이므로 TF 계산이 달라진다
- **metadata 필드가 바뀌면 검색 결과가 바뀐다**: multi_match 대상 필드가 바뀌면 score 분포가 바뀐다
- **"왜 이 문서가 나왔는가"를 설명할 수 없으면 boost 튜닝은 감(感)이다**: `matched_fields` + `highlight_terms` + `score`가 항상 노출돼야 한다
- **한 사이클의 변경은 한 PR에서 묶어서**: mapping 변경은 재색인을 동반하므로 chunking 변경과 동시에 처리

---

## [13] 현재 구현 상태

### 완료 (✅)

| 영역 | 항목 |
|------|------|
| Source/Ingestion | NAS 스캐너, sha256 중복 감지, access_scope 추출 |
| Document Transformation | RoutingParser + txt/pdf/docx/xlsx/hwp/hwpx 전 포맷 |
| Document Transformation | `parse_error_message` 기록, reprocess API |
| Search Preparation | markdown chunk 분리, section_title/heading_path/page_no metadata |
| Search Serving Index | OpenSearch bulk upsert, nori/BM25 매핑, filename/path boost |
| Serving/RAG | `/query` · `/discover` · `/generate` 3단 분리 엔드포인트 |
| Serving/RAG | chunk over-fetch → 문서 그룹핑, Search Post-processing 필터 |
| Serving/RAG | selected-document DB fallback |
| Serving/RAG | LLM mock / OpenAI-compat / 사내 generate API 실연동 |
| Governance | 권한 필터 (DB + OpenSearch 양쪽), PermissionPrincipal 구조 |
| Observability | `matched_fields`, `highlight_terms`, `score`, `retrieval_latency_ms` debug |
| Observability | `generation_context_chunks` preview, `llm_user_message_char_count` |
| Observability | 단계별 상태 컬럼 + reprocess API |
| UI | POC: discover → 선택 → generate 흐름, debug 패널, IME 처리 |
| Quality | NFC normalization 전 구간 |

### 부분 완료 (🟡)

| 항목 | 부족한 부분 |
|------|-------------|
| Governance (Access control) | `PermissionPrincipal`이 요청 바디 stub. 실 인증 토큰 미연동. trust boundary 미완성 |
| Search Serving Index (Reindex) | alias 기반 무중단 전환 미구현 (개발용 drop-recreate만 있음) |
| Search Serving Index (Indexer batch) | `INDEXER_BATCH_SIZE` 노출됐으나 동적 조정·실패 시 batch 분할 없음 |
| Observability (Generation) | LLM latency / token usage / cost 메트릭 없음 |

---

## [14] 남은 과제

### 단기 (다음 사이클)

| 과제 | 현황 |
|------|------|
| `/generate` 품질 검증 | 선택 문서 1건·3건 시나리오 end-to-end 검증 |
| Multi-document context 균형 | top_k chunk가 한 문서에 치우치는 문제 |
| Retrieval 정규화 고도화 | 현재 규칙 기반 → KoNLPy / nori 동의어 |
| Alias 기반 무중단 reindex | 운영 환경 배포 전 필수 |

### 중기 (Phase 2~3)

| 과제 | 방향 |
|------|------|
| JWT/세션 → PermissionPrincipal | 실제 사용자 인증 연결. trust boundary 완성 |
| Hybrid retrieval | BM25 + dense vector + Reranker |
| Embedding / Vector DB | 임베딩 모델 + OpenSearch knn 또는 별도 Vector DB |
| Table-aware chunking | 표를 별도 chunk 처리 또는 요약 변환 (heading-only chunk 문제 해소) |
| File change detection | 파일 갱신·삭제 감지 및 재처리 |
| Streaming 응답 | `/generate` SSE |
| 감사 로그 | 누가 어떤 문서를 조회했는지 추적 |

---

## [15] 다음 한 사이클 목표

**목표**: "POC에서 운영으로 가는 신뢰 가능한 한 걸음"

```
1. /generate 품질 검증 완료
   → 과업대비표 시나리오: 1건·3건 선택 → generation_context_chunks 확인
   → sources·answer 일치 확인. debug 패널로 "왜 이 답변인가" 설명 가능

2. OpenSearch alias 기반 무중단 reindex 구현
   → 운영 환경에서 mapping 변경 시 서비스 중단 없이 처리

3. 실 인증 연결 (JWT → PermissionPrincipal)
   → trust boundary 완성. 클라이언트가 권한을 임의 선언하는 상태 해소

4. 검색 품질 기준선 측정
   → BM25 기준 recall@5, recall@10 수치 확보
   → hybrid/vector 전환 전 비교 기준점
```

---

## [16] 마무리 — 운영형 RAG 구축 교훈

### 교훈 총정리 (12개)

| # | 교훈 | 관련 영역 |
|---|------|-----------|
| 1 | **가장 단순한 포맷으로 파이프라인 전체를 먼저 연결한다.** txt 한 줄로 끝까지 연결하고 포맷을 확장하면 어디가 문제인지 명확히 보인다. | 전 영역 |
| 2 | **"검색 안 됨"의 원인은 먼저 ingestion 상태 컬럼을 본다.** parse_status / chunk_status / index_status 순으로 확인한다. | Source/Ingestion, Document Transformation |
| 3 | **빈 parse 결과는 DONE이 아니라 FAILED다.** "파싱이 실행됐다"와 "의미 있는 내용이 추출됐다"는 다르다. | Document Transformation |
| 4 | **parser를 추가하거나 교체한 뒤에는 기존 FAILED 문서를 수동으로 reprocess해야 한다.** 자동 재처리는 없다. | Document Transformation, Observability |
| 5 | **매핑 설계 시 메타 필드(파일명, 경로)를 처음부터 포함한다.** 나중에 추가하면 전체 재색인 비용을 치른다. | Search Serving Index |
| 6 | **chunk top-k와 document top-k는 다른 개념이다.** 사용자에게 5개 문서를 보여주려면 50개 chunk를 가져와야 한다. chunk 독점 방지를 위해 fetch + grouping + filtering 3단계가 필요하다. | Serving/RAG |
| 7 | **"왜 이 문서가 나왔는가"를 설명할 수 없으면 boost 튜닝은 감이다.** `matched_fields`·`highlight_terms`·`score`는 항상 노출해야 한다. | Observability |
| 8 | **"왜 이런 답변이 생성됐는가"를 설명할 수 없으면 LLM 튜닝은 감이다.** `generation_context_chunks`로 context를 먼저 확인한다. | Observability |
| 9 | **검색과 생성은 분리해서 진단한다.** `/query`(retrieval only) → `/discover` → `/generate` 3단 분리가 있으면 어디가 나쁜지 빠르게 격리된다. | Serving/RAG |
| 10 | **OpenSearch는 projection이다.** DB에서 재생성 가능하다는 원칙이 있으면 매핑 변경·인덱스 교체가 두렵지 않다. | Search Serving Index |
| 11 | **NFC normalization은 파이프라인 전체에 일관되게 적용해야 한다.** 한 군데라도 빠지면 조용히 검색이 실패한다. macOS 개발 환경에서는 특히 주의한다. | cross-cutting |
| 12 | **권한은 파이프라인 전 구간에 흐른다. 하지만 입구가 신뢰되지 않으면 전체 설계가 의미 없다.** trust boundary 완성은 운영 배포 전 필수 조건이다. | Observability/Governance |

---

## 발표 스크립트 초안

### 오프닝 (2분)

> "안녕하세요. 오늘은 ContextHub라는 사내 문서 RAG 시스템을 만들면서 부딪힌 문제들과 그것을 해결한 방식을 공유하려고 합니다.
>
> 발표를 준비하면서 가장 강조하고 싶었던 건 이 한 문장입니다.
>
> **'RAG는 검색 엔진과 LLM을 붙이는 것이 아니라, 데이터 파이프라인 전체를 신뢰 가능하게 만드는 작업이다.'**
>
> 처음에는 OpenSearch에 문서 넣고 LLM 호출하면 되겠지 생각했는데, 실제로는 그 앞단 — 파일 감지, 파싱, 청킹, 색인 — 이 네 단계가 모두 정상이어야 검색이 됩니다. 그리고 검색이 됐다고 해서 LLM 답변이 좋은 것도 아닙니다.
>
> 오늘 발표의 핵심 교훈은 세 가지입니다. 트러블슈팅 사례를 이야기하면서 이 세 가지가 계속 등장한다는 걸 느끼실 겁니다."

---

### 큰 그림 (3분)

> "ContextHub가 뭘 하는 시스템인지 한 문장으로 설명하면, '사내 NAS에 있는 문서를 권한에 맞게 자연어로 검색하고 LLM이 답변해주는 챗봇'입니다.
>
> 예를 들어 '과업대비표 어디 있어요?'라고 물으면, 권한 범위 안의 문서에서 관련 내용을 찾아 '인사팀/프로젝트/ID_A01_과업대비표.xlsx를 참고하세요. 핵심 내용은…' 이렇게 답변하고 출처 문서를 링크로 보여줍니다.
>
> 지금은 NAS 문서 하나지만, 설계 자체는 DB, 웹 API, 실시간 이벤트 등 멀티소스로 확장할 수 있도록 영역별 책임 경계를 잡아놨습니다."

---

### 아키텍처 — 6개 영역 (5분)

> "아키텍처를 설명할 때 한 가지 용어를 먼저 명확히 하고 싶습니다. scanner, parser, chunker, indexer — 이것들을 레이어라고 부르지 않습니다. 이것들은 각 영역 안에서 돌아가는 workflow task입니다.
>
> 영역, 즉 Layer는 저장소 경계와 책임 경계와 인터페이스 경계를 모두 가진 단위에만 사용합니다. 6개 영역이 있습니다.
>
> Source/Ingestion은 NAS 파일을 PostgreSQL에 등록합니다. 파일 경로 기반으로 권한(부서, 공개/비공개)을 추출합니다.
>
> Document Transformation은 PDF, DOCX, XLSX, HWP 같은 임의 포맷을 통일된 markdown으로 변환합니다. RoutingParser workflow task가 확장자별로 적합한 어댑터에 위임합니다.
>
> Search Preparation은 markdown을 검색 단위 chunk로 쪼개고, 절 제목·heading 경로·페이지 번호 같은 메타데이터를 붙입니다. 결과는 PostgreSQL document_chunk에 저장됩니다.
>
> Search Serving Index는 document_chunk를 OpenSearch에 색인합니다. BM25, nori 분석기, 파일명·절 제목 boost를 여기서 관리합니다.
>
> Serving/RAG Application이 사용자 질의를 받아 검색하고 LLM을 호출해서 답변을 만듭니다.
>
> 마지막으로 Observability/Governance는 모든 영역을 가로질러 상태 가시성과 권한 enforcement를 담당합니다."

---

### 저장소 기준 흐름 (3분)

> "각 영역이 어떻게 연결되는지 보면, 답은 DB 상태 컬럼입니다. HTTP나 메시지 큐가 아닙니다.
>
> parse_status가 PENDING이 되면 parser workflow task가 픽업합니다. chunk_status가 PENDING이 되면 chunker workflow task가 픽업합니다. 이 방식 덕분에 한 단계가 실패해도 다음 단계가 멈추지 않고, 운영자는 상태 컬럼 4개만 보면 어디서 막혔는지 알 수 있습니다.
>
> 이 구조 때문에 '검색이 안 된다'는 신고가 오면 저는 검색 쿼리부터 보는 게 아니라 DB 상태 컬럼부터 봅니다. 이게 오늘 발표에서 가장 강조하고 싶은 첫 번째 교훈과 직결됩니다."

---

### 트러블슈팅 — 테마 1: 파이프라인이 막혔다 (5분)

> "이제 실제로 겪은 트러블슈팅 사례를 6개 테마로 이야기하겠습니다.
>
> 첫 번째 테마, '파이프라인이 막혔다'입니다.
>
> '과업대비표를 검색해도 결과가 안 나온다'는 신고가 들어왔습니다. 처음에는 검색 품질 문제라고 생각했는데, DB를 보니 parse_status가 FAILED였고, 에러 메시지는 'Unsupported document type: xlsx'였습니다. xlsx parser가 없었던 겁니다. 파일은 scanner workflow task에 잡혔는데 parse 단계에서 막혀 chunk도 index도 없는 상태였습니다. 이게 핵심 교훈 1번입니다. '검색이 안 되면 검색 품질보다 ingestion 상태를 먼저 본다.'
>
> 그런데 여기서 끝이 아닙니다. xlsx parser를 추가해도 기존 FAILED 문서는 자동으로 재처리되지 않습니다. parser workflow task는 PENDING만 처리하기 때문입니다. 자동 재시도를 허용하면 버그 있는 파서가 무한 루프를 만들 수 있어서 의도적으로 막아놨습니다. 운영자가 명시적으로 reprocess를 호출해야 합니다. parser를 업그레이드할 때마다 기존 FAILED 문서 재처리 절차가 필요하다는 것, 이걸 몰랐다면 xlsx 추가 후에도 기존 문서는 계속 검색이 안 됐을 겁니다."

---

### 트러블슈팅 — 테마 2: 색인이 약하다 (3분)

> "두 번째 테마, '색인이 약하다'입니다.
>
> 파일명 그대로 검색했는데 결과가 0건이었습니다. 'ID_A01_과업대비표'를 입력하면 아무 것도 안 나온 거죠. 이유는 초기 OpenSearch 매핑에서 파일명 필드가 keyword 타입이었습니다. 필터는 되는데 전문 검색 대상이 아니었습니다. 사내 문서에서 담당자는 파일명을 기억하고 검색합니다. 본문 기반 BM25로는 이 패턴을 잡을 수 없습니다.
>
> 매핑을 변경했고 재색인을 돌렸습니다. 여기서 배운 것은, 매핑 설계를 처음부터 잘 해야 한다는 겁니다. 나중에 추가하면 전체 재색인 비용을 치릅니다. 문서가 많으면 이 비용이 큽니다."

---

### 트러블슈팅 — 테마 3: 검색 후보가 이상하다 (4분)

> "세 번째 테마, '검색 후보가 이상하다'입니다. 이게 핵심 교훈 2번과 연결됩니다.
>
> top_k=5를 요청했는데 문서 후보가 1개만 나왔습니다. 왜냐하면 OpenSearch는 chunk 단위로 검색하거든요. size=5로 가져오니 관련성 높은 문서의 chunk 5개가 전부 차지했습니다.
>
> OpenSearch가 하는 일과 사용자에게 보여줄 것은 다릅니다. OpenSearch는 chunk 단위로 검색합니다. 사용자에게는 document 후보 목록을 보여줘야 합니다. 이 변환이 없으면 chunk 독점이 생깁니다.
>
> 해결책은 두 단계를 분리하는 겁니다. chunk_fetch_size를 top_k의 10배로 넉넉하게 가져오고, 애플리케이션에서 raw_document_id 기준으로 그룹핑해서 문서 단위 후보를 만듭니다.
>
> 그런데 recall을 높이면 이번엔 저품질 문서가 섞이기 시작합니다. precision과 recall의 전형적인 트레이드오프입니다. 상대 점수와 highlight 조건으로 저품질 문서를 필터링했습니다. 고정 threshold가 아니라 상대 비율을 쓴 이유는, 질의마다 점수 스케일이 달라서 고정값이 쉽게 깨지기 때문입니다."

---

### 트러블슈팅 — 테마 4: 답변 근거를 모른다 (4분)

> "네 번째 테마, '답변 근거를 모른다'입니다. 핵심 교훈 3번과 연결됩니다.
>
> 검색은 됐는데 LLM 답변이 엉뚱했습니다. 그런데 문제를 진단하려면 'LLM에 실제로 어떤 context가 들어갔는가'를 알아야 하는데, 그것을 볼 방법이 없었습니다.
>
> generation_context_chunks debug를 추가했습니다. ENABLE_RETRIEVAL_DEBUG=true 상태에서 /generate를 호출하면 응답에 LLM이 실제로 받은 context chunk 목록이 들어옵니다. 이걸 보고 알게 된 것들이 있습니다. 헤딩만 있고 내용이 없는 chunk가 들어가 있었습니다. 표 구조가 무너진 chunk가 있었습니다. 문서 3개를 선택했는데 context가 1개 문서 chunk에만 몰려 있었습니다.
>
> '답변이 이상하다 → LLM 프롬프트를 수정하자'는 접근이 틀릴 수 있습니다. context가 나쁜데 프롬프트를 아무리 잘 써도 한계가 있습니다. 반대로 context가 좋으면 단순한 프롬프트로도 좋은 답변이 나옵니다.
>
> mock 모드를 끄고 실 LLM을 연결할 때도 같은 원칙입니다. /query로 retrieval을 먼저 검증하고, mock만 끄면 generation 품질만 변수로 남습니다. 두 레이어를 격리해서 디버깅하는 겁니다."

---

### 트러블슈팅 — 테마 5: 권한은 작동하지만 신뢰가 없다 (2분)

> "다섯 번째 테마, 권한입니다.
>
> 권한 전파 구조 자체는 완성돼 있습니다. NAS 폴더 경로에서 access_scope를 추출하고, document_chunk에 복사하고, OpenSearch 색인에 매핑하고, 검색 시 필터로 적용합니다. DB와 OpenSearch 양쪽에 들어가 있습니다.
>
> 하지만 trust boundary가 열려 있습니다. 현재 PermissionPrincipal이 요청 바디의 test_department_codes에서 만들어지는 stub입니다. 클라이언트가 자신의 권한을 임의로 선언할 수 있는 상태입니다. '내부 필터링 로직은 살아 있는데 외부 신뢰 입구가 비어 있다'가 정확한 표현입니다. JWT 기반 실 인증 연결이 운영 배포 전 필수 작업입니다."

---

### 트러블슈팅 — 테마 6: 환경 차이가 조용히 품질을 망친다 (3분)

> "여섯 번째 테마입니다. 이건 코드 버그가 아니라 환경 차이였습니다.
>
> 한글 IME 깨짐 — 입력창에 '안녕'을 치면 'ㅇㅏㄴㄴㅕㅇ'으로 자모가 분리됐습니다. DOM 재렌더링이 IME 조합 중간에 일어났기 때문입니다. compositionstart/end 이벤트로 조합 중 렌더링을 막았습니다. CJK 서비스의 기본 요건입니다.
>
> NFC/NFD 불일치 — Windows에서는 잘 되는데 macOS에서는 '과업대비표' 검색이 0건이었습니다. macOS 파일시스템이 한글 파일명을 NFD로 반환하고, 검색어는 NFC였습니다. 같은 글자인데 코드 포인트가 달라 매칭이 안 됐습니다. 공들여 만든 파일명 boost가 NFD/NFC 불일치로 완전히 무력화된 겁니다.
>
> 파이프라인 전 구간에 NFC 정규화를 적용했습니다. scanner, parser, indexer, query 경로 모두. 한 군데라도 빠지면 다른 경로로 NFD가 새어들어와 같은 증상이 재현됩니다."

---

### 핵심 교훈 3가지 (3분)

> "트러블슈팅 사례들을 통해 반복해서 나타난 패턴을 3가지로 정리하겠습니다.
>
> 첫 번째. '검색이 안 된다'의 원인은 retrieval이 아니라 ingestion 누락일 수 있다. 상태 컬럼 5단계를 먼저 확인하고, 그게 다 정상일 때만 검색 쿼리를 본다는 프로토콜이 중요합니다.
>
> 두 번째. chunk 검색과 document 후보 검색은 다른 문제다. OpenSearch는 chunk를 찾는데, 사용자에게는 document를 보여줘야 합니다. 이 변환을 시스템이 처리해야 합니다. fetch는 chunk 단위로 넉넉하게, 반환은 document 단위로.
>
> 세 번째. LLM 답변이 나쁘면 프롬프트보다 context를 먼저 의심한다. generation_context_chunks를 보고 context 품질을 확인한 뒤, context가 좋은데 답변이 나쁠 때만 프롬프트나 모델을 검토한다."

---

### 현재 상태·남은 과제·다음 목표 (4분)

> "현재 상태를 한 줄로 정리하면, '전 포맷 ingestion → 검색 → 생성까지 엔드-투-엔드가 동작하는 POC'입니다. retrieval debug, generation_context_chunks debug, 권한 필터 모두 들어가 있습니다. 단, trust boundary — 실 인증 연결이 아직 없어서 운영 환경 배포 전에 반드시 해야 합니다.
>
> 다음 한 사이클 목표는 네 가지입니다. generate 품질 검증 완료, alias 기반 무중단 reindex, JWT 기반 실 인증 연결, BM25 기준선 수치 확보입니다. 마지막 항목이 중요한데, hybrid/vector 전환을 하기 전에 BM25로 얼마나 되는지 수치를 잡아놔야 '더 좋아졌다'를 말할 수 있습니다."

---

### 마무리 (2분)

> "마지막으로 오늘 발표를 한 줄로 정리하면 이겁니다.
>
> RAG 시스템에서 문제가 생겼을 때, 디버깅 순서는 이렇게 됩니다. ingestion 상태 확인 → retrieval 품질 확인 → context 품질 확인 → 그 다음에야 LLM 프롬프트. 이 순서를 뒤집으면 시간을 낭비합니다.
>
> 감사합니다. 질문 받겠습니다."

---

## 참고 문서

- `docs/architecture-overview.md` — 영역·저장소·workflow task 전체 구조
- `docs/rag-troubleshooting-and-lessons.md` — 트러블슈팅 상세 (23개 이슈)
- `docs/backend-status.md` — 현재 구현 상태 스냅샷
- `docs/todo-roadmap.md` — Phase별 로드맵
- `docs/search-index.md` — OpenSearch 매핑 + boost + 권한 필터
- `docs/chunking-strategy.md` — chunking policy 상세
- `docs/document-discovery.md` — discover 분리 철학, post-processing
- `docs/logging-audit.md` — generation context 로그 원칙
