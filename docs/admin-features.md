# 관리자 기능

## 설계 원칙

> 운영자가 "왜 검색 안 되지?"를 상태 기준으로 스스로 확인하고 대응할 수 있어야 한다.

관리자 화면은 **운영 가시성**과 **장애 대응**에 집중한다.
설정이나 권한 관리보다 **모니터링과 재처리**가 우선이다.

---

## 최소 기능 목록 (PoC 필수)

### 1. 반입 문서 목록

| 항목 | 내용 |
|------|------|
| 기능 | 전체 반입 문서를 상태별로 필터링하여 조회 |
| 표시 컬럼 | 파일명, 경로, access_scope, 각 상태값(ingest/parse/chunk/index), 등록일 |
| 필터 | 상태별 (PENDING / DONE / FAILED) |
| 정렬 | 등록일 역순 기본 |
| 페이지네이션 | 필수 (50건/페이지 기본) |

**화면 레이아웃 예시**

```
[반입 문서 목록]
필터: [ingest_status ▼] [parse_status ▼] [index_status ▼] [검색]

파일명              | scope   | 반입  | 파싱  | 청킹  | 색인  | 등록일
보안정책_v2.pdf     | PUBLIC  | ✅    | ✅    | ✅    | ❌    | 2026-05-11
인프라가이드.docx   | DEPT    | ✅    | ✅    | ✅    | ✅    | 2026-05-10
개인메모.txt        | PRIVATE | ✅    | ❌    | -     | -     | 2026-05-10
```

---

### 2. 파싱 실패 목록

| 항목 | 내용 |
|------|------|
| 기능 | `parse_status = FAILED` 문서 목록 |
| 표시 정보 | 파일명, 오류 메시지, 실패 일시 |
| 액션 | 재처리 버튼 (개별 / 일괄) |

---

### 3. 색인 실패 목록

| 항목 | 내용 |
|------|------|
| 기능 | `index_status = FAILED` 청크 목록 |
| 표시 정보 | 파일명, 청크 번호, OpenSearch 오류 메시지, 실패 일시 |
| 액션 | 재처리 버튼 (개별 / 일괄) |

---

### 4. 상태 요약 (대시보드)

| 항목 | 내용 |
|------|------|
| 기능 | 전체 처리 현황 수치 요약 |
| 표시 정보 | 단계별 상태 건수 |

**표시 예시**

```
[전체 현황]
총 반입 문서: 500건

반입(ingest):   RECEIVED 480  DUPLICATE 15  FAILED 5
파싱(parse):    DONE 460      PENDING 10    FAILED 10
청킹(chunk):    DONE 455      PENDING 12    FAILED 8
색인(index):    DONE 450      PENDING 15    FAILED 10

실패 문서 수: 25건  [실패 목록 보기]
```

---

### 5. 재처리 트리거

| 항목 | 내용 |
|------|------|
| 기능 | 실패 또는 특정 문서를 선택하여 재처리 요청 |
| 단계 선택 | parse / chunk / index 중 선택 |
| 처리 방식 | 해당 상태를 PENDING으로 리셋 → 워커 다음 주기에 처리 |
| 일괄 처리 | 실패 전체 일괄 재처리 버튼 제공 |

**재처리 로직**

```
parse 재처리 요청:
  parse_status = 'PENDING'  (chunk_status, index_status도 PENDING으로 리셋)

chunk 재처리 요청:
  chunk_status = 'PENDING'  (index_status도 PENDING으로 리셋)

index 재처리 요청:
  index_status = 'PENDING'
```

---

### 6. 검색 제외 처리

| 항목 | 내용 |
|------|------|
| 기능 | 특정 문서를 검색 결과에서 제외 |
| 사용 사례 | 법무 요청, 오업로드, 민감 정보 노출 등 |
| 동작 | `excluded = TRUE` 설정 + OpenSearch 청크 삭제 |
| 제외 이유 | 기록 필수 (`excluded_reason`) |
| 복구 | 제외 해제 버튼으로 재색인 가능 |

---

## PoC 이후 추가 기능 (우선순위 순)

| 기능 | 설명 | 시점 |
|------|------|------|
| 중복 문서 목록 | DUPLICATE 문서와 원본 비교 | Phase 2 |
| 처리 이력 로그 | 각 단계 처리 시각·소요 시간 기록 | Phase 2 |
| 반입 폴더 설정 | 공식 반입 경로 추가/변경 UI | Phase 2 |
| 문서 미리보기 | 파싱 결과 markdown 미리보기 | Phase 2 |
| 청크 목록 조회 | 문서별 청크 내용 확인 | Phase 2 |
| 스캔 주기 설정 | 워커 실행 주기 설정 | Phase 3 |
| 권한 관리 UI | access_scope 수동 변경 | Phase 3 |
| 알림 설정 | 실패 임계치 초과 시 알림 | Phase 3 |

---

## 관리자 API 연동

admin-api 설계는 [api-design.md](api-design.md) 참조.

| 화면 기능 | API |
|-----------|-----|
| 반입 문서 목록 | `GET /admin/documents` |
| 문서 상세 | `GET /admin/documents/{id}` |
| 실패 목록 | `GET /admin/documents/failed` |
| 현황 요약 | `GET /admin/stats` |
| 재처리 | `POST /admin/documents/{id}/reprocess` |
| 검색 제외 | `POST /admin/documents/{id}/exclude` |

---

## 관리자 인증

PoC에서는 별도 관리자 계정으로 구분한다.
AD/LDAP 연동은 PoC 이후 진행.

```
일반 사용자: /api/v1/chat → Bearer Token
관리자:      /api/v1/admin → Admin Token (별도 발급)
```
