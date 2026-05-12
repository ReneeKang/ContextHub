# Retrieval Roadmap

ContextHub 의 검색(retrieval) 레이어가 **지금 어디까지 와 있고**, **앞으로 어디로 갈 수 있는지** 정리한다.
이 문서는 "벡터를 도입하자"는 결심 문서가 아니다. **현재 keyword MVP 가 충분히 동작하고 있다는 전제**에서, 어느 시점에 무엇을, 왜 추가할지를 설계 의도 중심으로 적는다.

> 이 문서에서 **"현재"** 라고 표기된 항목은 저장소에 실제 코드가 있는 항목이며, **"향후"** / **"미구현"** 으로 표기된 항목은 설계 방향이다. 둘을 섞어 읽지 않도록 주의한다.

관련 문서: [`search-index.md`](search-index.md), [`search-quality.md`](search-quality.md), [`backend-status.md`](backend-status.md), [`permission-policy.md`](permission-policy.md), [`todo-roadmap.md`](todo-roadmap.md).

---

## 1. 현재 retrieval architecture

현재 구현된 retrieval 레이어는 **keyword 단일 경로**이고, **권한이 쿼리 안쪽에 박혀 있다.**

```
HTTP 요청 (question, principal)
  │
  ▼
[chat-api]  app/chat/service.py, app/agents/nas_rag.py
  │   - PermissionPrincipal 구성
  │   - retrieval_query = normalize_retrieval_query(question)
  │   - original question 은 LLM 프롬프트로만 사용
  ▼
[SearchClient]  app/adapters/search_protocol.py
  │   .search(query=retrieval_query, principal=..., top_k=...) -> list[SearchHit]
  │   구현체:
  │     - DbChunkSearchClient        (PostgreSQL, 권한 OR 를 SQL WHERE 로)
  │     - OpenSearchSearchClient     (OpenSearch HTTP, 권한 OR 를 bool.filter 로)
  ▼
[OpenSearch index: contexthub_chunks]
  - chunk 단위 색인
  - chunk_text/section_title/heading_path 는 nori(또는 로컬 standard+lowercase)
  - access_scope / owner_id / department_code 는 keyword
  - 임베딩 벡터 필드 없음
  ▼
SearchHit (chunk_id, raw_document_id, original_filename, section_title, page_no,
           chunk_text, access_scope, score, …)
  ▼
[chat-api]
  - /query  : 검색 결과만 stub answer 로 반환 (LLM 미호출)
  - /generate: nas_rag 가 hits → 프롬프트 조립 → LLM 호출
```

핵심 계약 두 가지:

- **`SearchClient.search(query=…)`** 는 단일 문자열을 받는다. 구현체가 바뀌어도 호출부는 그대로다.
- **권한은 `principal` 객체로 같이 들어가서 쿼리 내부 `filter` 에 합쳐진다.** 검색 후 애플리케이션 사후 필터는 금지한다.

이 두 가지가 유지되는 한, 아래에서 말하는 모든 확장은 호출부를 흔들지 않고 가능하다.

---

## 2. 현재 keyword retrieval 의 장점과 한계

### 잘 동작하는 이유

- **사내 문서는 고유명사·약어·코드 비중이 높다.** "Kubeflow", "kordoc", "방화벽 포트 오픈" 처럼 **정확한 토큰 매칭**이 의미적 유사도보다 우선인 경우가 많다. BM25 + 형태소 분석으로 충분한 첫 정답률이 나온다.
- **운영 가시성이 좋다.** 왜 이 chunk 가 떴는지 `_explanation` 로 즉시 설명 가능하다 (`OPENSEARCH_SEARCH_EXPLAIN=true`). 벡터 검색은 같은 디버깅이 훨씬 비싸다.
- **권한 필터를 그대로 얹기 쉽다.** `bool.filter` 안에 PUBLIC/DEPT/PRIVATE OR 절을 그대로 쓰면 끝이다. 임베딩 인덱스를 별도로 두면 같은 보장을 다시 만들어야 한다.
- **재색인 비용이 낮다.** chunking 만 바뀌어도 분석기·매핑만 갱신하고 다시 색인하면 된다. 임베딩 단계가 끼면 모델 호출 비용·시간이 한 자리수 더해진다.

### 한계 (벡터를 검토해야 하는 시점의 신호)

- **의역 / 동의어 / 어순 차이**에 약하다. "비밀번호 정책" ↔ "패스워드 규칙" 처럼 표면 토큰이 다르면 BM25 점수가 떨어진다. 동의어 사전(미구현)으로 일부 보완 가능하지만 운영 비용이 든다.
- **긴 자연어 질문에 약하다.** 사용자가 한 문장으로 길게 묻고 핵심 키워드가 중간에 끼어 있으면 토큰 AND 매칭이 쉽게 빠진다. 현재 `normalize_retrieval_query` 가 이를 완화하지만, 한계가 있다.
- **개념적 유사성 (concept-level recall) 이 없다.** "장애 대응 절차" 라는 질문에 "incident runbook" 만 들어 있는 문서를 끌어오지 못한다.
- **다국어 / 영문 혼용** 에서 약하다. 한글 분석기로 영문 토큰이 그대로 토크나이즈되는 경우, boost·analyzer 튜닝이 필요하다.

이 한계들이 **실제 사용자 질의 로그에서 미스로 잡힐 때** 벡터를 도입한다. 한계가 이론상 존재한다는 이유만으로 도입하지 않는다.

---

## 3. query normalization 을 도입한 이유

`app/chat/retrieval_query.py` 의 `normalize_retrieval_query` / `normalize_retrieval_query_pair` 가 하는 일은 **임베딩이 없는 BM25/토큰 매칭 환경에서 한국어 어미·요청구가 검색 정확도를 깎는 문제**를 막는 것이다.

대표 케이스:

```
입력 question : "방화벽 포트 오픈 설명해줘"
색인된 chunk  : "... 방화벽 포트 오픈 ..." (뒤에 "설명" / "해줘" 가 없음)
```

DB 토큰 AND 백엔드에서는 띄어쓰기에 따라 한 토큰으로 묶이면 미스가 난다. OpenSearch 의 nori 도 "설명해줘" 같은 요청구는 의미 없는 토큰을 만들어 스코어를 흐린다.

설계 의도는 세 가지다.

1. **검색 문자열과 원본 question 을 분리한다.** `retrieval_query` 만 정규화하고, **LLM 프롬프트에는 원본 `question` 을 그대로 둔다.** LLM 은 사용자의 말투·의도를 봐야 답을 잘 쓰고, 검색 엔진은 키워드만 보면 된다. 두 레이어의 요구사항이 다르다.
2. **모델로 풀지 않는다.** LLM 으로 query rewriting 하는 방식은 비용·지연·로그 복잡도가 다 늘어난다. 어미·요청구 제거 정도는 **결정론적 규칙**으로 충분하고, 디버깅이 쉽다.
3. **`normalization_applied` 를 로그에 남긴다.** 정규화가 실제로 매칭 결과를 바꿨는지 추적 가능해야, 향후 룰을 추가/삭제할 때 회귀를 발견할 수 있다.

벡터 검색을 도입하면 이 정규화의 가치는 줄어든다 (임베딩은 어미에 둔감하다). 그래도 **BM25 경로는 남아 있을 가능성이 크기 때문에**, 이 모듈은 hybrid 단계에서도 BM25 쪽 입력으로 계속 쓰일 수 있다.

---

## 4. 향후 vector retrieval 확장 방향 (미구현)

벡터 검색은 **BM25 를 대체하지 않고, 다른 종류의 미스를 보충하기 위해** 도입한다.

확장의 큰 그림:

1. **임베딩 모델을 선택하고 고정한다.** 한국어 비중이 높으므로 한국어 + 코드/영문 혼용을 다 견디는 모델을 쓴다. 모델은 **버전을 박아두고** 바꿀 때마다 재색인이 따라온다 (§8).
2. **색인 시 chunk 임베딩을 함께 만든다.** parse → chunk → embed → index 흐름에서 **embed 단계가 indexer 의 앞에 끼는 것이 자연스럽다.** chunk 가 만들어진 직후 임베딩이 한 번만 계산되고, 그 결과가 OpenSearch 문서의 `chunk_embedding` 필드로 들어간다.
3. **검색 시 question 임베딩을 한 번 만든다.** 같은 모델·같은 차원이어야 한다. 권한 필터는 BM25 때와 **완전히 동일한 `bool.filter` 절**을 재사용한다.
4. **응답 형태는 바꾸지 않는다.** `SearchHit` 계약은 그대로 두고, 내부 정렬 점수만 두 출처(BM25, 벡터)의 결합으로 바뀐다.

이 단계 전체에서 호출부 (`chat/service.py`, `agents/nas_rag.py`) 의 코드는 사실상 바뀌지 않아야 한다. 바뀌면 추상화가 새는 것이다.

---

## 5. chunk embedding / question embedding 흐름 (미구현)

### Chunk 측 (indexing time)

```
document_chunk  (PENDING)
  │
  ▼
[embed worker / 또는 indexer 의 한 단계]
  - embedding_model_id (예: "bge-m3-v1")
  - embedding_version  (모델·전처리 동일성 키)
  - vec = embed(chunk_text)
  - vec 는 정규화 (cosine 사용 시 L2 normalize)
  ▼
OpenSearch bulk
  {
    "chunk_id": ...,
    "chunk_text": ...,                 // BM25 용 그대로 유지
    "chunk_embedding": [...],          // 신규 필드 (knn_vector)
    "embedding_model_id": "bge-m3-v1", // 디버깅·재색인 분기용
    "embedding_version": 1,
    "access_scope": ..., "owner_id": ..., "department_code": ...
  }
```

여기서 중요한 점:

- **임베딩은 chunk 단위로만 만든다.** raw document 단위 임베딩은 의미가 흐려져 RAG 에 잘 안 맞는다. 현재 chunker 가 이미 적절한 크기로 자르고 있으므로 그 단위를 그대로 쓴다.
- **embedding 실패는 indexing 전체 실패가 아니다.** keyword 색인은 별개로 끝내고, `embedding_status` (PENDING/DONE/FAILED) 를 chunk 메타에 따로 두는 편이 운영 가시성이 좋다. (지금은 그런 컬럼이 없다 — 도입 시 신규 컬럼.)
- **재시도 가능해야 한다.** 임베딩 API 는 외부 의존이라 흔들린다. 워커 패턴 (`docs/pipeline-flow.md`) 의 PENDING/DONE/FAILED 규칙과 정렬한다.

### Question 측 (query time)

```
question (원문)
  │
  ├──► normalize_retrieval_query  ──► BM25 query string
  │
  └──► embed(question_for_vector)  ──► query vector
        ↑
        이 입력을 정규화된 문자열로 할지, 원문으로 할지는 모델에 따라 다르다.
        많은 한국어 임베딩 모델은 자연어 형태(원문)에서 더 잘 작동한다.
        그래서 BM25 입력(`retrieval_query`)과 vector 입력(`question` 원문 또는 다른 변형)을
        분리할 수 있도록 retrieval_query 모듈을 키워드 정규화 전용으로 유지한다.
```

→ 즉, `retrieval_query.py` 는 **BM25 전용 정규화**로 남고, 벡터 입력은 그와 독립적으로 결정한다. 두 경로가 같은 입력을 강제로 공유하지 않게 둔다.

---

## 6. hybrid retrieval 구조 방향 (미구현)

`docs/search-index.md` §"Hybrid (키워드 + 벡터) 확장 시" 와 `docs/search-quality.md` §4 의 방향을 더 구체화하면 다음과 같다.

### 6.1 추천 구조: 동일 인덱스, 동일 필터, recall-then-rerank

```
OpenSearch query
{
  "query": {
    "bool": {
      "should": [
        { "multi_match": { ... BM25 ... } },     // recall 경로 A
        { "knn":         { ... vector ... } }    // recall 경로 B
      ],
      "filter": [
        { ... PUBLIC | DEPT | PRIVATE OR ... }   // 권한, 변경 없음
      ]
    }
  }
}
```

이후 결과를 **RRF (Reciprocal Rank Fusion)** 또는 가중합으로 머지한다. RRF 가 운영상 안전하다 — 스코어 스케일이 달라도 견딘다.

### 6.2 두 경로를 합칠 때 주의할 점

- **권한 필터는 한 곳에만 있어야 한다.** 두 쿼리를 따로 보내 클라이언트에서 머지하면, 두 번 적용해야 하고 그중 하나라도 빠지면 권한 누수다. **OpenSearch 한 인덱스 + 단일 `bool` 쿼리** 구조가 이 보장을 가장 자연스럽게 만든다.
- **top-K 는 두 경로 각자 충분히 크게 잡고, 그 다음 머지 후 잘라낸다.** 한쪽에서만 충분히 뽑힌 정답을 머지 직전에 잃지 않기 위함이다.
- **머지 후 rerank** 는 별 단계이며, hybrid 와 같이 도입할 필요는 없다. 먼저 hybrid 효과만 측정하고, 그 다음 cross-encoder rerank 를 검토한다.

### 6.3 BM25 의 비중을 0 으로 두지 않는다

순수 벡터 검색만으로 가는 시점에도 사내 문서 특유의 **정확한 코드/명령어/숫자 매칭** 케이스가 남기 때문에, BM25 점수는 항상 일정 비중을 갖도록 둔다.

---

## 7. 권한 필터를 retrieval 단계에 유지해야 하는 이유

이 원칙은 BM25 든 벡터든 hybrid 든 **변하지 않는다.** (`docs/permission-policy.md`, `docs/search-index.md` 와 같은 원칙.)

이유 세 가지:

1. **사후 필터는 정답을 가린다.** "본인이 볼 수 있는 top-5" 가 아니라 "전 직원의 top-5 중 본인 것만" 이 되어, 자기 자신에게 가장 적합한 문서가 다른 사람의 문서로 가려지는 누락이 생긴다.
2. **누수가 시간차로 드러난다.** retrieval 후 어딘가에서 한 번이라도 chunk_text 가 로그/캐시/응답에 떨어지면, 사후 필터가 잡아내기 전에 새는 경로가 만들어진다. 검색 자체가 권한을 모르면 책임선이 흐려진다.
3. **벡터 인덱스가 들어와도 마찬가지다.** knn 쿼리 결과 자체를 권한 필터 안쪽으로 넣어야 한다 (`bool.filter` 안에 `knn`/`script_score` 가 같이 위치). 별도 벡터 DB (pgvector/Qdrant/Milvus) 를 쓰는 경우에도, **그 DB 안에 같은 권한 메타가 같이 있어야 하고, 같은 OR 절이 적용되어야 한다.** 이게 어려울수록 (§9) OpenSearch 단일 인덱스가 매력적이 된다.

---

## 8. embedding / versioning 분리 방향 (미구현)

임베딩은 **버전이 있는 자산**이다. 모델을 한 번 바꾸면 이전에 만든 모든 벡터는 "다른 공간"의 좌표가 된다 — 같이 쓰면 검색이 망가진다.

운영상 필요한 분리:

- **모델 식별자 (`embedding_model_id`)**: 예 `"bge-m3-v1"`. 사람이 읽을 수 있는 키.
- **임베딩 버전 (`embedding_version`)**: 같은 모델이라도 전처리(예: 정규화 방식, prefix 토큰)가 바뀌면 올린다.
- **인덱스 분기 또는 alias 전환**: 새 임베딩 버전으로 가는 동안 **신규 인덱스에 색인하면서 옛 인덱스로 서비스**하다가, 다 끝나면 alias 를 swap. `docs/search-quality.md` §6 의 reindex 패턴과 같은 모양이다.
- **부분 재색인이 가능해야 한다.** 모든 chunk 를 한 번에 재임베딩하는 건 비용/시간이 크다. `embedding_status = PENDING` 만 워커가 잡아가는 모델로 가면, 모델 변경 시 PENDING 으로 일괄 리셋하는 것만으로 점진적 재색인이 된다.
- **DB 상의 `document_chunk` 메타와 OpenSearch 의 임베딩 필드는 다른 수명을 갖는다.** chunk 의 텍스트는 안 바뀌어도 임베딩만 다시 만들어야 하는 경우가 흔하다. 그래서 chunk_status 와 embedding_status 는 별 컬럼이어야 한다 (현재는 둘 다 없음 — 도입 시 신규).

---

## 9. OpenSearch `knn_vector` 를 먼저 검토하는 이유

벡터 검색을 도입할 때 **첫 번째 선택지는 외부 벡터 DB 가 아니라 OpenSearch 의 `knn_vector` 필드**다. 그 이유:

1. **권한 필터가 이미 검증된 경로에 있다.** 같은 `bool.filter` 안에 knn 절을 두면, §7 의 보장이 자동으로 따라온다. 별 DB 로 가면 같은 OR 절을 한 번 더 구현·유지해야 한다.
2. **인덱스가 하나다.** chunk_text 와 embedding 이 같은 문서에 있으므로, hybrid 쿼리가 자연스럽다 (§6.1). 두 DB 를 동기화할 필요가 없고, 동기화 실패 시의 상태 불일치 (chunk 는 있는데 임베딩은 없거나, 그 반대) 를 만들지 않는다.
3. **운영 도구가 같다.** 모니터링·백업·인덱스 재생성·alias 전환의 기존 절차 (`docs/search-quality.md` §6) 가 그대로 적용된다.
4. **성능이 충분하다.** 사내 문서량 (수만~수십만 chunk) 규모에서는 OpenSearch 의 HNSW 구현으로 충분하다. 수억 vector 가 되면 다시 본다.

→ 즉, OpenSearch knn 은 **기본값**이고, 다른 옵션은 **그것이 부족한 이유가 명확할 때만** 검토한다.

---

## 10. pgvector / Qdrant / Milvus 로 갈 가능성

다음과 같은 조건이 **실측으로** 확인되면 외부 벡터 DB 도 검토한다. 어디까지나 가설이다.

| 후보 | 검토하는 시점 |
|------|----------------|
| **pgvector** | 메타·상태 DB 와 벡터를 하나의 트랜잭션 경계 안에서 다뤄야 하는 강한 이유가 생겼을 때. 예: chunk 작성과 임베딩을 원자적으로 묶고 싶을 때. 단점은 권한 필터를 또 SQL 쪽에서 똑같이 구현해야 한다는 것. |
| **Qdrant** | OpenSearch knn 의 recall/지연이 부족하고, 풍부한 payload 필터 (named vectors, filterable indexes) 가 필요할 때. 단점은 별 DB 운영·인증·백업 라인이 늘어난다는 것. |
| **Milvus** | vector 수가 OpenSearch HNSW 로 다루기 부담스러운 규모로 갈 때 (수억 단위). 사내 NAS 문서 기반 RAG 에서는 도달하지 않을 가능성이 높다. |

세 후보 모두 **현 단계에서는 도입하지 않는다.** 도입을 검토하더라도 **§7 의 권한 보장**과 **§8 의 임베딩 버전 관리**가 그 DB 안에서 같은 강도로 가능해야 한다.

---

## 11. 지금은 의도적으로 구현하지 않는 것들

벡터/하이브리드 외에도, 운영 가치 대비 도입 비용이 큰 항목들은 의식적으로 미룬다.

- **LLM 기반 query rewriting / HyDE.** 비용·지연·디버깅 비용이 크고, 현재 결정론적 normalization 으로 충분하다 (§3).
- **Cross-encoder rerank.** hybrid 효과를 먼저 측정한 뒤 검토한다. 추가 GPU 의존성이 따라온다.
- **동의어 사전 / 사용자 사전.** 운영 비용이 크다 (사전 관리 책임이 누군가에게 가야 한다). 실 미스 로그에서 동의어 누락이 다수 잡힐 때 시작한다.
- **개인화 랭킹 (사용자별 가중치).** 권한 모델과 섞이면 감사 로그가 복잡해진다. PoC 범위 밖.
- **자동완성 / 초성 검색.** 별도 인덱스/서브필드가 필요한 별 기능이고 RAG 정답률과 직접 관련이 없다.
- **검색 결과 캐싱.** 권한이 사용자별이라 cache key 가 복잡해진다. 부하 측정 후에 결정.

이 목록은 "절대 안 한다" 가 아니라, **"실 사용자 미스 로그가 그쪽을 가리킬 때 시작한다"** 라는 의미다.

---

## 12. 단계별 확장 roadmap

> 단계가 올라간다고 이전 단계가 폐기되지 않는다. **BM25 경로는 모든 단계에서 살아 있다.**

### Stage 0 — 현재 (구현 완료)

- OpenSearch keyword retrieval (BM25 + nori 또는 standard+lowercase)
- `SearchClient` 추상화 (`DbChunkSearchClient`, `OpenSearchSearchClient`)
- 권한 OR 절을 `bool.filter` 안쪽에 유지
- `retrieval_query` / `original question` 분리, `normalize_retrieval_query` 적용
- `/api/v1/chat/query` (retrieval-only) / `/api/v1/chat/generate` (LLM) 분리
- `app/llm` / `app/agents` 분리 — LLM 은 generation layer 전용
- scanner → parser → chunker → indexer 워커 흐름 동작
- 로그에 `original_query`, `retrieval_query`, `normalization_applied`, `retrieval_count` 등 기록

### Stage 1 — 키워드 품질 강화 (벡터 도입 전, 운영 흐름 안 깸)

- 실 사용자 질의 로그에서 미스/오답 패턴 수집 (정성/정량)
- BM25 `k1`/`b` 튜닝, `multi_match` 필드 boost 조정
- `original_filename`, `heading_path` 부스트 정교화
- 사용자 사전 / 동의어 후보 추출 (도입은 미정)
- 하이라이트(`SearchHit.highlights`) 를 LLM 컨텍스트에 활용할지 결정
- 정규화 룰 추가/축소를 회귀 테스트로 보호 (`test_retrieval_query_normalize.py` 확장)

이 단계는 **벡터 도입을 늦추기 위한 단계**다. BM25 로 풀 수 있는 만큼 풀어둔다.

### Stage 2 — 벡터 검색 도입 (단일 인덱스, hybrid 까지)

- 임베딩 모델 선정 + `embedding_model_id` / `embedding_version` 결정
- `document_chunk` 에 `embedding_status` 컬럼 추가 (DB 마이그레이션)
- chunk 임베딩 워커 추가 (parse/chunk 워커와 같은 PENDING/DONE/FAILED 패턴)
- OpenSearch 매핑에 `chunk_embedding` (knn_vector) 추가, 재색인
- `SearchClient` 구현체 안에서 **BM25 + knn 을 한 `bool` 쿼리**로 결합 (RRF 또는 가중합)
- `SearchHit` 계약은 변경 금지 — 호출부 변경 없음
- 평가 세트로 BM25 only vs hybrid recall@k 비교

### Stage 3 — 운영 강화

- 임베딩 버전 전환 절차 (신규 인덱스 + alias swap, 부분 재임베딩)
- Cross-encoder rerank 검토 (필요할 때만)
- 검색 지연/실패 메트릭 + 임베딩 API 실패율 모니터링
- 동의어 / 사용자 사전 (실 미스 로그에서 정당화될 때)

### Stage 4 — 외부 벡터 DB 검토 (도달 안 할 가능성도 큼)

- §10 의 조건이 실측으로 만족될 때만 후보 검토
- 검토 시에도 §7 권한 보장 / §8 임베딩 버전 관리가 그 DB 에서 같은 강도로 가능해야 함

---

## 부록 A. 변경 시 손대지 않는 계약

확장 단계에서도 다음 계약은 **흔들지 않는다** (`docs/todo-roadmap.md` §"확장 시 변경 금지 원칙" 과 정렬).

| 항목 | 이유 |
|------|------|
| `SearchClient.search(query, principal, top_k) -> list[SearchHit]` | 호출부 (chat/service, nas_rag) 가 retrieval 구현을 모르게 유지 |
| 권한 OR 절을 `bool.filter` 안쪽에 두는 위치 | 권한 누수 방지 (§7) |
| `original question` 을 LLM 프롬프트에 그대로 전달 | LLM 응답 품질 보호 (§3) |
| chunk 단위 색인 | 출처·권한·LLM 컨텍스트 크기 모두 chunk 단위가 자연스러움 |
| `SearchHit` 필드 (`chunk_id`, `raw_document_id`, `section_title`, `page_no`, `chunk_text`, `access_scope` …) | 응답 스키마·출처 표시 UX 안정성 |

이 계약 위에서 백엔드 구현, 인덱스 매핑, 임베딩 도입, 외부 DB 도입을 자유롭게 한다. 계약을 깨야 한다면 그건 별도 설계 문서가 필요한 변경이다.
