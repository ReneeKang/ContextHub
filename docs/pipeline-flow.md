# 파이프라인 처리 흐름

## 핵심 원칙

> 파일 발견 → 파싱 → 청킹 → 색인 → 응답을 **하나의 함수나 흐름으로 처리하지 않는다.**
>
> 반드시 **상태 기반으로 단계를 분리**하고,
> 운영자가 "왜 검색 안 되지?"를 상태 기준으로 추적할 수 있어야 한다.

---

## 전체 파이프라인

```
[NAS 공식 반입 폴더]
      │
      │ (주기 스캔 1분)
      ▼
┌─────────────────────────────────────────┐
│  STEP 1: nas-scan-worker                │
│                                         │
│  1. /nas/chatbot_docs/ 재귀 탐색        │
│  2. 파일별 size + mtime 조회            │
│  3. raw_document_scan_state 비교        │
│  4. 변경 없으면 → 안정화 판단          │
│  5. sha256 계산                         │
│  6. 동일 해시 존재? → DUPLICATE 처리   │
│  7. raw_document INSERT                 │
│     ingest_status = RECEIVED            │
│     parse_status  = PENDING             │
│     chunk_status  = PENDING             │
│     index_status  = PENDING             │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  STEP 2: document-parse-worker          │
│                                         │
│  1. parse_status = PENDING 문서 조회    │
│  2. NAS에서 원본 파일 읽기              │
│  3. kordoc 호출 (파싱 엔진)             │
│     - PDF / DOCX / HWP / TXT 지원      │
│  4. 결과 수신:                          │
│     - markdown_text                     │
│     - blocks_json (블록 트리)           │
│     - metadata_json (페이지 수 등)      │
│  5. document_parse_result INSERT        │
│  6. parse_status = DONE (또는 FAILED)   │
│  7. chunk_status = PENDING 트리거       │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  STEP 3: document-chunk-worker          │
│                                         │
│  1. chunk_status = PENDING 문서 조회    │
│  2. document_parse_result 조회          │
│  3. markdown_text → 청크 분리           │
│     - 헤딩·문단 규칙 (`docs/chunking-strategy.md`) │
│     - heading_path / page_no / 길이·overlap·짧은 청크 병합 │
│  4. 각 청크에 권한 메타 복사            │
│     - access_scope                      │
│     - owner_id                          │
│     - department_code                   │
│  5. document_chunk INSERT (복수)        │
│  6. chunk_status = DONE (또는 FAILED)   │
│  7. index_status = PENDING 트리거       │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  STEP 4: document-index-worker          │
│                                         │
│  1. index_status = PENDING 청크 조회    │
│  2. OpenSearch 문서 구성                │
│     - chunk_text, section_title, heading_path │
│     - page_no, chunk_char_count, chunk_metadata_json │
│     - access_scope / dept / owner       │
│  3. OpenSearch 색인 등록                │
│  4. document_index_status UPDATE        │
│  5. index_status = DONE (또는 FAILED)   │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  STEP 5: chat-api (사용자 요청 시)      │
│                                         │
│  1. 사용자 쿼리 수신                    │
│  2. 사용자 권한 정보 추출               │
│     - access_scope 목록                 │
│     - department_code 목록              │
│     - user_id                           │
│  3. 권한 필터 구성                      │
│     (access_scope=PUBLIC                │
│      OR dept IN (...)                   │
│      OR owner_id = ...)                 │
│  4. OpenSearch 검색 (권한 필터 포함)    │
│  5. 검색 결과 → LLM 컨텍스트 구성      │
│  6. LLM 호출                            │
│  7. 응답 + 출처 청크 반환               │
└─────────────────────────────────────────┘
```

---

## 상태 전환 규칙

| 상태 필드 | 초기값 | 성공 | 실패 |
|-----------|--------|------|------|
| `ingest_status` | — | `RECEIVED` | `FAILED` |
| (중복 감지 시) | — | `DUPLICATE` | — |
| `parse_status` | `PENDING` | `DONE` | `FAILED` |
| `chunk_status` | `PENDING` | `DONE` | `FAILED` |
| `index_status` | `PENDING` | `DONE` | `FAILED` |

### DUPLICATE 처리

- sha256 해시 비교로 동일 파일 감지
- `raw_document.duplicate_of_raw_document_id` 에 원본 ID 기록
- parse / chunk / index 단계 건너뜀
- 관리자 화면에서 중복 목록 조회 가능

---

## 안정화 판단 로직 (nas-scan-worker)

```
1차 스캔: 파일 감지 → scan_state에 size + mtime 기록
2차 스캔: 동일 파일 재감지
  → size, mtime 동일 → 안정화 완료 → raw_document 등록
  → size 또는 mtime 변경 → 대기 (업로드 중 판단)
```

업로드 중인 파일을 중간에 파싱하는 것을 방지하기 위한 안정화 판단.

---

## 재처리 흐름 (admin-api 트리거)

```
운영자 재처리 요청
  → 대상 raw_document_id 지정
  → 해당 상태 필드를 PENDING으로 리셋
  → 워커가 다음 주기에 재처리
```

예:
- 파싱 재처리: `parse_status = PENDING` 으로 리셋
- 색인 재처리: `index_status = PENDING` 으로 리셋

---

## 금지 패턴

```python
# 절대 금지: 하나의 함수에서 전체 파이프라인 처리
def process_file(path):
    content = parse(path)          # parse
    chunks = chunk(content)        # chunk
    index(chunks)                  # index
    return chat_response(chunks)   # chat
```

```python
# 올바른 구조: 워커별 독립 실행, 상태 기반 연동
def scan_worker():
    # raw_document 등록만

def parse_worker():
    # parse_status = PENDING 조회 후 처리만

def chunk_worker():
    # chunk_status = PENDING 조회 후 처리만

def index_worker():
    # index_status = PENDING 조회 후 처리만
```
