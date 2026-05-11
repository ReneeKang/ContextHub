# kordoc — 문서 파싱 엔진

## kordoc의 역할

kordoc은 ContextHub의 **문서 파싱 구현체**다.

전체 시스템의 아키텍처를 구성하거나 제어하는 역할이 아니다.
오직 **원본 파일을 받아 구조화된 텍스트로 변환**하는 역할만 수행한다.

```
[원본 파일: PDF / DOCX / HWP / HWPX / TXT]
            │
            ▼
         kordoc
            │
            ▼
  { markdown_text, blocks_json, metadata_json }
```

---

## kordoc 호출 위치

> **kordoc은 반드시 `document-parse-worker` 내부에서만 호출한다.**

다른 컴포넌트(chat-api, admin-api, chunk-worker, index-worker 등)에서 직접 호출하지 않는다.

```
NAS Scan Worker     → kordoc 호출 금지
document-chunk-worker → kordoc 호출 금지
document-index-worker → kordoc 호출 금지
chat-api            → kordoc 호출 금지

document-parse-worker → kordoc 호출 ✅ (유일한 호출 지점)
```

이 원칙을 지켜야 파서 교체(kordoc → 다른 파서) 시 `document-parse-worker`만 수정하면 된다.

---

## Parse Worker 내에서의 호출 흐름

```
document-parse-worker

  1. raw_document 조회
     WHERE parse_status = 'PENDING'

  2. NAS에서 원본 파일 읽기
     file_bytes = read(stored_path)

  3. kordoc 호출
     result = kordoc.parse(
         file_bytes=file_bytes,
         file_ext=raw_document.file_ext
     )

  4. 결과 수신
     result.markdown_text  → 마크다운 텍스트
     result.blocks_json    → 블록 트리 (구조 기반)
     result.metadata_json  → 페이지 수, 제목, 작성자 등
     result.page_count     → 총 페이지 수
     result.parser_version → 사용된 파서 버전

  5. document_parse_result 저장
     INSERT INTO document_parse_result (
         raw_document_id,
         parser_name,
         parser_version,
         markdown_text,
         blocks_json,
         metadata_json,
         page_count,
         parsed_at
     )

  6. parse_status 갱신
     UPDATE raw_document
     SET parse_status = 'DONE'  -- 또는 'FAILED'
     WHERE raw_document_id = ...
```

---

## kordoc 반환 구조

### markdown_text

일반 마크다운 텍스트. 청크 분리의 기본 재료.

```markdown
# 보안 정책 v2.0

## 1. 개요

본 문서는 사내 보안 정책을 정의합니다.

## 2. 비밀번호 규칙

비밀번호는 최소 8자리 이상이어야 합니다.

### 2.1 허용 문자

영문, 숫자, 특수문자 조합 필수.
```

---

### blocks_json

문서의 구조 트리. 나중에 구조 기반 청킹을 지원할 때 사용.

```json
[
  {
    "type": "heading",
    "level": 1,
    "text": "보안 정책 v2.0",
    "page_no": 1
  },
  {
    "type": "heading",
    "level": 2,
    "text": "1. 개요",
    "page_no": 1
  },
  {
    "type": "paragraph",
    "text": "본 문서는 사내 보안 정책을 정의합니다.",
    "page_no": 1
  },
  {
    "type": "heading",
    "level": 2,
    "text": "2. 비밀번호 규칙",
    "page_no": 2
  },
  {
    "type": "paragraph",
    "text": "비밀번호는 최소 8자리 이상이어야 합니다.",
    "page_no": 2
  }
]
```

---

### metadata_json

```json
{
  "page_count": 12,
  "title": "보안 정책 v2.0",
  "author": "정보보안팀",
  "created_date": "2026-01-15",
  "language": "ko"
}
```

---

## markdown_text와 blocks_json 모두 저장하는 이유

| 상황 | 사용 필드 |
|------|----------|
| 현재 PoC (텍스트 기반 청킹) | `markdown_text` |
| 향후 구조 기반 청킹 | `blocks_json` |
| 향후 표·리스트 특수 처리 | `blocks_json` |
| 파서 버전 업 후 재파싱 비교 | 양쪽 모두 |

**Markdown만 저장하면 나중에 blocks 구조가 필요할 때 전체 재파싱을 해야 한다.**
초기부터 blocks_json도 함께 저장해 두면 파서 재호출 없이 청킹 전략을 변경할 수 있다.

---

## 지원 파일 형식 (PoC 범위)

| 형식 | 지원 여부 |
|------|----------|
| PDF | ✅ |
| DOCX | ✅ |
| HWP | ✅ |
| HWPX | ✅ |
| TXT | ✅ |
| XLSX | ❌ (PoC 이후) |
| PPTX | ❌ (PoC 이후) |
| 이미지 OCR | ❌ (PoC 이후) |

---

## 파서 교체 전략

kordoc을 다른 파서로 교체할 때는 `document-parse-worker`만 수정한다.

```
변경 범위:
  - parser/ 모듈 내 kordoc 호출 코드
  - parser_name, parser_version 값

변경 불필요:
  - document_parse_result 스키마
  - markdown_text / blocks_json 저장 구조
  - chunk-worker, index-worker
  - chat-api
```

파서를 교체해도 `document_parse_result`의 인터페이스(markdown_text + blocks_json)는 동일하게 유지된다.

---

## 파싱 실패 처리

```
kordoc 호출 실패 또는 예외 발생 시:
  1. parse_status = 'FAILED' 설정
  2. 오류 메시지를 별도 로그 또는 오류 컬럼에 기록
  3. 운영자가 admin-api에서 실패 목록 조회
  4. 운영자가 재처리 버튼으로 parse_status = 'PENDING' 리셋
  5. 다음 워커 주기에 재처리
```

---

## parser_version 기록의 중요성

`document_parse_result.parser_version`에 kordoc 버전을 반드시 기록한다.

이유:
- kordoc 업그레이드 시 이전 버전으로 파싱된 문서를 일괄 재파싱하는 기준이 된다
- 파싱 품질 이슈 발생 시 특정 버전 범위의 문서를 추적할 수 있다
