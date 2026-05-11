# DB 스키마 설계

## 사용 DB

PostgreSQL

---

## 테이블 목록

| 테이블 | 역할 |
|--------|------|
| `raw_document` | 반입 문서 메타 + 상태 관리 (핵심) |
| `raw_document_scan_state` | NAS 스캔 안정화 판단용 임시 상태 |
| `document_parse_result` | kordoc 파싱 결과 저장 |
| `document_chunk` | 청크 분리 결과 저장 |
| `document_index_status` | 청크별 색인 상태 추적 |

---

## raw_document

문서 반입의 진실의 원천(Source of Truth).
문서의 전체 생애주기 상태를 이 테이블 하나에서 추적한다.

```sql
CREATE TABLE raw_document (
    raw_document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 원본 파일 정보
    source_type         VARCHAR(50)  NOT NULL DEFAULT 'NAS',
    inbox_path          TEXT         NOT NULL,   -- 공식 반입 폴더 내 경로
    stored_path         TEXT         NOT NULL,   -- NAS 실제 절대 경로
    original_filename   TEXT         NOT NULL,
    file_ext            VARCHAR(20)  NOT NULL,   -- pdf, docx, hwp, hwpx, txt
    file_size           BIGINT       NOT NULL,
    sha256_hash         VARCHAR(64)  NOT NULL,

    -- 권한 메타 (경로에서 자동 추출)
    access_scope        VARCHAR(20)  NOT NULL,   -- PUBLIC | DEPT | PRIVATE
    owner_id            VARCHAR(100),            -- PRIVATE 인 경우 사용자 ID
    department_code     VARCHAR(50),             -- DEPT 인 경우 부서 코드

    -- 처리 상태
    ingest_status       VARCHAR(20)  NOT NULL DEFAULT 'RECEIVED',
    parse_status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    chunk_status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    index_status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',

    -- 중복 처리
    duplicate_of_raw_document_id UUID REFERENCES raw_document(raw_document_id),

    -- 검색 제외 처리 (관리자 수동)
    excluded            BOOLEAN      NOT NULL DEFAULT FALSE,
    excluded_reason     TEXT,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_raw_document_parse_status  ON raw_document(parse_status)  WHERE parse_status  = 'PENDING';
CREATE INDEX idx_raw_document_chunk_status  ON raw_document(chunk_status)  WHERE chunk_status  = 'PENDING';
CREATE INDEX idx_raw_document_index_status  ON raw_document(index_status)  WHERE index_status  = 'PENDING';
CREATE UNIQUE INDEX idx_raw_document_sha256 ON raw_document(sha256_hash)   WHERE ingest_status = 'RECEIVED';
```

### 상태값 규칙

**ingest_status**

| 값 | 의미 |
|----|------|
| `RECEIVED` | 정상 반입 완료 |
| `DUPLICATE` | sha256 기준 중복 파일 |
| `FAILED` | 반입 실패 (파일 읽기 오류 등) |

**parse_status**

| 값 | 의미 |
|----|------|
| `PENDING` | 파싱 대기 |
| `DONE` | 파싱 완료 |
| `FAILED` | 파싱 실패 |

**chunk_status**

| 값 | 의미 |
|----|------|
| `PENDING` | 청킹 대기 |
| `DONE` | 청킹 완료 |
| `FAILED` | 청킹 실패 |

**index_status**

| 값 | 의미 |
|----|------|
| `PENDING` | 색인 대기 |
| `DONE` | 색인 완료 |
| `FAILED` | 색인 실패 |

---

## raw_document_scan_state

NAS 스캔 워커가 파일 안정화를 판단하기 위한 임시 상태 테이블.
업로드 중인 파일을 중간에 처리하는 것을 방지한다.

```sql
CREATE TABLE raw_document_scan_state (
    scan_state_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path       TEXT        NOT NULL UNIQUE,   -- NAS 절대 경로
    file_size       BIGINT      NOT NULL,
    mtime           TIMESTAMPTZ NOT NULL,
    stable          BOOLEAN     NOT NULL DEFAULT FALSE,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**안정화 판단 로직**

1. 1차 스캔: `file_path`, `file_size`, `mtime` 기록, `stable = FALSE`
2. 2차 스캔: `file_size`, `mtime` 동일 → `stable = TRUE` → `raw_document` 등록 트리거
3. 파일 등록 완료 후 해당 레코드 삭제 또는 상태 유지 (운영 정책에 따라)

---

## document_parse_result

kordoc 파싱 결과. Parse Worker만 이 테이블에 쓴다.

```sql
CREATE TABLE document_parse_result (
    parse_result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_document_id UUID NOT NULL REFERENCES raw_document(raw_document_id),

    parser_name     VARCHAR(100) NOT NULL DEFAULT 'kordoc',
    parser_version  VARCHAR(50)  NOT NULL,

    markdown_text   TEXT         NOT NULL,   -- 청킹용 마크다운 텍스트
    blocks_json     JSONB        NOT NULL,   -- 블록 트리 (구조 기반 청킹용)
    metadata_json   JSONB,                   -- 페이지 수, 제목, 작성자 등

    page_count      INTEGER,
    parsed_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (raw_document_id)
);
```

### markdown_text vs blocks_json 저장 이유

| 필드 | 용도 |
|------|------|
| `markdown_text` | 현재 PoC에서 텍스트 기반 청킹에 사용 |
| `blocks_json` | 나중에 제목/표/리스트 구조 기반 청킹이 필요할 때 사용 |

**Markdown만 저장하면 나중에 blocks 구조가 필요할 때 재파싱해야 한다.**
초기부터 blocks_json도 함께 저장해 두는 것이 원칙.

---

## document_chunk

청크 분리 결과. 검색 색인의 기본 단위.
각 청크에 권한 메타를 복사하여 검색 시 독립적으로 필터링 가능하게 한다.

```sql
CREATE TABLE document_chunk (
    chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_document_id UUID         NOT NULL REFERENCES raw_document(raw_document_id),

    chunk_no        INTEGER      NOT NULL,   -- 문서 내 순서
    section_title   TEXT,                   -- 리프 섹션 제목(또는 파일명 폴백)
    heading_path    TEXT,                   -- 계층 경로 e.g. "Chapter 1 > Section A"
    page_no         INTEGER,                -- 논리 시작 페이지(PDF `Page N` 등)
    chunk_text      TEXT         NOT NULL,
    chunk_char_count     INTEGER NOT NULL DEFAULT 0,
    chunk_token_estimate INTEGER NOT NULL DEFAULT 0,
    chunk_metadata_json  JSONB,           -- 청킹 버전·튜닝 메타(벡터 확장 여지)

    -- 권한 메타 (raw_document에서 복사)
    access_scope        VARCHAR(20)  NOT NULL,
    owner_id            VARCHAR(100),
    department_code     VARCHAR(50),

    -- 색인 상태
    index_status    VARCHAR(20)  NOT NULL DEFAULT 'PENDING',

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_document_chunk_raw_doc   ON document_chunk(raw_document_id);
CREATE INDEX idx_document_chunk_idx_status ON document_chunk(index_status) WHERE index_status = 'PENDING';
```

---

## document_index_status

청크별 OpenSearch 색인 이력 추적.
색인 실패 시 오류 메시지를 기록하여 운영자가 원인을 파악할 수 있게 한다.

```sql
CREATE TABLE document_index_status (
    index_status_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id        UUID         NOT NULL REFERENCES document_chunk(chunk_id),

    index_name      VARCHAR(100) NOT NULL,   -- OpenSearch 인덱스명
    opensearch_doc_id VARCHAR(200),          -- OpenSearch 내부 문서 ID

    status          VARCHAR(20)  NOT NULL,   -- DONE | FAILED
    error_message   TEXT,                    -- 실패 시 오류 내용
    indexed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_doc_index_status_chunk ON document_index_status(chunk_id);
```

---

## 테이블 관계 요약

```
raw_document
  │
  ├── raw_document_scan_state  (스캔 안정화 판단)
  │
  ├── document_parse_result    (1:1, kordoc 파싱 결과)
  │
  └── document_chunk           (1:N, 청크 분리 결과)
        │
        └── document_index_status  (1:N, 색인 이력)
```

---

## 마이그레이션 전략

- 초기 PoC: Alembic (Python) 또는 Flyway 기반 버전 관리
- 컬럼 추가는 nullable 또는 default 값 필수
- 컬럼 삭제 전 반드시 코드 참조 제거 확인
