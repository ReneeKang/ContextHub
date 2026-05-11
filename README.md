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

**파이프라인 순서**: 스캔 → 파서(`parse_status=DONE`) → 청커(`document_chunk` 생성, `chunk_status=DONE`) → 인덱서(stub: 대기 건만 로그).

청커는 **`parse_status=DONE`** 인 문서만 처리합니다. 로그에 `documents waiting on parser …` 가 나오면 파서 워커를 먼저 통과시키세요. 청킹 본문은 `app/chunker/service.py` 와 `markdown_chunk.py` 를 참고하면 됩니다.

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
3. **`POST /api/v1/chat/query`** 로 질문합니다. (DB `document_chunk` 검색: 공백으로 나눈 **모든** 토큰이 `chunk_text` 또는 `section_title`에 포함되어야 AND 매칭)

**기본 stub principal** (`app/chat/deps.py` 의 `get_stub_chat_principal`):

- **PUBLIC**: 항상 검색 가능 (`public/…`).
- **DEPT**: 기본값은 `department_codes=()` 이라 **`dept/infra/…` 문서는 검색되지 않음**. `INFRA_SAMPLE_KEYWORD` 만으로는 매칭 문서가 없어야 합니다.
- **PRIVATE**: `owner_id` 가 `stub-user` 인 경로만 가능 → `private/stub-user/…` 의 `PRIVATE_SAMPLE_KEYWORD` 는 매칭됩니다.

DEPT(infra) 문서까지 채팅에서 보고 싶으면 `get_stub_chat_principal` 에서 주석대로 `department_codes=("infra",)` 로 잠시 바꾼 뒤, 질문에 `INFRA_SAMPLE_KEYWORD` 또는 `ContextHub` 를 넣어 다시 호출합니다.

## 환경 변수 요약

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | 예: `postgresql+psycopg://contexthub:contexthub@127.0.0.1:5433/contexthub` (Compose 호스트 포트와 일치) |
| `NAS_INBOX_ROOT` | 반입 루트 (절대 경로 또는 **저장소 루트 기준 상대 경로**; 기본 `local_nas/chatbot_docs`) |
| `SCAN_INTERVAL_SECONDS` | (향후) 스캔/워커 주기 참고용 초 단위 |
| `SEARCH_INDEX_NAME` | (향후) OpenSearch 인덱스 이름 |
| `PARSER_NAME` / `PARSER_VERSION` | 파싱 결과 메타 |

## 외부 연동

- **kordoc**: `app.adapters.kordoc_stub` — 실제 연동 시 동일 `ParserClient` 프로토콜 구현체로 교체
- **OpenSearch / LLM**: `app.adapters.search_stub` 및 `app.chat.service` 내 TODO 참고

## DB 마이그레이션

이 저장소 단계에서는 **Alembic 없음**. 로컬은 `python -m app.db.init_db`만 사용하고, 스키마가 안정되면 Alembic 등 마이그레이션을 별도 단계에서 추가합니다.
