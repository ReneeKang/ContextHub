# NAS Document Chatbot / RAG System

## 프로젝트 목표

사내 NAS 문서를 기반으로 검색/권한제어/LLM 응답이 가능한 문서 기반 챗봇 시스템 구축.

목표는 단순 PoC가 아니라,
운영 확장이 가능한 최소 구조를 먼저 만드는 것이다.

처음부터 모든 기능을 구현하지 않는다.

핵심은:

* NAS 문서 반입 구조
* 문서 메타 관리
* 권한 기반 검색
* 문서 파싱
* 청킹
* 검색 인덱싱
* LLM 응답 흐름

을 역할별로 분리하는 것이다.

---

# 핵심 아키텍처 방향

역할을 명확하게 분리한다.

* NAS

  * 원본 저장소

* RDB(PostgreSQL)

  * 문서 메타
  * 상태 관리
  * 권한 메타
  * 처리 이력 관리

* kordoc

  * 문서 파싱 엔진

* Search Engine(OpenSearch 등)

  * 검색 인덱스

* LLM

  * 검색 결과 기반 응답 생성 계층

---

# 전체 처리 흐름

NAS 문서 폴더
→ NAS Scan Worker
→ raw_document 등록
→ Parse Worker
→ kordoc 호출
→ document_parse_result 저장
→ Chunk Worker
→ document_chunk 생성
→ Search Index Worker
→ 검색엔진 색인
→ Chat API
→ 권한 필터 + 검색 + LLM 응답

---

# 중요한 설계 원칙

절대 한 번에 처리하지 않는다.

금지:
파일 발견 → 파싱 → 청킹 → 색인 → 챗봇 응답
을 하나의 함수나 흐름으로 처리

반드시 상태 기반으로 단계 분리:

* ingest_status
* parse_status
* chunk_status
* index_status

운영자가:
“왜 검색 안 되지?”
를 상태 기준으로 확인 가능해야 한다.

---

# NAS 반입 정책

전체 NAS를 스캔하지 않는다.

공식 반입 경로만 사용한다.

예시:

/nas/chatbot_docs
├─ public
├─ dept
└─ private

초기 PoC는:

/nas/chatbot_docs/public
/nas/chatbot_docs/private

정도로 단순화 가능.

챗봇 대상 문서는 반드시 공식 반입 폴더에만 업로드한다.

---

# NAS Scan 전략

처음부터 이벤트 기반으로 가지 않는다.

주기 스캔 방식 사용:

* 1분마다 recursive scan
* 새 파일 발견
* 파일 크기/mtime 저장
* 다음 스캔에서도 동일하면 안정화 판단
* sha256 계산
* raw_document 등록

---

# 최소 DB 테이블

필수 테이블:

1. raw_document
2. raw_document_scan_state
3. document_parse_result
4. document_chunk
5. document_index_status

---

# raw_document 핵심 컬럼

* raw_document_id
* source_type
* inbox_path
* stored_path
* original_filename
* file_ext
* file_size
* sha256_hash
* access_scope
* owner_id
* department_code
* ingest_status
* parse_status
* chunk_status
* index_status
* duplicate_of_raw_document_id
* created_at
* updated_at

---

# 상태값 규칙

ingest_status:

* RECEIVED
* DUPLICATE
* FAILED

parse_status:

* PENDING
* DONE
* FAILED

chunk_status:

* PENDING
* DONE
* FAILED

index_status:

* PENDING
* DONE
* FAILED

---

# kordoc 사용 원칙

kordoc은 전체 시스템이 아니라
“문서 파싱 구현체” 역할만 수행한다.

반드시 Parse Worker 내부에서만 호출한다.

구조:

NAS Scan Worker

* 파일 발견
* 안정화 판단
* 해시 계산
* raw_document 등록

Parse Worker

* parse_status = PENDING 조회
* kordoc 호출
* markdown 저장
* blocks 저장
* parse_status 갱신

---

# Parse 결과 저장 전략

document_parse_result:

* raw_document_id
* parser_name
* parser_version
* markdown_text
* blocks_json
* metadata_json
* page_count
* parsed_at

중요:
Markdown만 저장하지 말고 blocks_json도 저장한다.

이유:
나중에 구조 기반 chunking 가능하도록.

---

# Chunking 전략

초기 PoC는 단순하게 간다.

규칙:

* 제목 기준 분리
* 너무 길면 1000~1500자 단위 분리
* overlap 일부 유지
* section_title 저장
* page_no 저장

document_chunk 예시 컬럼:

* chunk_id
* raw_document_id
* chunk_no
* section_title
* page_no
* chunk_text
* access_scope
* owner_id
* department_code

---

# 권한 정책

초기에는 경로 기반 권한 사용.

예시:

/public/**
→ PUBLIC

/dept/infra/**
→ DEPT + INFRA

/private/user001/**
→ PRIVATE + user001

중요:
검색 전에 권한 필터 적용.

금지:
전체 검색 후 권한 제거.

반드시:
권한 조건 포함 검색.

예시:

access_scope = PUBLIC
OR department_code IN (...)
OR owner_id = ...

---

# 초기 PoC 범위

지원 문서:

* PDF
* DOCX
* HWP/HWPX
* TXT

기능:

* NAS scan
* 문서 등록
* kordoc parsing
* markdown 저장
* chunk 생성
* 검색 색인
* 권한 기반 검색
* LLM 응답
* 출처 표시

---

# 하지 말아야 할 것

* 처음부터 전체 NAS 스캔
* 처음부터 OCR 완벽 지원
* 처음부터 모든 포맷 지원
* 처음부터 벡터DB 강결합
* 처음부터 AD/LDAP 완전연동
* 처음부터 마이크로서비스 분리
* 처음부터 자동 문서 분류

---

# 최소 컴포넌트 구조

1. nas-scan-worker
2. document-parse-worker
3. document-chunk-worker
4. document-index-worker
5. chat-api
6. admin-api

초기에는 하나의 프로젝트 내부 모듈로 구성 가능.

예시:

app/
├─ scanner/
├─ parser/
├─ chunker/
├─ indexer/
├─ chat/
├─ admin/
├─ db/
└─ config/

---

# 관리자 기능 최소 요구사항

* 반입 문서 목록
* 파싱 실패 목록
* 색인 실패 목록
* 상태 조회
* 재처리 버튼
* 검색 제외 처리

운영자가 장애 대응 가능해야 한다.

---

# 최종 목표

심플하지만 운영 가능한 구조.

나중에:

* OCR 추가
* Vector Search 추가
* OpenSearch 확장
* 권한 연동 확장
* Parser 교체
* 로그 챗봇 확장

이 가능해야 한다.

핵심은:
구조를 흔들지 않는 것.

---

# Claude Code CLI 작업 요청

위 내용을 기반으로:

1. docs 구조 생성
2. architecture md 작성
3. db-schema md 작성
4. api-design md 작성
5. worker flow md 작성
6. poc-scope md 작성
7. roadmap md 작성
8. README 작성

을 진행해주세요.

중요:

* 코드 생성 전에 md 문서부터 작성
* 실제 운영 가능한 구조 기준
* 과한 오버엔지니어링 금지
* PoC 가능한 최소 구조 우선
* 문서 간 연결관계 유지
* 이후 Cursor 구현이 가능하도록 구조화
