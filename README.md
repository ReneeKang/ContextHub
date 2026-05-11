# ContextHub

NAS 문서 기반 RAG/챗봇 시스템의 **PoC 골격**입니다. 설계는 `docs/` 디렉터리를 기준으로 합니다.

## 요구 사항

- Python 3.11+
- Docker Desktop (또는 Docker Engine) — 로컬 PostgreSQL용
- PostgreSQL은 Compose로 기동합니다. 앱은 `DATABASE_URL`로 접속합니다.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## 로컬 개발 실행 순서

### 1. PostgreSQL 기동 (Docker Compose)

저장소 루트에서:

```bash
docker compose up -d
```

- **DB**: `contexthub`
- **User / password**: `contexthub` / `contexthub`
- **Port**: 호스트 `5433` → 컨테이너 내부 `5432` (로컬에 이미 PostgreSQL이 `5432`를 쓰는 경우가 많아 Compose는 `5433`으로 노출합니다)
- **데이터**: 이름 붙은 볼륨 `contexthub_pgdata`

첫 기동 후 `pg_isready`가 성공할 때까지 잠시 기다린 뒤 다음 단계로 진행합니다.

이전에 기동이 실패했다면 `docker compose down` 후 다시 `docker compose up -d` 하세요. 이미 `.env`를 만들었다면 `DATABASE_URL`의 포트가 **5433**인지 확인하세요.

### 2. 환경 변수

`.env.example`을 복사해 `.env`를 만들고, 필요 시 `NAS_INBOX_ROOT`만 로컬 경로로 바꿉니다.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS / Linux:

```bash
cp .env.example .env
```

Compose 기본값과 맞춘 `DATABASE_URL`은 `.env.example`에 적어 두었습니다.

### 3. 개발용 DB 테이블 생성 (Alembic 없음)

ORM 메타데이터 기준으로 테이블만 생성합니다 (**운영 마이그레이션 아님**).

```bash
python -m app.db.init_db
```

구현은 `app/db/init_db.py`의 `create_all` 경로입니다.

### 3a. 기존 DB: `document_chunk` 확장 컬럼 (개발 전용)

이미 `init_db` 로 스키마가 잡혀 있는데 **청킹 메타 컬럼만** 빠진 경우(예: 이전 클론 DB), PostgreSQL에 한해 **비파괴 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`** 만 수행합니다. **운영·Alembic 대체용이 아님** (`app/db/dev_migrations.py` 주석 참고).

```bash
python -m app.db.dev_migrations
```

- 컬럼이 이미 있으면 해당 문은 건너뜁니다.
- 실패 시 stderr 로그에 **어느 단계(label)** 에서 실패했는지 남깁니다.

**이후 파이프라인(기존 문서를 새 청크 규칙으로 다시 쌓을 때)**:

1. `python -m app.db.dev_migrations` (위)
2. Admin **`POST /api/v1/admin/documents/{raw_document_id}/reprocess`** — body `{"stage":"chunk"}` (대상 문서마다, 또는 신규만)
3. **`python -m app.workers`** 로 청커·인덱서 등 실행

### 4. API 서버 (chat-api + admin-api)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 Swagger UI를 열어 동작을 확인합니다.

- **Swagger UI (`/docs`)**: `http://127.0.0.1:8000/docs`
- **ReDoc (`/redoc`)**: `http://127.0.0.1:8000/redoc`
- Chat API: `http://127.0.0.1:8000/api/v1/chat/...`
- Admin API: `http://127.0.0.1:8000/api/v1/admin/...`

### 5. 워커 (별도 터미널)

API와 **별도 진입점**입니다. 한 번 실행 시 단계별로 **각 서비스의 `run_once`만** 순서대로 호출합니다.

저장소 루트에서 실행해야 기본 `NAS_INBOX_ROOT=local_nas/chatbot_docs`가 올바르게 잡힙니다.

```bash
python -m app.workers
```

- 로그는 **표준 에러(stderr)** 로 출력되며, 레벨은 기본 **INFO** 입니다 (`logging` 모듈).
- 성공 시 마지막에 `worker cycle finished successfully (OK)` 가 나옵니다. 단계 중 예외가 나면 `logging.exception` 으로 스택트레이스가 붙고 **(ERROR)** 로 종료됩니다.
- DB 연결은 사이클 시작 시 `SELECT 1` 로 한 번 검증합니다.

**로컬 NAS 샘플**: `local_nas/chatbot_docs/public/sample.txt`  
스캐너는 `docs/pipeline-flow.md` 에 맞게 **mtime+size 가 연속 두 번 동일할 때만** `raw_document` 를 등록합니다. 첫 실행에서 안정화 대기만 보이면, 파일을 바꾸지 않은 채 **`python -m app.workers` 를 한 번 더** 실행해 보세요.

### 지원 문서 포맷 (파서)

워커의 파서는 **`RoutingParser`** (`app/adapters/parsers/routing.py`)가 MIME(파일명 추정) 또는 확장자로 어댑터를 고릅니다.

| 포맷 | 상태 | 엔진 | 비고 |
|------|------|------|------|
| `.txt` / `.md` | 지원 | `stub-text` | UTF-8 디코드, 줄 단위 블록 |
| `.pdf` | 지원 | `pypdf` | 텍스트 추출만, **OCR 없음** |
| `.docx` | 지원 | `python-docx` | 문단 + 스타일 기반 제목(`Heading n`, `Title`) → 마크다운 헤딩 |
| `.hwp` / `.hwpx` | 예정 | placeholder | 파싱 시도 시 **명시적 오류**(향후 kordoc 등 별도 연동) |
| 스캔 PDF·표·이미지 본문 | 미지원 | — | 빈 페이지 섹션 가능; OCR/레이아웃 복원은 범위 밖 |

`document_parse_result.parser_name`에는 실제 엔진 이름(`stub-text`, `pypdf`, `python-docx` 등)이 저장되고, 어댑터가 비우면 `PARSER_NAME` 기본값(`routing`)이 쓰입니다.

추가 샘플 파일과 테스트 순서는 **`sample_docs/README.md`** 를 참고하세요.

**파이프라인 순서**: 스캔 → 파서(`parse_status=DONE`) → 청커(`document_chunk` 생성, `chunk_status=DONE`) → 인덱서(stub: 대기 건만 로그).

청커는 **`parse_status=DONE`** 인 문서만 처리합니다. 로그에 `documents waiting on parser …` 가 나오면 파서 워커를 먼저 통과시키세요. 청킹 본문은 `app/chunker/service.py` 와 `markdown_chunk.py` 를 참고하면 됩니다.

### 청킹 전략 (요약)

- **설계·트레이드오프**: `docs/chunking-strategy.md` (문단 / 헤딩 / 페이지 / 슬라이딩 윈도우 / overlap 비교).
- **구현**: 마크다운 ATX 헤딩으로 1차 분리 → 선두 헤딩 체인으로 **`heading_path`**·**`section_title`**·PDF **`Page N` → `page_no`** → 길이 초과 시 **가변 경계 슬라이딩**(`CHUNK_MAX_CHARS` / `CHUNK_OVERLAP`) → 동일 섹션에서 **짧은 청크 병합**.
- **메타**: `document_chunk`에 `chunk_char_count`, `chunk_token_estimate`(문자/4 휴리스틱), `chunk_metadata_json`(청킹 버전 등). 인덱스 스텁 바디에도 동일 키를 넣어 향후 벡터 필드와 합치기 쉽게 유지.
- **운영 확인**: `GET /api/v1/admin/documents/{raw_document_id}` 응답의 **`chunks`** 배열(미리보기 텍스트·크기·`section_title`·`heading_path`·`source_page`).
- **기존 PostgreSQL DB**에 이미 `document_chunk` 가 있는 경우 `create_all`만으로는 새 컬럼이 생기지 않습니다. **`python -m app.db.dev_migrations`**(§3a) 또는 수동 SQL은 **`docs/chunking-strategy.md` §5** 를 참고하세요.

스키마 스냅샷은 `docs/db-schema.md` 의 `document_chunk` 절을 참고합니다.

### 6. Chat 권한 필터 검증 (샘플 NAS)

권한별 샘플 파일(공통 키워드 **ContextHub** + 고유 키워드):

| 경로 | access_scope | 고유 키워드(질문에 넣어 테스트) |
|------|----------------|-------------------------------|
| `local_nas/chatbot_docs/public/sample-public.txt` | PUBLIC | `PUBLIC_SAMPLE_KEYWORD` |
| `local_nas/chatbot_docs/dept/infra/sample-infra.txt` | DEPT (`infra`) | `INFRA_SAMPLE_KEYWORD` |
| `local_nas/chatbot_docs/private/stub-user/sample-private.txt` | PRIVATE (`stub-user`) | `PRIVATE_SAMPLE_KEYWORD` |

기존 `public/sample.txt` 도 그대로 두어도 됩니다.

**테스트 순서 (Swagger)**

1. 저장소 루트에서 **`python -m app.workers` 를 2회 이상** 실행해 새 파일이 스캔·안정화·파싱·청킹·색인까지 반영합니다. (스캐너는 mtime/size 안정화 규칙을 따릅니다.)
2. **`GET /api/v1/admin/documents`** 로 `ingest_status=RECEIVED` 등으로 문서 3건(+기존 샘플)이 보이는지 확인합니다.
3. **`POST /api/v1/chat/query`** 로 질문합니다. (DB `document_chunk` 검색: 공백으로 나눈 **모든** 토큰이 `chunk_text`, `section_title`, **`heading_path`** 중 하나에 포함되어야 AND 매칭)

**관리자 재처리·검색 제외 (Swagger `/docs`)**

1. **`GET /api/v1/admin/documents/{raw_document_id}`** 로 대상 UUID를 확인합니다 (`GET /api/v1/admin/documents` 목록의 `raw_document_id`).
2. **`POST /api/v1/admin/documents/{raw_document_id}/exclude`** — body 예: `{"reason":"manual takedown"}` → `excluded=true` 저장, 인덱서용 `SearchClient.delete_chunks_for_document` 호출(스텁은 로그만). 이어서 **`POST /api/v1/chat/query`** 로 같은 문서 키워드를 질의해 **DB 검색 경로에서는 결과에서 빠지는지** 확인합니다 (`SEARCH_BACKEND=db` 기준).
3. **`POST /api/v1/admin/documents/{raw_document_id}/include`** → 제외 해제 및 청크·문서 `index_status=PENDING` 리셋 후, **`python -m app.workers`** 를 한 번 더 돌려 색인을 복구합니다.
4. **`POST /api/v1/admin/documents/{raw_document_id}/reprocess`** — body `{"stage":"parse"|"chunk"|"index"}` 로 단계별 DB 파생 데이터 삭제·상태 리셋(정책은 `docs/ops-reprocess.md`) 후 워커를 다시 실행해 파이프라인이 이어지는지 확인합니다. `ingest_status=DUPLICATE` 인 행은 **400** 으로 거절됩니다.

Swagger에서 **admin** 태그 아래 위 엔드포인트를 펼치고 **Try it out** → UUID·JSON 입력 → **Execute** 순으로 호출하면 됩니다.

**Stub principal** (`app/chat/deps.py` 의 `resolve_stub_principal_for_chat`): `user_id` 는 고정 `stub-user` 이고, **`department_codes` 는 요청 필드로만 덮어씁니다.**

- **PUBLIC**: 항상 검색 가능 (`public/…`).
- **DEPT**: `test_department_codes` 에 해당 부서 코드가 없으면 `department_codes=()` 로 간주되어 **`dept/infra/…` 청크는 SQL 권한 필터에서 제외**됩니다.
- **PRIVATE**: `owner_id` 가 `stub-user` 인 경로만 가능 → `private/stub-user/…` 의 `PRIVATE_SAMPLE_KEYWORD` 는 매칭됩니다.

**DEPT(infra) 검증 (코드 수정 없이 Swagger)** — `POST /api/v1/chat/query` body 예시:

```json
{
  "question": "INFRA_SAMPLE_KEYWORD",
  "top_k": 5,
  "test_department_codes": ["infra"]
}
```

- `test_department_codes` **생략** 또는 `[]` → infra 전용 키워드는 **결과 없음**이 정상입니다.
- `["infra"]` → `dept/infra/sample-infra.txt` 에서 색인된 청크가 매칭될 수 있습니다.

`test_department_codes` 는 **개발·테스트 전용** 필드입니다. 운영 인증 도입 시 세션/Bearer에서 부서를 채우고 이 필드는 무시·제거하면 됩니다.

### 검색 백엔드 (요약)

| 단계 | 동작 |
|------|------|
| **현재 (기본)** | `SEARCH_BACKEND=db` → 채팅은 **`DbChunkSearchClient`**: `document_chunk` + **SQL 권한 필터** (`app/adapters/db_chunk_search.py`). 인덱서는 **`StubSearchClient`** 로 index/delete no-op (DB만 진실). |
| **통합 스텁** | `SEARCH_BACKEND=opensearch_stub` → **`OpenSearchSearchClient`**: OpenSearch에 보낼 **쿼리/바디 JSON**을 조립·검증·로그만 하고 **HTTP는 호출하지 않음**. 채팅 `search()`는 빈 결과. |
| **향후** | 동일 `SearchClient` 프로토콜을 구현한 **HTTP 클라이언트** 클래스를 추가하고, `search_backend.py` / 설정에서 선택. 권한은 **`opensearch_payload.build_permission_filter_clause`** 와 동일한 `bool.filter` 를 쿼리에 포함. **Hybrid** 는 BM25 `must` + `knn`/벡터 `should` + 동일 `filter` (자세한 매핑·단계는 `docs/search-index.md`). |

관련 코드: `app/adapters/search_protocol.py`, `opensearch_payload.py`, `opensearch_stub.py`, `search_backend.py`, `app/chat/deps.py` 의 `get_search_client`.

## 환경 변수 요약

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | 예: `postgresql+psycopg://contexthub:contexthub@127.0.0.1:5433/contexthub` (Compose 호스트 포트와 일치) |
| `NAS_INBOX_ROOT` | 반입 루트 (절대 경로 또는 **저장소 루트 기준 상대 경로**; 기본 `local_nas/chatbot_docs`) |
| `SCAN_INTERVAL_SECONDS` | (향후) 스캔/워커 주기 참고용 초 단위 |
| `SEARCH_INDEX_NAME` | OpenSearch 인덱스 논리 이름 (`contexthub_chunks`) |
| `SEARCH_BACKEND` | `db`(기본) 또는 `opensearch_stub`(로그만; 클러스터 없음) |
| `OPENSEARCH_BASE_URL` | 실제 연동 시 예: `https://localhost:9200` (현재 스텁 경로에서는 미사용) |
| `PARSER_NAME` / `PARSER_VERSION` | DB에 쓸 파서 이름 폴백(기본 `routing`) / 버전 폴백; 포맷별 어댑터가 `parser_name`·`parser_version`을 넣으면 그 값이 우선 |

## 외부 연동

- **파서**: `app.adapters.parsers.RoutingParser` + `ParserClient` 구현체(`pypdf`, `python-docx`, `stub-text` 등). **kordoc 실연동은 아직 없음**; 과거 import 경로 `KordocStubParser`는 `stub-text`와 동일(`app/adapters/kordoc_stub.py`).
- **OpenSearch / LLM**: `app.adapters.search_stub` 및 `app.chat.service` 내 TODO 참고

## DB 마이그레이션

이 저장소 단계에서는 **Alembic 없음**. 로컬은 `python -m app.db.init_db`로 최초 테이블 생성하고, 이미 만든 DB에 **컬럼만 덧붙일 때**는 개발용 `python -m app.db.dev_migrations`(PostgreSQL, 비파괴)를 쓸 수 있습니다. 스키마가 안정되면 Alembic 등으로 이전하는 것이 좋습니다.
