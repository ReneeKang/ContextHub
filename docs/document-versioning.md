# 문서 변경 감지 및 버전 전략

## 문서 목적

이 문서는 두 가지 목적을 동시에 다룬다.

1. **현재 구현**: PoC에서 의도적으로 선택한 단순 정책과 그 이유
2. **확장 설계**: 운영형 RAG 시스템에서 문서 버전을 관리하는 실제 접근법과 확장 경로

---

# Part 1. 현재 정책 (PoC)

## 1-1. 동일 경로 파일 변경은 자동 반영되지 않는다

현재 NAS Scan Worker는 **신규 파일 감지** 와 **중복 해시 감지** 만 처리한다.

```
현재 스캐너 판단 로직:

1. 파일 경로(path)가 raw_document에 없음 → 신규 등록
2. 파일 경로가 있고, sha256_hash가 동일 → 이미 처리된 파일, 무시
3. 파일 경로가 없고, sha256_hash가 다른 파일과 같음 → DUPLICATE 처리
```

**동일 경로에 파일을 덮어쓴 경우(overwrite)**:

- `sha256_hash`가 바뀌었어도 `stored_path`로 기존 `raw_document`를 찾아 갱신하는 로직이 없다
- 스캐너는 경로를 재발견하지만, 현재 구현에서는 이를 "변경"이 아닌 상황으로 처리하지 않는다
- 결과적으로 **이전 버전의 내용이 검색 인덱스에 남아 있다**

## 1-2. 운영자 reprocess 기반 처리

현재 문서 갱신의 공식 경로는 다음이다.

```
운영자 개입 흐름:

1. 담당자가 NAS에 갱신된 파일 업로드 (동일 경로 덮어쓰기 또는 새 파일명)
2. 운영자가 admin-api에서 기존 문서 확인
3. 필요 시 기존 문서 exclude 처리 (검색에서 제거)
4. 새 파일이 자동 감지되어 신규 raw_document 등록
5. 파이프라인 자동 진행 (parse → chunk → index)
```

또는:

```
reprocess 흐름 (내용은 같고 재파싱만 필요한 경우):

1. 운영자가 POST /admin/documents/{id}/reprocess { "stage": "parse" } 호출
2. parse_status = PENDING 리셋, 기존 parse_result / chunk / index 삭제
3. 워커가 재처리
```

## 1-3. 이것이 PoC에서의 의도된 선택인 이유

자동 변경 감지와 버전 관리는 단순해 보이지만, 실제 구현에서 많은 엣지 케이스를 만든다.

| 엣지 케이스 | 설명 |
|------------|------|
| 동시 업로드 | 변경 중인 파일을 감지하면 불완전한 내용이 파싱됨 |
| 롤백 필요 | 새 버전 파싱이 실패하면 이전 버전을 살려야 하는가? |
| 부분 성공 | 청킹은 됐는데 색인이 실패하면 이전 색인을 유지하는가? |
| 검색 공백 | 재색인 중에는 어떤 버전을 서빙하는가? |
| 권한 변경 | 새 버전의 경로가 달라서 권한도 바뀌면? |

PoC는 파이프라인 구조 자체를 검증하는 단계다.
**버전 관리 시스템을 먼저 완성하면, 파이프라인 검증이 늦어진다.**

---

# Part 2. 버전 전략 비교

운영형 RAG 시스템에서 실제로 사용하는 문서 버전 전략은 크게 네 가지다.

## 2-1. Overwrite Update 방식

```
기존 raw_document를 제자리 갱신한다.

raw_document (id=A)
  content_hash: "old_hash"  → "new_hash"
  parse_status: DONE        → PENDING (리셋)
  chunk_status: DONE        → PENDING (리셋)
  index_status: DONE        → PENDING (리셋)
```

**장점**
- 구현이 단순하다. 기존 ID가 유지된다.
- DB 레코드 수가 증가하지 않는다.

**단점**
- 이전 버전이 사라진다. 롤백 불가.
- 재처리 중 검색 공백(Search Gap)이 발생한다.
- 감사 추적(Audit Trail)이 불가능하다.
- "언제 어떤 내용이 검색됐는가"를 사후 확인할 수 없다.

**적합한 경우**: 버전 이력이 불필요한 단순 운영, 소규모 내부 시스템

---

## 2-2. Append-Only Version 방식

```
변경 시마다 새 raw_document를 생성한다.
이전 버전은 비활성화(inactive)로 전환한다.

raw_document (id=A, version=1, is_latest=FALSE, superseded_at=T1)
raw_document (id=B, version=2, is_latest=TRUE,  superseded_at=NULL)
```

**장점**
- 모든 버전이 보존된다. 언제든 롤백 가능.
- 새 버전 색인이 완료된 후 이전 버전을 비활성화하면 검색 공백이 없다.
- 감사 추적 가능.

**단점**
- DB 레코드와 검색 인덱스가 버전마다 증가한다.
- `is_latest` 플래그 동기화 로직이 필요하다.
- 검색 쿼리에 `is_latest = TRUE` 조건이 추가된다.

**적합한 경우**: 법무·컴플라이언스 문서, 정책 문서, 버전 이력이 중요한 기업 시스템

---

## 2-3. Document Lineage 방식

```
논리 문서(Logical Document)와 물리 문서(Physical Document)를 분리한다.

logical_document (id=L1, key="보안정책")
  ├── raw_document (id=A, version=1, logical_id=L1)  ← 과거
  └── raw_document (id=B, version=2, logical_id=L1)  ← 현재
```

**장점**
- "보안정책"이라는 개념적 문서 단위로 버전 계보를 추적한다.
- 사용자에게 "이 문서의 v1 vs v2 차이"를 보여줄 수 있다.
- 출처 표시에서 "보안정책 v2 (2026-05-11)"처럼 의미 있는 메타를 제공한다.

**단점**
- 논리 문서 개념을 어떻게 정의하는가가 복잡하다 (파일명 기반? 경로 기반? 수동 지정?).
- 테이블 구조가 더 복잡해진다.

**적합한 경우**: 문서 관리 시스템(DMS) 통합, 지식 베이스 운영, 장기 운영 플랫폼

---

## 2-4. Index Rollover 방식

```
검색 인덱스를 버전 단위로 관리한다.

contexthub_chunks_v1  ← 이전 버전 문서들의 청크
contexthub_chunks_v2  ← 현재 활성 인덱스
  alias: contexthub_chunks  ← 검색 시 사용하는 alias
```

**장점**
- 새 인덱스를 완성한 후 alias를 전환하면 무중단 전환이 가능하다.
- 파서·청킹 전략 변경 시 전체 재색인을 이전 인덱스에 영향 없이 수행 가능.
- 잘못된 재색인 시 이전 인덱스로 즉시 롤백 가능.

**단점**
- 인덱스 관리 복잡도 증가.
- 두 인덱스를 동시에 유지하는 동안 스토리지 비용 2배.

**적합한 경우**: 파서·임베딩 모델 교체 시 무중단 전환, 대규모 재색인 운영

---

# Part 3. 운영형 RAG 시스템의 실제 관행

## 3-1. 최신 활성 버전만 검색

대부분의 운영형 RAG 시스템은 **"현재 유효한 문서"만 검색 대상**으로 한다.

```
검색 대상 조건 (OpenSearch filter에 추가):

{
  "term": { "is_latest": true }
}

또는

{
  "term": { "document_status": "ACTIVE" }
}
```

이전 버전 문서는 인덱스에 남아 있지만 검색에서 제외된다.
"과거 문서로 질문"이 필요한 경우는 별도 API로 분리한다.

## 3-2. 이전 버전 보관 및 Soft Delete

```
문서 상태 값 (향후):

ACTIVE      → 검색 가능
SUPERSEDED  → 새 버전으로 대체됨, 검색 제외, 데이터 보관
EXCLUDED    → 운영자 수동 제외, 검색 제외
DELETED     → 논리 삭제, 데이터 보관 (물리 삭제 안 함)
```

물리 삭제(DB에서 행 삭제)는 컴플라이언스·감사 이유로 피하는 것이 일반적이다.

## 3-3. Versioned Chunk

청크 단위로도 버전을 추적하는 패턴이다.

```
document_chunk
  chunk_id
  raw_document_id      ← 특정 버전의 raw_document를 가리킴
  chunk_no
  chunk_text
  is_latest            ← 이 청크가 현재 검색 대상인가
```

`raw_document.is_latest = FALSE`가 되면
해당 문서의 모든 청크도 `is_latest = FALSE`로 연쇄 갱신된다.

이 방식을 쓰면 OpenSearch에서 청크를 삭제하지 않고 필터로만 제외할 수 있어
재색인 중 검색 공백을 막을 수 있다.

## 3-4. Search Gap 방지 패턴 (Blue/Green 색인)

운영형 시스템에서 재색인 중 검색 공백을 막는 표준 패턴이다.

```
1. 새 버전 색인 완성 전:
   검색 → old_index (alias: contexthub_chunks)

2. 새 버전 색인 완성 후:
   alias를 new_index로 원자적 전환
   검색 → new_index (alias: contexthub_chunks)

3. 이전 인덱스는 일정 기간 보관 후 삭제
```

PoC에서는 alias 없이 단일 인덱스를 사용해도 충분하다.

---

# Part 4. 현재 raw_document 구조에서의 확장 경로

현재 `raw_document` 테이블을 깨지 않고 버전 관리 필드를 추가하는 방향이다.

## 4-1. 추가 가능한 필드

```sql
ALTER TABLE raw_document ADD COLUMN IF NOT EXISTS
    logical_document_key  TEXT,         -- 논리 문서 식별키 (경로 또는 수동 지정)
    document_version      INTEGER NOT NULL DEFAULT 1,  -- 해당 논리 문서의 버전 번호
    parent_document_id    UUID REFERENCES raw_document(raw_document_id),
                                        -- 이 문서가 대체하는 이전 버전의 ID
    is_latest             BOOLEAN NOT NULL DEFAULT TRUE,  -- 현재 검색 활성 버전 여부
    superseded_at         TIMESTAMPTZ,  -- 더 새로운 버전으로 대체된 시각
    document_status       VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';
                                        -- ACTIVE | SUPERSEDED | EXCLUDED | DELETED
```

**필드별 역할**

| 필드 | 역할 | PoC 기본값 |
|------|------|-----------|
| `logical_document_key` | 동일 문서의 여러 버전을 묶는 키 | `NULL` (경로 기반으로 나중에 채움) |
| `document_version` | 버전 번호 | `1` |
| `parent_document_id` | 이 문서가 대체하는 이전 버전 | `NULL` |
| `is_latest` | 검색 활성 여부 | `TRUE` |
| `superseded_at` | 대체된 시각 | `NULL` |
| `document_status` | ACTIVE / SUPERSEDED / EXCLUDED / DELETED | `ACTIVE` |

모든 필드에 기본값이 있으므로, 기존 코드를 수정하지 않고 컬럼만 추가할 수 있다.

## 4-2. logical_document_key 전략

논리 문서 키를 무엇으로 잡을지는 운영 정책에 따라 다르다.

| 전략 | 설명 | 장단점 |
|------|------|--------|
| **경로 기반** | `stored_path` 를 key로 사용 | 자동, 경로 변경 시 새 논리 문서로 처리 |
| **파일명 기반** | `original_filename` (확장자 포함) | 이동해도 동일 문서로 인식, 동명 파일 충돌 위험 |
| **수동 지정** | 운영자가 API로 명시 | 정확하지만 운영 부담 |
| **해시 접두사** | `sha256_hash[:8] + filename` | 내용이 같으면 같은 문서, 다소 복잡 |

초기 확장 시에는 **경로 기반**이 가장 단순하고 안전하다.

## 4-3. 버전 전환 시 DB 상태 변화

새 파일이 기존 경로를 대체하는 경우의 처리 흐름 (Phase 2 이후):

```
기존 상태:
  raw_document (id=A)
    logical_document_key = "/nas/chatbot_docs/public/보안정책.pdf"
    document_version = 1
    is_latest = TRUE
    document_status = ACTIVE

새 파일 감지 후:
  1. 기존 문서 비활성화:
     UPDATE raw_document
     SET is_latest = FALSE,
         document_status = 'SUPERSEDED',
         superseded_at = NOW()
     WHERE id = A

  2. 새 raw_document 등록:
     raw_document (id=B)
       logical_document_key = "/nas/chatbot_docs/public/보안정책.pdf"
       document_version = 2
       parent_document_id = A
       is_latest = TRUE
       document_status = ACTIVE

  3. 파이프라인 정상 진행 (parse → chunk → index)

  4. 새 버전 색인 완료 후:
     기존 문서(id=A) 청크는 is_latest=FALSE로 갱신
     또는 OpenSearch에서 삭제
```

---

# Part 5. Scanner에서의 변경 감지 정책 옵션

스캐너가 "같은 경로의 파일이 바뀌었다"를 감지하는 방법은 세 가지다.

## 5-1. Hash 기준

```python
기존 raw_document WHERE stored_path = path → sha256_hash 조회
현재 파일의 sha256_hash 계산
동일 → 변경 없음
다름 → 변경 감지
```

**장점**: 내용 기반 감지이므로 파일 메타(mtime) 변조에 속지 않는다.
**단점**: 파일을 읽어 해시를 계산해야 하므로 CPU·IO 부담이 있다.

## 5-2. mtime 기준

```python
기존 raw_document_scan_state WHERE file_path = path → mtime 조회
현재 파일의 mtime 비교
다름 → 변경 감지 후보 → 안정화 판단 후 hash 계산
```

**장점**: 파일을 읽지 않고 메타데이터만 비교하므로 빠르다.
**단점**: mtime은 복사·백업 도구에 의해 보존될 수 있어 false negative 가능성이 있다.

## 5-3. Path + Hash 조합 (권장 향후 전략)

```python
1차 판단: mtime 또는 size 변화로 변경 후보 선정 (빠름)
2차 판단: 실제 sha256_hash 계산으로 내용 변경 확정 (정확)
```

이 두 단계를 조합하면 성능과 정확도를 모두 확보할 수 있다.

## 5-4. 정책별 비교

| 정책 | 감지 기준 | 장점 | 단점 | 권장 단계 |
|------|----------|------|------|----------|
| Hash only | sha256 | 정확 | 느림 | PoC 가능 |
| mtime only | 수정 시각 | 빠름 | false negative | 적합하지 않음 |
| size + mtime | 크기 + 시각 | 중간 | mtime 변조 취약 | 안정화 판단에 사용 중 |
| path + hash (2단계) | 경로 추적 + sha256 | 정확 + 빠름 | 구현 복잡도 소폭 증가 | Phase 2 권장 |

---

# Part 6. 지금은 단순 구조를 유지하는 이유

## 6-1. 조기 버전 시스템 구현의 위험

| 문제 | 결과 |
|------|------|
| `is_latest` 플래그 동기화 로직이 복잡하다 | 버그 발생 시 검색 결과가 이전 버전을 서빙한다 |
| 버전 전환 중 Search Gap 방지 로직이 필요하다 | 파이프라인보다 인프라 작업이 먼저다 |
| `logical_document_key` 정의가 도메인 지식 없이 어렵다 | 운영 경험 전에 설계하면 틀릴 가능성이 높다 |
| `parent_document_id` 체인 추적 로직이 필요하다 | 핵심 파이프라인 검증이 늦어진다 |

## 6-2. 현재 PoC가 검증해야 할 것

```
✅ NAS → 파싱 → 청킹 → 색인 → 검색 → LLM 응답 파이프라인
✅ 상태 기반 단계 분리가 운영 가시성을 제공하는가
✅ 권한 필터가 검색 단계에서 동작하는가
✅ reprocess 흐름이 운영자 대응 도구로 충분한가

❌ 자동 변경 감지  ← PoC 범위 아님
❌ 버전 이력 보존  ← PoC 범위 아님
❌ Search Gap 없는 재색인  ← PoC 범위 아님
```

## 6-3. 운영 확장 포인트만 남기는 전략

현재 구조에서 세 가지 확장 포인트를 미리 확보해 둔다.

**1. `raw_document.sha256_hash`는 이미 있다**

변경 감지의 핵심 재료가 이미 존재한다.
스캐너에서 경로 기반으로 기존 해시와 비교하는 로직만 추가하면 된다.

**2. `raw_document.duplicate_of_raw_document_id`는 lineage 구조의 씨앗이다**

현재는 중복 감지용이지만, `parent_document_id` 의미로 재해석하면
버전 체인의 기초가 된다. 스키마 변경 없이 활용 가능하다.

**3. `build_permission_filter`와 검색 쿼리는 `is_latest` 필터를 나중에 추가할 수 있다**

검색 필터 구성 함수가 단일 진입점으로 분리되어 있어,
`is_latest = TRUE` 조건을 내부에 추가하는 것이 다른 코드에 영향을 주지 않는다.

---

# Part 7. 버전 관리 로드맵

| Phase | 범위 | 주요 구현 |
|-------|------|----------|
| **PoC** | 변경 감지 없음, 운영자 reprocess | 현재 구조 |
| **Phase 2** | 경로 기반 변경 감지 | 스캐너에 path→hash 비교 추가, `parent_document_id` 활성화 |
| **Phase 2** | `is_latest` 플래그 도입 | `raw_document`, `document_chunk` 에 `is_latest` 추가, 검색 필터 포함 |
| **Phase 2** | `document_status` SUPERSEDED 전환 | 기존 버전 비활성화 로직 |
| **Phase 3** | `logical_document_key` 도입 | 논리 문서 단위 버전 계보 추적 |
| **Phase 3** | Search Gap 방지 | 신규 색인 완성 후 이전 버전 비활성화 순서 보장 |
| **Phase 4** | Index Rollover | OpenSearch alias 기반 무중단 재색인 |
| **Phase 4** | 버전 비교 API | 두 버전 간 내용 diff 제공 |

---

## 현재 구현 범위 정리

| 기능 | 현재 구현 | 향후 |
|------|----------|------|
| 신규 파일 감지 및 등록 | ✅ | — |
| sha256 중복 감지 | ✅ | 변경 감지 기반으로 재활용 |
| 운영자 reprocess | ✅ | — |
| 운영자 exclude / include | ✅ | — |
| 동일 경로 변경 자동 감지 | ❌ | Phase 2 |
| `is_latest` 플래그 | ❌ | Phase 2 |
| `document_status` 상태 전환 | ❌ | Phase 2 |
| `logical_document_key` | ❌ | Phase 3 |
| `parent_document_id` 체인 | ❌ | Phase 3 |
| Index Rollover | ❌ | Phase 4 |
