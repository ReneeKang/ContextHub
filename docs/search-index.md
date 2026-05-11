# 검색 인덱스 설계

## 검색 엔진

OpenSearch (또는 Elasticsearch 호환)

---

## 인덱스 구조

### 인덱스명

```
contexthub_chunks
```

청크 단위로 색인한다. 문서 단위가 아니다.

---

### 인덱스 매핑 (Mapping)

```json
{
  "mappings": {
    "properties": {
      "chunk_id": {
        "type": "keyword"
      },
      "raw_document_id": {
        "type": "keyword"
      },
      "original_filename": {
        "type": "keyword"
      },
      "file_ext": {
        "type": "keyword"
      },
      "chunk_no": {
        "type": "integer"
      },
      "section_title": {
        "type": "text",
        "analyzer": "nori"
      },
      "page_no": {
        "type": "integer"
      },
      "chunk_text": {
        "type": "text",
        "analyzer": "nori"
      },
      "access_scope": {
        "type": "keyword"
      },
      "owner_id": {
        "type": "keyword"
      },
      "department_code": {
        "type": "keyword"
      },
      "created_at": {
        "type": "date"
      }
    }
  },
  "settings": {
    "analysis": {
      "analyzer": {
        "nori": {
          "type": "nori"
        }
      }
    }
  }
}
```

한국어 형태소 분석기 `nori`를 기본으로 사용한다.

---

## 권한 필터 포함 검색 쿼리

> **검색 쿼리에 권한 필터를 반드시 포함한다.**
> 전체 검색 후 결과를 필터링하는 방식은 절대 금지한다.

### 기본 검색 쿼리 구조

```json
{
  "size": 5,
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "비밀번호 규칙",
            "fields": ["chunk_text^2", "section_title^3"],
            "type": "best_fields"
          }
        }
      ],
      "filter": [
        {
          "bool": {
            "should": [
              { "term": { "access_scope": "PUBLIC" } },
              {
                "bool": {
                  "must": [
                    { "term": { "access_scope": "DEPT" } },
                    { "terms": { "department_code": ["infra", "dev"] } }
                  ]
                }
              },
              {
                "bool": {
                  "must": [
                    { "term": { "access_scope": "PRIVATE" } },
                    { "term": { "owner_id": "user001" } }
                  ]
                }
              }
            ],
            "minimum_should_match": 1
          }
        }
      ]
    }
  },
  "_source": [
    "chunk_id",
    "raw_document_id",
    "original_filename",
    "section_title",
    "page_no",
    "chunk_text",
    "access_scope"
  ]
}
```

### 권한 조건 설명

| 조건 | 의미 |
|------|------|
| `access_scope = PUBLIC` | 모든 사용자 접근 가능 |
| `access_scope = DEPT AND department_code IN [...]` | 해당 부서 구성원만 |
| `access_scope = PRIVATE AND owner_id = ...` | 본인만 |

세 조건을 `should` (OR)로 연결하여 사용자가 접근 가능한 모든 문서를 포함한다.

---

## 색인 단위: 청크

문서 전체가 아닌 **청크 단위**로 색인하는 이유:

1. **검색 정확도**: 긴 문서를 통째로 색인하면 관련 없는 내용이 검색 스코어를 낮춤
2. **LLM 컨텍스트 크기**: 청크 단위로 가져와야 LLM 컨텍스트 길이 제어 가능
3. **출처 표시**: 청크의 `section_title`, `page_no`로 정확한 출처 제공
4. **권한 적용**: 청크마다 권한 메타가 있어 문서 일부 섹션 접근 제어 가능 (미래)

---

## 색인 흐름 (document-index-worker)

```
1. document_chunk 조회
   WHERE index_status = 'PENDING'
   LIMIT 100  (배치 처리)

2. 각 청크를 OpenSearch 문서로 변환
   {
     "chunk_id": chunk.chunk_id,
     "raw_document_id": chunk.raw_document_id,
     "chunk_no": chunk.chunk_no,
     "section_title": chunk.section_title,
     "page_no": chunk.page_no,
     "chunk_text": chunk.chunk_text,
     "access_scope": chunk.access_scope,
     "owner_id": chunk.owner_id,
     "department_code": chunk.department_code,
     ...
   }

3. OpenSearch Bulk API로 일괄 색인

4. 성공한 청크:
   document_chunk.index_status = 'DONE'
   document_index_status INSERT (status='DONE')

5. 실패한 청크:
   document_chunk.index_status = 'FAILED'
   document_index_status INSERT (status='FAILED', error_message=...)
```

---

## 색인 제외 처리

관리자가 특정 문서를 검색 결과에서 제외하는 경우:

```
1. admin-api: POST /documents/{id}/exclude 호출
2. raw_document.excluded = TRUE
3. OpenSearch에서 해당 raw_document_id의 청크 전체 삭제
   DELETE BY QUERY WHERE raw_document_id = '...'
4. document_chunk.index_status 는 'EXCLUDED' 또는 유지
```

---

## 검색 결과 구조

```json
{
  "hits": {
    "total": { "value": 3 },
    "hits": [
      {
        "_id": "chunk-uuid-...",
        "_score": 0.92,
        "_source": {
          "chunk_id": "uuid-...",
          "raw_document_id": "uuid-...",
          "original_filename": "보안정책_v2.pdf",
          "section_title": "2. 비밀번호 규칙",
          "page_no": 12,
          "chunk_text": "비밀번호는 최소 8자리 이상이어야 하며 영문, 숫자, 특수문자를 포함해야 합니다...",
          "access_scope": "PUBLIC"
        }
      }
    ]
  }
}
```

---

## 향후 확장: 벡터 검색

PoC에서는 키워드(BM25) 검색만 사용한다.
이후 단계에서 벡터 검색 추가 가능.

| 단계 | 검색 방식 |
|------|----------|
| PoC | 키워드 검색 (BM25, nori 분석기) |
| Phase 2 | Dense Vector 검색 (임베딩 모델 추가) |
| Phase 3 | Hybrid Search (키워드 + 벡터 결합) |

벡터 검색 도입 시에도:
- **권한 필터는 동일하게 쿼리에 포함**
- `chunk_text`는 그대로 유지, 임베딩 벡터 필드만 추가

---

## 인덱스 운영

| 작업 | 설명 |
|------|------|
| 인덱스 생성 | 시스템 초기화 시 1회 |
| 재색인 | 파서 교체 또는 청킹 전략 변경 시 전체 재처리 |
| 청크 삭제 | 문서 제외 처리 시 |
| 샤드 수 | PoC: 1 primary, 0 replica (단일 노드) |

---

## 주의사항

- `chunk_text` 필드는 `_source`에 저장하되, 검색 시 highlight 기능 사용 가능
- `access_scope`, `owner_id`, `department_code`는 `keyword` 타입 (정확 일치 필터용)
- `chunk_text`, `section_title`은 `text` + `nori` 분석기 (형태소 분석 검색용)
- `chunk_id`는 OpenSearch `_id`와 동일하게 설정하여 중복 색인 방지
