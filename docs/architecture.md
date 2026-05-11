# 시스템 아키텍처

## 역할 분리 원칙

각 컴포넌트는 **하나의 역할만** 수행한다.
역할 간 직접 호출은 금지한다. DB 상태를 통해 간접적으로 연동한다.

---

## 전체 구성도

```
┌──────────────────────────────────────────────────────────┐
│                        NAS                               │
│   /nas/chatbot_docs/                                     │
│   ├─ public/          (전사 공개)                        │
│   ├─ dept/{code}/     (부서별)                           │
│   └─ private/{uid}/   (개인)                             │
└──────────────────────────┬───────────────────────────────┘
                           │ 주기 스캔 (1분)
                           ▼
┌──────────────────────────────────────────────────────────┐
│               nas-scan-worker                            │
│  - 공식 반입 폴더만 스캔                                 │
│  - 파일 안정화 판단 (mtime/size 비교)                    │
│  - sha256 계산                                           │
│  - raw_document 등록 / 중복 감지                         │
└──────────────────────────┬───────────────────────────────┘
                           │ ingest_status = RECEIVED
                           ▼
┌──────────────────────────────────────────────────────────┐
│            document-parse-worker                         │
│  - parse_status = PENDING 인 문서 조회                   │
│  - kordoc 호출 (파싱 엔진)                               │
│  - markdown_text 저장                                    │
│  - blocks_json 저장                                      │
│  - document_parse_result 생성                            │
│  - parse_status 갱신                                     │
└──────────────────────────┬───────────────────────────────┘
                           │ parse_status = DONE
                           ▼
┌──────────────────────────────────────────────────────────┐
│            document-chunk-worker                         │
│  - chunk_status = PENDING 인 문서 조회                   │
│  - 제목/길이 기준 청크 분리                              │
│  - document_chunk 생성                                   │
│  - 권한 메타 청크에 복사                                 │
│  - chunk_status 갱신                                     │
└──────────────────────────┬───────────────────────────────┘
                           │ chunk_status = DONE
                           ▼
┌──────────────────────────────────────────────────────────┐
│            document-index-worker                         │
│  - index_status = PENDING 인 청크 조회                   │
│  - OpenSearch 색인 등록                                  │
│  - document_index_status 갱신                            │
└──────────────────────────┬───────────────────────────────┘
                           │ index_status = DONE
                           ▼
┌──────────────────────────────────────────────────────────┐
│                     chat-api                             │
│  - 사용자 요청 수신                                      │
│  - 권한 조건 구성 (access_scope / dept / owner)          │
│  - OpenSearch 권한 필터 검색                             │
│  - 검색 결과 → LLM 컨텍스트 구성                        │
│  - LLM 응답 + 출처 반환                                  │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                     admin-api                            │
│  - 반입 문서 목록 조회                                   │
│  - 파싱/색인 실패 목록 조회                              │
│  - 상태 조회                                             │
│  - 재처리 트리거                                         │
│  - 검색 제외 처리                                        │
└──────────────────────────────────────────────────────────┘
```

---

## 데이터 저장소 역할

| 저장소 | 역할 | 비고 |
|--------|------|------|
| NAS | 원본 파일 저장 | 공식 반입 폴더만 사용 |
| PostgreSQL | 문서 메타 · 상태 · 권한 · 처리 이력 | 진실의 원천 |
| OpenSearch | 검색 인덱스 | 청크 단위 색인 |
| (미래) Vector DB | 의미 기반 검색 | PoC 이후 도입 |

---

## 컴포넌트별 역할 요약

### nas-scan-worker

- 공식 반입 폴더(`/nas/chatbot_docs/`) 하위만 대상
- 주기적 재귀 스캔 (초기: 1분 간격)
- 파일 크기·mtime 비교로 안정화 판단 (업로드 중인 파일 제외)
- sha256 해시로 중복 감지
- `raw_document` 테이블에 등록

### document-parse-worker

- `raw_document.parse_status = PENDING` 문서 처리
- **kordoc는 이 워커 내부에서만 호출**
- 파싱 결과를 `document_parse_result`에 저장
  - `markdown_text`: 청킹용 텍스트
  - `blocks_json`: 구조 기반 청킹을 위한 블록 트리

### document-chunk-worker

- `markdown_text` 기준으로 청크 분리
- 제목 단위 분리 → 과한 경우 1000~1500자 단위 추가 분리
- overlap 일부 유지
- `document_chunk`에 권한 메타(`access_scope`, `owner_id`, `department_code`) 함께 저장

### document-index-worker

- `document_chunk` → OpenSearch 색인
- 청크 단위로 `document_index_status` 기록

### chat-api

- 사용자 세션에서 권한 조건 추출
- **검색 전 권한 필터 적용** (전체 검색 후 필터링 금지)
- 검색 결과 → LLM 프롬프트 구성 → 응답 생성

### admin-api

- 운영자용 상태 조회·재처리 인터페이스
- 장애 대응 도구

---

## 상태 흐름 다이어그램

```
raw_document 등록
  ingest_status: RECEIVED | DUPLICATE | FAILED

parse_status:   PENDING → DONE | FAILED

chunk_status:   PENDING → DONE | FAILED

index_status:   PENDING → DONE | FAILED
```

각 상태 전환은 해당 워커가 직접 DB를 갱신한다.
운영자는 `admin-api`를 통해 실패 문서를 조회하고 재처리할 수 있다.

---

## 확장 전략

초기 PoC는 **단일 프로젝트 내 모듈**로 구성한다.

```
app/
├─ scanner/   # nas-scan-worker
├─ parser/    # document-parse-worker
├─ chunker/   # document-chunk-worker
├─ indexer/   # document-index-worker
├─ chat/      # chat-api
├─ admin/     # admin-api
├─ db/        # 모델 · 마이그레이션
└─ config/    # 환경 설정
```

운영 안정화 이후 단계적으로:
1. 워커 프로세스 분리 (큐 기반)
2. 마이크로서비스 분리
3. OCR · Vector Search 추가
