# ContextHub 발표 슬라이드 설계 문서

> PPT 제작용 상세 설계. 각 슬라이드는 독립적으로 제작 가능하도록 기술한다.
> 상세 트러블슈팅, 코드 예시, 운영 절차 등은 **부록(Appendix)** 후보로 분리했다.
> 전체 흐름은 `docs/presentation-outline.md`를 원본으로 한다.

---

## 발표 흐름 한눈에 보기

```
[왜 필요한가]         슬라이드 01  오프닝
[무엇을 만들 것인가]  슬라이드 02  큰 그림
[어떻게 설계했나]     슬라이드 03  아키텍처 6개 영역
                      슬라이드 04  저장소 Bronze/Silver/Gold
[어떻게 만들었나]     슬라이드 05  첫 번째 구현 범위: txt end-to-end
                      슬라이드 06  데이터 흐름: 상태 컬럼이 신호다
                      슬라이드 07  구현 진행 순서
[각 영역을 깊이]      슬라이드 08  문서 변환: parser adapter
                      슬라이드 09  검색 준비: chunking과 metadata
                      슬라이드 10  검색 색인: OpenSearch/BM25/boost
                      슬라이드 11  검색 후처리: chunk → document candidate
                      슬라이드 12  생성: LLM은 Stateless Engine
                      슬라이드 13  관측성: retrieval·generation debug
[배운 것]             슬라이드 14  주요 트러블슈팅 — 핵심 교훈 3가지
[지금과 앞으로]       슬라이드 15  현재 구현 상태
                      슬라이드 16  남은 과제와 다음 사이클
                      슬라이드 17  확장 방향
[마무리]              슬라이드 18  결론
```

**발표 전체를 관통하는 6개 물음**
1. 왜 단순 챗봇이 아니라 운영형 RAG 플랫폼을 만들려 했는가
2. 가장 작은 범위(txt)로 end-to-end를 먼저 연결한 이유는 무엇인가
3. parser / 검색 / 생성 / 관측에서 어떤 문제를 실제로 겪었는가
4. 기능 흐름이 아니라 저장소·책임·인터페이스 기준으로 재구조화한 이유는 무엇인가
5. retrieval과 generation이 독립 품질 영역이라는 것을 어떻게 깨달았는가
6. 지금 만든 기반이 어떻게 멀티소스·멀티에이전트 플랫폼으로 이어지는가

---

## 슬라이드 01 — 오프닝

### 슬라이드 제목
사내 문서, 있는데 못 찾는다

### 핵심 메시지 한 줄
문서가 없어서가 아니라 찾을 수 없어서 일이 안 된다 — RAG는 이 문제를 해결한다

### 본문 bullet
- NAS 폴더를 뒤지거나 담당자에게 매번 묻는 것이 현실
- PDF · DOCX · XLSX · HWP · TXT가 쌓여 있지만 자연어 검색 불가
- 권한에 맞게 · 자연어로 · 출처와 함께 — 사내 RAG의 세 요건
- "과업대비표 어디 있어요?" → 담당 파일 + 핵심 내용 + 출처 링크

### 그림/다이어그램 아이디어
- **좌측**: 파일 아이콘들(PDF·XLSX·HWP)이 흩어진 NAS 폴더 구조 이미지
- **우측**: 채팅 말풍선 `"과업대비표 알려줘"` → 답변 말풍선 + 파일 링크
- 화살표 하나가 "RAG" 레이블과 함께 좌→우 연결

### 발표 스크립트
> 팀 안에 문서가 없어서 일이 안 되는 경우는 거의 없습니다. 문서는 있는데 찾을 수 없어서 막히는 경우가 대부분입니다. NAS 폴더를 직접 뒤지거나, 그 파일 담당자가 누구인지 알아서 물어봐야 하거나, 비슷한 이름의 파일이 여럿 있어서 어느 게 최신인지 모르거나. 이 상황은 문서 관리의 실패가 아니라 검색 인터페이스의 부재입니다. 자연어로 물어보면 권한 범위 안에서 답을 찾아 출처와 함께 알려주는 시스템, 이것이 ContextHub를 시작한 이유입니다. 오늘은 이 시스템을 어떻게 만들었고, 어떤 시행착오를 겪었는지 공유하겠습니다.

### 부록 후보
- 사내 문서 검색 패턴 분석 (파일명 검색 vs 내용 검색 비율)
- 기존 도구(Confluence, SharePoint) 대비 RAG의 차이

---

## 슬라이드 02 — 큰 그림

### 슬라이드 제목
단순 챗봇이 아니라 운영형 RAG 플랫폼을 만들고 싶었다

### 핵심 메시지 한 줄
기능 추가가 아니라 확장 가능한 구조를 처음부터 설계한다

### 본문 bullet
- **지금 MVP**: NAS 문서 · 단일 에이전트 · BM25 검색 · OpenAI-compat LLM
- **향후 플랫폼**: 멀티소스(NAS+DB+API) × 멀티에이전트 × 하이브리드 검색
- 차이: 나중에 확장할 때 영역 경계를 깨지 않아야 한다
- 이번 발표: MVP 구현 경험 + 확장 기반을 어떻게 잡았는가

### 그림/다이어그램 아이디어
- **2열 비교 테이블**

| | MVP (지금) | 플랫폼 (목표) |
|--|------------|---------------|
| 소스 | NAS 문서 | NAS + DB + API + 크롤링 |
| 에이전트 | 단일 NAS RAG | 도메인별 에이전트 + 라우터 |
| 검색 | BM25 | BM25 + Vector 하이브리드 |
| LLM | Mock / OpenAI-compat | 사내 LLM 게이트웨이 |

### 발표 스크립트
> 처음부터 운영형 플랫폼을 목표로 잡았습니다. 단순히 문서를 검색해서 LLM에 넣는 챗봇을 만드는 것과, 여러 소스·여러 에이전트가 올라올 수 있는 기반을 만드는 것은 설계 출발점이 다릅니다. NAS 문서 하나로 시작하더라도, 나중에 DB나 API 소스가 추가됐을 때 기존 코드를 뜯어고치지 않아야 합니다. 오늘 발표의 MVP는 이 플랫폼 설계 위에서 가장 작은 범위를 구현한 결과입니다. 어떤 구조를 선택했고, 그 구조가 실제 구현에서 어떻게 작동했는지, 그리고 어떤 시행착오를 겪었는지를 순서대로 이야기하겠습니다.

### 부록 후보
- 멀티에이전트 아키텍처 상세 설계 (`docs/agent-architecture.md`)
- Phase별 로드맵 전체 (`docs/todo-roadmap.md`)

---

## 슬라이드 03 — 전체 아키텍처

### 슬라이드 제목
저장소·책임·인터페이스 기준으로 6개 영역

### 핵심 메시지 한 줄
scanner·parser·chunker·indexer는 workflow task다 — 영역(Layer)이 아니다

### 본문 bullet
- **영역(Layer)**: 저장소 경계 + 책임 경계 + 인터페이스 경계를 모두 가진 단위
- **workflow task**: 한 영역 안에서 돌아가는 실행 단위. 상태 컬럼으로 신호를 넘긴다
- Source/Ingestion → Document Transformation → **Search Preparation** → **Search Serving Index** → Serving/RAG → Observability/Governance
- Search Preparation(Silver)과 Search Serving Index(Gold)는 분리된 영역

### 그림/다이어그램 아이디어
- **수직 스택 + 저장소 레이블** (좌측에 저장소, 우측에 영역명)

```
NAS ──────────────► Source/Ingestion
                          │
PostgreSQL raw_document   │
                          ▼
                    Document Transformation
                          │
PostgreSQL document_chunk │
                          ▼
                    Search Preparation   ← Silver
                          │
OpenSearch ───────────────│
                          ▼
                    Search Serving Index ← Gold
                          │
                          ▼
                    Serving/RAG Application
                          │
                    [Observability/Governance — 가로로 전체를 감싸는 띠]
```

### 발표 스크립트
> 설계를 시작할 때 가장 먼저 한 것은 용어를 정리하는 것이었습니다. scanner, parser, chunker, indexer — 이것들을 레이어라고 부르면 나중에 설계가 흐려집니다. 이것들은 각 영역 안에서 돌아가는 workflow task입니다. 영역, 즉 Layer는 저장소 경계와 책임 경계와 인터페이스 경계를 모두 가진 단위에만 사용합니다. 6개 영역이 있는데, 특히 Search Preparation과 Search Serving Index를 분리한 것이 중요합니다. 청킹 정책을 바꾸는 것과 OpenSearch 매핑을 바꾸는 것은 책임이 다릅니다. 한쪽을 바꾸면 다른 쪽에 영향이 가지만, 담당하는 저장소는 다릅니다. 이 경계를 처음부터 명확히 해야 나중에 튜닝 사이클을 관리할 수 있습니다.

### 부록 후보
- 영역별 인터페이스 계약 상세 (SearchClient, LLMClient, PermissionPrincipal)
- `docs/architecture-overview.md` §2 전체

---

## 슬라이드 04 — 저장소 관점

### 슬라이드 제목
Bronze · Silver · Gold — 데이터는 성숙해지면서 흐른다

### 핵심 메시지 한 줄
OpenSearch는 projection — Silver(document_chunk)가 있는 한 언제든 재생성 가능하다

### 본문 bullet
- **Bronze**: NAS 원본 파일 (불변. 임의 포맷)
- **Silver**: PostgreSQL `document_chunk` — 구조화된 Source of Truth. chunk metadata + 권한 복사 완료
- **Gold**: OpenSearch `contexthub_chunks` — BM25/nori/boost 적용. 서비스 최적화 projection
- Gold가 날아가도 Silver로부터 전체 재색인 → 매핑 변경·장애 복구가 두렵지 않다

### 그림/다이어그램 아이디어
- **3단 피라미드** (하단 Bronze → 중간 Silver → 상단 Gold)
- 각 단계 옆에 저장소 이름 + 역할 한 줄
- Gold → Silver 방향 "재생성 가능" 역방향 점선 화살표
- 슬라이드 하단에 한 줄: `"OpenSearch에 있는 모든 값은 PostgreSQL에서 파생된다"`

### 발표 스크립트
> 데이터가 어디에 있고 어디서 왔는지를 명확히 하는 것이 운영에서 가장 중요합니다. Bronze는 NAS의 원본 파일입니다. 건드리지 않습니다. Silver는 PostgreSQL의 document_chunk 테이블입니다. markdown을 chunk 단위로 쪼개고 section_title, heading_path, 권한 메타를 붙인 구조화된 Source of Truth입니다. Gold는 OpenSearch입니다. Silver로부터 파생된 검색 최적화 사본입니다. 이 구분이 중요한 이유는, Gold가 날아가도 Silver로부터 전체 재색인이 가능하기 때문입니다. 매핑을 바꾸거나 analyzer를 교체해도 Silver만 있으면 복구됩니다. "OpenSearch에 있는 값은 모두 DB에서 파생된다"는 원칙 하나가 운영 변경을 두렵지 않게 만듭니다.

### 부록 후보
- PostgreSQL 테이블 스키마 상세 (`docs/db-schema.md`)
- alias switch 기반 무중단 reindex 전략 상세

---

## 슬라이드 05 — 첫 번째 구현 범위

### 슬라이드 제목
txt 한 줄로 파이프라인 전체를 먼저 연결했다

### 핵심 메시지 한 줄
가장 단순한 포맷으로 end-to-end를 검증한 뒤 포맷을 확장한다

### 본문 bullet
- 처음부터 PDF/HWP/xlsx를 다 연결하려다 "어디서 막혔는지" 모르는 상황이 생긴다
- txt 한 파일 → scanner → parse → chunk → index → `/discover` → 검색 결과 확인
- 파이프라인 구조 문제와 포맷별 파서 문제를 분리해서 볼 수 있다
- 최초 검색 성공 후: PDF → DOCX → XLSX → HWP/HWPX 순서로 확장

### 그림/다이어그램 아이디어
- **수평 파이프라인** + 각 단계 위에 체크 표시
```
[txt 파일] → [scanner] → [raw_document] → [parser] → [document_parse_result]
                                                              ↓
[/discover ✓] ← [OpenSearch] ← [indexer] ← [document_chunk] ← [chunker]
```
- 아래에 "포맷 확장 순서" 타임라인: txt/md → PDF → DOCX → XLSX → HWP

### 발표 스크립트
> 구현을 시작할 때 가장 중요한 결정은 "무엇을 먼저 연결할 것인가"였습니다. 처음에는 PDF, DOCX, XLSX를 한꺼번에 지원하려고 했습니다. 그런데 파이프라인 전체가 연결되지 않은 상태에서 포맷별 파서를 만들면, 파서가 문제인지 파이프라인이 문제인지 구분이 안 됩니다. 그래서 먼저 txt 한 파일로 scanner부터 /discover까지 전체를 연결했습니다. 최초로 검색 결과가 나왔을 때 그것이 진짜 첫 번째 검증이었습니다. 파이프라인 구조가 맞다는 것을 확인한 뒤에야 포맷을 순서대로 확장했습니다. 이 원칙은 나중에 새 기능을 추가할 때도 계속 적용됩니다.

### 설계 판단: 왜 txt부터 시작했는가

> **"작은 포맷으로 전체 사이클을 먼저 닫고, 그 다음 포맷과 품질을 확장한다"**

운영형 RAG에서 포맷 완성도보다 먼저 확인해야 하는 것이 있다. **파이프라인 전체가 연결되는가**다. 수집 → 변환 → 청킹 → 색인 → 검색 → 생성까지 데이터가 실제로 흐르는지를 가장 단순한 형태로 먼저 검증해야 한다.

- 처음부터 PDF·OCR·HWP까지 모두 붙이지 않았다. 파서가 필요 없을 만큼 단순한 txt 한 파일로 end-to-end를 먼저 검증했다.
- txt로 파이프라인이 닫히면, 이후 PDF·DOCX·XLSX adapter를 추가해도 파이프라인 **구조**는 동일하다. 포맷 문제와 파이프라인 구조 문제를 분리해서 볼 수 있다.
- 이후 PDF → DOCX → XLSX → HWP/HWPX 순서로 parser coverage를 확장했다. 각 포맷 추가는 Document Transformation 영역 안에서만 일어났다. 다른 영역은 건드리지 않았다.
- 이 접근은 새 소스·새 에이전트를 추가할 때도 동일하게 적용된다. 가장 단순한 케이스로 파이프라인 전체를 먼저 검증하고, 그 다음 케이스를 확장한다.

### 부록 후보
- Docker Compose 설정 상세 (WSL2, vm.max_map_count)
- 파일 안정화(stabilization) 로직 상세

---

## 슬라이드 06 — 데이터 흐름

### 슬라이드 제목
영역 간 연결은 DB 상태 컬럼으로 — HTTP가 아니다

### 핵심 메시지 한 줄
상태 컬럼 4개만 보면 어느 단계에서 막혔는지 알 수 있다

### 본문 bullet
- `ingest_status` → `parse_status` → `chunk_status` → `index_status`
- 한 단계가 실패해도 다음 단계가 멈추지 않는다 (느슨한 결합)
- **"검색 안 됨" 진단 프로토콜**: 5단계 상태 확인 → 그 다음에야 검색 쿼리
- `POST /admin/documents/{id}/reprocess` — 특정 stage를 PENDING으로 리셋

### 그림/다이어그램 아이디어
- **상태 컬럼 흐름도**

```
raw_document                     document_chunk
┌──────────────────┐             ┌──────────────┐
│ ingest_status    │──RECEIVED──►│              │
│ parse_status     │──PENDING──► │ (parser 픽업)│
│ chunk_status     │──PENDING──► │ (chunker 픽업│
│ index_status     │             │  index_status│──PENDING──► OpenSearch
└──────────────────┘             └──────────────┘
```

- 우측 하단에 진단 체크리스트 박스:
  ```
  ① raw_document 존재? → ② parse=DONE? → ③ chunk 존재?
  → ④ index=DONE? → ⑤ OpenSearch 확인 → ⑥ 검색 쿼리
  ```

### 발표 스크립트
> 각 영역이 어떻게 연결되는지 설명하겠습니다. HTTP 호출이나 메시지 큐가 아닙니다. DB 상태 컬럼이 신호입니다. parse_status가 PENDING이 되면 parser workflow task가 픽업합니다. chunk_status가 PENDING이 되면 chunker workflow task가 픽업합니다. 한 단계가 실패해도 다음 단계가 멈추지 않고, 운영자는 상태 컬럼만 보면 어느 단계에서 막혔는지 알 수 있습니다. 실제로 "문서가 검색이 안 된다"는 신고가 오면 저는 검색 쿼리부터 보는 게 아니라 이 상태 컬럼을 먼저 봅니다. 파이프라인 5단계가 모두 정상일 때만 검색 쿼리 품질을 의심합니다. 이 진단 순서가 뒤바뀌면 시간을 낭비합니다.

### 부록 후보
- reprocess API 사용 가이드 (`docs/ops-reprocess.md`)
- PENDING/DONE/FAILED 상태 전이 다이어그램

---

## 슬라이드 07 — 구현 진행 순서

### 슬라이드 제목
어떻게 만들었나 — 16단계 구현 순서

### 핵심 메시지 한 줄
기능 완성도보다 파이프라인 전체 흐름과 관측 가능성을 먼저 확보했다

### 본문 bullet
- **단계 1~3**: 인프라 + scanner + txt end-to-end (파이프라인 뼈대)
- **단계 4~6**: parser adapter + PDF/DOCX + xlsx/hwp (포맷 확장)
- **단계 7~11**: chunk + index + boost + discover + generate (검색·생성 핵심)
- **단계 12~16**: post-processing + observability + UI + LLM 실연동 + NFC (품질·운영)

### 그림/다이어그램 아이디어
- **4행 그룹 타임라인** (각 그룹에 색상 구분)

| 그룹 | 단계 | 핵심 |
|------|------|------|
| 🔵 파이프라인 뼈대 | 1~3 | 인프라·scanner·txt end-to-end |
| 🟢 포맷 확장 | 4~6 | parser adapter · PDF · xlsx/hwp |
| 🟡 검색·생성 | 7~11 | chunk · index · boost · discover · generate |
| 🔴 품질·운영 | 12~16 | post-processing · observability · LLM 실연동 · NFC |

### 발표 스크립트
> 구현 순서를 보면 우선순위가 보입니다. 처음 3단계는 파이프라인 뼈대를 만드는 것입니다. txt 한 줄로 끝까지 연결합니다. 다음 3단계는 포맷 확장입니다. 뼈대가 있으니까 PDF, xlsx, hwp를 순서대로 붙입니다. 이때 각 포맷 추가는 Document Transformation 영역 안에서만 일어납니다. 다른 영역은 건드리지 않습니다. 그다음 5단계가 검색과 생성의 핵심입니다. chunking, indexing, filename boost, discover, generate를 순서대로 만들었습니다. 마지막 5단계는 품질과 운영입니다. post-processing, debug 가시성, LLM 실연동, NFC 정규화. 기능 완성도를 높이는 것이 아니라 "운영할 수 있는가"를 확보하는 단계입니다.

### 부록 후보
- 16단계 전체 표 (핵심 결정 포함) — `docs/presentation-outline.md` [9]
- Phase 0→1→2→3 로드맵 (`docs/todo-roadmap.md`)

---

## 슬라이드 08 — 문서 변환

### 슬라이드 제목
parser는 adapter 구조 — 포맷 교체는 Document Transformation 영역 안에서만

### 핵심 메시지 한 줄
chat-api는 어떤 파서를 썼는지 알지 못한다 — 이것이 경계의 목적이다

### 본문 bullet
- `RoutingParser` → 확장자별 adapter 위임 → 동일한 `ParseResult` 인터페이스 반환
- 출력: `markdown_text` + `blocks_json` + `metadata_json` (section_title, heading_path, page_no)
- 빈 `markdown_text`는 DONE이 아니라 FAILED — "파싱 실행"과 "내용 추출"은 다르다
- `parse_error_message` 컬럼이 없으면 "왜 이 문서가 검색이 안 되지?"를 추적 불가

### 그림/다이어그램 아이디어
- **RoutingParser 분기 트리**
```
                    RoutingParser
                         │
         ┌───────┬───────┼────────┬──────────┐
         ▼       ▼       ▼        ▼          ▼
    .txt/.md   .pdf    .docx    .xlsx   .hwp/.hwpx
   PlainText  PdfPypdf  Docx   Xlsx    KordocCli
   Parser     Parser    Parser  Parser  Parser
         │       │       │        │          │
         └───────┴───────┴────────┴──────────┘
                              ▼
                         ParseResult
              (markdown_text / blocks_json / metadata_json)
```
- 우측에 작은 박스: `parse_status` → DONE / FAILED + `parse_error_message`

### 발표 스크립트
> 문서 포맷이 다양하다는 것은 초기 설계에서 예상한 문제였습니다. PDF, DOCX, XLSX, HWP가 있고, 앞으로 더 추가될 수 있습니다. 이 문제를 해결하는 방법은 RoutingParser 구조입니다. 확장자를 보고 적합한 adapter에 위임하고, 모든 adapter는 동일한 ParseResult 인터페이스를 반환합니다. chat-api, chunker, indexer는 어떤 파서를 썼는지 알 필요가 없습니다. 새 포맷을 추가할 때 다른 영역은 건드리지 않습니다. 그리고 한 가지 중요한 원칙이 있습니다. 빈 markdown_text는 FAILED입니다. 파싱이 실행됐다는 것과 의미 있는 내용이 추출됐다는 것은 다릅니다. parse_error_message 컬럼이 있어야 "왜 이 파일이 검색이 안 되지?"를 DB 한 줄만 보고 알 수 있습니다.

### 부록 후보
- kordoc CLI 연동 상세 (`docs/parser-kordoc.md`)
- parser 추가 후 FAILED 문서 reprocess 절차 전체

---

## 슬라이드 09 — 검색 준비 (Search Preparation)

### 슬라이드 제목
chunk_text만으로는 부족하다 — metadata가 검색 품질을 결정한다

### 핵심 메시지 한 줄
Search Preparation은 document_chunk(Silver)를 만드는 영역 — chunk + metadata가 모든 검색 단서의 원천이다

### 본문 bullet
- chunker workflow task: markdown → 의미 단위 chunk 분리 + 권한 메타 복사
- 핵심 metadata: `section_title` · `heading_path` · `page_no` · `sheet_name`
- 이 metadata가 OpenSearch의 boost 대상이 되고, 검색 recall과 precision을 결정한다
- heading-only chunk 문제: 제목만 있고 내용이 없는 chunk가 context에 들어가면 LLM 답변이 나빠진다

### 그림/다이어그램 아이디어
- **before/after** 2열 비교

| Before (markdown 원본) | After (document_chunk) |
|------------------------|------------------------|
| `# 1장. 시스템 개요` | chunk_text: "본 시스템은..." |
| `시스템 개요를 설명한다` | section_title: "시스템 개요" |
| `## 1.1 목적` | heading_path: "1장 > 1.1 목적" |
| `목적은 다음과 같다` | page_no: 3 |

- 우측 작은 박스: `chunk_status` → DONE / FAILED

### 발표 스크립트
> Search Preparation 영역이 하는 일은 markdown을 검색 가능한 단위로 재구성하는 것입니다. 단순히 텍스트를 쪼개는 것이 아닙니다. 절 제목이 무엇인지, 어떤 heading 계층 아래에 있는지, 몇 페이지인지, 어떤 시트에서 왔는지 — 이 metadata가 document_chunk에 기록됩니다. 이것이 중요한 이유는, OpenSearch에서 이 metadata 필드들이 boost 대상이 되기 때문입니다. chunk_text에 키워드가 없어도 section_title에 있으면 검색됩니다. 반대로, heading만 있고 내용이 없는 chunk가 LLM context에 들어가면 답변이 나빠집니다. chunking 정책의 품질이 이후 검색 품질과 답변 품질 모두에 영향을 줍니다.

### 부록 후보
- chunking policy 상세 (크기·오버랩·heading 보존) — `docs/chunking-strategy.md`
- table-aware chunking 후보 설명

---

## 슬라이드 10 — 검색 색인 (Search Serving Index)

### 슬라이드 제목
파일명이 본문보다 강한 검색 단서다 — 처음부터 매핑에 포함해야 한다

### 핵심 메시지 한 줄
Search Serving Index는 document_chunk를 OpenSearch Gold projection으로 만드는 영역이다

### 본문 bullet
- `multi_match` boost 구조: `original_filename(4.0)` > `section_title(3.0)` > `heading_path(2.0)` > `inbox_path(1.5)` > `chunk_text(1.0)`
- 사내 문서에서 담당자는 파일명·경로를 기억하고 검색한다 — chunk_text 위주 설계는 함정
- 매핑 변경은 전체 재색인을 동반한다 — 처음 설계가 비용을 결정한다
- 운영 reindex 전략: alias switch 기반 무중단 전환 (`contexthub_chunks_v{n+1}` → alias swap)

### 그림/다이어그램 아이디어
- **boost 필드 bar chart** (가로 막대)

```
original_filename  ████████████████████ 4.0
section_title      ███████████████      3.0
heading_path       ██████████           2.0
inbox_path         ███████              1.5
chunk_text         █████                1.0
```

- 슬라이드 하단 작은 박스: `"매핑 변경 → 재색인 필요 → alias switch로 무중단 전환"`

### 발표 스크립트
> Search Serving Index 영역에서 가장 중요한 결정은 어떤 필드를 얼마나 가중치를 줄 것인가입니다. 처음에 파일명과 경로 필드를 keyword 타입으로만 설정했습니다. 필터는 되는데 전문 검색이 안 됩니다. 그 결과 "ID_A01_과업대비표"라고 파일명 그대로 검색해도 결과가 0건이었습니다. 사내 문서에서 담당자는 파일명을 기억하고 검색합니다. 본문 기반 BM25로는 이 패턴을 잡을 수 없습니다. 파일명 boost를 4.0으로 올린 뒤 파일명 검색이 됐습니다. 단, 매핑을 변경하면 기존 인덱스에 자동으로 반영되지 않습니다. 전체 재색인이 필요합니다. 이 비용을 피하려면 처음 매핑 설계 시 메타 필드를 포함해야 합니다.

### 설계 판단: 왜 BM25/keyword retrieval을 먼저 선택했는가

> **"BM25 기준선을 먼저 안정화하고, 그 다음 vector/hybrid로 확장한다"**

처음부터 vector search를 선택하지 않은 것은 의도적인 판단이다.

- 사내 문서에는 파일명(`ID_A01_과업대비표`), 문서번호, 과업 ID, 표준명, 요구사항 번호처럼 **keyword precision이 결정적인** 검색 패턴이 많다. semantic similarity보다 정확한 키워드 매칭이 더 중요한 경우가 지배적이다.
- BM25 + metadata 기반 keyword retrieval을 먼저 안정화하면 **기준선(baseline)** 이 생긴다. 나중에 vector search나 hybrid를 붙였을 때 "더 좋아졌다"를 수치로 말할 수 있다. 기준선 없이 vector search를 먼저 도입하면 개선 효과를 측정할 수 없다.
- OpenSearch는 keyword retrieval 하나만을 위한 도구가 아니다. metadata filtering, nori 형태소 분석기, 향후 knn 기반 vector 필드 확장까지 동일한 인프라에서 지원된다. BM25로 시작해도 hybrid retrieval 기반을 동시에 확보하는 셈이다.
- 이후 확장 방향: BM25 → Embedding 생성 → BM25 + Vector hybrid → Cross-encoder Reranker 순서로 단계적으로 확장한다.

### 부록 후보
- OpenSearch 매핑 전체 JSON (`docs/search-index.md`)
- nori 분석기 설정 상세
- alias switch 무중단 reindex 절차 5단계

---

## 슬라이드 11 — 검색 후처리

### 슬라이드 제목
OpenSearch는 chunk를 반환한다 — 사용자에게는 document 후보를 보여줘야 한다

### 핵심 메시지 한 줄
chunk retrieval과 document candidate는 다른 문제다 — 사이에 grouping·ranking·filtering이 필요하다

### 본문 bullet
- `top_k=5` 요청 → OpenSearch `size=50` (chunk_fetch_size = top_k × 10)
- `raw_document_id` 기준 그룹핑 → 문서당 chunk quota 제한 → document 단위 top_k
- 저품질 document 필터: `top_score ≥ best_score × 0.1` AND `has_highlight`
- `/discover` 전용: `/generate`는 여전히 chunk-level top_k + document_ids 필터

### 그림/다이어그램 아이디어
- **3단계 변환 흐름**

```
[OpenSearch]              [Post-processing]           [사용자 UI]
chunk hit 50개    →    raw_document_id 그룹핑    →   document 카드 5개
(BM25 score 순)   →    저품질 필터링             →   (score + highlight 표시)
                  →    문서 단위 top_k 컷오프
```

- 좌측에 "before" 예시: 같은 문서에서 chunk 10개
- 우측에 "after" 예시: 서로 다른 문서 5개 카드

### 발표 스크립트
> 이 슬라이드가 핵심 교훈 2번과 직결됩니다. OpenSearch는 chunk 단위로 검색합니다. top_k=5로 요청하면 size=5로 가져오는데, 관련성 높은 문서의 chunk 5개가 전부 차지해서 다른 문서는 후보에 등장하지 않습니다. 사용자에게 5개 문서를 보여주려면 OpenSearch에서 50개 chunk를 가져와야 합니다. 이 불일치를 시스템이 처리해야 합니다. chunk를 넉넉하게 가져온 뒤 raw_document_id 기준으로 그룹핑하고, 문서 단위 top_k를 적용합니다. 그런데 recall을 높이면 이번엔 저품질 문서가 섞입니다. 상대 점수와 highlight 조건으로 필터링했습니다. 고정 threshold가 아닌 상대 비율을 쓴 이유는 질의마다 점수 스케일이 달라서입니다.

### 부록 후보
- `discovery_service.py` post-processing 로직 상세
- precision vs recall 트레이드오프 사례 (`docs/document-discovery.md`)

---

## 슬라이드 12 — 생성

### 슬라이드 제목
LLM은 Stateless Generation Engine — context가 전부다

### 핵심 메시지 한 줄
LLM 답변이 나쁘면 프롬프트보다 context를 먼저 의심한다

### 본문 bullet
- LLM은 메모리·세션·툴콜이 없다 — `messages[] + context chunks` → `answer`
- `LLMClient.complete` 단일 인터페이스 뒤에 mock / OpenAI-compat / 사내 generate API
- 출처는 LLM 출력 파싱이 아니라 hits 객체에서 직접 구성 (파싱 실패 방지)
- 검색 결과 0건 → LLM 미호출 → 고정 안전 메시지 반환

### 그림/다이어그램 아이디어
- **중앙에 LLM 박스**, 입출력 명시

```
               ┌─────────────────────────┐
messages[]  ──►│                         │
context     ──►│   LLM (Stateless)       │──► answer (문자열)
chunks      ──►│   메모리 없음            │
               │   세션 없음              │──► sources[] (hits에서 직접)
               └─────────────────────────┘

               ↑
   mock / OpenAI-compat / 사내 generate
   (LLMClient.complete 인터페이스 뒤에 숨음)
```

- 슬라이드 하단 작은 박스: `"context 품질 → 답변 품질. LLM은 주어진 것만 참조한다"`

### 발표 스크립트
> LLM을 어떻게 설계에서 위치시킬 것인가가 중요합니다. ContextHub에서 LLM은 Stateless Generation Engine입니다. 메모리도, 세션도, 툴콜도 없습니다. messages 배열과 context chunk를 받아 answer 문자열을 반환합니다. 대화 상태는 클라이언트가 들고 있습니다. LLMClient.complete라는 단일 인터페이스 뒤에 mock, OpenAI-compat, 사내 generate API가 숨습니다. 교체해도 코드 변경이 없습니다. 출처를 LLM 출력에서 파싱하지 않는 것도 중요한 결정입니다. "출처를 [1], [2] 형식으로 표시해라"고 프롬프트에 넣으면 LLM이 형식을 틀릴 수 있습니다. 검색에 포함된 hits 객체에서 직접 sources를 구성합니다. 그리고 이 슬라이드에서 가장 강조하고 싶은 것은, LLM 답변이 나쁘면 프롬프트보다 context를 먼저 의심해야 한다는 것입니다.

### 부록 후보
- 사내 generate API 구조 (system_prompt/user_prompt 변환)
- MockLLMClient → OpenAI-compat 전환 설정 상세
- answer sanitizing 이유

---

## 슬라이드 13 — 관측성

### 슬라이드 제목
왜 이 문서가 나왔는가 · 왜 이런 답변인가 — 설명할 수 없으면 개선할 수 없다

### 핵심 메시지 한 줄
retrieval debug + generation debug = 품질 개선의 전제 조건

### 본문 bullet
- **retrieval debug**: `matched_fields` · `highlight_terms` · `score` · `document_rank` · `chunk_rank`
- **generation debug**: `generation_context_chunks` — LLM이 실제로 받은 context chunk preview
- `/query` (retrieval only) → `/discover` → `/generate` 3단 분리로 어느 레이어 문제인지 격리
- `ENABLE_RETRIEVAL_DEBUG=true`일 때 응답 JSON + POC UI debug 패널에 노출

### 그림/다이어그램 아이디어
- **2열 debug 패널 mockup**

```
[Retrieval Debug]                    [Generation Debug]
───────────────────────────────      ──────────────────────────────
chunk_rank: 1                        context_chunk 1
document_rank: 1                       filename: ID_A01_과업대비표.xlsx
score: 117.4                           section_title: 1. 과업 개요
matched_fields:                        text_preview: "본 과업은..."
  ✓ original_filename                context_chunk 2
  ✓ section_title                      filename: ...
highlight_terms: ["과업대비표"]
```

- 슬라이드 하단: `/query → /discover → /generate` 3단계 격리 다이어그램

### 발표 스크립트
> 관측성은 운영형 시스템의 필수 조건입니다. "왜 이 문서가 나왔는가"를 설명할 수 없으면 boost 튜닝은 감이 됩니다. matched_fields를 보면 파일명에서 매칭됐는지 본문에서 매칭됐는지 알 수 있습니다. 그 다음 레벨의 관측성이 generation_context_chunks입니다. LLM이 실제로 받은 context chunk 목록입니다. 이걸 보고 알게 된 것들이 있습니다. 헤딩만 있고 내용이 없는 chunk가 들어가 있었습니다. 문서 3개를 선택했는데 context가 1개 문서 chunk에만 몰려 있었습니다. "LLM이 이상하다"고 했는데 실제로는 context 품질 문제였습니다. 그리고 /query, /discover, /generate를 분리한 것도 같은 이유입니다. retrieval만 검증할 수 있어야 "이게 검색 문제인가 생성 문제인가"를 격리할 수 있습니다.

### 설계 판단: 왜 generation debug가 중요한가

> **"답변 품질을 개선하려면 LLM이 실제로 받은 context를 먼저 볼 수 있어야 한다"**

LLM 응답 품질 문제를 모델 문제로만 보면 안 된다. 실제로는 LLM이 받은 context가 부족하거나 잘못된 경우가 더 많다.

- `generation_context_chunks`를 통해 LLM이 실제로 받은 chunk preview를 확인할 수 있다. 이 debug 없이는 "모델이 나쁘다"와 "context가 나쁘다"를 구분할 방법이 없다.
- 확인한 실제 문제 사례들: heading-only chunk가 context에 들어가 내용이 없는 답변 생성 / 문서 3개를 선택했는데 context가 1개 문서 chunk에만 몰려 불균형 답변 / 관련 없는 chunk가 들어가 hallucination 발생.
- 이로써 "검색 문제인지, 청킹 문제인지, 프롬프트 문제인지, 모델 문제인지"를 분리해서 볼 수 있다. 진단 없이 프롬프트나 모델을 바꾸는 것은 비용이 크고 효과가 불확실하다.
- 운영형 RAG에서는 답변 생성보다 **"왜 그런 답변이 나왔는지 추적 가능성"** 이 더 중요하다. 추적할 수 없으면 개선할 수 없다.

### 부록 후보
- debug JSON 스키마 전체 (`RetrievalDebugInfo`)
- 로깅 원칙: chunk_text/answer 원문 로그 금지 이유 (`docs/logging-audit.md`)

---

## 슬라이드 14 — 주요 트러블슈팅

### 슬라이드 제목
문제의 대부분은 "어느 영역, 어느 단계에서 막혔는가"의 문제였다

### 핵심 메시지 한 줄
3개 대표 사례가 핵심 교훈 3가지와 정확히 대응한다

### 본문 bullet — 3개 사례 요약

**사례 A — 교훈 1 (Document Transformation 영역)**
- 증상: "과업대비표" 검색 0건
- 원인: xlsx parser 없음 → `parse_status=FAILED`
- 교훈: 검색 쿼리보다 ingestion 상태를 먼저 본다

**사례 B — 교훈 2 (Serving/RAG discover 단계)**
- 증상: top_k=5 요청인데 문서 후보 1개만 나옴
- 원인: OpenSearch size=5 → 한 문서 chunk 5개가 독점
- 교훈: chunk top-k ≠ document top-k. fetch → grouping → filtering 3단계 필요

**사례 C — 교훈 3 (Search Preparation + Observability)**
- 증상: 답변이 불완전하거나 엉뚱함
- 원인: heading-only chunk가 context에 들어감 (generation_context_chunks로 확인)
- 교훈: LLM 프롬프트 전에 context 품질을 확인한다

### 그림/다이어그램 아이디어
- **3행 표** (증상 → 원인 → 영역 → 교훈)

| | 사례 A | 사례 B | 사례 C |
|--|--------|--------|--------|
| 증상 | 검색 0건 | 후보 1개 | 답변 나쁨 |
| 원인 | parser 없음 | chunk 독점 | context 불량 |
| 영역 | Document Transformation | Serving/RAG | Search Prep + Observability |
| 교훈 | ingestion 먼저 | chunk ≠ doc | context 먼저 |

### 발표 스크립트
> 트러블슈팅 사례를 모두 이야기하면 시간이 너무 걸리니, 핵심 교훈 3가지에 각각 대응하는 사례 하나씩만 짚겠습니다. 첫 번째, "과업대비표 검색이 안 된다"는 신고입니다. 검색 품질을 의심하기 전에 parse_status를 봤습니다. FAILED였고 에러 메시지는 'Unsupported document type: xlsx'였습니다. xlsx parser가 없었던 겁니다. 교훈: ingestion 상태를 먼저 본다. 두 번째, top_k=5 요청인데 문서가 1개만 나왔습니다. OpenSearch는 chunk를 검색하는데, 관련성 높은 문서 하나가 chunk 5개를 전부 차지했습니다. chunk fetch와 document 반환을 분리해야 합니다. 교훈: chunk top-k와 document top-k는 다른 개념이다. 세 번째, 답변이 불완전했습니다. generation_context_chunks를 봤더니 heading-only chunk가 context에 들어가 있었습니다. 교훈: LLM 이전에 context를 확인한다.

### 부록 후보
- 트러블슈팅 사례 전체 12개 + 테마별 분류 (`docs/presentation-outline.md` [10A~10F])
- RAG 구축 체크리스트 3단계 (`docs/rag-troubleshooting-and-lessons.md` 말미)

---

## 슬라이드 15 — 현재 구현 상태

### 슬라이드 제목
end-to-end POC 완료 — 운영 배포를 위한 3개 조건이 남아 있다

### 핵심 메시지 한 줄
파이프라인은 동작한다. trust boundary · alias reindex · generate 검증이 마지막 조각이다

### 본문 bullet
- ✅ 전 포맷 ingestion (txt/pdf/docx/xlsx/hwp) + 검색 + 생성 end-to-end 동작
- ✅ retrieval debug (matched_fields · score) + generation debug (generation_context_chunks)
- ✅ 권한 필터 (DB + OpenSearch 양쪽) + NFC normalization 전 구간
- 🟡 trust boundary: `PermissionPrincipal`이 요청 바디 stub — JWT 연결 필요
- 🟡 alias 기반 무중단 reindex: 개발용 drop-recreate만 있음
- 🟡 `/generate` 품질 검증: 1건·3건 선택 시나리오 end-to-end 미완

### 그림/다이어그램 아이디어
- **완료/미완 2열 체크리스트**

```
✅ 완료                          🟡 남은 것
─────────────────────────────    ──────────────────────────────
전 포맷 ingestion                trust boundary (JWT 연결)
BM25/boost 검색                  alias 기반 무중단 reindex
discover/generate 엔드포인트     /generate 품질 검증
retrieval + generation debug     LLM latency 메트릭
권한 필터 (DB + OpenSearch)
NFC normalization
POC UI
```

### 발표 스크립트
> 현재 상태를 한 줄로 정리하면, "전 포맷 ingestion부터 생성까지 end-to-end가 동작하는 POC"입니다. 검색 debug와 생성 context debug도 들어가 있습니다. 권한 필터도 DB와 OpenSearch 양쪽에 들어가 있습니다. 운영 배포를 위해 남은 것은 세 가지입니다. 첫째, trust boundary 완성입니다. 현재 PermissionPrincipal이 요청 바디에서 만들어지는 stub입니다. JWT 연결이 필요합니다. 둘째, alias 기반 무중단 reindex입니다. 지금은 개발 환경에서만 쓰는 drop-recreate 방식밖에 없습니다. 셋째, /generate 품질 검증입니다. 문서 1건, 3건 선택 시나리오에서 sources와 answer가 일치하는지 확인해야 합니다. 이 세 가지가 운영 신뢰성의 마지막 조각입니다.

### 부록 후보
- 완료/부분완료/미구현 전체 표 (`docs/presentation-outline.md` [13])
- `docs/backend-status.md` 전체

---

## 슬라이드 16 — 남은 과제와 다음 사이클

### 슬라이드 제목
다음 사이클: POC에서 운영으로 가는 신뢰 가능한 한 걸음

### 핵심 메시지 한 줄
4가지 우선순위 과제 — 모두 "기능 추가"가 아니라 "신뢰성 확보"다

### 본문 bullet
- `/generate` 품질 검증 — generation_context_chunks로 context·sources·answer 일치 확인
- alias 기반 무중단 reindex 구현 — 운영 환경 mapping 변경 시 서비스 중단 없이
- JWT → `PermissionPrincipal` 연결 — trust boundary 완성
- BM25 recall@5·recall@10 수치 확보 — hybrid/vector 전환 전 비교 기준점

### 그림/다이어그램 아이디어
- **우선순위 매트릭스** (긴급도 × 중요도) 또는 단순 4항목 체크리스트
- 각 항목 옆에 "왜 지금인가" 한 줄 이유

| 과제 | 왜 지금인가 |
|------|------------|
| generate 품질 검증 | 운영 배포 전 품질 기준선 확보 |
| alias reindex | 매핑 변경이 있을 때마다 서비스 중단 방지 |
| JWT 연결 | trust boundary 없으면 권한 설계가 의미 없음 |
| BM25 기준선 | hybrid 전환 후 "더 좋아졌다"를 수치로 말하기 위해 |

### 발표 스크립트
> 다음 사이클 목표는 "기능을 더 만드는 것"이 아니라 "지금 만든 것을 신뢰할 수 있게 하는 것"입니다. 네 가지입니다. 첫째, /generate 품질 검증입니다. generation_context_chunks를 보면서 context가 올바르게 구성됐는지 확인합니다. 둘째, alias 기반 무중단 reindex입니다. 지금은 매핑을 바꿀 때마다 인덱스를 통째로 내리고 다시 올립니다. 운영 환경에서는 불가능합니다. 셋째, JWT 연결입니다. 권한 필터 로직이 완성됐는데 trust boundary가 열려 있습니다. 넷째, BM25 기준선 수치입니다. hybrid search나 vector search로 전환했을 때 "더 좋아졌다"를 말하려면 지금 BM25가 어느 수준인지 먼저 알아야 합니다.

### 부록 후보
- Phase 2~3 중기 과제 전체 목록
- hybrid retrieval 로드맵 (`docs/retrieval-roadmap.md`)

---

## 슬라이드 17 — 확장 방향

### 슬라이드 제목
지금 만든 기반 위에 hybrid search · document chat · multi-agent가 올라온다

### 핵심 메시지 한 줄
각 영역의 인터페이스를 바꾸지 않고 구현체를 교체·확장한다 — 설계 원칙이 지금 이미 적용돼 있다

### 본문 bullet
- **SearchClient**: BM25 → Hybrid (BM25 + dense vector) → Reranker 추가
- **LLMClient**: mock → OpenAI-compat → 사내 LLM → streaming · multi-turn
- **Source**: NAS → DB + API + 웹 크롤링 (Source/Ingestion 영역만 확장)
- **Agent**: 단일 NAS RAG → AgentRouter → 도메인별 전문 에이전트

### 그림/다이어그램 아이디어
- **확장 로드맵 다이어그램**

```
지금 (MVP)                         단계 확장
─────────────────────────────      ──────────────────────────────────
Source: NAS                    →   Source: NAS + DB + API
                                   (Source/Ingestion 영역 내부만)

Search: BM25 only              →   BM25 + Vector → Hybrid + Reranker
                                   (SearchClient 인터페이스 유지)

LLM: OpenAI-compat             →   사내 LLM 게이트웨이 → Streaming
                                   (LLMClient.complete 유지)

Agent: 단일 NAS RAG            →   AgentRouter → 전문 에이전트들
                                   (PermissionPrincipal 위임 구조)
```

### 발표 스크립트
> 지금 만든 MVP가 단순히 동작하는 챗봇이 아니라는 것을 보여드리겠습니다. 각 영역의 인터페이스를 유지한 채로 구현체를 교체할 수 있도록 설계했습니다. SearchClient 인터페이스 뒤에는 지금 BM25가 있지만, 나중에 dense vector를 붙이고 하이브리드로 전환해도 chat-api는 코드를 바꾸지 않습니다. LLMClient.complete 인터페이스 뒤에는 지금 OpenAI-compat이 있지만, 사내 LLM 게이트웨이로 교체해도 NasRagUsecase는 모릅니다. Source/Ingestion 영역에 새 소스를 추가해도 파이프라인 아래는 그대로입니다. 지금 당장 구현된 것은 작지만, 이 기반 위에 hybrid search, document chat, multi-agent가 올라올 때 영역 경계를 다시 설계하지 않아도 됩니다. 처음부터 이 구조를 선택한 이유가 여기 있습니다.

### 부록 후보
- AgentRouter 설계 (`docs/agent-architecture.md`)
- hybrid retrieval 임베딩 모델 후보
- source viewer 설계 (`docs/document-discovery.md`)

---

## 슬라이드 18 — 결론

### 슬라이드 제목
RAG는 파이프라인 전체를 신뢰 가능하게 만드는 작업이다

### 핵심 메시지 한 줄
디버깅 순서: ingestion → retrieval → context → LLM 프롬프트

### 본문 bullet — 핵심 교훈 3가지로 마무리
- **교훈 1**: "검색이 안 된다"의 원인은 retrieval이 아니라 ingestion 누락일 수 있다 — 상태 컬럼을 먼저 본다
- **교훈 2**: chunk 검색과 document 후보 검색은 다른 문제다 — fetch → grouping → filtering
- **교훈 3**: LLM 답변 품질은 프롬프트가 아니라 context 품질에 좌우된다 — generation_context_chunks 먼저

### 핵심 철학 — 이 작업이 의미하는 것

- **챗봇을 하나 만든 것이 아니다.** 검색과 생성 이전에 데이터 구조화와 관측 가능성을 확보하는 운영형 RAG 기반을 만들었다.
- **LLM은 핵심 저장소가 아니라 마지막 생성 엔진이다.** 문서가 들어와 검색 가능한 지식 자산이 되고, 권한과 trace를 가진 상태로 LLM에 전달되는 구조가 중요하다.
- **작은 포맷으로 전체 사이클을 먼저 닫고, 그 다음 포맷과 품질을 확장한다.** BM25 기준선을 먼저 안정화하고, 그 다음 vector/hybrid로 확장한다. 이 순서가 품질 측정 가능성을 보장한다.
- **저장소·인터페이스·workflow task 경계를 처음부터 잡았기 때문에**, 현재 NAS 문서 기반 MVP에서 멀티소스·멀티에이전트 플랫폼으로 확장할 수 있다. 나중에 경계를 다시 설계하지 않아도 된다.
- **운영형 RAG의 신뢰성은 추적 가능성에서 온다.** "왜 이 문서가 검색됐는가", "왜 이런 답변이 나왔는가"를 설명할 수 있어야 개선할 수 있다.

### 그림/다이어그램 아이디어
- **디버깅 순서 다이어그램** (수평 흐름)

```
"검색/답변이 안 된다"
        ↓
① ingestion 상태 확인    ② retrieval 품질 확인    ③ context 품질 확인    ④ LLM/프롬프트
   parse_status?             matched_fields?          generation_context      모델/temperature
   chunk 존재?               score 분포?              chunk 내용?
   index_status?             document recall?         치우침?
        ↓
   여기서 막히면
   parser·reprocess
```

- 슬라이드 하단 인용구 박스:
  > *"RAG는 검색 엔진과 LLM을 붙이는 것이 아니라,*
  > *데이터 파이프라인 전체를 신뢰 가능하게 만드는 작업이다."*

### 발표 스크립트
> 오늘 발표를 한 줄로 정리하면 이겁니다. "RAG는 파이프라인 전체를 신뢰 가능하게 만드는 작업이다." 문제가 생겼을 때 디버깅 순서는 정해져 있습니다. ingestion 상태 확인, retrieval 품질 확인, context 품질 확인, 그 다음에야 LLM 프롬프트나 모델을 봅니다. 이 순서를 뒤집으면 시간을 낭비합니다. 핵심 교훈 세 가지입니다. 첫째, 검색이 안 되면 ingestion 상태 컬럼을 먼저 본다. 둘째, chunk top-k와 document top-k는 다른 개념이다. 셋째, LLM 답변이 나쁘면 context를 먼저 의심한다. 지금은 NAS 문서 RAG MVP지만, 이 기반 위에 멀티소스·멀티에이전트가 올라올 수 있는 구조를 만들었습니다. 감사합니다.

### 부록 후보
- 운영형 RAG 교훈 12개 전체 목록 (`docs/presentation-outline.md` [16])
- RAG 구축 체크리스트 3단계

---

## Appendix 슬라이드 목록

질문이 나오거나 시간이 허락할 때 꺼내는 보조 슬라이드.

| Appendix | 내용 | 원본 출처 |
|----------|------|-----------|
| A-1 | 트러블슈팅 전체 12개 사례 (6개 테마 분류) | `presentation-outline.md` [10A~10F] |
| A-2 | RAG 구축 체크리스트 (ingestion→검색→운영 3단계) | `rag-troubleshooting-and-lessons.md` 말미 |
| A-3 | OpenSearch 매핑 전체 + nori analyzer 설정 | `search-index.md` |
| A-4 | chunking policy 상세 (크기·오버랩·heading 보존) | `chunking-strategy.md` |
| A-5 | alias switch 무중단 reindex 5단계 절차 | `architecture-overview.md` §5 |
| A-6 | 권한 전파 구조 전체 + trust boundary 한계 | `architecture-overview.md` §6 |
| A-7 | NFC/NFD 불일치 사례 + 전 구간 적용 방법 | `rag-troubleshooting-and-lessons.md` §23 |
| A-8 | 사내 LLM generate API 구조 + answer sanitizing | `backend-status.md` §2 |
| A-9 | Phase 2~3 로드맵 전체 | `todo-roadmap.md` |
| A-10 | POC UI 구조 + debug 패널 상세 | `poc-ui-design.md` |

---

## 관련 문서

- `docs/presentation-outline.md` — 이 문서의 원본 (상세 스크립트·전체 트러블슈팅 포함)
- `docs/architecture-overview.md` — 영역·저장소·workflow task 전체 구조
- `docs/rag-troubleshooting-and-lessons.md` — 트러블슈팅 상세 23개 이슈
- `docs/backend-status.md` — 현재 구현 상태 스냅샷
