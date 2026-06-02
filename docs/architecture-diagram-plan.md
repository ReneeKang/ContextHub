# ContextHub 발표용 아키텍처 다이어그램 설계

> PPT/Figma/draw.io에서 그릴 수 있도록 구성 요소·레이아웃·연결 관계·색상을 설계한 문서.
> 실제 그림 파일이 아니라 **제작 명세서**다.
> 발표 슬라이드 매핑은 `docs/presentation-slide-plan.md`를 참조한다.

---

## 공통 설계 원칙

| 원칙 | 내용 |
|------|------|
| **Layer vs task** | 영역(Layer)은 테두리 있는 큰 박스. workflow task(scanner·parser·chunker·indexer)는 영역 경계 위에 걸친 작은 원형/타원 레이블로 표현. 절대 Layer 박스와 동일한 크기로 그리지 않는다. |
| **영역 명칭** | "Layer 1", "Layer 2" 같은 번호 레이블은 사용하지 않는다. OSI 계층 구조와 혼동된다. "Source/Ingestion Area", "Document Transformation Area" 등 영역명 중심으로 표기한다. |
| **MVP vs 미래** | 현재 구현 = 실선 테두리 + 진한 색상. 미래/계획 = 점선 테두리 + 연한 색상(투명도 40%) |
| **저장소 역할 구분** | PostgreSQL = Source of Truth/Metadata Store (원본 기준). OpenSearch = Keyword Search Projection (재생성 가능). Vector DB = Semantic Index (미래). 세 저장소를 동일 수준으로 나열하면 역할이 혼동된다. |
| **Chunking 소속** | Chunking은 Document Transformation이 아니라 **Search Preparation** 영역이다. 그림에서 Document Processing 박스 안에 Chunking을 넣지 않는다. |
| **데이터 흐름** | 단방향 → 실선 화살표. 참조/fallback → 점선 화살표. 양방향 금지(단방향만 허용). |
| **폰트 크기** | 영역 제목: 14pt Bold. 저장소 이름: 12pt. workflow task 레이블: 10pt Italic. 메시지 캡션: 11pt. |

---

## 그림 1. 전체 AI 플랫폼 아키텍처

### 그림 제목
사내 지식 자산을 AI가 활용 가능한 구조로 — 멀티소스·멀티에이전트 플랫폼

### 핵심 메시지
> "사내 문서를 AI가 활용 가능한 지식 자산으로 전환한다.
> NAS 챗봇은 시작점이고, 멀티소스·멀티에이전트 구조는 처음부터 설계에 내재돼 있다."

---

### 레이아웃 설명

**전체 캔버스**: 가로 1600px × 세로 900px (16:9)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [ZONE A] 데이터 소스 (좌측 세로 컬럼, 너비 180px)                          │
│  [ZONE B] 처리 파이프라인 (중앙, 너비 700px, 영역 4개 세로 적층)            │
│  [ZONE C] 저장소 (중앙-우측, 너비 200px, 세로 배치)                         │
│  [ZONE D] 서빙·에이전트 (우측, 너비 280px)                                  │
│  [ZONE E] Observability/Governance (전체 하단 또는 배경 띠)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**5개 Zone 상세 배치**:

```
Zone A          Zone B (파이프라인)        Zone C (저장소)    Zone D (서빙)
────────        ─────────────────────     ───────────────    ──────────────────
NAS ──────►  Source/Ingestion        ──► raw_document
Wiki ─────►                              parse_result   ──► Search Preparation
Git ──────►  Document Transformation                         ↓
DB ───────►                              document_chunk ──► Search Serving Index
API ──────►  (워크플로우 태스크들)                            ↓
Logs ─────►                              OpenSearch     ──► Serving/RAG App
            Search Preparation      ──►                         ↓
            Search Serving Index        Vector DB       ──► Multi-Agent (미래)
                                        (미래)               ↓
                                                         LLM Gateway
────────────────────────────────────────────────────────────────────────────
                      Zone E: Observability / Governance (전체 하단 띠)
```

---

### 박스/컴포넌트 목록

#### Zone A — 데이터 소스 (6개 박스, 세로 배열)

| 컴포넌트 | 모양 | 색상 | MVP 여부 |
|----------|------|------|----------|
| NAS `local_nas/` | 사각형 + 드라이브 아이콘 | `#E3F2FD` (연파랑) 실선 | ✅ MVP |
| Wiki / Confluence | 사각형 + 책 아이콘 | `#E3F2FD` 점선 | 미래 |
| Git / Code Repo | 사각형 + 브랜치 아이콘 | `#E3F2FD` 점선 | 미래 |
| DB / 사내 시스템 | 실린더 | `#E3F2FD` 점선 | 미래 |
| External API | 사각형 + 화살표 아이콘 | `#E3F2FD` 점선 | 미래 |
| Logs / Event | 사각형 + 번개 아이콘 | `#E3F2FD` 점선 | 미래 |

소스 박스들을 세로로 배열하고 Zone B의 "Source/Ingestion" 박스로 향하는 수평 화살표를 연결한다.

#### Zone B — 처리 파이프라인 (4개 영역, 세로 적층)

| 영역(Layer) | 모양 | 배경색 | 테두리 | 높이 |
|-------------|------|--------|--------|------|
| Source / Ingestion | 사각형, 좌우 패딩 20px | `#E8F5E9` (연초록) | 실선 2px `#388E3C` | 120px |
| Document Transformation | 사각형 | `#FFF8E1` (연황) | 실선 2px `#F57F17` | 120px |
| Search Preparation | 사각형 | `#F3E5F5` (연보라) | 실선 2px `#7B1FA2` | 120px |
| Search Serving Index | 사각형 | `#FFF9C4` (연금) | 실선 2px `#F9A825` | 120px |

각 영역 박스 내부에 작은 이탤릭 텍스트로 "workflow tasks: scanner", "workflow tasks: parser", 등을 회색(`#9E9E9E`)으로 표시한다.

> **⚠️ 용어 주의**: Zone B에서 "Layer 1", "Layer 2" 같은 번호 표현은 사용하지 않는다. 이 그림은 OSI처럼 완전 단절된 계층 구조가 아니라, 저장소·책임·인터페이스 기준의 **capability area**를 표현한다. "Document Processing Area", "Search Preparation Area" 등 영역명 중심 표기를 사용한다. Layer라는 단어 자체는 괜찮지만 "Layer N" 형식의 번호 레이블은 오해를 만든다.

> **⚠️ Chunking 소속 주의**: Document Transformation 영역은 임의 포맷을 markdown/structured text로 변환하는 것까지가 책임이다. **Chunking(청킹)은 Document Transformation이 아니라 Search Preparation 영역에 속한다.** 마찬가지로 검색 품질을 위한 metadata enrichment(section_title, heading_path, page_no 생성)도 Search Preparation의 책임이다. 그림에서 Document Processing Area 박스 안에 "Chunking"을 넣으면 오해를 만든다. 반드시 별도 영역(Search Preparation)으로 분리해서 표시한다.

#### Zone C — 저장소와 검색 인덱스 역할 구분 (실린더 모양, 영역 박스 오른쪽에 위치)

저장소는 역할에 따라 세 유형으로 구분한다. 그림에서 실린더 오른쪽 또는 위에 역할 뱃지를 붙여 구분한다.

**① Metadata Store / Source of Truth** (PostgreSQL — 원본 상태와 권한의 기준 저장소)

| 저장소 | 모양 | 색상 | 역할 레이블 |
|--------|------|------|-------------|
| `raw_document` | 실린더 | `#ECEFF1` 실선 | "Metadata Store · 상태 컬럼 · 권한" |
| `document_parse_result` | 실린더 | `#ECEFF1` 실선 | "Parsed Document Store" |
| `document_chunk` | 실린더 | `#E8EAF6` (연남) **굵은 테두리 3px** | "**Silver — Source of Truth**" |

**② Keyword Search Index** (OpenSearch — Serving Index, 재생성 가능한 projection)

| 저장소 | 모양 | 색상 | 역할 레이블 |
|--------|------|------|-------------|
| OpenSearch `contexthub_chunks` | 실린더 | `#FFF9C4` (연금) **굵은 테두리 3px** | "**Gold — Search Projection / Serving Index**" |

**③ Semantic Retrieval Index** (Vector DB — 미래, semantic similarity 검색)

| 저장소 | 모양 | 색상 | 역할 레이블 |
|--------|------|------|-------------|
| Vector DB | 실린더 | `#FFF9C4` 점선 | "Semantic Index (미래)" |

> **역할 구분 요약 (슬라이드 캡션 또는 범례에 포함)**:
> - PostgreSQL = **Source of Truth / Metadata Store** — 원본 상태, 권한, 파이프라인 신호
> - OpenSearch = **Keyword Search Projection** — BM25, nori, boost. Silver에서 재생성 가능
> - Vector DB = **Semantic Retrieval Index** — 임베딩 기반 semantic 검색 (미래)
> - OpenSearch와 Vector DB는 **Serving Index** 역할. Postgres는 원본 기준 저장소

Silver / Gold 뱃지(작은 둥근 레이블)를 실린더 위에 붙인다.

#### Zone D — 서빙·에이전트 (우측 세로 배열)

| 컴포넌트 | 모양 | 색상 | MVP |
|----------|------|------|-----|
| Serving/RAG Application | 사각형 | `#FCE4EC` (연분홍) 실선 | ✅ 현재 중심 |
| Multi-Agent Router | 사각형 | `#FCE4EC` 점선 40% | 미래 확장 |
| LLM Gateway | 사각형 + 번개 아이콘 | `#EDE7F6` (연라벤더) 실선 | ✅ (OpenAI-compat) |

> **⚠️ Multi-Agent 위치 주의**: Multi-Agent System은 현재 구현된 Serving/RAG Application의 내부 기능이 **아니다**. 미래 확장 방향이다. 그림에서 반드시 점선 + 낮은 투명도로 표현하고, "future" 레이블을 붙인다. 현재 MVP의 중심은 Serving/RAG Application(ContextHub RAG Engine)이다. 장기적으로는 Multi-Agent Router가 RAG Engine, Tool Executor, LLM Gateway를 조합하는 orchestration 구조가 된다. 이 확장은 Serving/RAG 영역 인터페이스(`SearchClient`, `LLMClient`, `PermissionPrincipal`)를 바꾸지 않고 가능하도록 설계돼 있다.

#### Zone D-2 — 운영 라이프사이클 (Search Serving Index 영역 내부 또는 하위 박스)

Search Serving Index 영역 박스 내부 하단에 작은 박스들로 표현하거나, Zone C(저장소)와 Zone D(서빙) 사이에 별도 열로 배치한다.

| 컴포넌트 | 모양 | 색상 | 내용 |
|----------|------|------|------|
| Change Detection | 작은 사각형 | `#FFF9C4` 실선 | "파일 추가·수정·삭제 감지" |
| Reindex Queue | 작은 사각형 | `#FFF9C4` 실선 | "재색인 대상 chunk 큐" |
| Incremental Sync | 작은 사각형 | `#FFF9C4` 실선 | "delta 반영 (upsert/delete)" |
| Alias Switch | 작은 사각형 | `#FFF9C4` 실선 | "무중단 인덱스 교체" |

> **발표 설명 포인트**: "운영 환경에서는 개발환경의 `opensearch_reset_dev`(인덱스 drop + 전체 재생성)를 사용하지 않는다. 문서가 추가·수정·삭제될 때 서비스 중단 없이 검색 인덱스에 반영되어야 한다. 새 인덱스를 생성하고 데이터를 로딩한 뒤 alias를 switch해서 이전 인덱스를 대체하는 방식이 운영 표준이다."

운영 라이프사이클 박스들을 모두 연결하는 순환 화살표(점선 루프): Change Detection → Reindex Queue → Incremental Sync → Alias Switch → (다시 Change Detection 대기)

#### Zone E — Observability/Governance

전체 하단에 **얇은 가로 띠** (높이 50px). 배경 `#EFEBE9` (연브라운), 테두리 없음.
텍스트: "Observability / Governance — 상태 추적 · 권한 enforcement · retrieval debug · generation debug"

---

### 연결선 설명

| 출발 | 도착 | 선 종류 | 레이블 |
|------|------|---------|--------|
| NAS → Source/Ingestion | 실선 → | | |
| Source/Ingestion → raw_document | 실선 → | **scanner** (workflow task 레이블, 이탤릭) |
| raw_document → Document Transformation | 실선 → | `parse_status=PENDING` (작은 회색 텍스트) |
| Document Transformation → document_parse_result | 실선 → | **parser** (workflow task 레이블) |
| document_parse_result → Search Preparation | 실선 → | `chunk_status=PENDING` |
| Search Preparation → document_chunk | 실선 → | **chunker** |
| document_chunk → Search Serving Index | 실선 → | `index_status=PENDING` |
| Search Serving Index → OpenSearch | 실선 → | **indexer** |
| OpenSearch → Serving/RAG | 실선 → | |
| document_chunk → Serving/RAG | 점선 → | "DB fallback" |
| Serving/RAG → LLM Gateway | 실선 → | `/generate` |
| Serving/RAG → Multi-Agent Router | 점선 → | 미래 |
| Wiki/Git/DB/API → Source/Ingestion | 점선 → | 미래 소스 |
| OpenSearch → Vector DB | 점선 ↔ | "future hybrid" |

**workflow task 표현 방법**: 연결선 중간에 작은 타원(높이 20px)을 올려놓고 내부에 "scanner", "parser", "chunker", "indexer"를 이탤릭으로 표기. 타원 배경 흰색, 테두리 `#757575`.

---

### 강조 색상 추천

| 대상 | HEX | 용도 |
|------|-----|------|
| Source/Ingestion 영역 | `#388E3C` | 테두리·제목 |
| Document Transformation 영역 | `#F57F17` | 테두리·제목 |
| Search Preparation 영역 | `#7B1FA2` | 테두리·제목 |
| Search Serving Index 영역 | `#F9A825` | 테두리·제목 |
| Serving/RAG 영역 | `#C62828` | 테두리·제목 |
| Silver 뱃지 | `#78909C` | 배경 흰, 테두리 `#78909C` |
| Gold 뱃지 | `#F9A825` | 배경 흰, 테두리 `#F9A825` |
| MVP 컴포넌트 | 각 영역 색상 진하게 | 실선 |
| 미래 컴포넌트 | 각 영역 색상 연하게 (40% 투명도) | 점선 |
| Observability 띠 | `#BCAAA4` | 배경 |

---

### 발표 시 설명 포인트

1. **좌측에서 우측으로 읽는다**: 소스 → 파이프라인 → 저장소 → 서빙. 데이터가 성숙해지면서 흐른다.
2. **MVP(실선)와 미래(점선)를 구분해서 읽는다**: 지금 구현된 것과 확장 방향이 같은 그림 안에 있다.
3. **workflow task 타원을 가리키며**: "scanner, parser, chunker, indexer는 영역이 아니라 영역 경계를 넘어가는 실행 단위다. Layer 박스와 혼동하지 않도록 별도 표기했다."
4. **Silver/Gold 뱃지를 가리키며**: "PostgreSQL document_chunk가 Silver, 즉 Source of Truth다. OpenSearch는 Gold, 즉 projection이다. Gold가 날아가도 Silver로 재생성 가능하다."
5. **Observability 띠를 가리키며**: "Observability/Governance는 특정 영역이 아니라 전체를 가로지른다."

---

### PPT/Figma/draw.io 구현 팁

**PowerPoint**
- SmartArt > "프로세스" 템플릿을 기반으로 Zone B를 만들고, 나머지를 텍스트 상자로 추가한다.
- 실린더 모양: 삽입 > 도형 > 실린더. 3D 효과 없이 평면으로 사용한다.
- 점선 테두리: 도형 서식 > 선 > 대시 유형 > "파선".
- workflow task 타원: 도형 > 타원, 흰 배경, 회색 테두리 1px, 텍스트 이탤릭 10pt.
- 그룹화: Zone별로 개체를 그룹으로 묶어 전체 이동 시 레이아웃이 흐트러지지 않게 한다.

**Figma**
- Frame: 1600×900, 배경 `#FAFAFA`.
- Auto Layout을 Zone B에 적용해 영역 박스 간격을 균등하게 유지한다.
- Component로 workflow task 타원을 만들어 재사용한다.
- 미래 컴포넌트: Opacity 40% 레이어 + 점선 stroke.

**draw.io**
- 실린더: Search > "cylinder". Label 위치는 center-bottom.
- Swimlane 레이아웃으로 Zone A/B/C/D를 분리한다.
- Edge style: `edgeStyle=orthogonalEdgeStyle` + `dashed=1` for 점선.
- workflow task 타원: shape=ellipse, fillColor=#FFFFFF, strokeColor=#757575, fontStyle=2(Italic).

---

## 그림 2. ContextHub RAG 데이터 흐름

### 그림 제목
ContextHub MVP — 현재 구현한 데이터 흐름

### 핵심 메시지
> "Bronze 원본 → Silver 구조화 → Gold 검색 최적화 → 답변 생성.
> workflow task는 영역 경계를 연결하는 실행 단위이고, OpenSearch는 projection이다."

---

### 레이아웃 설명

**전체 캔버스**: 가로 1600px × 세로 1000px

**3-Track 수직 레이아웃**:

```
                        ┌──────────────────────────────────────────────┐
                        │          중앙: 처리 흐름 (Main Track)         │
 좌측:                  │                                              │  우측:
 저장소 레이블          │  NAS (Bronze)                                │  상태 컬럼
 + 뱃지                 │     │ [scanner]                              │  신호 표시
                        │  raw_document                                │
                        │     │ [parser]                               │
                        │  document_parse_result                       │
                        │     │ [chunker]                              │
                        │  document_chunk (Silver)                     │
                        │     │ [indexer]                              │
                        │  OpenSearch (Gold)                           │
                        │     │                                        │
                        │  ┌──┴──────────────┐                        │
                        │  │   Serving 분기   │                        │
                        │  /discover  /generate                       │
                        │      │           │                           │
                        │  doc grouping  context                       │
                        │      │         packing                       │
                        │  candidates   LLM call                       │
                        │              answer+sources                  │
                        └──────────────────────────────────────────────┘
                        하단 전체 띠: Observability / Governance
```

**메인 트랙 좌측에 Bronze/Silver/Gold 구간 표시**:
- NAS ~ raw_document 구간 옆: `🟫 Bronze` 뱃지
- document_parse_result ~ document_chunk 구간 옆: `⬜ Silver` 뱃지
- OpenSearch 구간 옆: `🟡 Gold` 뱃지

---

### 박스/컴포넌트 목록

#### 저장소 컴포넌트 (실린더/DB 모양)

| 컴포넌트 | 색상 | 테두리 | 내부 텍스트 |
|----------|------|--------|-------------|
| NAS `local_nas/` | `#EFEBE9` (연갈색) | `#795548` 실선 2px | "txt·pdf·docx·xlsx·hwp" |
| `raw_document` | `#F5F5F5` | `#757575` 실선 | "ingest/parse/chunk_status" |
| `document_parse_result` | `#F5F5F5` | `#757575` 실선 | "structured text / parsed document (markdown_text, metadata_json)" |
| `document_chunk` | `#E8EAF6` (연남색) | `#3949AB` **굵은선 3px** | "chunk_text, section_title, heading_path, page_no, 권한 메타" |
| OpenSearch | `#FFFDE7` (연금) | `#F9A825` **굵은선 3px** | "contexthub_chunks — Gold (Search Projection / Serving Index)" |

#### 영역(Layer) 구분 배경

메인 트랙 전체에 Layer 구분을 **옅은 배경 띠**로 표현한다. 박스 테두리 없이 배경 색상만으로 구분한다.

| 영역 | 배경 | 적용 범위 |
|------|------|-----------|
| Source/Ingestion | `#F1F8E9` 10% 투명도 | NAS → raw_document 구간 |
| Document Transformation | `#FFF8E1` 10% 투명도 | raw_document → document_parse_result 구간 |
| Search Preparation | `#F3E5F5` 10% 투명도 | document_parse_result → document_chunk 구간 |
| Search Serving Index | `#FFFDE7` 10% 투명도 | document_chunk → OpenSearch 구간 |
| Serving/RAG | `#FCE4EC` 10% 투명도 | OpenSearch → 답변 구간 |

영역 배경 좌측에 세로로 영역명을 회전 텍스트(rotate 90°)로 붙인다.

#### workflow task 타원 (연결선 위에 위치)

| task | 위치 | 색상 |
|------|------|------|
| scanner | NAS → raw_document 화살표 중간 | 흰색 배경, `#388E3C` 테두리 |
| parser | raw_document → document_parse_result 중간 | 흰색 배경, `#F57F17` 테두리 |
| chunker | document_parse_result → document_chunk 중간 | 흰색 배경, `#7B1FA2` 테두리 |
| indexer | document_chunk → OpenSearch 중간 | 흰색 배경, `#F9A825` 테두리 |

타원 크기: 너비 80px × 높이 28px. 폰트: 10pt Italic.

#### Serving 분기 컴포넌트

OpenSearch 아래에서 **두 갈래** 화살표로 분기한다.

| 컴포넌트 | 색상 | 내용 |
|----------|------|------|
| `/discover` 경로 박스 | `#E8F5E9` | "chunk over-fetch → doc grouping → score filter → candidates" |
| `/generate` 경로 박스 | `#FCE4EC` | "chunk retrieval → context packing → LLM call" |
| LLM (Stateless) | `#EDE7F6` (연라벤더) | "messages + context → answer" |
| `answer + sources[] + debug{}` | 흰색, 굵은 테두리 | 최종 출력 |

LLM 박스 좌측에 작은 캡션: *"메모리 없음 · 세션 없음 · stateless"*

> **⚠️ Retriever 위치 주의**: Retriever를 독립 레이어나 별도 저장소처럼 표현하지 않는다. Retriever는 Serving/RAG Application 내부의 검색 전략 컴포넌트다. `/discover` 경로 박스 내부에 "chunk retrieval → doc grouping → ranking → filtering" 흐름으로 표현하는 것이 정확하다. 독립 박스로 빼면 영역(Layer) 구조와 혼동된다.

> **⚠️ generation_context_chunks 위치 주의**: `generation_context_chunks`를 파이프라인 중앙의 저장소처럼 표현하지 않는다. 이것은 저장소가 아니라 **observability/debug artifact**이면서, retrieval 결과가 generation으로 넘어가는 인터페이스를 보여주는 산출물이다. `/generate` 경로 박스 내부 또는 오른쪽 Observability 패널에 점선으로 연결하는 방식을 권장한다. 또는 `/generate` 박스 위에 작은 캡션으로 "context selected for LLM (generation_context_chunks)"라고 표기하는 방법도 있다. 중앙 파이프라인 흐름에서 독립 박스로 배치하면 저장소 역할이 있는 것처럼 오해된다.

#### 우측 상태 컬럼 신호 패널

메인 트랙 우측에 **좁은 세로 패널** (너비 140px):

```
ingest_status
 └─ RECEIVED ──► parse_status
     └─ PENDING ──► parser 픽업
         └─ DONE ──► chunk_status
             └─ PENDING ──► chunker 픽업
                 └─ DONE ──► index_status
                     └─ PENDING ──► indexer 픽업
```

배경 `#FAFAFA`, 테두리 없음, 회색 점선으로 저장소 컴포넌트와 연결.

---

### 연결선 설명

| 출발 | 도착 | 선 | 레이블 |
|------|------|-----|--------|
| NAS → raw_document | 실선 → | `ingest_status=RECEIVED` |
| raw_document → document_parse_result | 실선 → | `parse_status=PENDING` |
| document_parse_result → document_chunk | 실선 → | `chunk_status=PENDING` |
| document_chunk → OpenSearch | 실선 → | `index_status=PENDING` |
| OpenSearch → /discover 경로 | 실선 → 분기 | |
| OpenSearch → /generate 경로 | 실선 → 분기 | |
| document_chunk → /generate 경로 | 점선 → | "selected-document DB fallback" |
| /generate 경로 → LLM | 실선 → | |
| LLM → answer+sources | 실선 → | |

**주의**: document_chunk ↔ OpenSearch는 단방향. OpenSearch → document_chunk 역방향 없음.

---

### 강조 색상 추천

| 대상 | HEX |
|------|-----|
| Bronze 뱃지 | `#795548` 테두리, `#EFEBE9` 배경 |
| Silver 뱃지 | `#3949AB` 테두리, `#E8EAF6` 배경 |
| Gold 뱃지 | `#F9A825` 테두리, `#FFFDE7` 배경 |
| 상태 컬럼 텍스트 | `#757575` (회색) |
| DB fallback 점선 | `#9E9E9E` |
| LLM "stateless" 캡션 | `#7B1FA2` Italic |

---

### 발표 시 설명 포인트

1. **왼쪽에 Bronze/Silver/Gold 뱃지를 가리키며**: "데이터가 성숙해지면서 Bronze 원본에서 Silver 구조화 단계를 거쳐 Gold 검색 최적화로 흐른다. Silver인 document_chunk가 Source of Truth다."
2. **workflow task 타원을 가리키며**: "scanner, parser, chunker, indexer는 영역 박스가 아니다. 영역과 영역 사이의 경계를 연결하는 실행 단위다. 이 구분이 중요하다."
3. **상태 컬럼 패널을 가리키며**: "영역 간 연결은 HTTP가 아니라 DB 상태 컬럼이다. parse_status가 PENDING이 되면 parser가 픽업한다. 검색이 안 될 때 이 순서대로 확인한다."
4. **Serving 분기를 가리키며**: "/discover는 문서 후보를 만들고, /generate는 LLM을 호출한다. 두 엔드포인트가 분리돼 있어 retrieval 품질과 generation 품질을 독립적으로 진단할 수 있다."
5. **LLM 박스의 'stateless' 캡션을 가리키며**: "LLM은 상태가 없다. context chunks만 받아서 answer를 반환한다. context가 나쁘면 LLM을 바꿔도 답변이 좋아지지 않는다."
6. **OpenSearch 실린더를 가리키며**: "OpenSearch는 keyword retrieval 하나만을 위한 도구가 아니다. BM25 기반 multi-match, nori 형태소 분석기, metadata filtering, filename·path·section_title·heading_path boost가 모두 들어간다. 나중에 knn 기반 vector 필드를 추가해 hybrid retrieval로 전환할 수도 있다. 지금 BM25로 시작해도 hybrid 기반을 동시에 확보하는 셈이다." (이 설명은 그림 박스 안에 전부 넣지 말고 발표 스크립트에서 구두로 설명한다. 그림 박스에는 "BM25 · nori · metadata boost · future hybrid" 정도의 짧은 subcaption만 넣는다.)
7. **document_parse_result 실린더를 가리키며**: "parse 결과는 단순 markdown만이 아니다. OCR text, table extraction, structured text까지 확장 가능한 형태로 저장된다. 발표에서는 markdown_text보다 'structured text / parsed document'로 표현하는 것이 더 정확하다."

---

### PPT/Figma/draw.io 구현 팁

**PowerPoint**
- 배경 띠(영역 구분): 도형 > 사각형, 선 없음, 채우기 색상 투명도 90%. 가장 뒤 레이어에 배치.
- 세로 영역명 텍스트: 텍스트 상자 선택 > 서식 > 텍스트 방향 > 90° 회전.
- 상태 컬럼 패널: 별도 텍스트 상자에 들여쓰기로 트리 구조 표현. SmartArt 사용하지 않는다(정렬이 흐트러짐).
- 분기 화살표: 커넥터 도구로 OpenSearch에서 두 경로로 나가는 elbow connector 사용.

**Figma**
- Vertical Flow: Auto Layout(Vertical) + Gap 40px로 저장소 스택 구성.
- 배경 띠: Rectangle을 각 구간 높이에 맞게 배치, Fill `#F3E5F5` Opacity 10%.
- workflow task 타원: Component로 만들어 color variant(scanner/parser/chunker/indexer)별로 stroke 색 변경.
- 상태 컬럼: 별도 Frame으로 분리해 마스킹.

**draw.io**
- 배경 띠: 사각형 + `fillColor=#F3E5F5;opacity=10;strokeColor=none`.
- 세로 영역명: `label` + `rotation=-90;fontStyle=1`.
- workflow task 타원: `shape=ellipse;fillColor=#FFFFFF;strokeColor=#388E3C;fontStyle=2`.
- 상태 컬럼 트리: `shape=mxgraph.flowchart.decision` 사용하지 말고 단순 label + edge로 구성.
- Bronze/Silver/Gold 뱃지: `shape=mxgraph.basic.rect;rounded=1` + 별도 색상.

---

## 그림 3. Retrieval vs Generation 분리 구조

### 그림 제목
Retrieval과 Generation은 독립 품질 영역이다

### 핵심 메시지
> "LLM이 이상한 게 아니라 context 품질 문제일 수 있다.
> retrieval과 generation은 독립 품질 영역이고, 진단도 독립적으로 수행한다."

---

### 레이아웃 설명

**전체 캔버스**: 가로 1400px × 세로 800px

**3-Column 레이아웃**:

```
┌────────────────────┬──────────────────────┬────────────────────────┐
│                    │                      │                        │
│  LEFT COLUMN       │  CENTER COLUMN       │  RIGHT COLUMN          │
│  Search/Retrieval  │  인터페이스 브릿지    │  Generation            │
│  (파란 계열)        │  (주황 계열)          │  (초록 계열)            │
│  너비 400px        │  너비 300px          │  너비 400px            │
│                    │                      │                        │
└────────────────────┴──────────────────────┴────────────────────────┘
          ↑                    ↑                        ↑
   "검색 품질 영역"      "인터페이스 계약"          "생성 품질 영역"
```

**컬럼 상단에 큰 제목 박스**:
- 좌: `검색·Retrieval` (파란 배경)
- 중: `인터페이스` (주황 배경)
- 우: `생성·Generation` (초록 배경)

**컬럼 하단에 진단 패널**:
- 좌 하단: `/query` + `/discover` API 박스
- 우 하단: `/generate` API 박스
- 중 하단: 두 경로가 만나는 지점

---

### 박스/컴포넌트 목록

#### 좌측 컬럼 — Search/Retrieval (위→아래 순서)

| 컴포넌트 | 모양 | 배경색 | 내용 |
|----------|------|--------|------|
| **[1] 질의 입력** | 사각형, 모서리 둥글게 | `#E3F2FD` | "사용자 질의 → `retrieval_query` 정규화 (NFC)" |
| **[2] OpenSearch BM25** | 사각형 | `#BBDEFB` | "multi_match: filename·section_title·heading_path·chunk_text" |
| **[3] boost 필드** | 내부 표 | `#BBDEFB` | "filename×4 / section×3 / heading×2 / path×1.5 / text×1" |
| **[4] chunk over-fetch** | 사각형 | `#90CAF9` | "size = max(top_k×10, 50)" |
| **[5] document grouping** | 사각형 | `#90CAF9` | "raw_document_id 기준 그룹핑" |
| **[6] score filtering** | 사각형 | `#64B5F6` | "상대 점수 ≥ 0.1 AND has_highlight" |
| **[7] (미래) reranking** | 사각형, 점선 테두리 | `#BBDEFB` 연하게 | "cross-encoder 재정렬" |
| **[8] document candidates** | 둥근 사각형, 진한 테두리 | `#1565C0` 배경, 흰 텍스트 | "Document Candidate[]" |

좌측 컬럼 제목: `Search / Retrieval` — `#1565C0` 배경, 흰 텍스트, 굵은 폰트.

#### 가운데 컬럼 — 인터페이스 브릿지 (위→아래)

| 컴포넌트 | 모양 | 배경색 | 내용 |
|----------|------|--------|------|
| **[A] retrieval debug** | 사각형 | `#FFF3E0` | "`matched_fields`·`highlight_terms`·`score`·`document_rank`·`chunk_rank`" |
| **[B] generation_context_chunks** | 사각형, **굵은 강조 테두리** | `#FFE0B2` (진주황) | "LLM에 실제로 전달된 chunk 목록 preview" |
| **[C] sources[]** | 사각형 | `#FFF3E0` | "hits 객체에서 직접 구성. LLM 출력 파싱 없음" |
| **[D] debug{}** | 사각형 | `#FFF3E0` | "ENABLE_RETRIEVAL_DEBUG=true 시 응답에 포함" |
| **[E] 진단 분리선** | 수평 점선 | — | 텍스트: *"이 경계를 기준으로 독립 진단"* |

가운데 컬럼 제목: `인터페이스 / 브릿지` — `#E65100` 배경, 흰 텍스트.

가운데 컬럼 중앙에 핵심 메시지 박스:
```
┌───────────────────────────────────────┐
│  "LLM이 이상한 게 아니라              │
│   context 품질 문제일 수 있다"         │
│                                       │
│  진단 순서:                            │
│  ① retrieval debug 확인               │
│  ② generation_context_chunks 확인     │
│  ③ 그 다음에야 LLM/프롬프트           │
└───────────────────────────────────────┘
```
배경 `#FFF3E0`, 테두리 `#E65100` 2px, 폰트 Bold.

#### 우측 컬럼 — Generation (위→아래)

| 컴포넌트 | 모양 | 배경색 | 내용 |
|----------|------|--------|------|
| **[I] context packing** | 사각형 | `#E8F5E9` | "`build_nas_rag_user_prompt`: CONTEXT 블록 조립" |
| **[II] token budget** | 사각형 | `#E8F5E9` | "선택 문서 청크 우선 → 컨텍스트 길이 제한" |
| **[III] prompt template** | 사각형 | `#C8E6C9` | "system_prompt + user_prompt (QUESTION + CONTEXT 블록)" |
| **[IV] LLM call** | 사각형, **굵은 테두리** | `#4CAF50` 배경, 흰 텍스트 | "LLMClient.complete(messages, model, temp)" |
| **[V] stateless** | 작은 캡션 박스 | — | *"메모리 없음·세션 없음·toolcall 없음"* |
| **[VI] citation** | 사각형 | `#A5D6A7` | "출처 = hits 객체에서 직접. LLM 파싱 없음" |
| **[VII] answer + sources** | 둥근 사각형, 진한 테두리 | `#1B5E20` 배경, 흰 텍스트 | "answer (str) + sources[] + debug{}" |

우측 컬럼 제목: `Generation` — `#1B5E20` 배경, 흰 텍스트.

#### 하단 — API 엔드포인트 진단 패널

좌측 컬럼 하단에 두 개의 API 박스:
```
┌─────────────┐    ┌──────────────────────┐
│ /query      │    │ /discover            │
│ retrieval   │    │ retrieval +          │
│ only        │    │ doc grouping         │
│ LLM 없음    │    │ LLM 없음             │
└─────────────┘    └──────────────────────┘
   ▲                        ▲
   └────────┐ ┌─────────────┘
            ▼ ▼
         retrieval 품질만 독립 검증
```

우측 컬럼 하단:
```
┌──────────────────────────┐
│ /generate                │
│ retrieval + LLM 호출     │
│ generation 품질 포함      │
└──────────────────────────┘
         ▲
 generation 품질 추가 검증
```

가운데 하단 연결 텍스트: `"mock을 끄면 generation 품질만 변수로 남는다"`

---

### 연결선 설명

| 출발 | 도착 | 선 | 방향 |
|------|------|-----|------|
| [1] 질의 → [2] BM25 | 실선 → | 좌측 컬럼 내부 하향 |
| [2] BM25 → [3] boost | 실선 → | |
| [3] → [4] chunk over-fetch | 실선 → | |
| [4] → [5] grouping | 실선 → | |
| [5] → [6] filtering | 실선 → | |
| [6] → [8] candidates | 실선 → | |
| [7] reranking → [8] | 점선 → | "미래" |
| [8] candidates → [A] retrieval debug | 실선 → | 좌→중 수평 화살표 |
| [A] debug → [B] gen_context_chunks | 실선 → | 중앙 컬럼 내부 하향 |
| [B] gen_context_chunks → [I] context packing | 실선 → | 중→우 수평 화살표, **굵은 강조선** |
| [I] → [II] → [III] → [IV] | 실선 → | 우측 컬럼 하향 |
| [IV] LLM → [VI] citation | 실선 → | |
| [VI] → [VII] answer+sources | 실선 → | |
| [VII] → [C] sources[] | 실선 → | 우→중 역방향 점선 화살표 |
| [C] sources → [D] debug{} | 실선 → | 중앙 컬럼 내부 |

**좌우 컬럼의 하단 API 박스 연결**:
- `/query` + `/discover` 박스는 좌측 컬럼 [6] filtering 이후에서 분기
- `/generate` 박스는 우측 컬럼 [IV] LLM call 이후

---

### 강조 색상 추천

| 대상 | HEX |
|------|-----|
| 좌측 컬럼 (Retrieval) 계열 | `#1565C0` (진파랑) → `#BBDEFB` (연파랑) 그라디언트 상단→하단 |
| 우측 컬럼 (Generation) 계열 | `#1B5E20` (진초록) → `#C8E6C9` (연초록) |
| 가운데 컬럼 (인터페이스) | `#E65100` (진주황) → `#FFF3E0` (연주황) |
| `generation_context_chunks` 박스 강조 | `#FF6F00` 테두리 3px + 그림자 효과 |
| 핵심 메시지 박스 | `#E65100` 테두리, 약간 그림자 |
| "미래" 컴포넌트 | 모두 점선 + 40% 투명도 |

**색상 법칙**: 좌측은 파랑 계열(검색=차가운 정밀도), 우측은 초록 계열(생성=따뜻한 창의), 가운데는 주황(두 영역의 경계·인터페이스).

---

### 발표 시 설명 포인트

1. **3개 컬럼 전체를 가리키며 오프닝**: "이 그림 한 장이 핵심 교훈 3번을 설명합니다. Retrieval과 Generation은 독립 품질 영역입니다."
2. **좌측 컬럼을 가리키며**: "검색 품질은 BM25 score, boost 설정, document grouping, filtering에 의해 결정됩니다. LLM과는 무관합니다."
3. **가운데 `generation_context_chunks` 박스를 강조하며**: "이 박스가 두 영역의 인터페이스입니다. Retrieval이 고른 chunk가 Generation에 전달됩니다. LLM이 실제로 받은 context가 무엇인지 이 debug로 확인합니다."
4. **우측 컬럼을 가리키며**: "Generation 품질은 context packing, prompt template, LLM 모델에 의해 결정됩니다. 검색 결과가 나쁘면 아무리 좋은 LLM도 한계가 있습니다."
5. **하단 API 박스를 가리키며**: "/query와 /discover로 LLM 없이 retrieval 품질만 검증합니다. 이게 괜찮으면 mock을 끄고 /generate로 전환합니다. 이때 generation 품질만 변수가 남습니다."
6. **핵심 메시지 박스를 가리키며 마무리**: "'LLM이 이상하다'는 결론 전에 반드시 generation_context_chunks를 확인합니다. context 품질 문제를 LLM 문제로 오진하는 것이 가장 흔한 실수입니다."

---

### PPT/Figma/draw.io 구현 팁

**PowerPoint**
- 3-column 구조: 슬라이드에 세로 가이드를 3분할로 설정한다 (보기 > 안내선).
- 컬럼 내부 컴포넌트 세로 정렬: 동일 간격 정렬(Ctrl+A 선택 후 "세로 균등 분배").
- `generation_context_chunks` 박스 강조: 도형 > 그림자 효과 > 바깥쪽 오른쪽 아래. 테두리 색 `#FF6F00` 3px.
- 핵심 메시지 박스: 도형 > 텍스트 상자 > 테두리 `#E65100` 점선 2px + 배경 `#FFF3E0`.
- 컬럼 제목 박스: 도형 > 직사각형, 배경 진한색, 흰 텍스트 14pt Bold.

**Figma**
- 3개 Frame을 나란히 배치하고 각각 `Retrieval`, `Interface`, `Generation` 이름 부여.
- 컬럼 간 화살표: Component connector로 `Arrow`를 Frame 경계에 연결. 화살표 색상은 컬럼 출발 색상 사용.
- `generation_context_chunks` 강조: Drop shadow + stroke 3px `#FF6F00`.
- Auto Layout(Vertical) + padding 16px로 각 컬럼 내부 컴포넌트 간격 균등 유지.

**draw.io**
- 3-column swimlane: `shape=pool;startSize=30` + 3개 lane.
- `generation_context_chunks`: `strokeColor=#FF6F00;strokeWidth=3;shadow=1`.
- 컬럼 간 수평 화살표: `edgeStyle=elbowEdgeStyle;elbow=vertical`.
- 미래 컴포넌트: `dashed=1;opacity=40`.
- 핵심 메시지 박스: `shape=mxgraph.basic.rect;rounded=1;fillColor=#FFF3E0;strokeColor=#E65100;strokeWidth=2;fontStyle=1`.

---

## 슬라이드 배치 요약

| 그림 | 추천 슬라이드 | 대응 발표 슬라이드 번호 |
|------|--------------|------------------------|
| 그림 1 — 전체 플랫폼 아키텍처 | 단독 슬라이드 1장 | 슬라이드 03 (아키텍처 개요) + 슬라이드 17 (확장 방향) |
| 그림 2 — RAG 데이터 흐름 | 단독 슬라이드 1장 | 슬라이드 06 (데이터 흐름) |
| 그림 3 — Retrieval vs Generation | 단독 슬라이드 1장 | 슬라이드 11 (검색 후처리) + 슬라이드 12 (생성) + 슬라이드 13 (관측성) |

그림 2는 애니메이션 활용 시 단계별로 나타나도록 구성하면 효과적이다:
- Step 1: NAS → raw_document (scanner 타원 등장)
- Step 2: → document_parse_result (parser 타원 등장)
- Step 3: → document_chunk (Silver 뱃지 등장)
- Step 4: → OpenSearch (Gold 뱃지 등장)
- Step 5: 분기 → /discover / /generate

---

## 관련 문서

- `docs/presentation-slide-plan.md` — 슬라이드별 그림 사용 계획
- `docs/presentation-outline.md` — 발표 스크립트 원본
- `docs/architecture-overview.md` — 영역·저장소·workflow task 정의
