# 재처리 · 검색 제외 · 파일 변경 (운영 메모)

## 재처리 (`POST /api/v1/admin/documents/{id}/reprocess`)

관리자가 파이프라인 단계를 **PENDING으로 되돌리고** 워커가 다음 주기에 다시 처리하게 한다.

### POC 정책: 파생 행은 **삭제** 후 재생성

`document_parse_result`, `document_chunk`, `document_index_status` 는 **상태만 남기고 병행 유지**하면 다음이 생길 수 있다.

- 동일 `chunk_no` 중복, 오래된 색인 이력과 신규 이력 혼재
- 파서/청커가 “이미 있음” 분기와 충돌

따라서 POC에서는 **재처리 범위에 들어가는 단계의 파생 데이터는 삭제**하고, 워커가 **깨끗한 INSERT**로 다시 쌓도록 한다.

| `stage` | 삭제 | `raw_document` 상태 |
|---------|------|---------------------|
| `parse` | `document_index_status` → `document_chunk` → `document_parse_result` | `parse_status=PENDING`, `chunk_status=PENDING`, `index_status=PENDING` |
| `chunk` | `document_index_status` → `document_chunk` (parse 결과는 유지) | `chunk_status=PENDING`, `index_status=PENDING`, `parse_status=DONE` |
| `index` | 없음 (청크 행 유지) | 모든 해당 청크 `index_status=PENDING`, 문서 `index_status=PENDING` |

`ingest_status=DUPLICATE` 인 문서는 파이프라인을 타지 않는 설계이므로 **재처리 요청은 400** 으로 거절한다.

---

## 검색 제외 (`POST …/exclude`) / 제외 해제 (`POST …/include`)

- **exclude**: `raw_document.excluded=true`, `excluded_reason` 저장. 채팅 DB 검색은 `RawDocument.excluded=false` 조건으로 **조인 단계에서 제외**. OpenSearch 연동 시 `SearchClient.delete_chunks_for_document` 호출(현재 스텁은 로그만).
- **include**: `excluded=false`, 사유 초기화. 재색인을 위해 해당 문서의 모든 청크 `index_status=PENDING` 및 문서 `index_status=PENDING` 으로 되돌린다(워커가 다시 색인).

---

## 동일 경로에서 파일 내용만 바뀐 경우 (버전 정책)

**현재 스캐너**: `stored_path` 기준으로 이미 `raw_document`가 있으면 **재등록하지 않음** (`already_registered`). 따라서 **같은 NAS 경로에서 파일을 덮어써도** DB 행은 그대로이고, **자동 재파싱은 되지 않는다.**

### POC 권장

운영자가 내용 변경을 반영하려면 **`reprocess` API**로 파싱부터 다시 돌리거나, 추후 스캐너가 **mtime/sha256 변화 시 동일 row 갱신 + PENDING 리셋**을 하도록 확장한다.

### 확장(버전)

- **옵션 A**: 동일 `raw_document_id` 에서 `file_size` / `sha256_hash` / `updated_at` 만 갱신하고 파이프라인 PENDING 리셋 (이력 단순).
- **옵션 B**: 새 `raw_document` 행(버전 번호 또는 이전 ID 참조)으로 감사 추적 강화.

OpenSearch 쪽은 `raw_document_id` 또는 `content_version` 필드로 **구버전 청크 삭제**와 정합을 맞춘다.

---

## 워커와의 관계

재처리/제외/포함은 **동기적으로 DB만 갱신**한다. 이후 **`python -m app.workers`**(또는 스케줄러)가 `PENDING` 행을 소비해 parse → chunk → index 순으로 진행한다.
