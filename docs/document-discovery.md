# Document Discovery / Selection 계층 설계

## 문서 목적

현재 ContextHub의 chunk 중심 검색 → 즉시 LLM 응답 흐름에
**문서 단위 탐색 및 선택 계층**을 어떻게 추가할지 설계한다.

코드 구현 지침이 아니라 **설계 검토 문서**다.
scanner / parser / chunker / indexer는 이 설계에서 건드리지 않는다.

---

## 1. 왜 이 계층이 필요한가

### 현재 관찰된 문제 (실제 사례)

`public/projects/sanrim-platform/` 아래 산림공간 디지털 플랫폼 문서를 색인했을 때:

| 질의 | 결과 | 문제 |
|------|------|------|
| `"산림공간 디지털 플랫폼"` | `ID_P05_테일러링내역서.pdf` 청크 반환 | 청크는 맞지만 사용자는 "어떤 문서에서 온 건지" 모름 |
| `"산출내역서"` | `테일러링내역서.pdf` 청크 반환 | 유사어 매칭이지만 제목이 달라 사용자 혼란 |
| `"제안요청서"` | 결과 없음 | 문서는 있지만 청크 키워드 미스 |

현재 응답은 **청크 중심**이어서, 문서가 수십~수백 개로 늘면:

- 같은 문서의 청크가 여러 개 나와도 "어떤 문서"인지 표면에 드러나지 않는다
- LLM이 연관성 낮은 청크까지 컨텍스트로 받아 hallucination 위험이 높아진다
- 사용자가 "이 주제는 어떤 문서를 봐야 하는가"를 파악할 수 없다

### 운영형 사내 문서 플랫폼에서 이 계층이 필요한 이유

성숙한 사내 지식 플랫폼(Confluence, Notion, SharePoint)은 모두 같은 패턴을 쓴다.

```
1단계: 탐색 (Discovery)
  질문/키워드로 관련 문서 후보 목록 제시
  → 파일명, 경로, 섹션, 점수, 최신성

2단계: 선택 (Selection)
  사용자가 특정 문서(들)를 선택하거나 범위를 좁힘

3단계: 생성 (Generation)
  선택된 문서 범위 안에서 LLM 답변 생성
```

이 흐름이 없으면 RAG는 "LLM이 아무 문서나 참고해서 답변하는 블랙박스"로 남는다.
사용자가 답변 근거를 신뢰하려면 **어떤 문서를 선택했는지 알아야** 한다.

---

## 2. 현재 아키텍처에서의 위치

### 기존 흐름

```
question
  → normalize_retrieval_query()
  → SearchClient.search(query, permission_filter, top_k)
  → SearchHit[]  ← chunk 단위
  → (즉시) LLM 프롬프트 조립
  → LLM 호출
  → answer + sources
```

### 제안 흐름

```
question
  → normalize_retrieval_query()
  → SearchClient.search(query, permission_filter, top_k_chunks)  ← 변경 없음
  → SearchHit[]  ← chunk 단위, 변경 없음
  → [신규] group_hits_by_document(hits)
  → DocumentCandidate[]  ← 문서 단위 그룹
  → (탐색 모드) 후보 목록 반환  ←─── /discover 엔드포인트
       ↓ 사용자 선택
  → (생성 모드) selected_document_ids 기준 필터링
  → 선택된 청크만 LLM 컨텍스트로 사용
  → answer + sources  ←───────────── /generate 엔드포인트 (확장)
```

### 어느 계층에 두는가

| 계층 | 역할 | 이 설계에서 |
|------|------|-----------|
| `app/adapters/` | 외부 인터페이스 추상화 (SearchClient, LLMClient) | 변경 없음 |
| `app/chat/` | HTTP 요청 처리, 스키마, 서비스 조율 | **신규 discovery_service.py 추가** |
| `app/agents/` | RAG 오케스트레이션, 프롬프트 조립 | 선택 필터 수용 확장 |
| `app/scanner~indexer/` | NAS 반입 파이프라인 | 변경 없음 |

`group_hits_by_document()`는 `app/chat/discovery_service.py`에 위치한다.
외부 I/O가 없는 순수 변환 함수이므로 adapter 계층이 아니라 service 계층이 맞다.

---

## 3. DocumentCandidate 데이터 모델

chunk 단위 `SearchHit`을 document 단위로 집계한 결과 구조.

```python
@dataclass
class DocumentCandidate:
    # 문서 식별
    raw_document_id: str           # raw_document.raw_document_id
    original_filename: str         # 파일명 (표시용)
    stored_path: str               # NAS 절대 경로
    file_ext: str                  # pdf / docx / hwp / txt

    # 경로 기반 추론
    inbox_path: str                # 공식 반입 폴더 내 상대 경로
    project_key: str | None        # 경로에서 추론 (아래 참조)
    path_display: str              # UI 표시용 경로 요약

    # 검색 집계
    matched_chunk_count: int       # 이 문서에서 매칭된 청크 수
    top_score: float               # 청크 중 최고 점수
    avg_score: float               # 청크 평균 점수
    representative_sections: list[str]  # 상위 N개 section_title (중복 제거)

    # 권한
    access_scope: str              # PUBLIC | DEPT | PRIVATE
    department_code: str | None

    # 시간
    indexed_at: datetime | None    # 색인 완료 시각 (document_chunk.created_at 기준)
```

### 집계 규칙

```python
def group_hits_by_document(hits: list[SearchHit]) -> list[DocumentCandidate]:
    groups: dict[str, list[SearchHit]] = {}
    for hit in hits:
        groups.setdefault(hit.raw_document_id, []).append(hit)

    candidates = []
    for doc_id, doc_hits in groups.items():
        first = doc_hits[0]   # 공통 메타는 첫 번째 hit에서 추출
        candidates.append(DocumentCandidate(
            raw_document_id=doc_id,
            original_filename=first.original_filename,
            matched_chunk_count=len(doc_hits),
            top_score=max(h.score for h in doc_hits),
            avg_score=sum(h.score for h in doc_hits) / len(doc_hits),
            representative_sections=_top_sections(doc_hits, n=3),
            # ... 나머지 필드
        ))

    # 기본 정렬: top_score 내림차순
    return sorted(candidates, key=lambda c: c.top_score, reverse=True)
```

**정렬 정책 (기본)**:
- 1순위: `top_score` 내림차순 (가장 관련성 높은 청크가 있는 문서)
- 선택 정렬: `matched_chunk_count` (여러 섹션에서 언급된 문서), `indexed_at` 최신 우선

---

## 4. project_key 추론

NAS 경로 패턴에서 `project_key`를 자동으로 추출한다.
인덱서 변경 없이 `inbox_path`(기존 컬럼)를 파싱한다.

```
/nas/chatbot_docs/public/projects/sanrim-platform/ID_P05_테일러링내역서.pdf
  → project_key = "sanrim-platform"

/nas/chatbot_docs/public/projects/cloud-migration/설계서.pdf
  → project_key = "cloud-migration"

/nas/chatbot_docs/dept/infra/운영가이드.pdf
  → project_key = None  (부서 문서, project 없음)

/nas/chatbot_docs/public/보안정책.pdf
  → project_key = None  (최상위 공용 문서)
```

추출 규칙: `inbox_path`에서 `/projects/{slug}/` 패턴 추출.

```python
import re

_PROJECT_PATTERN = re.compile(r"/projects/([^/]+)/")

def infer_project_key(inbox_path: str) -> str | None:
    m = _PROJECT_PATTERN.search(inbox_path)
    return m.group(1) if m else None
```

이 함수는 `group_hits_by_document()` 내부에서만 호출된다.
인덱서가 `project_key`를 색인할 필요가 없다.

---

## 5. API 설계

기존 `/query`, `/generate`는 변경하지 않는다.
신규 엔드포인트 `/discover`를 추가한다.

### 신규: POST /api/v1/chat/discover

```
목적: 질문에 관련된 문서 후보 목록 반환 (LLM 호출 없음)
```

**Request**

```json
{
  "question": "산림공간 디지털 플랫폼 제안요청서",
  "top_k_chunks": 30,
  "top_n_docs": 10,
  "project_key": null,
  "access_scope": null,
  "test_department_codes": null
}
```

| 필드 | 설명 |
|------|------|
| `question` | 필수. 검색 키워드 또는 자연어 질문 |
| `top_k_chunks` | 검색할 최대 청크 수 (기본값: 30). 많을수록 더 많은 문서를 포함 |
| `top_n_docs` | 반환할 최대 문서 수 (기본값: 10) |
| `project_key` | (선택) 특정 프로젝트만 필터 |
| `access_scope` | (선택) `PUBLIC`/`DEPT`/`PRIVATE` 필터 |

**Response**

```json
{
  "question": "산림공간 디지털 플랫폼 제안요청서",
  "retrieval_query": "산림공간 디지털 플랫폼 제안요청서",
  "total_matched_docs": 4,
  "total_matched_chunks": 11,
  "documents": [
    {
      "raw_document_id": "uuid-001",
      "original_filename": "ID_P05_테일러링내역서.pdf",
      "inbox_path": "public/projects/sanrim-platform/ID_P05_테일러링내역서.pdf",
      "file_ext": "pdf",
      "project_key": "sanrim-platform",
      "path_display": "public / sanrim-platform",
      "matched_chunk_count": 5,
      "top_score": 0.87,
      "avg_score": 0.72,
      "representative_sections": [
        "1. 개요",
        "3. 테일러링 내역",
        "5. 산출물 목록"
      ],
      "access_scope": "PUBLIC",
      "department_code": null,
      "indexed_at": "2026-05-13T10:30:00Z"
    },
    {
      "raw_document_id": "uuid-002",
      "original_filename": "RFP_산림플랫폼_v2.pdf",
      "inbox_path": "public/projects/sanrim-platform/RFP_산림플랫폼_v2.pdf",
      "file_ext": "pdf",
      "project_key": "sanrim-platform",
      "path_display": "public / sanrim-platform",
      "matched_chunk_count": 2,
      "top_score": 0.61,
      "avg_score": 0.55,
      "representative_sections": ["제안 배경"],
      "access_scope": "PUBLIC",
      "department_code": null,
      "indexed_at": "2026-05-12T14:00:00Z"
    }
  ],
  "search_backend": "db",
  "retrieval_latency_ms": 142
}
```

### 기존 확장: POST /api/v1/chat/generate

`document_ids` 필드를 선택적으로 추가한다.

```json
{
  "question": "테일러링 내역에서 산출물 목록을 알려줘",
  "document_ids": ["uuid-001"],
  "top_k": 5,
  "session_id": null
}
```

`document_ids`가 있으면 해당 문서의 청크만 검색 결과에 포함한다.
없으면 기존 동작 그대로.

**document_ids 필터 적용 방식:**

```
SearchClient.search(query, permission_filter, top_k)
  → hits 전체 반환 (변경 없음)
  → document_ids 지정 시: [h for h in hits if h.raw_document_id in document_ids]
  → 필터 후 0건이면: 안전 메시지 반환 (LLM 미호출)
```

SearchClient 계약 변경 없음. 필터링은 그 결과를 받은 service 계층에서 처리.

---

## 6. 사용자 흐름

### 흐름 A: 문서 탐색 후 선택 생성

```
사용자: "산림공간 플랫폼 관련 문서 보여줘"
  → POST /discover
  → 문서 목록 표시 (파일명, 프로젝트, 섹션, 점수)

사용자: "이 중 테일러링내역서 기준으로 답해줘"
  → POST /generate { document_ids: ["uuid-001"] }
  → LLM: 해당 문서 청크만 컨텍스트로 사용
  → 응답 + 출처 (명확하게 해당 문서만)
```

### 흐름 B: 바로 생성 (기존 유지)

```
사용자: "산림공간 플랫폼 테일러링 산출물이 뭐야?"
  → POST /generate (document_ids 없음)
  → 기존 동작 그대로
```

### 흐름 C: 프로젝트 필터 탐색

```
사용자: "sanrim-platform 프로젝트 문서 중 제안 관련 문서 있어?"
  → POST /discover { project_key: "sanrim-platform", question: "제안" }
  → project_key 필터된 문서 목록
```

---

## 7. 검색 모드와 답변 모드를 분리하는 이유

| | 검색 모드 (`/discover`) | 답변 모드 (`/generate`) |
|-|------------------------|------------------------|
| LLM 호출 | 없음 | 있음 |
| 반환 단위 | 문서 (grouped) | 문장 답변 |
| 사용자 목적 | "뭐가 있는지 보고 싶다" | "이 문서 기준으로 답 줘" |
| 신뢰성 | 검색 결과 그대로 | LLM 해석 포함 |
| 비용 | 낮음 | 높음 (LLM 토큰) |

분리하면:
- 문서가 없을 때 LLM을 호출하지 않을 수 있다 (`/discover` 결과 0건 → `/generate` 호출 안 함)
- 사용자가 문서 범위를 좁힌 후 LLM을 호출하므로 hallucination이 줄어든다
- 장래에 `/discover`는 캐시 가능 (동일 질의에 동일 문서 목록)

---

## 8. Retrieval Debug와의 연결

기존 `ENABLE_RETRIEVAL_DEBUG=true` 시 반환하는 `debug` 객체에 문서 그룹 정보를 포함한다.

```json
{
  "debug": {
    "original_query": "산림공간...",
    "retrieval_query": "산림공간...",
    "normalization_applied": false,
    "retrieval_backend": "db",
    "retrieval_count": 11,
    "retrieved_chunk_ids": ["..."],
    "retrieved_document_ids": ["uuid-001", "uuid-002"],
    "document_groups": {
      "uuid-001": { "chunk_count": 5, "top_score": 0.87 },
      "uuid-002": { "chunk_count": 2, "top_score": 0.61 }
    },
    "retrieval_scores": [0.87, 0.81, ...],
    "retrieval_filenames": ["ID_P05_테일러링내역서.pdf", ...]
  }
}
```

`/discover`에서도 동일 debug 정보를 선택적으로 반환할 수 있다.

---

## 9. pagination / filter / sort 확장 방향

MVP에서는 단순하게 유지한다. 확장 경로만 정의한다.

### pagination (Phase 2)

```json
// Request
{
  "question": "...",
  "page": 1,
  "per_page": 10
}

// Response
{
  "documents": [...],
  "total_matched_docs": 42,
  "page": 1,
  "per_page": 10,
  "has_next": true
}
```

MVP에서는 `top_n_docs`로 단순 제한. pagination은 문서가 50개 이상 될 때부터.

### filter (Phase 2)

| 필터 | 구현 방식 |
|------|----------|
| `project_key` | `group_hits_by_document` 결과 후처리 필터 |
| `file_ext` | 동일 |
| `access_scope` | 검색 전 permission_filter에 이미 포함 |
| `date_range` | `indexed_at` 범위 필터 |

### sort (Phase 2)

| 정렬 기준 | 설명 |
|----------|------|
| `score` (기본) | top_score 내림차순 |
| `chunk_count` | 많이 매칭된 문서 우선 (주제 집중도) |
| `indexed_at` | 최신 문서 우선 |
| `filename` | 파일명 가나다순 |

---

## 10. SearchClient 계약 유지 전략

`SearchClient.search()` 인터페이스는 **변경하지 않는다**.

```python
# 현재 계약 (변경 없음)
hits: list[SearchHit] = search_client.search(
    query=retrieval_query,
    permission_filter=permission_filter,
    top_k=top_k_chunks,  # 값만 커질 수 있음 (30 이상)
)

# 문서 단위 변환은 그 결과를 받은 서비스 계층에서
candidates = group_hits_by_document(hits, top_n=top_n_docs)
```

`top_k_chunks`를 `/discover`에서 더 크게 설정(예: 30~50)하는 이유:
- 문서가 여러 개일 때 각 문서별로 매칭 청크가 필요
- `top_k=5`이면 같은 문서 청크만 5개 나올 수 있어 다른 문서를 못 봄
- `/discover`는 폭넓게 검색하고 문서 단위로 집계하는 것이 목적

**SearchHit에 추가 가능한 필드 (선택)**:

현재 `SearchHit`에 없을 수 있는 필드들:

| 필드 | 출처 | 비고 |
|------|------|------|
| `inbox_path` | `document_chunk` 또는 JOIN | project_key 추론에 필요 |
| `indexed_at` | `document_chunk.created_at` | 최신성 정렬용 |
| `file_ext` | `raw_document.file_ext` | 파일 유형 필터용 |

이 필드들은 `SearchHit` 데이터클래스에 선택 필드로 추가하거나,
`group_hits_by_document`가 DB를 추가 조회하는 방식으로 보완 가능하다.
단, DB 추가 조회는 `raw_document_id` 목록으로 1회 batch 조회여야 한다 (N+1 금지).

---

## 11. 데이터 모델 관계: document / chunk / source / citation

현재 모델에 계층이 추가되는 방식:

```
raw_document (문서 원본 메타)
  │
  └── document_chunk (청크, 검색 단위)
        │
        └── SearchHit (검색 결과, runtime 객체)
              │
              └── [신규] DocumentCandidate (문서 단위 집계, runtime 객체)
                    │
                    └── source (응답에 포함되는 출처 정보)
                          │
                          └── citation (사용자에게 표시하는 출처 표기)
```

`DocumentCandidate`는 **DB 테이블이 아니다**. 검색 결과를 집계한 runtime 객체.
새로운 테이블이 필요하지 않다.

---

## 12. 지금 구현하면 안 되는 것

| 항목 | 이유 |
|------|------|
| 문서 분류 자동화 (ML) | 도메인 지식 없이 설계 불가, Phase 4 |
| 문서 유사도 클러스터링 | 임베딩 없이 불가, Phase 3 |
| 문서 관계 그래프 | 복잡도 급증, 요구사항 불명확 |
| project 테이블 별도 생성 | 경로 기반 추론으로 충분, 조기 추상화 |
| 사용자 선택 이력 저장 | 세션 관리 미완성 단계 |
| `/discover` + `/generate` 자동 파이프라인 | 사용자 개입 없는 자동화는 신뢰성 저하 |
| document_type 분류 | 파일 확장자 수준으로 충분 (현재), 내용 기반 분류는 Phase 4 |
| 문서 버전 비교 UI | `document-versioning.md` 설계 참조, Phase 3 |

---

## 13. MVP 구현 범위

Phase 1에서 구현할 최소 범위.

**현재 코드 기준 (document discovery):** `POST /api/v1/chat/discover`는 `SearchClient.search` → `raw_document_id` 그룹화, `project_key` 경로 추론, 구조화 로그(`chat_discover`)까지 구현됨. `/generate`에 `document_ids` 필터를 넘기는 단계는 아직 없다.

| 항목 | 상태 |
|------|------|
| `group_hits_by_document(hits)` 변환 함수 | `run_discover` 내부 그룹화로 MVP 대응 (별도 export 함수 없음) |
| `DocumentCandidate` 데이터클래스 | `DiscoverDocumentItem` 등 응답 스키마로 동일 역할 |
| `infer_project_key(inbox_path)` 유틸 | **MVP 구현됨** |
| `POST /api/v1/chat/discover` 엔드포인트 | **MVP 구현됨** |
| `document_ids` 필터 (`/generate` 확장) | 미구현 (차후) |
| `representative_sections` 집계 | **MVP 구현됨** |
| SearchClient 계약 | 변경 없음 |
| scanner / parser / chunker / indexer | 변경 없음 |
| pagination | Phase 2 |
| project_key 필터 | Phase 2 |
| sort 옵션 | Phase 2 |
| 문서 분류·클러스터링 | Phase 4 |

---

## 14. 모듈 위치 제안

```
app/
└─ chat/
    ├─ discovery_service.py    # 신규: group_hits_by_document, infer_project_key
    ├─ schemas.py              # 신규: DocumentCandidate, DiscoverRequest/Response 추가
    └─ router.py               # 신규: POST /discover 라우트 추가
```

`app/agents/nas_rag.py`:
- `run_nas_rag_generate()`에 `document_ids: list[str] | None` 파라미터 추가
- 있으면 hits를 document_ids 기준으로 필터 후 LLM 호출

---

## 15. 관련 문서

- `docs/search-index.md` — OpenSearch 인덱스 구조, chunk 단위 색인
- `docs/permission-policy.md` — PermissionPrincipal, 검색 전 권한 필터
- `docs/document-versioning.md` — 버전 관리 확장 시 DocumentCandidate에 영향
- `docs/retrieval-roadmap.md` — hybrid/vector 전환 시 DocumentCandidate는 동일하게 유지
- `docs/backend-status.md` — 현재 구현 상태 및 retrieval debug 설계
