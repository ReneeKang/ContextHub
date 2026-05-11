# PoC 범위 정의

## PoC 목표

> 심플하지만 **운영 가능한 구조**를 검증한다.
>
> 기능을 많이 넣는 것이 아니라,
> **단계 분리 + 상태 관리 + 권한 검색**이 실제로 동작하는지 확인하는 것이 목표다.

---

## PoC에서 반드시 구현할 것

### 핵심 파이프라인

| 단계 | 구현 내용 |
|------|----------|
| NAS 스캔 | `/nas/chatbot_docs/` 하위 주기 스캔 (1분 간격) |
| 파일 안정화 | size + mtime 비교로 업로드 완료 판단 |
| sha256 해시 | 중복 감지 |
| raw_document 등록 | ingest_status = RECEIVED |
| parse_status 관리 | PENDING → DONE / FAILED |
| kordoc 호출 | PDF / DOCX / HWP / HWPX / TXT |
| markdown_text 저장 | document_parse_result 저장 |
| blocks_json 저장 | 동일 테이블에 함께 저장 |
| 청크 분리 | 제목 기준 + 1000~1500자 단위 |
| chunk_status 관리 | PENDING → DONE / FAILED |
| OpenSearch 색인 | 청크 단위 색인 |
| index_status 관리 | PENDING → DONE / FAILED |
| 권한 필터 검색 | 검색 전 access_scope / dept / owner 필터 |
| LLM 응답 | 검색 결과 컨텍스트 기반 응답 |
| 출처 표시 | 파일명 + section_title + page_no |

### 관리자 기능

| 기능 | 구현 내용 |
|------|----------|
| 반입 문서 목록 | 상태별 필터 조회 |
| 실패 목록 | 파싱/색인 실패 조회 |
| 현황 요약 | 단계별 상태 건수 |
| 재처리 트리거 | PENDING 리셋 |
| 검색 제외 | excluded = TRUE + OpenSearch 삭제 |

### 권한 정책

| 항목 | 구현 내용 |
|------|----------|
| PUBLIC | /public/** 경로 → 전체 접근 |
| DEPT | /dept/{code}/** → 해당 부서만 |
| PRIVATE | /private/{uid}/** → 본인만 |
| 경로 자동 추출 | NAS Scan Worker에서 자동 처리 |

---

## PoC에서 하지 말아야 할 것

### 아키텍처 관련

| 항목 | 이유 |
|------|------|
| 전체 NAS 스캔 | 공식 반입 경로 외 스캔은 권한 범위 모호 |
| 마이크로서비스 분리 | 초기에 배포 복잡도 증가, 운영 비용 과다 |
| 큐(Kafka, RabbitMQ) 도입 | DB 상태 기반 폴링으로 충분 |
| 파일 발견→응답 단일 흐름 | 상태 추적 불가, 재처리 불가 |

### 기능 관련

| 항목 | 이유 |
|------|------|
| OCR 완벽 지원 | 복잡도 급증, 별도 엔진 필요 |
| 모든 파일 포맷 지원 | XLSX, PPTX, 이미지 등은 PoC 이후 |
| AD/LDAP 완전 연동 | 사내 인프라 의존성, 초기 검증 불필요 |
| 벡터 DB 강결합 | 키워드 검색으로 PoC 충분 |
| 자동 문서 분류 | ML 모델 필요, 복잡도 과다 |
| 다국어 지원 | 한국어 우선, 추후 확장 |
| 실시간 이벤트 기반 스캔 | inotify 등 OS 의존, 주기 스캔으로 충분 |
| 문서 버전 관리 | sha256 중복 감지로 충분 |
| 대화 이력 영구 저장 | session 범위로 충분 |

### 구현 방식 관련

| 항목 | 이유 |
|------|------|
| 검색 후 권한 필터링 | 권한 외 정보 노출 위험 |
| 전체 문서 단위 색인 | 검색 정확도 저하, LLM 컨텍스트 초과 |
| 파싱 결과 markdown만 저장 | blocks_json 없으면 나중에 재파싱 필요 |
| 상태 없는 파이프라인 | 장애 추적 불가 |

---

## PoC 완료 기준

| 항목 | 기준 |
|------|------|
| 문서 반입 | NAS 반입 폴더에 PDF 파일 복사 → 자동 등록 확인 |
| 파싱 | kordoc 호출 후 markdown_text + blocks_json 저장 확인 |
| 청킹 | 10개 이상 청크 분리 확인 |
| 색인 | OpenSearch에서 쿼리로 청크 조회 확인 |
| 권한 검색 | PUBLIC 문서는 검색되고, 다른 사용자 PRIVATE 문서는 검색 안 됨 확인 |
| LLM 응답 | 질문 → 출처 포함 응답 반환 확인 |
| 관리자 | 실패 문서 조회 및 재처리 동작 확인 |

---

## PoC 검증 시나리오

### 시나리오 1: 정상 흐름

```
1. /nas/chatbot_docs/public/ 에 보안정책_v2.pdf 복사
2. 1분 이내 NAS Scan Worker가 감지
3. raw_document 등록 (ingest_status=RECEIVED, parse_status=PENDING)
4. Parse Worker 실행 → kordoc 호출 → parse_status=DONE
5. Chunk Worker 실행 → 청크 분리 → chunk_status=DONE
6. Index Worker 실행 → OpenSearch 색인 → index_status=DONE
7. chat-api: "비밀번호 규칙이 뭐야?" → 응답 + 출처 반환
```

### 시나리오 2: 권한 분리 검증

```
1. user001이 /nas/chatbot_docs/private/user001/ 에 개인메모.txt 복사
2. user002가 "개인메모 내용 알려줘" 질문
3. 검색 결과에 개인메모.txt 청크 미포함 확인
4. user001이 동일 질문 → 개인메모.txt 내용 포함 응답 확인
```

### 시나리오 3: 재처리 검증

```
1. 파싱 실패 문서 발생 (parse_status=FAILED)
2. admin-api에서 실패 목록 확인
3. 재처리 버튼 클릭 → parse_status=PENDING 리셋
4. Parse Worker 재처리 → parse_status=DONE
5. 이후 자동으로 chunk, index 단계 진행
```

---

## 지원 파일 형식 (PoC)

| 형식 | 지원 | 비고 |
|------|------|------|
| PDF | ✅ | 텍스트 추출 |
| DOCX | ✅ | |
| HWP | ✅ | kordoc 의존 |
| HWPX | ✅ | kordoc 의존 |
| TXT | ✅ | UTF-8 |
| XLSX | ❌ | Phase 2 |
| PPTX | ❌ | Phase 2 |
| 이미지 | ❌ | OCR 필요, Phase 3 |

---

## 환경 구성 (PoC)

| 항목 | 구성 |
|------|------|
| 서버 | 단일 서버 또는 Docker Compose |
| DB | PostgreSQL 단일 인스턴스 |
| 검색 엔진 | OpenSearch 단일 노드 |
| 워커 | 동일 프로세스 내 스케줄러 (APScheduler 등) |
| NAS | 파일 시스템 마운트 또는 SMB |
