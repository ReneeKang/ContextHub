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

### 1. PostgreSQL · OpenSearch 기동 (Docker Compose)

저장소 루트에서:

```bash
docker compose up -d
```

- **DB**: `contexthub`
- **User / password**: `contexthub` / `contexthub`
- **Port**: 호스트 `5433` → 컨테이너 내부 `5432` (로컬에 이미 PostgreSQL이 `5432`를 쓰는 경우가 많아 Compose는 `5433`으로 노출합니다)
- **데이터**: 이름 붙은 볼륨 `contexthub_pgdata`
- **OpenSearch** (선택, 실 검색/색인용): Compose는 호스트 **9201** → 컨테이너 **9200** 으로 매핑합니다(로컬에서 **9200 포트가 이미 쓰인 경우**가 많아 기본 개발 포트를 9201로 둠). HTTP 예: `http://127.0.0.1:9201`. 이미지는 **`docker/opensearch/Dockerfile`** 로 빌드하며 **`analysis-nori`** 플러그인을 포함합니다. 최초/매핑 변경 후: `docker compose build opensearch && docker compose up -d`. 보안 플러그인은 **비활성**(`plugins.security.disabled=true`) 개발 설정입니다. Linux 호스트에서 컨테이너가 바로 죽으면 `vm.max_map_count` 등 OpenSearch 요구사항을 확인하세요.
- **OpenSearch 초기 admin 비밀번호 (Compose 전용)**: OpenSearch **2.12 이상**은 컨테이너 기동 시 데모 보안 설치 단계에서 `OPENSEARCH_INITIAL_ADMIN_PASSWORD`가 없으면 **즉시 종료**됩니다. `docker-compose.yml`에 **로컬 개발용** 데모 값(`ContextHubAdmin123!`)을 넣어 두었습니다. 이 값은 **운영 환경에서 절대 사용하지 마세요.** 운영에서는 Security 플러그인·TLS·계정/역할·네트워크 격리 등을 **별도로 설계**하고, 비밀번호·인증서는 비밀 저장소 등으로 관리해야 합니다. 앱의 `OPENSEARCH_BASE_URL`은 **무인증 HTTP**(개발)로 붙는 경로와 별개이며, 이 데모 패스워드를 앱 설정에 넣을 필요는 없습니다.

첫 기동 후 `pg_isready`가 성공할 때까지 잠시 기다린 뒤 다음 단계로 진행합니다. OpenSearch는 healthcheck 통과까지 **1분 내외** 걸릴 수 있습니다.

이전에 기동이 실패했다면 `docker compose down` 후 다시 `docker compose up -d` 하세요. 이미 `.env`를 만들었다면 `DATABASE_URL`의 포트가 **5433**인지 확인하세요.

#### OpenSearch 인덱스 생성 (한 번)

`.env`에 `OPENSEARCH_BASE_URL=http://127.0.0.1:9201` 를 넣은 뒤:

```bash
python -m app.db.opensearch_bootstrap
```

인덱스 이름은 `SEARCH_INDEX_NAME`(기본 `contexthub_chunks`)입니다. 이미 있으면 **건너뜁니다**. 매핑·분석기는 `docs/search-index.md` 및 `app/adapters/opensearch_index_mapping.py` 를 참고하세요.

#### OpenSearch 개발용 인덱스 리셋 (매핑·분석기 변경 후)

**운영에서는 사용하지 마세요.** `app/db/opensearch_reset_dev.py` 는 로컬에서 매핑/분석기(nori 등)를 바꾼 뒤 인덱스를 비우고 다시 올릴 때만 쓰는 스크립트입니다.

동작 요약:

1. `SEARCH_INDEX_NAME`에 해당하는 OpenSearch 인덱스가 있으면 **삭제** 후, `python -m app.db.opensearch_bootstrap` 과 **동일한** `chunk_index_create_body()`로 **재생성**합니다.
2. PostgreSQL: 모든 `document_chunk.index_status`·`raw_document.index_status`를 **PENDING**으로 되돌려 워커가 다시 색인하도록 합니다.
3. **`document_index_status`**: 같은 인덱스 이름(`index_name` = 현재 `SEARCH_INDEX_NAME`)에 대한 이력 행은 **삭제**합니다. 재색인 시 인덱서가 DONE/FAILED 이력을 새로 쌓으며, 관리 화면 등에서 이전 성공 건수와 실제 OpenSearch 상태가 어긋나지 않게 하기 위함입니다. (다른 인덱스 이름으로 쌓인 과거 행은 그대로 둡니다.)

실행 순서 예시:

```bash
docker compose build opensearch
docker compose up -d
python -m app.db.opensearch_reset_dev
python -m app.workers
```

- **리셋 스크립트가 인덱스를 삭제 후 재생성**하므로, 매핑 변경 루프에서는 위처럼 `opensearch_reset_dev`만으로 충분합니다. OpenSearch를 처음 붙일 때만 `python -m app.db.opensearch_bootstrap` 으로 인덱스를 만들어도 됩니다(이미 있으면 스킵).
- 워커를 한 번 이상 돌려 PENDING 청크를 소비한 뒤, `SEARCH_BACKEND=opensearch`인 상태에서 Swagger **`POST /api/v1/chat/query`** 등으로 검색을 확인하면 됩니다.

실제 HTTP 검색/색인을 쓰려면 같은 `.env`에서 **`SEARCH_BACKEND=opensearch`** 로 바꾼 다음 API·워커를 재시작합니다. 기본값 **`SEARCH_BACKEND=db`** 는 PostgreSQL 폴백을 유지합니다.

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
2. **`POST /api/v1/admin/documents/{raw_document_id}/exclude`** — body 예: `{"reason":"manual takedown"}` → `excluded=true` 저장, `SearchClient.delete_chunks_for_document` 호출(`SEARCH_BACKEND=db` 는 스텁, **`opensearch`** 는 실제 delete-by-query). 이어서 **`POST /api/v1/chat/query`** 로 같은 문서 키워드를 질의해 결과에서 빠지는지 확인합니다 (`SEARCH_BACKEND` 에 맞는 백엔드 기준).
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
| **기본 (폴백)** | `SEARCH_BACKEND=db` → 채팅 **`DbChunkSearchClient`** (`document_chunk` + SQL 권한 필터). 인덱서는 **`StubSearchClient`** (index/delete no-op; DB가 진실). |
| **통합 스텁** | `SEARCH_BACKEND=opensearch_stub` → **`OpenSearchSearchClient`**: 쿼리/페이로드 검증·로그만, **HTTP 없음**. |
| **OpenSearch HTTP** | `SEARCH_BACKEND=opensearch` + `OPENSEARCH_BASE_URL` → **`OpenSearchHttpClient`** (`opensearch_client.py`): `index` / `search` / `delete_by_query` 실호출. 권한은 **`opensearch_payload.build_keyword_search_body`** 의 `bool.filter` (앱 레벨에서 결과를 좁히지 않음). |

관련 코드: `app/adapters/search_protocol.py`, `opensearch_payload.py`, `opensearch_stub.py`, `opensearch_client.py`, `opensearch_index_mapping.py`, `search_backend.py`, `app/chat/deps.py` 의 `get_search_client`.

**Hybrid / 벡터** 는 BM25 `must` + `knn` `should` + 동일 `filter` 로 확장 (미구현). 품질·재색인·nori 전략은 **`docs/search-quality.md`** 를 참고하세요.

## 환경 변수 요약

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | 예: `postgresql+psycopg://contexthub:contexthub@127.0.0.1:5433/contexthub` (Compose 호스트 포트와 일치) |
| `NAS_INBOX_ROOT` | 반입 루트 (절대 경로 또는 **저장소 루트 기준 상대 경로**; 기본 `local_nas/chatbot_docs`) |
| `SCAN_INTERVAL_SECONDS` | (향후) 스캔/워커 주기 참고용 초 단위 |
| `SEARCH_INDEX_NAME` | OpenSearch 인덱스 논리 이름 (`contexthub_chunks`) |
| `SEARCH_BACKEND` | `db`(기본) \| `opensearch_stub`(무HTTP) \| `opensearch`(HTTP; 인덱스 부트스트랩 필요) |
| `OPENSEARCH_BASE_URL` | 예: `http://127.0.0.1:9201` (Compose 기본 호스트 포트; `SEARCH_BACKEND=opensearch` 일 때 필수) |
| `OPENSEARCH_SEARCH_HIGHLIGHT` | `true`(기본): 검색 바디에 `highlight` 포함 |
| `OPENSEARCH_SEARCH_EXPLAIN` | `false`(기본): `true` 이면 첫 히트 BM25 explain 을 DEBUG 로그에 일부 출력 |
| `PARSER_NAME` / `PARSER_VERSION` | DB에 쓸 파서 이름 폴백(기본 `routing`) / 버전 폴백; 포맷별 어댑터가 `parser_name`·`parser_version`을 넣으면 그 값이 우선 |

## 외부 연동

- **파서**: `app.adapters.parsers.RoutingParser` + `ParserClient` 구현체(`pypdf`, `python-docx`, `stub-text` 등). **kordoc 실연동은 아직 없음**; 과거 import 경로 `KordocStubParser`는 `stub-text`와 동일(`app/adapters/kordoc_stub.py`).
- **OpenSearch**: `SEARCH_BACKEND=opensearch` → `app.adapters.opensearch_client.OpenSearchHttpClient`; 인덱스는 `python -m app.db.opensearch_bootstrap`. **LLM** 은 `app.chat.service` 등 TODO 참고.

## DB 마이그레이션

이 저장소 단계에서는 **Alembic 없음**. 로컬은 `python -m app.db.init_db`로 최초 테이블 생성하고, 이미 만든 DB에 **컬럼만 덧붙일 때**는 개발용 `python -m app.db.dev_migrations`(PostgreSQL, 비파괴)를 쓸 수 있습니다. 스키마가 안정되면 Alembic 등으로 이전하는 것이 좋습니다.
