# 검색 품질 · 운영 확장 (ContextHub)

BM25 키워드 검색을 기준으로, **한국어 분석**, **하이브리드**, **재색인**까지의 확장 방향을 정리한다. (현재 코드는 **벡터 필드 없음**.)

---

## 1. BM25 (기본 스코어링)

OpenSearch 기본 유사도는 **BM25**이다. 인덱스별로 `k1`, `b` 를 튜닝하려면 `settings.index.similarity` 에 커스텀 BM25를 정의한 뒤 필드에 `similarity` 를 지정한다.

품질에 영향을 주는 주요 요소:

- **필드 boost** (`multi_match.fields` 의 `^` 가중치)
- **쿼리 타입** (`cross_fields` + `operator: and` 로 다필드 AND 토큰 정합)
- **동의어 / 사용자 사전** (향후 `synonym_graph` 등 analyzer filter로 추가)

구현 참고: `app/adapters/opensearch_payload.py` 의 `build_keyword_search_body`.

---

## 2. Analyzer 전략 (한국어 + 파일명)

### 현재 (로컬 Compose)

- `docker/opensearch/Dockerfile` 로 **`analysis-nori`** 플러그인 설치.
- `chunk_text`, `section_title`, `heading_path`, `original_filename.nori` 에 **`nori_analyzer`** (`nori_tokenizer` + `nori_part_of_speech` + `lowercase`).
- **정확 일치·필터** 용: `heading_path.kw` (keyword + `filename_lowercase` normalizer), `original_filename` (keyword + normalizer).
- **파일명 검색**: 토큰 기반은 `original_filename.nori`, 정확/정규화 매칭은 `original_filename` keyword.

### TODO (품질 한 단계 더)

- **사용자 사전** (`user_dictionary` / `decompound_mode`) — 제품명·고유명사.
- **nori_readingform** 등 읽기 필터 — 검색어 변형 대응.
- **ICU** / **edge n-gram** 서브필드 — 자동완성·초성 검색(별도 필드 권장).

---

## 3. Nori

- 공식 플러그인: `opensearch-plugin install analysis-nori` (이미지 빌드에 포함됨).
- 매핑 변경 시 **재색인** 필요(아래 §6).

---

## 4. Hybrid search (BM25 + 벡터) — 미구현

확장 시 권장 패턴:

- 동일 `bool.filter` 에 **권한 절** 유지 (절대 앱 사후 필터로 대체하지 않음).
- `should` 절에 `script_score` 또는 `knn` / `nested` 벡터 쿼리 추가.
- **가중치**: `dis_max` 또는 `constant_score` + `boost` 로 BM25 vs 벡터 비중 조절.

---

## 5. Reranking — 미구현

- OpenSearch **rescore** (2단계 BM25) 또는 외부 reranker (cross-encoder) 파이프라인.
- 벡터 검색 도입 후 **two-stage** (recall → rerank) 가 일반적.

---

## 6. 재색인 · 매핑 변경 (운영)

`create_all` / 부트스트랩은 **기존 인덱스 매핑을 바꾸지 않는다.** Analyzer·필드 타입을 바꾸면:

1. **새 인덱스** 생성 (예: `contexthub_chunks_v2`) — `app/adapters/opensearch_index_mapping.py` 갱신.
2. **Reindex API** (`POST _reindex`) 로 구 인덱스 → 신 인덱스 복사, 또는 파이프라인에서 **문서 단위 재색인** (`reprocess` + 워커).
3. **Alias 전환** (`contexthub_chunks` alias를 새 인덱스로 스위치) — 무중단에 가깝게.
4. **Rollover** (시간/크기 기준)은 로그성·대용량 클러스터에서 검토.

개발 PoC에서는 인덱스 드롭 후 `python -m app.db.opensearch_bootstrap` 으로 재생성해도 된다 (데이터만 잃지 않도록 DB에서 재색인).

---

## 7. 청크 구조와 검색 품질

- **청크 길이·경계**: 너무 긴 청크는 키워드 스코어가 희석되고, 너무 짧으면 문맥이 부족하다. `app/chunker/markdown_chunk.py` 의 `CHUNK_MAX_CHARS` / overlap / 병합 정책이 BM25 품질과 직결된다.
- **`heading_path` / `section_title`**: 네비게이션·스니펫에 유리; 부스트와 nori 필드로 질의 정밀도 상승.
- **`page_no` / `source_page` alias**: 출처 UI·필터(향후)용; 키워드 본문과는 별개.
- **Highlight**: OpenSearch `highlight` 로 스니펫 준비; `SearchHit.highlights` 에 담아 후속 UI/LLM에서 사용 (채팅 API 스키마 확장은 별도 작업).

---

## 8. 디버그

- `.env`: `OPENSEARCH_SEARCH_EXPLAIN=true` → 첫 히트의 `_explanation` 을 **DEBUG** 로그에 일부 덤프 (`opensearch_client`).
- `OPENSEARCH_SEARCH_HIGHLIGHT=false` 로 하이라이트 바디 생략 가능.

---

## 9. 관련 파일

| 영역 | 경로 |
|------|------|
| 매핑 | `app/adapters/opensearch_index_mapping.py` |
| 쿼리 | `app/adapters/opensearch_payload.py` |
| HTTP 검색 | `app/adapters/opensearch_client.py` |
| 인덱스 생성 | `app/db/opensearch_bootstrap.py` |
| 이미지 | `docker/opensearch/Dockerfile` |

---

## 10. Vector search — 미구현

- `dense_vector` 매핑, ingest 파이프라인 임베딩, `knn` 쿼리, **동일 filter** 재사용이 목표.
- 임베딩 차원·정규화·인덱스별 `index.knn` 설정은 별도 설계 문서로 다룬다.
