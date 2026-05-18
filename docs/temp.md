docs/[architecture-overview.md](http://architecture-overview.md) 를 다시 수정해주세요.

중요:

현재 문서에서 Scanner Layer, Parser Layer, Chunker Layer, Indexer Layer처럼 세부 태스크를 모두 Layer라고 부르는 표현은 부정확합니다.

레이어라는 표현은 저장소 경계, 책임 경계, 인터페이스 경계가 있는 큰 영역에만 사용하고,

scanner/parser/chunker/indexer는 각 레이어 내부의 workflow task로 재정리해주세요.

수정 방향:

1. “레이어”를 아래 큰 영역 중심으로 재구성

- Source/Ingestion 영역

- Document Transformation 영역

- Search Index Preparation 영역

- Serving/RAG Application 영역

- Observability/Governance 영역

2. 각 영역마다 다음을 명시

- 목적

- 입력 데이터

- 출력 데이터

- 저장소

- 내부 workflow task

- 다음 영역으로 넘기는 인터페이스

3. 데이터 저장소 기준 흐름 추가

- NAS/local_nas: 원본 파일

- PostgreSQL raw_document: 수집 메타, 상태, 권한

- PostgreSQL parsed result: markdown_text, parser metadata

- PostgreSQL document_chunk: 검색 준비 단위와 chunk metadata

- OpenSearch index: 서비스 검색용 projection

- LLM: 저장소가 아니라 stateless generation engine

4. 기존 workflow는 “처리 흐름” 섹션으로 이동

- scanner

- parser

- chunker

- indexer

- discover

- generate

이들은 layer가 아니라 workflow task라고 명확히 표현

5. 운영 관점의 index loading/reindex/delete 전략 추가

- 신규 문서 추가 시 upsert

- 변경 문서 감지 시 versioning 또는 reprocess

- 삭제 문서는 soft delete 후 OpenSearch delete 반영

- 운영 전체 재색인은 기존 index 삭제 방식이 아니라 새 index 생성 후 alias switch 방식

- opensearch_reset_dev는 개발환경 전용이라고 명시

6. 청킹/인덱싱/검색은 별개 레이어가 아니라 Search Index Preparation 영역 내부의 반복 튜닝 사이클로 설명

- chunking policy

- chunk metadata

- OpenSearch mapping

- BM25/nori

- metadata boost

- filtering/ranking

- reranking

이 서로 영향을 주므로 하나의 검색 품질 개선 사이클로 묶어 설명

7. 권한도 단순 UI 라벨이 아니라 Governance 영역과 Retrieval Filter 인터페이스로 설명

- access_scope는 ingestion에서 태깅

- document_chunk/OpenSearch로 전파

- serving 단계에서 PermissionPrincipal로 필터링

- 현재 한계는 trust boundary, 즉 실제 사용자 인증 출처 미연결이라고 명시

8. 문서 마지막에 용어 정리 추가

- Layer

- Workflow task

- Interface

- Source of Truth

- Projection

- Reindex

- Alias switch

- Soft delete

- Metadata enrichment

코드는 수정하지 말고 문서만 수정해주세요.