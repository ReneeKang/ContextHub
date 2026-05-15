# POC UI 설계 — 단일 중심 문서

## 문서 목적

ContextHub Phase 1 POC UI의 **유일한 기준 문서**다.

화면 구조, UX 흐름, 컴포넌트 설계, 현재 구현 상태, 다음 작업을 이 문서 하나에서 관리한다.

> 이 문서의 부록 초안 문서: `reference-ui-analysis.md`, `ui-architecture.md`,
> `ui-screen-flow.md`, `admin-console-design.md`, `search-experience-design.md`
> — README 링크에서 제외되어 있으며, Phase 2 이후 설계 시 참고용으로만 보존한다.

---

## 현재 구현 상태 (스냅샷)

> **단계**: Connected POC UI — `/discover` → 문서 선택 → `/generate` 전체 흐름 연결 완료

| 영역 | 구현 상태 |
|------|---------|
| FastAPI StaticFiles 서빙 (`/poc` 라우트) | ✅ 완료 |
| 좌측 사이드바 레이아웃 | ✅ 완료 |
| 에이전트 선택 드롭다운 | ✅ 완료 (MVP 단일 에이전트 고정) |
| 중앙 검색 입력창 | ✅ 완료 |
| Retrieval Pipeline 카드 (5단계) | ✅ 완료 (phase 전환 연결) |
| 문서 후보 카드 영역 | ✅ 완료 (discover 응답 기반 렌더링) |
| 답변·출처 영역 | ✅ 완료 (generate 응답 기반 렌더링) |
| 우측 패널 (선택 문서 / Sources / Debug) | ✅ 완료 |
| Advanced 설정 (top_k, test_department_codes) | ✅ 완료 (API 요청에 반영) |
| `POST /api/v1/chat/discover` 연결 | ✅ 완료 |
| `POST /api/v1/chat/generate` 연결 | ✅ 완료 |
| 문서 카드 실제 렌더링 | ✅ 완료 |
| `raw_document_id` 기준 체크박스 선택 관리 | ✅ 완료 |
| 선택 `document_ids` → generate 전달 | ✅ 완료 |
| 답변 / 출처 / 디버그 실제 렌더링 | ✅ 완료 |
| 상태 전환 (DISCOVERING → DISCOVERED → GENERATING → ANSWERED) | ✅ 완료 |
| 빈 결과 (EMPTY) 처리 | ✅ 완료 |
| /discover 오류 → 후보 영역 오류 표시 | ✅ 완료 |
| /generate 오류 → 선택 상태 유지 + 답변 영역 오류 표시 | ✅ 완료 |
| mock 데이터 제거 | ✅ 완료 |

현재 화면은 **실제 ContextHub API와 연결된 동작하는 POC**다.
하드코딩 데이터는 제거되었으며, 실패 시 연결 오류 메시지만 표시한다.

---

## 1. POC UI의 핵심 원칙

**ContextHub는 단순 챗봇이 아니다.**

일반 LLM 챗봇: 질문 → 바로 LLM 응답

ContextHub 흐름:
```
질문 → [문서 탐색] → 관련 문서 후보 목록 표시
     → 사용자가 문서 선택 → [선택 문서로 답변 생성]
     → 선택된 문서 범위 안에서만 LLM 응답 + 출처 표시
```

이 분리가 화면에 명확하게 보여야 한다.
사용자가 "어떤 문서를 근거로 답변했는지"를 알고 신뢰할 수 있어야 한다.

---

## 2. 레퍼런스 UI 분석: 가져올 것 / 제외할 것

운영형 RAG 서비스 레퍼런스 화면을 분석한 결과.

### POC에 채택하는 요소

| 요소 | 이유 |
|------|------|
| 좌측 고정 사이드바 | 에이전트 선택·메뉴 확장을 위한 뼈대 |
| 에이전트 선택 드롭다운 | 멀티에이전트 확장 포인트를 지금 자리만 잡아둠 |
| 검색 필터 바 | 프로젝트/파일유형/권한 기준으로 문서 범위 좁히기 |
| 문서 후보 카드 목록 | `/discover` 결과를 시각화, 점수·섹션·경로 표시 |
| Retrieval Progress 패널 | RAG가 어떤 문서를 읽고 답변하는지 단계별로 투명하게 표시 |
| 답변 + 출처 영역 | 출처(파일명·섹션·페이지)를 답변과 함께 표시 |
| 우측 Chunk 상세 패널 | 문서 또는 출처 클릭 시 청크 내용 확인 |
| 디버그 패널 (접이식) | 검색 쿼리·정규화·점수 확인 (개발/스테이징용) |

### POC에서 제외하는 요소

| 요소 | 이유 |
|------|------|
| 관리자 콘솔 전체 | Phase 2. 에이전트·문서·LLM 관리 UI |
| 가드레일 설정 | Phase 3 |
| LLM 전환 관리 UI | `.env` 기반 설정으로 충분 |
| Reranker 설정 | Phase 3 |
| 스케줄러 관리 | Phase 2 |
| 인기 검색어 | 검색 이력 수집 미구현 |
| 유사질문 자동 제안 | LLM 추가 호출 필요 |
| PDF 뷰어 내장 | NAS 파일 서빙 미구현, Chunk 상세 패널로 대체 |
| 로그인 / 사용자 인증 UI | `test_department_codes`로 충분 |
| 좋아요/싫어요 피드백 | 피드백 저장 DB 미설계 |
| 대화 이력 / 멀티턴 | `/history` 미구현 |
| 모바일 반응형 | 데스크탑 전용 (1280px 기준) |

---

## 3. 전체 화면 레이아웃

```
┌──────────────────────────────────────────────────────────────────┐
│  ┌──────────┐  ┌──────────────────────────────┐  ┌───────────┐  │
│  │          │  │  [에이전트] [필터 바]          │  │           │  │
│  │  사이드바 │  │  ─────────────────────────── │  │  우측     │  │
│  │  w-56    │  │                               │  │  패널     │  │
│  │  고정    │  │  검색 입력창  [문서 탐색]      │  │  w-72    │  │
│  │          │  │                               │  │  상황에   │  │
│  │  ContextH│  │  ┌──────────────┐  ┌────────┐│  │  따라     │  │
│  │  ub      │  │  │ 📄 문서 후보  │  │💬 답변 ││  │  전환     │  │
│  │  ───────│  │  │  카드 목록   │  │   +    ││  │           │  │
│  │  💬 채팅 │  │  │             │  │📎 출처 ││  │           │  │
│  │          │  │  │  [선택 문서  │  │        ││  │           │  │
│  │          │  │  │  로 답변생성]│  │        ││  │           │  │
│  │          │  │  └──────────────┘  └────────┘│  │           │  │
│  │          │  │                               │  │           │  │
│  │          │  │  🔬 디버그 패널 (접이식)       │  │           │  │
│  │          │  └──────────────────────────────┘  └───────────┘  │
│  └──────────┘                                                    │
└──────────────────────────────────────────────────────────────────┘
```

| 영역 | 너비 | 내용 |
|------|------|------|
| 사이드바 | `w-56` 고정 | 에이전트 선택, 메뉴 (향후 확장) |
| 메인 콘텐츠 | `flex-1` | 검색 입력 + 문서 카드 + 답변 |
| 우측 패널 | `w-72` 고정 | 검색 요약 또는 Chunk 상세 (상황에 따라 전환) |

---

## 4. 컴포넌트 상세

### 4-A. 사이드바

```
┌────────────────────┐
│  🏢 ContextHub     │
│  ─────────────────│
│                   │
│  에이전트          │
│  [NAS RAG ▼]      │  ← 드롭다운. MVP는 1개 고정.
│                   │
│  ─────────────────│
│  💬 채팅 / 검색 ●  │  ← 현재 활성 메뉴
│                   │
│  (아래 메뉴는      │
│   Phase 2 이후)   │
│  📄 문서 탐색      │
│  🕐 최근 대화      │
│  ─────────────────│
│  👤 부서 설정      │  ← test_department_codes 지정
└────────────────────┘
```

**에이전트 드롭다운 (MVP)**:
```
[NAS RAG 에이전트 ▼]
─────────────────────
✅ NAS RAG 에이전트  (현재)
   (준비 중) 로그 분석 에이전트
   (준비 중) 표준 검토 에이전트
```
MVP는 "NAS RAG 에이전트" 1개만 선택 가능. 나머지는 회색 비활성.

**부서 설정 (POC 인증 대체)**:
- 클릭 시 `test_department_codes` 입력 모달 표시
- 예: `infra`, `dev` 입력 → DEPT 권한 문서 포함 검색
- 운영 시에는 로그인 토큰으로 대체 예정임을 레이블로 표시

---

### 4-B. 검색 영역

```
에이전트: [NAS RAG 에이전트 ▼]    부서: [infra ×]  [부서 변경]

[📁 프로젝트 ▼]  [📄 파일유형 ▼]  [🔒 권한 ▼]  [필터 초기화]

┌─────────────────────────────────────────────────────┐
│ 🔍 찾고 싶은 내용이나 문서명을 입력하세요...        │
│                                       [문서 탐색 →] │
└─────────────────────────────────────────────────────┘
```

| 요소 | 동작 |
|------|------|
| 텍스트 입력창 | 자연어 질문 또는 키워드 입력 |
| Enter 키 | [문서 탐색]과 동일 |
| [문서 탐색] 버튼 | `POST /discover` 호출 |
| 프로젝트 필터 | `/discover` 결과의 `project_key` 집계 후 표시, 클라이언트 후처리 |
| 파일유형 필터 | PDF / DOCX / HWP / TXT, 클라이언트 후처리 |
| 권한 필터 | PUBLIC / DEPT, 클라이언트 후처리 |

필터는 `/discover` 재호출 없이 클라이언트에서 결과를 후처리한다.

---

### 4-C. Retrieval Progress 패널

레퍼런스 UI의 "인텔리전트 검색" 패널과 동일한 역할.
RAG가 블랙박스가 아님을 보여주는 **핵심 UX 차별점**.

```
⏳ 인텔리전트 검색 진행 중...
─────────────────────────────────────────────
✅ 1) 질문을 분석합니다.
      검색어: "산림공간 디지털 플랫폼 산출물"
      ⚠ "목록" 제거됨 (정규화 적용)

✅ 2) 관련 문서를 검색합니다.
      백엔드: db  ·  결과: 11개 청크 / 4개 문서

⏳ 3) 문서를 읽어옵니다.
      📄 ID_P05_테일러링내역서.pdf
      📄 RFP_산림플랫폼_v2.pdf
      📄 보안정책_v2.pdf  ... +1개

⬜ 4) 관련 내용을 선별합니다.
⬜ 5) 답변을 생성합니다.
─────────────────────────────────────────────
```

**단계 표시 규칙**:

| 단계 | 활성 조건 | 표시 내용 |
|------|---------|---------|
| 1) 질문 분석 | `/discover` 호출 즉시 | `retrieval_query`, 정규화 여부 |
| 2) 문서 검색 | 검색 중 | 백엔드, 청크/문서 수 |
| 3) 문서 읽기 | `/discover` 응답 수신 | 문서명 목록 (최대 3개) |
| 4) 내용 선별 | `/generate` 호출 시 | "N청크 중 M개 선별" |
| 5) 답변 생성 | LLM 호출 중 | 모델명 |
| ✅ 완료 | `/generate` 응답 | "문서 N개 · 섹션 M개 참조" |

단계 완료 시 체크마크(`✅`)로 전환. 대기 중은 빈 상자(`⬜`).

---

### 4-D. 문서 후보 카드 목록

```
📄 관련 문서 후보 (4개 문서 · 11개 청크)
[전체선택]  [선택해제]              정렬: [점수순 ▼]
───────────────────────────────────────────────────

☑  ID_P05_테일러링내역서.pdf
   📁 public / sanrim-platform  ·  PDF  ·  2026-05-13 색인
   ████████░░  0.87  ·  청크 5개
   > 1. 개요    > 3. 테일러링 내역    > 5. 산출물목록
                                            [상세 →]

☐  RFP_산림플랫폼_v2.pdf
   📁 public / sanrim-platform  ·  PDF  ·  2026-05-12 색인
   ████░░░░░░  0.61  ·  청크 2개
   > 제안 배경
                                            [상세 →]

☐  보안정책_v2.pdf
   📁 public  ·  🔒 PUBLIC  ·  PDF
   ██░░░░░░░░  0.43  ·  청크 4개
   > 시스템 보안 요구사항
                                            [상세 →]
───────────────────────────────────────────────────
[✨ 선택 문서로 답변 생성]          1개 선택됨
```

#### 문서 카드 요소

| 요소 | API 필드 | 표시 규칙 |
|------|---------|---------|
| 파일명 | `original_filename` | 굵게 |
| 경로 | `path_display` | `📁 public / sanrim-platform` |
| 파일유형 | `file_ext` | PDF / DOCX / HWP / TXT |
| 색인일 | `indexed_at` | `YYYY-MM-DD 색인` |
| 점수 바 | `top_score` | 0.80↑ 녹색, 0.60↑ 주황, 미만 회색 |
| 청크 수 | `matched_chunk_count` | `청크 N개` |
| 대표 섹션 | `representative_sections` | `> 섹션명`, 최대 3개 |
| 권한 배지 | `access_scope` | PUBLIC(회색) / DEPT(파랑) / PRIVATE(주황) |

**카드 인터랙션**:
- 체크박스 클릭 → 답변 생성 대상 선택/해제
- `[상세 →]` 클릭 → 우측 패널에 Chunk 상세 표시
- 카드 영역 클릭 → `[상세 →]`와 동일

---

### 4-E. 답변 + 출처 패널

```
상태: 대기
  문서를 선택한 후 [선택 문서로 답변 생성] 을 눌러주세요.

상태: 생성 중
  ⏳ ID_P05_테일러링내역서.pdf 기준으로 답변 생성 중...

상태: 완료
  ─────────────────────────────────────────────
  💬 답변

  테일러링 내역서 기준 산출물 목록은 다음과 같습니다.
  1. WBS (작업 분류 체계)
  2. 요구사항 정의서
  ...

  [📋 복사]

  ─────────────────────────────────────────────
  📎 출처 (2건)

  📄 ID_P05_테일러링내역서.pdf
     5. 산출물 목록  ·  p.12  ·  점수 0.87    [상세 →]
  📄 ID_P05_테일러링내역서.pdf
     3. 테일러링 내역  ·  p.8  ·  점수 0.81   [상세 →]

  ─────────────────────────────────────────────
  ⏱ 검색 142ms  ·  LLM 2,341ms  ·  총 2,483ms
  [🔬 디버그 정보 ▼]
```

출처 `[상세 →]` 클릭 → 우측 패널에 해당 청크 내용 표시.

---

### 4-F. 우측 패널 (상황별 전환)

| 화면 상태 | 우측 패널 내용 |
|---------|--------------|
| IDLE | 검색 가이드, 색인 현황 placeholder |
| DISCOVERING | "검색 중..." |
| DISCOVERED | 검색 결과 요약 (문서 수, 청크 수, 지연, 정규화 여부) |
| ANSWERED | 검색 결과 요약 유지 |
| 문서/출처 `[상세 →]` 클릭 | **Chunk 상세 패널** (슬라이드 인) |

**Chunk 상세 패널**:
```
📄 문서 상세                      [← 닫기]
────────────────────────────────────────
파일명:  ID_P05_테일러링내역서.pdf
경로:    public / sanrim-platform
권한:    🔓 PUBLIC  ·  PDF
색인일:  2026-05-13

매칭 섹션 (5개)
────────────────────────────────────────
▼ 5. 산출물 목록  (p.12)  점수 0.87
  본 프로젝트의 산출물 목록은 다음
  WBS 기준에 따라 정의됩니다...
  [더 보기]

▶ 3. 테일러링 내역  (p.8)  점수 0.81
▶ 1. 개요  (p.2)  점수 0.74
▶ 2. 적용 범위  (p.4)  점수 0.68
▶ 4. 품질 기준  (p.10)  점수 0.61
────────────────────────────────────────
[📋 파일 경로 복사]
```

chunk_text 최대 300자, 더보기 토글. PDF 뷰어는 MVP 제외.

---

### 4-G. 디버그 패널 (접이식)

`ENABLE_RETRIEVAL_DEBUG=true`일 때만 의미 있는 데이터를 표시한다.
시연 시 "RAG 내부 동작이 투명하다"를 보여주는 용도.

```
🔬 디버그 정보  [▶ 펼치기]
```

펼쳤을 때:
```
🔬 디버그 정보                               [▲ 접기]
────────────────────────────────────────────────────
원본 질문:    "산림공간 디지털 플랫폼...목록"
검색 쿼리:    "산림공간 디지털 플랫폼...산출물"
정규화 적용:  ✅  ("목록" 제거됨)
검색 백엔드:  db  ·  청크 11개  ·  문서 4개

청크별 결과
  순위  문서                  섹션          점수   매칭 필드
  1     ID_P05_테일러링...    5. 산출물목록  0.87   chunk_text
  2     ID_P05_테일러링...    3. 테일러링    0.81   chunk_text, section_title
  3     RFP_산림플랫폼_v2     제안 배경      0.61   chunk_text
  ...
────────────────────────────────────────────────────
```

| 표시 필드 | API 출처 |
|---------|---------|
| 원본 질문 (앞 80자) | `debug.original_query` |
| 검색 쿼리 | `debug.retrieval_query` |
| 정규화 여부 | `debug.normalization_applied` |
| 청크별 점수·매칭 필드 | `debug.chunks[].score`, `matched_fields` |
| 문서 랭크 | `debug.chunks[].document_rank` |

---

## 5. 화면 상태값

```
                  IDLE (초기)
                      │ [문서 탐색] 클릭
                      ▼
               DISCOVERING ──── 오류 ──→ ERROR
                      │ 응답 수신
          ┌───────────┴────────────┐
       결과 있음                결과 없음
          ▼                        ▼
      DISCOVERED               EMPTY_RESULT
          │ [선택 문서로 답변 생성]
          ▼
        GENERATING ──── LLM 오류 ──→ ERROR
          │ 응답 수신
          ▼
        ANSWERED
          │ [새 질문 입력]
          ▼
         IDLE
```

| 상태 | 사이드바 | 검색 버튼 | 문서 패널 | 답변 패널 | 우측 패널 |
|------|---------|---------|---------|---------|---------|
| `IDLE` | 정상 | 활성 | 빈 화면 | 안내 문구 | 가이드 |
| `DISCOVERING` | 정상 | 비활성 | 스켈레톤 + Progress 1~2단계 | — | "검색 중" |
| `DISCOVERED` | 정상 | 활성 | 카드 목록 + Progress 3단계 | "문서 선택" 안내 | 결과 요약 |
| `GENERATING` | 정상 | 비활성 | 카드 유지 + Progress 4~5단계 | "생성 중" | 결과 요약 |
| `ANSWERED` | 정상 | 활성 | 카드 유지 | 답변 + 출처 | 결과 요약 |
| `EMPTY_RESULT` | 정상 | 활성 | "문서 없음" 안내 | — | 가이드 |
| `ERROR` | 정상 | 활성 | 유지 | 오류 메시지 | 유지 |

---

## 6. API 호출 순서

```
[문서 탐색] 클릭
      │
      ▼
POST /api/v1/chat/discover
  { question, top_k, test_department_codes }
      │
      ▼
{ documents, total_matched_docs, total_matched_chunks,
  retrieval_query, normalization_applied, search_backend,
  retrieval_latency_ms }
      │
      ▼ 문서 카드 렌더링
      
[선택 문서로 답변 생성] 클릭 (document_ids 지정)
      │
      ▼
POST /api/v1/chat/generate
  { question, document_ids: ["uuid-001", ...], top_k }
      │
      ▼
{ answer, sources, llm_model, llm_mock,
  retrieval_latency_ms, llm_latency_ms, total_latency_ms }
      │
      ▼ 답변 + 출처 렌더링
```

**중요**: `/discover` 결과의 `document_ids`를 `/generate`에 그대로 전달한다.
`document_ids` 없이 `/generate`만 호출하는 것도 가능 (기존 흐름 호환 유지).

### 오류 처리

| 상황 | 처리 |
|------|------|
| `/discover` 0건 | "관련 문서를 찾을 수 없습니다. 다른 표현으로 다시 시도해보세요." |
| `/generate` 선택 문서 청크 없음 | "선택 문서에서 관련 내용을 찾을 수 없습니다." + `[전체 결과로 다시 시도]` |
| LLM 오류 (502) | "답변 생성에 실패했습니다. 잠시 후 다시 시도해주세요." |
| 타임아웃 | "응답 시간이 초과되었습니다." |

---

## 7. POC 핵심 시나리오

### 시나리오 A: 문서 선택 → 근거 있는 답변

```
질문: "테일러링 내역서에서 산출물 목록 알려줘"
→ ID_P05_테일러링내역서.pdf 1개 선택
→ [선택 문서로 답변 생성]
→ 답변: 산출물 목록 나열
→ 출처: "5. 산출물 목록 · p.12"

보여주는 것: LLM이 선택된 문서 범위 안에서만 답변한다
```

### 시나리오 B: 권한 분리

```
부서 설정 A (infra): "인프라 운영 절차" 질문
→ DEPT:infra 문서 포함 결과 표시

부서 설정 B (없음): 동일 질문
→ PUBLIC 문서만 결과
→ 부서 문서 카드가 보이지 않음

보여주는 것: 같은 질문인데 권한에 따라 다른 문서 목록
```

### 시나리오 C: 검색 투명성

```
질문: "쿠베플로우에 대해 설명해줘"
→ Retrieval Progress 1단계:
   원본: "쿠베플로우에 대해 설명해줘"
   검색: "쿠베플로우"  ← "에 대해 설명해줘" 제거
→ 디버그 패널: normalization_applied: true

보여주는 것: RAG 내부 동작이 투명하게 관찰 가능
```

---

## 8. 기술 스택 (POC)

| 항목 | 선택 |
|------|------|
| 렌더링 | React (Vite) 또는 Vanilla JS + HTML 단일 파일 |
| CSS | Tailwind CDN 또는 shadcn/ui (향후 확장 시) |
| 상태 관리 | `useState` 또는 DOM 직접 조작 |
| API | `fetch()` |
| 서빙 | FastAPI `StaticFiles` + 동일 uvicorn 프로세스 |

```python
# app/main.py (예시)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@app.get("/", include_in_schema=False)
async def serve_poc():
    return FileResponse("frontend/index.html")
```

같은 origin이므로 CORS 불필요. 데스크탑 전용(1280px 이상) 기준.

---

## 9. 파일 구조 (구현)

```
app/static/poc/
├─ index.html
├─ css/style.css
└─ js/
    ├─ api.js       # fetch 처리: /discover, /generate 호출 + FastAPI detail 에러 파싱
    ├─ state.js     # phase 관리, selectedDocumentIds Set, canStartDiscover/canStartGenerate 판단
    ├─ render.js    # API 응답 기반 DOM 렌더: 문서 카드, 선택 패널, 답변, 출처, debug, progress
    └─ main.js      # 버튼/입력 이벤트 처리, API 호출 흐름 제어, phase 전환
```

접속: `uvicorn app.main:app --reload` 후 `http://127.0.0.1:8000/poc` (또는 `/`).
레이아웃: **좌측 사이드바** (에이전트·부서코드) · **중앙** (검색·진행·후보·답변) · **우측** (선택·출처·debug).

---

## 9-1. 구현 흐름 정리 (완료 기준)

API Wiring이 완료된 현재 구현 흐름을 정리한다.
**백엔드 API 계약은 변경하지 않는다.** UI는 기존 흐름을 시각화하는 역할만 한다.

### 구현된 흐름

**[문서 탐색] 클릭 → `/discover`**
```
main.js: 버튼 클릭 이벤트 수신
  → state.js: IDLE → DISCOVERING, canStartDiscover() 확인
  → api.js: POST /api/v1/chat/discover
     { question, top_k, test_department_codes }
  → render.js: Retrieval Progress 1~2단계 active
     → 응답 수신 (documents[])
  → state.js: DISCOVERING → DISCOVERED or EMPTY
  → render.js: 문서 카드 DOM 생성 (원본 문서별 1장)
     original_filename, path_display, top_score, matched_chunk_count,
     representative_sections, access_scope, indexed_at
  → render.js: Retrieval Progress 3단계 완료, 우측 패널 요약 갱신
```

**체크박스 선택 → `document_ids` 수집**
```
render.js: 카드 체크박스 이벤트 위임
  → state.js: selectedDocumentIds Set에 raw_document_id 추가/제거
  → render.js: 카드 하이라이트, 선택 건수, 생성 버튼 활성/비활성
```

**[선택 문서로 답변 생성] 클릭 → `/generate`**
```
main.js: 버튼 클릭, canStartGenerate() 확인
  → state.js: DISCOVERED → GENERATING
  → api.js: POST /api/v1/chat/generate
     { question, document_ids: [...selectedDocumentIds], top_k }
  → render.js: Retrieval Progress 4~5단계 active, 답변 영역 "생성 중..."
     → 응답 수신 (answer, sources, debug)
  → state.js: GENERATING → ANSWERED
  → render.js: answer 표시, sources[] 출처 목록, debug → details 패널
```

**오류 / 빈 결과 처리**
```
/discover 0건         → state: EMPTY, 후보 영역 안내 메시지
/discover 오류        → state: ERROR, 후보 영역 오류 표시 (FastAPI detail 파싱)
/generate 오류        → 선택 상태 유지 (DISCOVERED로 복귀), 답변 영역만 오류 표시
```

### 아키텍처 원칙 (준수 중)

| 원칙 | 현재 적용 방식 |
|------|-------------|
| 백엔드 API 계약 불변 | request body 구조 임의 변경 없음 |
| 검색/답변 모드 분리 | `/discover` 후 명시적 선택이 있어야만 `/generate` 호출 |
| chunk 내부 비노출 | 사용자에게는 document 단위 표시. chunk_id는 내부 처리만 |
| 모듈 역할 분리 유지 | api.js(fetch), state.js(상태), render.js(DOM), main.js(이벤트) |
| React 이전 가능성 | DOM 조작은 render.js에만. state.js는 순수 상태 로직 |

---

## 9-2. 현재 검증 필요 항목 및 다음 개선 후보

### API 연결 후 검증해야 할 항목

| 항목 | 확인 방법 |
|------|---------|
| `/discover` 빈 결과 처리 | 색인 없는 질문으로 EMPTY 상태 진입 확인 |
| `/generate` 실패 시 선택 상태 유지 | LLM 오류 발생 시 문서 카드 선택 상태 유지 확인 |
| `test_department_codes` 필터 적용 | 부서 설정 후 DEPT 문서 포함 여부 확인 |
| `top_k` 적용 여부 | Advanced 설정 변경 후 결과 수 변화 확인 |
| `sources` / `debug` 표시 여부 | ENABLE_RETRIEVAL_DEBUG=true 환경에서 debug 패널 확인 |
| `raw_document_id` ↔ `document_ids` 매핑 정확성 | 선택한 카드의 ID가 generate 요청에 정확히 전달되는지 확인 |
| `discover 0건` 후 `generate` 버튼 비활성화 | EMPTY 상태에서 생성 버튼 클릭 불가 확인 |

### 다음 구현 후보

| 항목 | 설명 |
|------|------|
| 선택 문서 미리보기 강화 | 우측 패널에 선택된 문서의 representative_sections 표시 |
| Retrieval Debug UI 가독성 개선 | matched_fields, highlight_terms, document_rank를 테이블로 정리 |
| Progress 단계별 로그 표시 | 각 단계 완료 시각·소요 시간 표시 |
| 문서 카드 점수 시각화 개선 | score 바 색상 + top_score 수치 동시 표시 |
| POC 테스트 시나리오 문서화 | 시나리오 A/B/C를 재현 가능한 단계별 절차로 정리 |

---

## 10. 향후 확장 방향

이 POC UI는 다음 단계의 뼈대가 된다.

| Phase | 추가 내용 |
|-------|---------|
| Phase 2 | 에이전트 목록 추가 (AgentRouter 연동), 관리자 콘솔 (문서 현황, LLM 설정) |
| Phase 3 | 대화 이력, 유사질문 제안, 좋아요/싫어요 피드백, 사용자 인증 |
| Phase 4 | 가드레일 설정, Reranker 설정, 통계 대시보드, 모바일 반응형 |

지금 만드는 사이드바 레이아웃, 에이전트 드롭다운 자리, 우측 패널 슬롯이
그대로 확장 포인트가 된다.

---

## 11. 관련 문서

| 문서 | 참조 용도 |
|------|---------|
| `docs/document-discovery.md` | `/discover` API 설계, DocumentCandidate 모델 |
| `docs/api-design.md` | `/generate` 엔드포인트 상세 |
| `docs/backend-status.md` | 현재 구현 상태, 디버그 필드, POC 접속 경로 |
| `docs/permission-policy.md` | access_scope 분류, 권한 필터 원칙 |
