# RAG 구축 트러블슈팅 기록 — ContextHub MVP 운영 일지

## 문서 목적

ContextHub RAG MVP를 실제로 구축하면서 부딪힌 문제들을
**발생 순서대로** 기록한 운영 일지다.

단순한 카테고리 분류가 아니라,
어떤 문제를 먼저 만났고, 그것이 어떻게 다음 문제로 이어졌는지
**흐름**이 보이도록 작성했다.

발표·업무보고·면접에서 "실제로 구축하면서 부딪힌 문제들"을
설명할 수 있는 수준을 목표로 한다.

---

## 전체 흐름 한눈에 보기

```
[1] Docker/인프라 부트스트랩
  └→ [2] NAS 스캐너 동작 확인
       └→ [3] 최초 ingestion MVP (txt/md)
            └→ [4] parser adapter 구조 도입
                 └→ [5] PDF/DOCX parser 확장
                      └→ [6] parser coverage 부족 발견
                           └→ [7] xlsx parser 추가
                                └→ [8] dependency drift
                                     └→ [9] FAILED 문서 재처리
                                          └→ [10] 파일명/경로 검색 약함
                                               └→ [11] mapping 변경 + 재색인
                                                    └→ [12] chunk 독점 문제
                                                         └→ [13] document-level recall 개선
                                                              └→ [14] precision 저하
                                                                   └→ [15] observability 부족
                                                                        └→ [16] POC UI API 연결
                                                                             └→ [17] 한글 IME 깨짐
                                                                                  └→ [18] 전체 흐름 안정화
                                                                                       └→ [19] generation vs retrieval 품질 분리
                                                                                            └→ [20] 문서 버전 ranking 문제
                                                                                                 └→ [21] 운영형 RAG 교훈 정리
```

---

## 1. Docker / 인프라 부트스트랩

### 증상

`docker compose up`이 실패했다.
PostgreSQL과 OpenSearch 컨테이너가 올라오지 않거나,
올라오더라도 Python 백엔드에서 연결 오류가 발생했다.
Windows 환경에서 Docker Desktop이 실행 중인데도 "Docker daemon에 연결할 수 없다"는 메시지가 나왔다.

### 원인 분석

크게 세 가지 원인이 겹쳐 있었다.

첫째, Windows CMD와 PowerShell에서 환경 변수 설정 방식이 달랐다.
`docker compose`가 `.env` 파일을 참조할 때 경로 구분자, 줄바꿈 인코딩이 플랫폼마다 달라 오작동했다.

둘째, Docker Desktop의 WSL2 통합 설정이 완전하지 않은 상태였다.
daemon이 시작됐다고 표시되어도 실제 소켓이 연결 가능한 상태가 되기까지 시간이 필요했다.

셋째, OpenSearch 단일 노드 설정에서 `vm.max_map_count` 값이 낮아 컨테이너가 OOM으로 종료됐다.

### 조치

- `docker compose.yml`에 `OPENSEARCH_JAVA_OPTS="-Xms512m -Xmx512m"` 메모리 제한 추가
- `opensearch-dashboards` 서비스를 개발 초기에 제외해 불필요한 리소스 사용 감소
- 환경 변수는 `.env` 파일로 통일하고 shell 직접 주입 방식 제거
- Docker Desktop 재시작 후 소켓 연결 대기 시간(30초)을 README에 명시

### 실무 포인트

인프라가 불안정한 상태에서는 애플리케이션 코드 오류와 인프라 오류를 구분하기 어렵다.
**먼저 컨테이너 각각을 독립적으로 healthcheck하는 절차를 정해두는 것이 중요하다.**
`docker compose ps`, `docker logs`, 각 서비스 `curl` 확인을 표준 절차로 만들었다.

### 이후 연결된 문제

인프라가 올라오자 NAS 스캐너가 실제로 파일을 감지하는지 확인해야 했다.

---

## 2. NAS 스캐너 동작 및 파일 감지 확인

### 증상

컨테이너가 올라왔는데 스캐너 워커가 실행되어도 `raw_document` 테이블에 행이 생기지 않았다.
`local_nas/chatbot_docs/public/` 에 파일을 넣었는데 감지가 안 됐다.

### 원인 분석

두 가지 문제가 있었다.

첫째, 스캐너가 바라보는 경로와 실제 파일이 있는 경로가 달랐다.
`.env`의 `NAS_ROOT` 가 컨테이너 내부 경로를 가리켜야 하는데 호스트 경로로 설정되어 있었다.
volume mount 설정이 맞지 않아 스캐너가 빈 디렉터리를 보고 있었다.

둘째, 파일 안정화(stabilization) 판단 로직이 처음에 명확하지 않았다.
같은 파일이 1차 스캔에서 발견되었지만 2차 스캔에서 `mtime`/`size` 비교 결과 "변경됨"으로 판단되어
계속 대기 상태로 남았다. 네트워크 드라이브에서 mtime이 부정확하게 반환되는 경우였다.

### 조치

- `docker-compose.yml`의 volume mount를 `./local_nas:/nas` 형태로 명시
- `.env`의 `NAS_ROOT=/nas/chatbot_docs` 로 컨테이너 내부 경로로 통일
- 안정화 판단을 `size` 일치 + `mtime` 2회 연속 동일로 조건 완화
- `raw_document_scan_state` 테이블에 `stable` 플래그 추가

### 실무 포인트

스캐너는 "파일이 업로드 완료된 상태인가"를 판단해야 한다.
업로드 중인 파일을 파싱하면 불완전한 내용이 색인된다.
**stabilization 개념**은 RAG 시스템에서 중요한 인프라 원칙이다:
1차 스캔에서 발견 → 다음 스캔에서도 동일 → "안정됨" 판단 후 등록.

### 이후 연결된 문제

파일 감지가 안정화되자 실제 ingestion 파이프라인을 최소한으로 연결해야 했다.

---

## 3. txt/md 기반 최소 Ingestion MVP

### 증상

파일 감지는 되는데 OpenSearch에서 검색이 안 됐다.
`discover` API를 호출하면 항상 결과가 0건이었다.

### 원인 분석

파이프라인 각 단계를 차례로 확인했다.

```
raw_document → ingest_status = RECEIVED  ✅
document_parse_result → 행 없음  ❌
```

parse worker가 실행되지 않고 있었다.
처음에는 parser, chunker, indexer, discover를 한 번에 연결하려다
worker 실행 순서와 상태 전환 흐름이 꼬였다.

### 조치

가장 단순한 포맷(`.txt`, `.md`)만으로 먼저 엔드-투-엔드를 연결했다.

```
txt 파일 → scanner → raw_document 등록
  → parse worker (txt → markdown_text 직접 읽기)
  → document_parse_result INSERT
  → chunk worker → document_chunk 생성
  → index worker → OpenSearch 색인
  → /discover 호출 → 결과 확인
```

최초 retrieval 성공을 확인한 뒤 포맷을 확장하는 방식으로 전환했다.

### 실무 포인트

**RAG는 완전한 파이프라인을 한 번에 구축하는 것이 아니라,
가장 단순한 포맷으로 파이프라인 전체를 먼저 연결하고 포맷을 순차적으로 확장하는 방식이 효과적이다.**

파이프라인 전체를 한 번에 연결하려다 어디서 막혔는지 모르는 상황이 생긴다.
txt로 먼저 연결하면 파이프라인 구조 문제와 포맷별 파서 문제를 분리해서 볼 수 있다.

### 이후 연결된 문제

txt만으로는 실제 사내 문서를 처리할 수 없었다. PDF/DOCX 지원이 필요했고,
이를 위해 포맷별 parser를 구조적으로 관리하는 방법이 필요했다.

---

## 4. Parser Adapter 구조 도입

### 증상

txt는 됐는데 PDF를 넣으면 `parse_status = FAILED` 가 됐다.
포맷마다 다른 처리 방식이 필요한데 하나의 함수로 처리하려다 복잡해졌다.

### 원인 분석

초기 parser 코드는 파일 확장자를 분기해 처리하는 단일 함수 구조였다.
포맷이 늘어날수록 조건 분기가 많아지고, 특정 포맷 처리가 실패해도
어느 포맷 처리 코드에서 문제가 생겼는지 추적이 어려웠다.

### 조치

`RoutingParser` 구조를 도입했다.

```
RoutingParser
  .parse(file_ext, file_bytes)
    → .txt / .md  → PlainTextParser
    → .pdf        → PdfPypdfParser
    → .docx       → DocxParser
    → .xlsx       → XlsxOpenpyxlParser  (나중에 추가)
    → .hwp/.hwpx  → KordocCliParser     (나중에 추가)
    → 기타         → UnsupportedFormatError
```

각 parser adapter는 `ParseResult(markdown_text, blocks_json, metadata_json, page_count, parser_name, parser_version)`를 반환하는 동일한 인터페이스를 구현한다.
`document_parse_result` 테이블은 어떤 adapter를 썼든 동일한 구조로 저장된다.

### 실무 포인트

**파서 교체나 추가가 `document-parse-worker` 내부에서만 일어나야 한다.**
chat-api, chunk-worker, index-worker는 파서가 무엇인지 알면 안 된다.
이 경계를 처음부터 잡아야 나중에 kordoc, pypdf 등을 교체할 때 범위가 명확하다.

### 이후 연결된 문제

구조가 생기자 PDF와 DOCX parser를 실제로 구현해야 했다.

---

## 5. PDF / DOCX Parser 확장

### 증상

PDF 파일을 넣으면 parse_status가 계속 FAILED였다.
초기에는 parser adapter 구조 자체 문제인지 pypdf 문제인지 구분이 안 됐다.

### 원인 분석

여러 PDF에서 서로 다른 이유로 실패했다.

- 스캔 PDF(이미지로만 구성): `pypdf`가 텍스트를 추출하지 못해 `markdown_text = ""`
- 암호화된 PDF: `pypdf`가 예외 발생
- 테이블이 많은 PDF: 텍스트가 추출되지만 구조가 무너져 청킹 품질 저하

DOCX에서는 `python-docx`가 도형, 텍스트 박스 내용을 추출하지 못하는 경우가 있었다.

### 조치

- 빈 `markdown_text`는 경고 로그 후 `parse_status = FAILED` (정상 처리로 오인하지 않도록)
- `parse_error_message` 컬럼을 `raw_document`에 추가해 원인 기록
- 스캔 PDF는 OCR 미지원임을 명시, 나중에 처리하기로 범위 확정
- DOCX는 `python-docx` 기반으로 단락(paragraph) + 표(table) → 마크다운 변환 구현

### 실무 포인트

**`markdown_text`가 비어 있어도 `parse_status = DONE`으로 처리하면 나중에 찾기 어렵다.**
파싱이 "실행됐다"와 "의미 있는 내용이 추출됐다"는 다르다.
빈 결과는 FAILED로 처리하거나 별도 상태(EMPTY)로 구분해야 한다.

`parse_error_message` 컬럼은 단순해 보이지만 실제 운영에서 결정적이다.
"왜 이 문서가 안 검색되지?"를 추적할 때 DB 한 줄만 보면 원인을 알 수 있다.

### 이후 연결된 문제

PDF/DOCX가 되자 사용자들이 xlsx, hwp 같은 다른 포맷을 넣기 시작했다.

---

## 6. Parser Coverage 부족 발견

### 증상

`"과업대비표"`로 검색해도 `ID_A01_과업대비표.xlsx`가 결과에 나오지 않았다.
처음에는 검색 키워드 문제라고 생각했다.
같은 주제의 PDF 문서는 잘 검색됐기 때문에 더 혼란스러웠다.

### 원인 분석

단계별로 파이프라인을 추적했다.

```sql
SELECT original_filename, parse_status, parse_error_message
FROM raw_document
WHERE original_filename LIKE '%과업대비표%';
```

결과: `parse_status = 'FAILED'`, `parse_error_message = 'Unsupported document type: xlsx'`

xlsx parser가 없었다. 파일은 scanner에 잡혀 `raw_document`에 등록됐지만
parse 단계에서 막혀 chunk도, index도 없었다.

OpenSearch에서 해당 `raw_document_id`로 직접 쿼리하면 결과 0건이 나왔다.
이것은 검색 품질 문제가 아니라 **ingestion 누락** 이었다.

### 조치 방향 결정

이 시점에서 중요한 결정을 내렸다: **"검색이 안 된다"는 증상을 보면 항상 ingestion 파이프라인부터 확인한다.**

```
체크 순서:
1. raw_document에 행이 있는가?           (scanner)
2. parse_status = DONE 인가?             (parser)
3. document_chunk에 행이 있는가?         (chunker)
4. index_status = DONE 인가?             (indexer)
5. OpenSearch에 실제 문서가 있는가?
6. 그 다음에야 검색 쿼리 문제를 본다
```

### 실무 포인트

**검색 품질 문제처럼 보여도 실제 원인이 ingestion 누락인 경우가 많다.**
ingestion 파이프라인이 단계별 상태를 DB에 기록하고,
운영자가 이를 쉽게 조회할 수 있어야 하는 이유가 바로 여기에 있다.
`parse_status`, `chunk_status`, `index_status`를 분리해 관리하는 것이 결정적이다.

### 이후 연결된 문제

xlsx parser를 추가해야 했다. 그리고 hwp/hwpx도 같은 이유로 누락 상태였다.

---

## 7. xlsx Parser 추가 (openpyxl)

### 증상

xlsx 문서 전체가 검색에서 제외되어 있었다.
한국 공공기관·기업에서 xlsx를 많이 쓰기 때문에 이 포맷 지원은 필수였다.

### 조치

`openpyxl` 기반 `XlsxOpenpyxlParser` adapter를 구현했다.

- 시트별로 순회하면서 각 셀의 내용을 마크다운 테이블 형식으로 변환
- 시트 이름을 `## 시트명` 헤딩으로 추가
- 병합 셀 처리: 병합된 영역의 값은 첫 번째 셀에만 포함
- 빈 시트는 건너뜀

동시에 hwp/hwpx는 `kordoc CLI`를 subprocess로 호출하는 `KordocCliParser`를 추가했다.
kordoc CLI는 Node.js 기반이라 `KORDOC_ENGINE_CMD` 환경변수로 실행 명령을 주입받는다.

`parse_error_message` 컬럼도 이때 `raw_document`에 추가했다.

### 실무 포인트

xlsx → 마크다운 변환에서 중요한 결정은 **표 구조를 얼마나 보존할 것인가**다.
완벽한 재현을 목표로 하면 복잡도가 급증한다.
RAG 청킹 목적에서는 "내용이 텍스트로 추출됐는가"가 더 중요하다.
완벽한 표 렌더링보다 내용 추출에 집중했다.

### 이후 연결된 문제

parser를 추가했는데 실행 환경에서 `openpyxl` 모듈을 찾지 못하는 오류가 발생했다.

---

## 8. Parser Dependency Drift

### 증상

`openpyxl`을 코드에 import했는데 worker 실행 시 `ModuleNotFoundError: No module named 'openpyxl'` 가 발생했다.
로컬 개발 환경에서는 잘 됐는데 배포 환경(또는 새로 설정한 환경)에서 실패했다.

### 원인 분석

`pyproject.toml`의 `[project.dependencies]`에 `openpyxl`을 추가했지만
실행 환경에서 `pip install -e .` 를 다시 실행하지 않았다.
또는 `pyproject.toml` 변경 전에 이미 설치된 환경을 그대로 사용했다.

의존성 파일과 실제 설치된 패키지가 동기화되지 않은 상태였다.

### 조치

- `pyproject.toml`에 `openpyxl`, `pypdf`, `python-docx` 모두 명시
- 환경 설정 절차에 `pip install -e ".[dev]"` 필수 단계 추가
- CI/CD가 없는 환경에서는 `requirements.txt`도 병행 관리

### 실무 포인트

**parser adapter를 추가할 때마다 의존성 파일 동기화가 필수다.**
하나의 parser가 실패하면 해당 포맷의 모든 문서가 FAILED가 된다.
신규 parser 추가 체크리스트에 "의존성 추가 + 환경 재설치 확인"을 포함해야 한다.

### 이후 연결된 문제

parser가 다 추가됐는데도 기존에 FAILED 됐던 문서들이 자동으로 재처리되지 않았다.

---

## 9. FAILED 문서 재처리가 자동으로 되지 않음

### 증상

xlsx parser를 추가했는데도 기존 xlsx 문서가 검색되지 않았다.
새로 반입한 xlsx 파일은 정상적으로 검색됐다.

### 원인 분석

parse worker는 `parse_status = 'PENDING'`인 문서만 처리한다.
이미 `parse_status = 'FAILED'`로 기록된 문서는 worker가 자동으로 다시 시도하지 않는다.

이것은 의도된 설계다:
자동 재시도를 하면 파서 버그가 있을 때 무한 루프가 발생할 수 있다.
재처리는 운영자가 원인을 확인하고 명시적으로 트리거해야 한다.

### 조치

1. `GET /admin/documents?parse_status=FAILED` 로 실패 문서 목록 확인
2. `POST /admin/documents/{id}/reprocess {"stage": "parse"}` 호출
   → `parse_status = 'PENDING'`으로 리셋
   → `parse_error_message` 클리어
   → `chunk_status`, `index_status`도 연쇄 리셋
3. Worker 재실행 → `DONE → DONE → DONE` 흐름 확인

여러 문서를 일괄 재처리할 때는 FAILED 목록을 조회하여 loop 처리했다.

### 실무 포인트

**parser를 개선하거나 교체한 뒤에는 기존 실패 문서를 재처리하는 운영 절차가 필요하다.**

```
parser 업그레이드 표준 절차:
1. 새 parser adapter 코드 배포
2. 의존성 재설치 확인
3. 새 파일 1개로 parser 동작 확인
4. FAILED 문서 목록 조회 (parse_error_message 원인 필터)
5. 해당 포맷 문서 reprocess (stage=parse)
6. Worker 실행 → 상태 확인
7. 이미 DONE인 문서는 재처리 불필요
```

이 절차를 admin-api와 결합하면 운영자가 코드 없이 대응할 수 있다.

### 이후 연결된 문제

모든 포맷이 정상 ingestion되자 이번에는 진짜 검색 품질 문제가 드러났다.
파일명이나 경로로 검색하면 결과가 약했다.

---

## 10. 파일명 / 경로 기반 검색 품질 부족

### 증상

`"ID_A01_과업대비표"` (파일명 그대로 검색)를 입력했을 때 결과가 0건이거나 매우 약했다.
파일 내용이 아니라 파일명으로 문서를 찾으려는 사용자 패턴이 많았다.

### 원인 분석

초기 OpenSearch 매핑에서 검색 대상 필드는 `chunk_text`와 `section_title` 위주였다.
`original_filename`과 `inbox_path`는 필터용 `keyword` 타입으로만 설정되어 있었다.
즉, 파일명과 경로는 **full-text 검색 대상이 아니었다**.

사내 문서 검색 패턴을 관찰한 결과:
- 담당자가 파일명을 알고 있는 경우: "ID_A01" 또는 "과업대비표" 검색
- 프로젝트 경로를 알고 있는 경우: "sanrim-platform 문서" 검색
- 이 두 패턴 모두 본문 기반 BM25로는 잘 안 됐다

### 조치

OpenSearch 매핑에 필드를 추가하고 boost 설정을 조정했다.

```json
"original_filename": {
  "type": "text",
  "analyzer": "nori",
  "fields": {
    "keyword": { "type": "keyword" }
  }
},
"inbox_path": {
  "type": "text",
  "analyzer": "nori"
}
```

검색 쿼리에서 boost 적용:
```json
"multi_match": {
  "fields": [
    "chunk_text",
    "section_title^2",
    "original_filename^4",
    "inbox_path^2",
    "heading_path^1.5"
  ]
}
```

### 실무 포인트

**사내 문서 RAG에서는 파일명과 폴더 경로가 본문보다 강한 검색 단서가 될 때가 많다.**
일반 웹 검색은 본문 기반 BM25가 효과적이지만,
사내 문서는 담당자가 파일명·경로를 기억하고 검색하는 패턴이 지배적이다.

매핑 설계 시 `chunk_text` 위주 설계는 사내 문서 RAG에서 함정이다.
반드시 `original_filename`, `inbox_path` 같은 메타데이터 필드도 검색 대상에 포함해야 한다.

### 이후 연결된 문제

매핑을 변경해야 했는데, 기존 인덱스에는 반영되지 않는다는 문제가 있었다.

---

## 11. OpenSearch 매핑 변경과 재색인 필요

### 증상

매핑 파일을 수정하고 서버를 재시작했는데 검색 결과가 변하지 않았다.

### 원인 분석

OpenSearch(Elasticsearch)에서 기존 인덱스의 매핑은 변경 후 자동으로 반영되지 않는다.
새 필드를 추가하거나 분석기(analyzer)를 변경하면
**인덱스를 삭제하고 재생성한 뒤 전체 재색인**이 필요하다.

기존 인덱스에 이미 색인된 문서들은 이전 매핑으로 저장되어 있어
새 매핑을 적용해도 기존 데이터에는 영향이 없다.

### 조치

개발 환경에서는 `opensearch_reset_dev` 스크립트로 처리했다.

```
1. OpenSearch 인덱스 삭제
2. 새 매핑으로 인덱스 재생성
3. DB의 document_chunk.index_status = 'PENDING' 전체 리셋
4. index worker 실행 → 전체 재색인
```

운영 환경에서는 인덱스 alias를 이용한 무중단 전환이 필요하다 (현재 PoC 이후 과제).

### 실무 포인트

**매핑 변경은 대규모 운영 작업이다. PoC에서 매핑 설계를 충분히 검토하고 시작해야 한다.**

매핑 변경 → 재색인은:
- 전체 chunk 수에 비례하는 시간이 소요된다
- 재색인 중에는 검색 품질이 저하될 수 있다 (일부는 이전 매핑, 일부는 새 매핑)
- 운영 환경에서는 alias 기반 Blue/Green 인덱스 전환 전략이 필요하다

매핑은 나중에 바꾸면 비용이 크다. 처음 설계 시 메타데이터 필드까지 포함해야 한다.

### 이후 연결된 문제

매핑이 개선되고 재색인이 완료되자 이번에는 새로운 문제가 나타났다.
특정 질의에서 한 문서의 chunk가 검색 결과를 독점했다.

---

## 12. Chunk 독점 — Document-level Recall 부재

### 증상

`"과업대비표"` 검색 시 `/discover` 응답에서 `total_matched_docs = 1`이었다.
해당 문서 하나의 `matched_chunk_count = 30` 이었다.

관련 문서가 여러 개 있을 것으로 예상되는 질의인데도 사용자에게 후보가 1개만 제시됐다.

### 원인 분석

`/discover` 요청의 `top_k`가 그대로 OpenSearch `size` 파라미터로 사용되고 있었다.

```
top_k = 5 요청
  → OpenSearch: hits size = 5
  → 상위 5개 chunk가 전부 같은 문서에서 나옴
  → raw_document_id 기준 groupBy
  → 결과: 문서 1개, matched_chunk_count = 5
```

한 문서에서 관련 chunk가 많으면 그 문서가 chunk를 독점하고,
다른 문서의 chunk는 top 5 밖으로 밀려나 아예 후보에 등장하지 않았다.

이것은 **chunk precision**(개별 chunk 관련성)과 **document recall**(다양한 문서 포함)이 충돌하는 구조적 문제다.

### 실무 포인트

이 시점에서 RAG 시스템에서 retrieval의 두 가지 관점을 분리해서 이해하게 됐다.

| 관점 | 질문 | 관련 메트릭 |
|------|------|-----------|
| Chunk Precision | 가져온 chunk들이 질문과 얼마나 관련 있는가? | BM25 스코어, 관련 청크 비율 |
| Document Recall | 관련 문서들이 빠지지 않고 후보에 포함됐는가? | 총 반환 문서 수, 관련 문서 누락률 |

단순 챗봇은 chunk precision만 고려해도 된다.
**문서 선택 UI가 있는 시스템에서는 document recall과 diversity가 중요하다.**
사용자가 선택할 수 있는 충분한 후보가 제시되어야 한다.

### 이후 연결된 문제

document-level recall을 개선하는 방법을 설계해야 했다.

---

## 13. Document-level Recall 개선 — Chunk/Document Top-K 분리

### 조치

`top_k`의 의미를 두 층으로 분리했다.

```python
# 이전: top_k가 chunk size로 직접 사용됨
chunk_hits = opensearch.search(query, size=body.top_k)

# 이후: 두 층 분리
top_k_documents   = body.top_k              # 사용자에게 보여줄 문서 수
chunk_fetch_size  = max(top_k_documents * 10, 50)  # 넉넉하게 가져올 chunk 수

chunk_hits = opensearch.search(query, size=chunk_fetch_size)

# raw_document_id 기준 그룹핑
# → 문서당 matched_chunks 최대 5개로 제한
# → top_k_documents 개 문서 반환
```

chunk를 넉넉하게 가져온 뒤 문서 단위로 집계하면,
한 문서가 chunk를 독점해도 다른 문서의 chunk도 포함될 수 있다.

### 실무 포인트

`top_k = 5`로 요청했을 때 사용자에게 5개 문서를 보여주려면
OpenSearch에서는 50개 chunk를 가져와야 할 수 있다.
이 불일치를 시스템이 내부적으로 처리해야 한다.
사용자에게 노출되는 `top_k`(문서 수)와 내부 `chunk_fetch_size`는 분리된 개념이다.

### 이후 연결된 문제

document diversity가 개선되자 이번에는 낮은 관련성의 문서가 후보에 섞이기 시작했다.

---

## 14. Recall 개선 이후 Low-quality Candidate 유입

### 증상

`"과업대비표"` 검색 시 관련 없는 `ID_P05_테일러링내역서.pdf`가 후보 목록에 포함됐다.
점수가 낮은 문서(`top_score ≈ 0.2`)도 문서 후보로 나타났다.

### 원인 분석

chunk_fetch_size를 늘려 여러 문서를 포함하게 만들었더니,
관련성이 낮은 문서도 후보에 포함되기 시작했다.
이것은 **precision vs recall의 전형적인 트레이드오프**다.

recall을 높이면 precision이 낮아질 수 있다.
반대로 precision을 높이면 (threshold를 높이면) recall이 낮아진다.

### 조치 방향 결정

현재 PoC 단계에서는 두 가지 방향을 선택했다.

1. **Score threshold 적용**: `top_score < 0.3`인 문서는 후보에서 제외
2. **문서 카드에 점수 표시**: 사용자가 점수를 보고 직접 판단할 수 있도록

완전한 해결책은 reranking(cross-encoder로 문서-질문 관련성 재평가)이지만
이것은 PoC 이후 과제로 남겼다.

### 실무 포인트

**RAG에서 retrieval 품질을 한 번에 최적화하는 방법은 없다.**
precision과 recall은 서로 상충하며, 어느 쪽을 우선할지는 사용 패턴에 따라 다르다.

사용자가 직접 문서를 선택하는 UI에서는 recall이 더 중요하다.
(나쁜 후보는 선택 안 하면 되기 때문)
자동으로 컨텍스트를 구성하는 시스템에서는 precision이 더 중요하다.
(나쁜 chunk가 컨텍스트에 포함되면 답변 품질이 저하됨)

### 이후 연결된 문제

"왜 이 문서가 검색됐는가"를 설명할 수 없다는 문제가 생겼다.
낮은 점수 문서가 왜 나왔는지 추적하기 어려웠다.

---

## 15. Retrieval Observability 부족

### 증상

`/discover` 결과를 보면서 "왜 이 문서가 나왔지?"를 설명할 방법이 없었다.
어떤 필드에서 매칭됐는지, 어떤 토큰이 매칭됐는지 볼 수 없었다.

검색 품질을 개선하려면 현재 상태를 관찰할 수 있어야 하는데,
결과(문서 목록)만 보이고 이유(왜 이 문서인가)가 보이지 않았다.

### 원인 분석

초기 구현에서는 OpenSearch 응답에서 `_source`(문서 내용)만 추출하고
`_score`, `matched_queries`, `highlight` 정보는 버렸다.

### 조치

`ENABLE_RETRIEVAL_DEBUG=true` 환경변수가 있을 때 응답에 `debug` 객체를 포함하도록 했다.

```json
{
  "debug": {
    "original_query": "과업대비표",
    "retrieval_query": "과업대비표",
    "normalization_applied": false,
    "retrieval_backend": "opensearch",
    "chunks": [
      {
        "chunk_id": "...",
        "document_rank": 1,
        "chunk_rank": 1,
        "score": 0.87,
        "matched_fields": ["original_filename", "chunk_text"],
        "highlight_terms": ["과업대비표"]
      }
    ]
  }
}
```

이 정보를 통해:
- 어떤 필드에서 매칭됐는지 (`matched_fields`)
- 어떤 토큰이 매칭됐는지 (`highlight_terms`)
- chunk와 문서의 상대적 순위 (`document_rank`, `chunk_rank`)

를 확인하고 boost 설정을 튜닝할 수 있게 됐다.

### 실무 포인트

**RAG 검색 품질을 개선하려면 "왜 검색됐는가"를 볼 수 있어야 한다.**
결과만 보고 boost 값을 바꾸는 것은 감(感) 튜닝이다.
`matched_fields`를 보면 어떤 필드 boost를 올려야 할지 명확해진다.

운영 환경에서는 `ENABLE_RETRIEVAL_DEBUG=false`(기본값)로 유지하고,
개발·스테이징에서는 항상 켜두는 것이 효과적이다.
로그보다 UI 패널로 노출하면 기획자·운영자도 직접 확인할 수 있다.

### 이후 연결된 문제

백엔드 observability가 갖춰지자 POC UI에서 이를 보여주는 작업을 시작했다.

---

## 16. POC UI API 연결 (Wiring)

### 증상

백엔드가 동작하는데 UI가 없어 브라우저에서 직접 확인이 불가능했다.
Swagger로 테스트하면 되지만, 비개발자(기획자, 운영자)가 사용하기 어렵고
discover → 문서 선택 → generate 흐름을 연속으로 테스트하기 불편했다.

### 조치

FastAPI StaticFiles 기반으로 POC UI를 구축하고
`/api/v1/chat/discover` → 문서 선택 → `/api/v1/chat/generate` 흐름을 연결했다.

파일 구조를 역할별로 분리했다:
- `api.js`: fetch 처리, FastAPI detail 에러 파싱, 빈 결과 판별
- `state.js`: phase 관리, selectedDocumentIds Set, 버튼 활성화 판단
- `main.js`: 이벤트 처리, API 호출 흐름 제어
- `render.js`: API 응답 기반 DOM 렌더링, progress 단계 표시

`ENABLE_RETRIEVAL_DEBUG=true` 상태에서 debug 객체를 UI 패널로 표시해
`matched_fields`, `highlight_terms`, `document_rank`를 브라우저에서 바로 확인할 수 있게 했다.

Advanced 설정 패널에서 `top_k`, `test_department_codes`를 직접 입력하면
실제 API 요청에 반영되도록 했다.

### 실무 포인트

**POC UI의 목적은 기능 구현이 아니라 검색 흐름 검증이다.**
discover 결과를 보면서 "이 문서가 왜 나왔지?"를 추적하고,
generate 결과에서 "답변이 어떤 문서를 참조했지?"를 확인하는 도구다.

Swagger는 개발자 도구다. 비개발자가 검색 품질을 평가하려면 UI가 필요하다.
발표 자리에서도 "RAG 내부 동작이 투명하다"를 직접 보여줄 수 있다.

### 이후 연결된 문제

UI를 만들자 한국어 입력에서 예상치 못한 문제가 발생했다.

---

## 17. 한글 IME 입력 깨짐

### 증상

질문 입력창에 한글을 입력할 때 자모가 분리됐다.
"안녕"을 입력하면 "ㅇㅏㄴㄴㅕㅇ"처럼 조합이 깨진 상태로 표시됐다.
영어 입력은 정상이었다.

### 원인 분석

`input` 이벤트 핸들러에서 상태 갱신 후 DOM을 다시 렌더링했다.
한글은 IME(Input Method Editor) 조합 단계가 있어
문자를 순차적으로 조합하는 중간 상태(ㅇ → 아 → 안)가 존재한다.

이 조합 중간에 DOM이 다시 그려지면 IME가 조합 중이던 문자를 확정하고
다음 문자 입력을 새로 시작해 자모가 분리됐다.

### 조치

`compositionstart` / `compositionend` 이벤트를 활용해
IME 조합 중에는 렌더링 갱신을 지연했다.

```javascript
let isComposing = false;

input.addEventListener('compositionstart', () => { isComposing = true; });
input.addEventListener('compositionend', () => {
  isComposing = false;
  handleInputChange(input.value);
});
input.addEventListener('input', (e) => {
  if (!isComposing) handleInputChange(e.target.value);
});
```

### 실무 포인트

**한국어 서비스에서 IME 처리는 기본 요구사항이다.**
`compositionstart` + `compositionend` 패턴은 CJK 언어권 웹 서비스의 표준 처리 방식이다.
React의 `onChange`는 이 처리를 내부적으로 해주지만 Vanilla JS에서는 직접 구현해야 한다.

**RAG 검색 품질 이전에 질문 입력 자체가 안정적이어야 한다.**
아무리 retrieval이 좋아도 입력이 깨지면 사용자가 올바른 질문을 전달할 수 없다.

### 이후 연결된 문제

UI가 안정화되자 전체 흐름을 통합 검증했고, 추가 품질 이슈가 드러났다.

---

## 18. Discover → Document Selection → Generate 흐름 안정화

### 증상

전체 흐름을 연결하고 보니 여러 엣지 케이스가 나타났다.

- `/discover` 결과가 0건일 때 generate 버튼이 활성화되어 있어 클릭하면 오류
- generate 실패 시 선택한 문서 카드가 사라져서 재선택이 필요
- debug 패널이 없으면 "왜 이 답변이 나왔는지" 추적 불가

### 조치

상태 머신을 명확하게 정의하고 각 상태 전환 조건을 코드로 강제했다.

```
IDLE
  → DISCOVERING: /discover 호출 중, generate 버튼 비활성
  → DISCOVERED: 문서 카드 표시, generate 버튼 활성
  → EMPTY: 결과 없음, generate 버튼 비활성

DISCOVERED
  → GENERATING: /generate 호출 중, discover/generate 버튼 모두 비활성
  → ANSWERED: 답변·출처·debug 표시
  → ERROR(generate 실패): 문서 카드 선택 상태 유지(DISCOVERED로 복귀), 답변 영역에만 오류 표시
```

generate 실패 시 선택 상태를 유지하는 것이 UX에서 중요하다.
사용자가 다시 같은 문서를 선택할 필요가 없어야 한다.

### 실무 포인트

**오류 처리에서 사용자의 작업 컨텍스트를 보존하는 것이 중요하다.**
generate가 실패해도 사용자가 선택한 문서 목록은 유지해야 한다.
오류가 발생한 레이어(LLM)만 초기화하고, 이전 레이어(문서 선택)는 유지한다.

sources와 debug 정보가 같이 표시되어야 "이 답변이 어떤 문서를 참조했는가"를 추적할 수 있다.
이것이 ContextHub가 단순 챗봇과 다른 핵심 가치다.

### 이후 연결된 문제

흐름이 안정화되자 generation 품질 자체에 대한 질문이 생겼다.
retrieval은 됐는데 답변이 엉뚱하다는 피드백이 나왔다.

---

## 19. Generation 품질과 Retrieval 품질의 분리

### 증상

검색 결과(sources)는 관련 있는 문서인데 LLM 답변이 엉뚱하거나 불완전했다.
반대로 검색 결과가 안 좋아도 LLM이 어떻게든 답변을 만들어냈다.

두 현상이 섞여 있어 "검색 품질 문제인지 LLM 품질 문제인지"를 구분하기 어려웠다.

### 원인 분석

RAG 시스템에서 최종 답변 품질은 두 요소에 의존한다.

```
최종 답변 품질 = retrieval 품질 × generation 품질

retrieval 품질이 나쁘면:
  → 관련 없는 chunk가 컨텍스트로 들어감
  → LLM이 엉뚱한 내용을 참조해 답변 생성
  → 답변 품질 저하

retrieval 품질이 좋아도:
  → LLM이 컨텍스트를 무시하고 훈련 데이터 기반으로 답변
  → 출처와 다른 내용 생성 (hallucination)
  → 답변 품질 저하
```

두 문제가 증상은 비슷해도 해결 방법이 완전히 다르다.

### 조치 방향 결정

**retrieval과 generation을 분리 검증하는 절차를 만들었다.**

1. `/discover` + `/query` (LLM 없는 retrieval 전용 검증)로 먼저 retrieval 품질 확인
2. retrieval이 충분하면 `/generate`로 generation 품질 확인
3. retrieval이 문제면 → chunk_fetch_size, boost, mapping 튜닝
4. generation이 문제면 → 시스템 프롬프트, 컨텍스트 구성 방식 튜닝

이것이 `/query`(retrieval 전용)와 `/generate`(retrieval + generation)를 분리한 API 설계의 진짜 이유다.

reranking(cross-encoder 기반 문서-질문 관련성 재평가)은
retrieval과 generation 사이에 들어가는 레이어인데, 현재 PoC 이후 과제로 남겼다.

### 실무 포인트

**generation 품질이 나쁠 때 LLM 프롬프트 튜닝으로만 해결하려는 것은 틀린 접근이다.**
retrieval이 나쁘면 프롬프트를 아무리 잘 써도 한계가 있다.
반대로 retrieval이 좋으면 단순한 프롬프트로도 좋은 답변이 나온다.

레이어를 분리해서 문제를 격리하는 것이 RAG 품질 개선의 핵심이다.

---

## 20. 최신본 vs 구버전 문서 우선순위 문제

### 증상

같은 주제로 여러 버전의 문서가 있을 때(예: `보안정책_v1.0.pdf`, `보안정책_v2.0.pdf`)
구버전이 더 많은 chunk를 가져서 검색 결과 상위에 올라오는 경우가 있었다.

사용자는 당연히 최신 버전의 내용을 기대하는데 구버전 기반으로 답변이 생성됐다.

### 원인 분석

BM25 기반 검색은 **관련성**만 보고 **최신성**은 고려하지 않는다.
구버전 문서가 더 많은 내용을 담고 있거나 키워드가 더 많으면 더 높은 점수를 받을 수 있다.

현재 `indexed_at`(색인 시각) 필드가 있지만 검색 스코어에 반영되지 않고 있었다.

### 조치 방향 결정

완전한 해결책은 두 가지 방향이 있다.

1. **metadata-aware reranking**: `indexed_at`, 파일명의 버전 번호를 reranker가 고려
2. **document versioning 관리**: 같은 논리적 문서의 여러 버전을 연결하고 최신 버전만 검색 대상으로 설정

현재 PoC에서는 `indexed_at` 기준 클라이언트 정렬 옵션 제공으로 부분 해결했다.
문서 버전 관리 전략은 `docs/document-versioning.md`에 별도 설계했다.

### 실무 포인트

**사내 문서 RAG에서는 "최신 문서"와 "더 관련성 높은 문서"가 다를 수 있다.**
이것은 BM25의 한계이며, 완전한 해결책은 reranking이나 document lineage 관리다.
단기적으로는 사용자가 날짜 기준 정렬로 직접 판단할 수 있도록 UI를 제공하는 것이 현실적이다.

---

## 21. 운영형 RAG 관점의 최종 교훈

### ContextHub는 단순 챗봇이 아니다

구축 과정에서 가장 중요하게 깨달은 것은
**RAG 시스템의 품질은 LLM 하나의 문제가 아니라는 것이다.**

```
Ingestion Quality
  → 파서가 모든 포맷을 처리하는가?
  → FAILED 문서가 관측되고 재처리 가능한가?

Index Quality
  → 파일명/경로 같은 메타데이터도 검색 대상인가?
  → 매핑 변경 후 재색인됐는가?

Retrieval Quality
  → chunk precision: 관련 chunk가 상위에 오는가?
  → document recall: 관련 문서가 후보에 빠지지 않는가?
  → document diversity: 한 문서가 chunk를 독점하지 않는가?

Generation Quality
  → LLM이 검색 결과를 올바르게 참조하는가?
  → 출처가 정확하게 표시되는가?

Observability
  → 어느 레이어에서 문제가 생겼는지 추적 가능한가?
  → 상태 컬럼(parse/chunk/index_status)이 정확히 기록되는가?
  → matched_fields, highlight_terms 같은 debug 정보가 노출되는가?
```

### 검색 품질을 LLM 프롬프트 튜닝으로만 해결하려는 접근의 한계

초반에 "검색이 안 된다"는 문제가 생기면 프롬프트를 수정하거나
LLM을 바꾸고 싶어진다. 그러나 실제로는 대부분 ingestion 문제였다.

```
"검색이 안 된다"
  → 먼저 확인: raw_document 상태
  → 그다음: chunk가 있는가
  → 그다음: OpenSearch에 있는가
  → 그다음: 검색 쿼리가 맞는 필드를 보는가
  → 마지막에: LLM 프롬프트/모델 문제
```

**ingestion pipeline 없이 좋은 RAG를 만들 수 없다.**

---

## 22. Discover Search Post-processing (Recall 개선 후 저품질 후보 유입)

### 증상

`chunk_fetch_size`를 키운 뒤 document-level recall은 좋아졌지만, **약한 매칭·저점수 chunk**까지 후보 풀에 들어왔다.

예: `question="과업대비표"` discover 결과에 관련 `ID_A01_과업대비표` 3건과 함께,
`ID_P05_테일러링내역서` PDF가 `top_score≈1.0`, `highlights=null` 상태로 섞여 내려왔다.
반면 실제 관련 문서는 score 117~122대이고 `section_title` / `heading_path` highlight가 있다.

### 원인 분석

discover 파이프라인은 두 단계로 나뉜다.

```
[1] Retrieval (OpenSearch/DB)
      chunk_fetch_size만큼 상위 chunk hit 수집
           ↓
[2] Search Post-processing (애플리케이션 레이어)
      raw_document_id 그룹핑
      → document top_k 제한
      → 저품질 문서 필터 (상대 점수 + highlight)
```

**Search Post-processing** 이란, 검색 엔진이 반환한 hit 목록을 **그대로 사용자에게 보여주지 않고**
애플리케이션에서 문서 단위로 재구성·필터링·컷오프하는 단계다.
(OpenSearch `function_score` rerank와 달리, PoC에서는 Python `discovery_service.py`에서 수행.)

recall을 올리면 tail chunk(약한 BM25 매칭)도 fetch window에 들어온다.
그룹핑만 하면 “문서 1개 = chunk 30개” 문제는 해결되지만,
**서로 다른 문서 후보** 중 일부는 질의와 실질적으로 무관한 저점수 문서일 수 있다.

### 조치

`app/chat/discovery_service.py`에 문서 후보 필터를 추가했다.

| 조건 | 유지 |
|------|------|
| `has_highlight` | `matched_chunks` 중 메타데이터 highlight 존재 (`chunk_text` 제외) |
| `relative_score_ok` | `top_score >= best_score × 0.1` |

둘 다 아니면 제외. 로그에 `dropped_documents_count`, `documents_before_filter` 기록.

예: `best_score≈122`, `ID_P05` `top_score≈1.03` → 비율 ~0.8% & highlight 없음 → **drop**.

### 실무 포인트

- **고정 `min_score`만 쓰면** 질의·인덱스마다 점수 스케일이 달라져 튜닝이 깨진다. **상대 점수 + highlight** 조합이 운영 POC에 더 안전하다.
- Post-processing은 **discover 전용**이다. `/generate`는 여전히 chunk-level `top_k` 검색 후 `document_ids` 필터만 적용한다.
- 동일 키워드로 **chunk가 매우 많은 한 문서**(예: v0.9 xlsx 130청크)가 fetch window를 독점하면,
  다른 관련 문서가 discover 후보에 안 잡힐 수 있다 → `chunk_fetch_size` 추가 상향 또는 **문서당 chunk quota** 검토.

### 이후 연결된 문제

discover 후보가 정리되면 다음 병목은 **Generate quality validation**이다.
선택 문서 3개를 넘겨도 retrieval context가 한 문서 청크에 치우칠 수 있음(본 문서 §19, `backend-status.md` 진행 단계 참고).

---

## RAG 구축 체크리스트

### 1단계: Ingestion Pipeline 확인

```
□ 문서가 scanner에 잡혔는가?
  → raw_document에 행이 있는가? ingest_status = RECEIVED?

□ parser가 해당 포맷을 지원하는가?
  → RoutingParser에 해당 확장자 adapter가 있는가?
  → 의존성 패키지가 환경에 설치됐는가?

□ parse가 성공했는가?
  → parse_status = DONE?
  → FAILED라면 parse_error_message 확인

□ chunk가 생성됐는가?
  → document_chunk 테이블에 행이 있는가?
  → chunk_status = DONE?

□ index가 완료됐는가?
  → document_chunk.index_status = DONE?
  → document_index_status.error_message 확인

□ OpenSearch에 실제 들어갔는가?
  → raw_document_id로 OpenSearch 직접 쿼리
```

### 2단계: 검색 로직 확인

```
□ 검색 대상 필드가 충분한가?
  → original_filename, inbox_path에 boost가 있는가?
  → section_title, heading_path가 검색 대상인가?

□ 정규화가 의도대로 됐는가?
  → retrieval_query가 올바른가?
  → normalization_applied 여부 확인

□ chunk top_k와 document top_k가 분리됐는가?
  → chunk_fetch_size = max(top_k * 10, 50) 이상인가?
  → 한 문서가 chunk를 독점하지 않는가?

□ discover Search Post-processing이 적용됐는가?
  → 저점수·highlight 없는 tail 문서가 후보에서 제외되는가?
  → 로그 `dropped_documents_count`로 필터링 건수 확인 가능한가?

□ 매핑 변경 후 재색인됐는가?
  → 매핑 변경 시 인덱스 재생성 + 전체 재색인 완료?
```

### 3단계: 운영 흐름 확인

```
□ 실패 문서 reprocess 경로가 있는가?
  → FAILED → reprocess → PENDING → worker 재실행 절차가 명확한가?

□ parser 추가 후 기존 FAILED 문서를 재처리했는가?
  → 자동 재처리가 아니라 수동 reprocess가 필요함

□ debug/observability가 노출되는가?
  → matched_fields, highlight_terms, document_rank 확인 가능한가?
  → UI 또는 API에서 debug 정보를 볼 수 있는가?

□ generation vs retrieval을 분리 검증하는가?
  → /query(retrieval만)로 먼저 검색 품질 확인
  → 이후 /generate로 전체 품질 확인
```

---

## 관련 문서

- `docs/architecture.md` — 전체 파이프라인 구조
- `docs/db-schema.md` — raw_document 상태 컬럼 정의
- `docs/parser-kordoc.md` — kordoc 및 parser adapter 구조
- `docs/search-index.md` — OpenSearch 매핑 및 검색 쿼리 설계
- `docs/document-discovery.md` — chunk → document grouping, top_k 분리
- `docs/document-versioning.md` — 문서 버전 관리 전략
- `docs/backend-status.md` — 현재 구현 상태 스냅샷
