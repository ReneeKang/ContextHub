# UI 아키텍처

## 개요

ContextHub 프론트엔드 전체 구조를 정의한다.
App Router 기반 Next.js + shadcn/ui를 전제로 설계하되,
MVP는 **FastAPI StaticFiles + Vanilla JS / 경량 React**로도 구현 가능하다.

---

## 1. 전체 레이아웃 구조

```
┌─────────────────────────────────────────────────────────────────┐
│  AppShell                                                       │
│  ┌──────────┐  ┌─────────────────────────────┐  ┌───────────┐  │
│  │          │  │                             │  │           │  │
│  │ Sidebar  │  │    MainContent              │  │ RightPanel│  │
│  │  w-60    │  │    flex-1                   │  │  w-80     │  │
│  │  고정    │  │    스크롤 가능               │  │  고정     │  │
│  │          │  │                             │  │  컨텍스트 │  │
│  └──────────┘  └─────────────────────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

RightPanel은 화면 상태에 따라 내용이 바뀐다:
- 검색 전: 필터 설정 + 인기 검색어 (placeholder)
- 검색 후: 검색 결과 요약 (문서 수, 청크 수, 백엔드)
- 문서 클릭: Chunk 상세 패널

---

## 2. 라우트 구조

```
/                           → 메인 검색/채팅 화면
/chat                       → 채팅 화면 (현재 메인과 동일)
/chat/[sessionId]           → 대화 이력 (Phase 2)

/admin                      → 관리자 대시보드
/admin/agents               → 에이전트 관리
/admin/agents/[id]          → 에이전트 상세/수정
/admin/documents            → 문서 현황 (raw_document 목록)
/admin/documents/failed     → 실패 문서
/admin/llm                  → LLM 설정
/admin/scheduler            → 데이터 수집 스케줄러 (Phase 2)
/admin/guardrail            → 가드레일 설정 (Phase 3)
/admin/reranker             → Reranker 설정 (Phase 3)
/admin/stats                → 통계 대시보드 (Phase 3)
```

---

## 3. 사이드바 메뉴 구조

### 사용자 사이드바

```
┌──────────────────────────┐
│  🏢 ContextHub            │
├──────────────────────────┤
│  💬 채팅 / 검색  (active) │
│  📄 문서 탐색             │  ← /discover 전용 화면 (Phase 2)
│  ─────────────────────── │
│  🕐 최근 대화              │  ← Phase 2
├──────────────────────────┤
│  ⚙  설정                  │
│  👤 [사용자 정보]          │
└──────────────────────────┘
```

### 관리자 사이드바

```
┌──────────────────────────┐
│  🏢 ContextHub 관리자     │
├──────────────────────────┤
│  📊 대시보드               │  Phase 3
│  ─────────────────────── │
│  🤖 에이전트 관리          │  MVP
│  📁 문서 현황              │  MVP
│  ─────────────────────── │
│  🔧 LLM 설정              │  MVP
│  📅 데이터 스케줄러        │  Phase 2
│  🛡 가드레일               │  Phase 3
│  🔄 Reranker              │  Phase 3
│  ─────────────────────── │
│  👥 사용자/그룹            │  Phase 3
│  📢 공지사항               │  Phase 3
└──────────────────────────┘
```

---

## 4. 컴포넌트 계층

```
app/
├─ layout.tsx              # AppShell: Sidebar + 라우터 outlet
│
├─ (user)/
│   ├─ page.tsx            # 메인 채팅/검색 화면
│   └─ layout.tsx          # 사용자 레이아웃 (우측 패널 포함)
│
├─ admin/
│   ├─ layout.tsx          # 관리자 레이아웃 (관리자 사이드바)
│   ├─ page.tsx            # 대시보드 (Phase 3)
│   ├─ agents/
│   │   ├─ page.tsx        # 에이전트 목록
│   │   └─ [id]/page.tsx   # 에이전트 상세
│   ├─ documents/
│   │   └─ page.tsx        # 문서 현황
│   └─ llm/
│       └─ page.tsx        # LLM 설정
│
components/
├─ layout/
│   ├─ Sidebar.tsx
│   ├─ RightPanel.tsx
│   └─ AppHeader.tsx
│
├─ search/
│   ├─ SearchBar.tsx       # 검색 입력 + 에이전트 선택
│   ├─ FilterBar.tsx       # 필터 버튼 영역
│   ├─ DocumentCard.tsx    # 문서 후보 카드
│   ├─ RetrievalProgress.tsx  # 검색 진행 패널
│   └─ DocumentDetailPanel.tsx  # 우측 Chunk 상세
│
├─ chat/
│   ├─ AnswerBlock.tsx     # 답변 + 피드백 버튼
│   ├─ SourceList.tsx      # 출처 목록
│   └─ AgentSelector.tsx   # 에이전트 드롭다운
│
└─ admin/
    ├─ AgentTable.tsx
    ├─ AgentModal.tsx
    ├─ DocumentStatusTable.tsx
    └─ LLMSettingsForm.tsx
```

---

## 5. 상태 관리 전략

MVP는 컴포넌트 로컬 상태로 충분하다.
서버 상태(API 결과)는 React Query (TanStack Query)로 관리.

```
전역 상태 (최소):
  - 현재 선택된 에이전트 ID
  - 현재 로그인 사용자 (test_department_codes 포함)
  - 사이드바 열림/닫힘 여부

서버 상태 (React Query):
  - /discover 결과
  - /generate 결과
  - /admin/stats
  - /admin/documents

로컬 상태 (컴포넌트):
  - 선택된 document_ids
  - 검색 입력값
  - 필터 값
  - 디버그 패널 열림 여부
```

---

## 6. 기술 스택

| 항목 | MVP 선택 | 비고 |
|------|---------|------|
| 프레임워크 | Next.js 14 (App Router) 또는 FastAPI StaticFiles + React | POC는 후자도 가능 |
| UI 컴포넌트 | shadcn/ui | Radix UI 기반, 커스텀 가능 |
| 스타일 | Tailwind CSS | shadcn/ui 기본 |
| 상태 관리 | React Query + useState | 전역 상태 라이브러리 불필요 |
| 아이콘 | lucide-react | shadcn/ui 기본 |
| HTTP | fetch() 또는 axios | MVP는 fetch 충분 |
| 타입 | TypeScript | API 응답 타입 정의 |

### FastAPI 서빙 방식 (POC 최속)

```python
# app/main.py
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    return FileResponse("frontend/dist/index.html")
```

React 빌드 결과를 `frontend/dist/`에 놓고 FastAPI가 서빙.
개발 시에는 Vite dev server + CORS로 분리 운영.

---

## 7. API 클라이언트 타입 정의

```typescript
// types/api.ts

export interface DocumentCandidate {
  raw_document_id: string;
  original_filename: string;
  inbox_path: string;
  file_ext: string;
  project_key: string | null;
  path_display: string;
  matched_chunk_count: number;
  top_score: number;
  avg_score: number;
  representative_sections: string[];
  access_scope: string;
  department_code: string | null;
  indexed_at: string | null;
}

export interface DiscoverResponse {
  question: string;
  retrieval_query: string;
  normalization_applied: boolean;
  total_matched_docs: number;
  total_matched_chunks: number;
  documents: DocumentCandidate[];
  search_backend: string;
  retrieval_latency_ms: number;
}

export interface Source {
  chunk_id: string;
  raw_document_id: string;
  original_filename: string;
  section_title: string | null;
  page_no: number | null;
  score: number;
  access_scope: string;
}

export interface GenerateResponse {
  answer: string;
  sources: Source[];
  search_backend: string;
  llm_model: string;
  llm_mock: boolean;
  retrieval_latency_ms: number;
  llm_latency_ms: number;
  total_latency_ms: number;
}
```

---

## 8. Phase별 구현 범위

| Phase | 프론트 범위 |
|-------|-----------|
| **MVP (1차)** | 메인 검색/채팅, 에이전트 선택(단일), 필터 바, 문서 카드, Retrieval Progress, 답변+출처, Chunk 상세 Side Panel |
| **2차** | 관리자: 에이전트 목록/수정, 문서 현황, LLM 설정, 데이터 스케줄러 |
| **3차** | 관리자: 가드레일, Reranker, 통계, 사용자/그룹 관리, 대화 이력 |
