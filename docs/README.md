# ContextHub — NAS 문서 기반 챗봇 / RAG 시스템

## 프로젝트 개요

사내 NAS에 저장된 문서를 기반으로 **검색 · 권한 제어 · LLM 응답**이 가능한
문서 기반 챗봇 시스템.

단순 PoC가 아니라 **운영 확장이 가능한 최소 구조**를 먼저 만드는 것이 목표다.

---

## 핵심 목표

| 목표 | 설명 |
|------|------|
| NAS 문서 반입 | 공식 반입 폴더 기반 스캔·등록 |
| 문서 메타 관리 | PostgreSQL 기반 상태·이력 관리 |
| 권한 기반 검색 | 경로 기반 권한을 검색 전에 적용 |
| 문서 파싱 | kordoc 엔진으로 파싱 (Parse Worker 내부에서만 호출) |
| 청킹 | 제목/길이 기준 청크 분리 및 저장 |
| 검색 인덱싱 | OpenSearch 기반 색인 |
| LLM 응답 | 검색 결과 기반 응답 생성 + 출처 표시 |

---

## 최소 컴포넌트 구조

```
app/
├─ scanner/      # NAS 반입 폴더 주기 스캔 (nas-scan-worker)
├─ parser/       # 문서 파싱, kordoc 호출 (document-parse-worker)
├─ chunker/      # 청크 분리 (document-chunk-worker)
├─ indexer/      # 검색엔진 색인 (document-index-worker)
├─ chat/         # 권한 검색 + LLM 응답 (chat-api)
├─ admin/        # 반입·상태·재처리 관리 (admin-api)
├─ db/           # DB 모델 및 마이그레이션
└─ config/       # 환경 설정
```

초기 PoC에서는 하나의 프로젝트 내부 모듈로 구성한다.
마이크로서비스 분리는 운영 안정화 후 진행한다.

---

## 전체 처리 흐름 (요약)

```
NAS 공식 반입 폴더
  → [nas-scan-worker]      파일 감지 · 안정화 · 해시 계산 → raw_document 등록
  → [document-parse-worker] kordoc 호출 → markdown + blocks 저장
  → [document-chunk-worker] 청크 분리 → document_chunk 생성
  → [document-index-worker] 검색엔진 색인
  → [chat-api]              권한 필터 → 검색 → LLM 응답
```

> 단계별 상태(`ingest_status / parse_status / chunk_status / index_status`)를
> 반드시 DB에 기록한다. 운영자가 장애 원인을 상태 기준으로 확인할 수 있어야 한다.

---

## 문서 목록

| 문서 | 내용 |
|------|------|
| [architecture.md](architecture.md) | 시스템 아키텍처 · 컴포넌트 역할 분리 |
| [pipeline-flow.md](pipeline-flow.md) | NAS → 색인 → 챗봇 전체 처리 흐름 |
| [db-schema.md](db-schema.md) | DB 테이블 스키마 · 상태값 규칙 |
| [api-design.md](api-design.md) | chat-api · admin-api 엔드포인트 설계 |
| [permission-policy.md](permission-policy.md) | 경로 기반 권한 정책 · 검색 전 필터 원칙 |
| [parser-kordoc.md](parser-kordoc.md) | kordoc 역할 범위 · Parse Worker 연동 구조 |
| [search-index.md](search-index.md) | 검색 인덱스 설계 · 권한 필터 검색 |
| [admin-features.md](admin-features.md) | 관리자 최소 기능 요구사항 |
| [poc-scope.md](poc-scope.md) | PoC에서 할 것 / 하지 말아야 할 것 |
| [todo-roadmap.md](todo-roadmap.md) | 단계별 로드맵 |

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 원본 저장소 | NAS (파일 서버) |
| 메타 / 상태 DB | PostgreSQL |
| 문서 파싱 엔진 | kordoc |
| 검색 엔진 | OpenSearch (또는 Elasticsearch) |
| LLM | 사내 LLM API 또는 외부 API |
| 백엔드 | Python (FastAPI 권장) |

---

## 설계 원칙

1. **단계 분리** — 파일 발견부터 응답까지 하나의 흐름으로 처리하지 않는다.
2. **상태 기록** — 각 단계 상태를 DB에 기록하여 운영 가시성을 확보한다.
3. **권한 선행** — 검색 전에 반드시 권한 필터를 적용한다.
4. **공식 반입 경로** — 전체 NAS를 스캔하지 않는다.
5. **오버엔지니어링 금지** — PoC 범위에서 필요한 최소 구조만 구현한다.
