# Chunking 전략 (ContextHub PoC)

검색(키워드) 품질과 이후 **임베딩·벡터 검색**을 고려한 청크 단위 설계 메모. 현재는 DB / OpenSearch 스텁의 **텍스트 필드**만 사용하며, 벡터 DB·하이브리드 검색은 붙이지 않는다.

---

## 1. 전략 비교

| 전략 | 장점 | 단점 | PoC 적용 |
|------|------|------|----------|
| **Paragraph 기반** | 문단이 자연스러운 의미 단위, 키워드 매칭에 유리 | 문단 길이 편차 큼(짧은 조각·장문 혼재) | 마크다운에서 빈 줄 기준 1차 분리에 반영 |
| **Heading 기반** | 목차·섹션과 정합, `section_title`·계층(`heading_path`)에 적합 | 헤딩 없는 문서는 보조 규칙 필요 | ATX `#` … `######` 줄로 섹션 경계·경로 구축 |
| **Page 기반** | PDF·인쇄물과 정합, `page_no`로 UI/인용 용이 | 페이지마다 주제가 섞일 수 있음 | PDF 파서의 `## Page N` 제목에서 `page_no` 추정 |
| **Sliding window** | 긴 절 고정 길이로 나눔, 컨텍스트 일정 | 동일 문맥이 인접 청크에 중복 | `chunk_max_chars` 초과 시 **가변 경계** 슬라이딩 |
| **Overlap** | 경계에서 잘리는 용어·문장 복구, RAG 답변 안정 | 저장·색인 비용 증가 | 인접 청크 끝·앞 `overlap_chars` 만큼 중복 |

**PoC 조합 (현재 구현)**

1. 마크다운 **헤딩 경계**로 1차 세그먼트 생성.  
2. 세그먼트 선두의 연속 ATX 헤딩으로 **`heading_path`**(`A > B`)·**`section_title`**(리프)·**`page_no`**(`Page N` 패턴) 결정.  
3. 본문이 **`chunk_max_chars`** 를 넘기면 **슬라이딩 윈도우**로 분할(문단/줄/문장 우선 분할점 탐색).  
4. **짧은 청크**는 동일 `heading_path`·`page_no` 인접 청크와 **병합**(상한 내).  
5. DB에 **`chunk_char_count`**, **`chunk_token_estimate`**, **`chunk_metadata_json`** 저장 → 인덱스 `_source`에 포함(향후 벡터 필드 확장 여지).

아주 짧은 본문(예: 한 줄 `A.`)은 헤딩과 같은 세그먼트로 묶이지만 **별도 청크로 남을 수 있다**. 이후 버전에서 인접 청크와의 병합 규칙을 더 촘촘히 할 수 있다.

---

## 2. 토큰 추정

실 토크나이저 없이 **문자 길이 기반 휴리스틱**만 사용한다 (의존성·언어 혼합 최소화).

- `chunk_token_estimate ≈ ceil(chunk_char_count / 4)` (라틴 위주 가정; 한글 비중이 크면 추후 `tiktoken` 등으로 교체).

---

## 3. 향후 (벡터·하이브리드)

- 동일 `chunk_id`에 임베딩 컬럼 또는 별도 벡터 저장소를 붙일 때 **`heading_path`**, **`page_no`**, **`chunk_metadata_json`** 를 메타데이터로 함께 넣는 패턴을 권장한다.  
- **하이브리드 검색**(BM25 + kNN)은 `docs/search-index.md` 에서 별도 단계로 다룬다 (현재 미구현).

---

## 4. 관련 코드

- 청크 생성: `app/chunker/markdown_chunk.py`  
- 영속화: `app/chunker/service.py`  
- 인덱스 바디: `app/indexer/service.py`, `app/adapters/opensearch_payload.py`  
- 운영 미리보기: Admin `GET .../documents/{id}` 의 `chunks` 배열

---

## 5. 기존 DB에 컬럼만 추가할 때 (Alembic 없음 PoC)

`python -m app.db.init_db` 의 `create_all` 은 **기존 테이블을 변경하지 않습니다.** 이미 `document_chunk` 가 있다면 **우선** 개발용 스크립트를 실행합니다.

```bash
python -m app.db.dev_migrations
```

(모듈은 **PostgreSQL 전용·개발 임시**이며 운영 마이그레이션 대체가 아님 — `app/db/dev_migrations.py` 참고.)

수동 실행이 필요할 때만 동일 내용의 SQL:

```sql
ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS heading_path TEXT;
ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_char_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_token_estimate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS chunk_metadata_json JSONB;
```

이후 **청크 단계 재실행**이 필요하면 Admin `POST .../reprocess` 의 `stage=chunk`(또는 `parse`) 정책을 따릅니다 (`docs/ops-reprocess.md`).
