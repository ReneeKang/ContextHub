# API 설계

## API 구성

| API | 대상 | 역할 |
|-----|------|------|
| `chat-api` | 일반 사용자 | 권한 기반 검색 + LLM 응답 |
| `admin-api` | 운영자 | 문서 상태 조회 · 재처리 · 관리 |

---

## chat-api

### 기본 정보

```
Base URL: /api/v1/chat
인증: Bearer Token (세션 기반 사용자 식별)
```

---

### POST /api/v1/chat/query

사용자 질문을 받아 권한 기반 검색 후 LLM 응답 반환.

**Request**

```json
{
  "question": "보안 정책 문서에서 비밀번호 규칙이 뭐야?",
  "top_k": 5,
  "session_id": "sess-abc123"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `question` | string | Y | 사용자 질문 |
| `top_k` | integer | N | 검색 결과 수 (기본값: 5) |
| `session_id` | string | N | 대화 세션 ID |

**Response 200**

```json
{
  "answer": "비밀번호는 최소 8자리 이상이어야 하며...",
  "sources": [
    {
      "chunk_id": "uuid-...",
      "raw_document_id": "uuid-...",
      "original_filename": "보안정책_v2.pdf",
      "section_title": "3.2 비밀번호 규칙",
      "page_no": 12,
      "score": 0.92,
      "access_scope": "PUBLIC"
    }
  ],
  "session_id": "sess-abc123"
}
```

**권한 처리 흐름**

```
1. Bearer Token에서 사용자 정보 추출
2. 권한 조건 구성:
   access_scope = 'PUBLIC'
   OR (access_scope = 'DEPT' AND department_code IN ['infra', 'dev'])
   OR (access_scope = 'PRIVATE' AND owner_id = 'user001')
3. 위 조건을 OpenSearch 쿼리 필터로 적용
4. 검색 결과 반환 (권한 외 문서는 결과에 포함되지 않음)
```

---

### GET /api/v1/chat/history/{session_id}

대화 이력 조회 (PoC 이후 구현 가능).

---

## admin-api

### 기본 정보

```
Base URL: /api/v1/admin
인증: 관리자 전용 토큰 또는 역할 기반 인증
```

---

### GET /api/v1/admin/documents

반입 문서 목록 조회.

**Query Parameters**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `ingest_status` | string | RECEIVED \| DUPLICATE \| FAILED |
| `parse_status` | string | PENDING \| DONE \| FAILED |
| `chunk_status` | string | PENDING \| DONE \| FAILED |
| `index_status` | string | PENDING \| DONE \| FAILED |
| `access_scope` | string | PUBLIC \| DEPT \| PRIVATE |
| `page` | integer | 페이지 번호 (기본값: 1) |
| `per_page` | integer | 페이지 크기 (기본값: 50) |

**Response 200**

```json
{
  "total": 142,
  "page": 1,
  "per_page": 50,
  "items": [
    {
      "raw_document_id": "uuid-...",
      "original_filename": "보안정책_v2.pdf",
      "access_scope": "PUBLIC",
      "ingest_status": "RECEIVED",
      "parse_status": "DONE",
      "chunk_status": "DONE",
      "index_status": "FAILED",
      "created_at": "2026-05-11T10:00:00Z"
    }
  ]
}
```

---

### GET /api/v1/admin/documents/{raw_document_id}

특정 문서 상세 상태 조회.

**Response 200**

```json
{
  "raw_document_id": "uuid-...",
  "original_filename": "보안정책_v2.pdf",
  "stored_path": "/nas/chatbot_docs/public/보안정책_v2.pdf",
  "file_ext": "pdf",
  "file_size": 204800,
  "sha256_hash": "abc123...",
  "access_scope": "PUBLIC",
  "ingest_status": "RECEIVED",
  "parse_status": "DONE",
  "chunk_status": "DONE",
  "index_status": "FAILED",
  "chunk_count": 14,
  "indexed_chunk_count": 0,
  "excluded": false,
  "created_at": "2026-05-11T10:00:00Z",
  "updated_at": "2026-05-11T10:05:00Z"
}
```

---

### GET /api/v1/admin/documents/failed

실패 문서 목록 조회 (파싱 실패 + 색인 실패 통합).

**Query Parameters**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `stage` | string | parse \| chunk \| index (미지정 시 전체) |

---

### POST /api/v1/admin/documents/{raw_document_id}/reprocess

특정 문서 재처리 트리거.

**Request**

```json
{
  "stage": "parse"
}
```

| stage 값 | 동작 |
|----------|------|
| `parse` | `parse_status = PENDING`으로 리셋 (이후 chunk, index도 연쇄 리셋) |
| `chunk` | `chunk_status = PENDING`으로 리셋 (이후 index도 리셋) |
| `index` | `index_status = PENDING`으로 리셋 |

**Response 200**

```json
{
  "raw_document_id": "uuid-...",
  "stage": "parse",
  "result": "scheduled"
}
```

---

### POST /api/v1/admin/documents/{raw_document_id}/exclude

검색 결과에서 문서 제외 처리.

**Request**

```json
{
  "reason": "법무팀 요청 - 외부 유출 금지 문서"
}
```

**동작**
- `raw_document.excluded = TRUE` 설정
- OpenSearch에서 해당 문서의 청크 삭제
- `index_status = PENDING`은 유지하지 않음 (재색인 불필요)

---

### GET /api/v1/admin/stats

전체 처리 현황 요약.

**Response 200**

```json
{
  "total_documents": 500,
  "ingest": {
    "RECEIVED": 480,
    "DUPLICATE": 15,
    "FAILED": 5
  },
  "parse": {
    "PENDING": 10,
    "DONE": 460,
    "FAILED": 10
  },
  "chunk": {
    "PENDING": 12,
    "DONE": 455,
    "FAILED": 8
  },
  "index": {
    "PENDING": 15,
    "DONE": 450,
    "FAILED": 10
  }
}
```

---

## 공통 에러 응답

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "해당 문서를 찾을 수 없습니다.",
    "detail": null
  }
}
```

| HTTP 코드 | 상황 |
|-----------|------|
| 400 | 잘못된 요청 파라미터 |
| 401 | 인증 실패 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 500 | 서버 오류 |

---

## 설계 원칙

1. chat-api는 권한 필터를 **쿼리 파라미터로 받지 않는다.** 서버가 세션에서 직접 추출한다.
2. admin-api의 재처리는 동기 실행하지 않는다. 상태를 PENDING으로 바꾸고 워커가 처리한다.
3. PoC에서는 페이지네이션 필수 (전체 결과 반환 금지).
