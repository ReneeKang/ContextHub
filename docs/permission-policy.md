# 권한 정책

## 기본 원칙

> **검색 전에 권한 필터를 적용한다.**
>
> 전체 검색 후 권한으로 결과를 제거하는 방식은 절대 금지한다.

---

## 경로 기반 권한 구조

초기 PoC는 NAS 반입 폴더의 **경로 자체가 권한을 결정**한다.
별도의 권한 설정 없이, 파일을 어떤 폴더에 넣느냐로 권한이 자동 부여된다.

```
/nas/chatbot_docs/
├─ public/                    → access_scope = PUBLIC
│   └─ 보안정책_v2.pdf
│
├─ dept/
│   ├─ infra/                 → access_scope = DEPT, department_code = infra
│   │   └─ 인프라_운영가이드.docx
│   └─ dev/                   → access_scope = DEPT, department_code = dev
│       └─ 개발표준_2026.pdf
│
└─ private/
    ├─ user001/               → access_scope = PRIVATE, owner_id = user001
    │   └─ 개인메모.txt
    └─ user002/               → access_scope = PRIVATE, owner_id = user002
        └─ 업무일지.hwp
```

---

## access_scope 정의

| access_scope | 접근 가능 대상 | 경로 패턴 |
|--------------|---------------|-----------|
| `PUBLIC` | 모든 인증된 사용자 | `/public/**` |
| `DEPT` | 해당 부서 구성원 | `/dept/{code}/**` |
| `PRIVATE` | 본인만 | `/private/{uid}/**` |

---

## 경로에서 권한 메타 추출 규칙

NAS Scan Worker가 파일 경로를 파싱하여 권한 메타를 자동 추출한다.

```python
# 경로 → 권한 메타 추출 예시 로직

def extract_permission(stored_path: str) -> dict:
    rel = stored_path.replace("/nas/chatbot_docs/", "")
    parts = rel.split("/")

    if parts[0] == "public":
        return {"access_scope": "PUBLIC", "owner_id": None, "department_code": None}

    elif parts[0] == "dept" and len(parts) >= 2:
        return {"access_scope": "DEPT", "owner_id": None, "department_code": parts[1]}

    elif parts[0] == "private" and len(parts) >= 2:
        return {"access_scope": "PRIVATE", "owner_id": parts[1], "department_code": None}

    else:
        raise ValueError(f"알 수 없는 반입 경로: {stored_path}")
```

---

## 권한 필터를 검색 전에 적용해야 하는 이유

### 잘못된 방식 (금지)

```
1. 사용자 질문 → 전체 OpenSearch 검색 (권한 무관)
2. 검색 결과 수신 (PRIVATE 문서 포함)
3. 권한 확인 후 필터링
4. 남은 결과로 LLM 응답 생성
```

**문제점:**
- PRIVATE 문서가 **검색 엔진에 이미 노출**된다
- LLM 컨텍스트에 포함되기 전에만 제거되므로 **노출 리스크** 존재
- 검색 엔진이 불필요한 문서를 처리하는 **성능 낭비**
- 필터링 로직 버그 시 **권한 외 정보 유출** 가능

### 올바른 방식 (필수)

```
1. 사용자 질문 수신
2. 사용자 세션에서 권한 정보 추출
3. 권한 조건을 포함한 OpenSearch 쿼리 구성
4. 검색 결과 = 이미 권한 필터가 적용된 결과
5. LLM 응답 생성
```

**장점:**
- 검색 엔진 레벨에서 권한 외 문서 완전 차단
- LLM 컨텍스트에 권한 외 정보가 절대 포함되지 않음
- 성능 최적화 (불필요한 문서 처리 없음)

---

## OpenSearch 쿼리 권한 필터 예시

```json
{
  "query": {
    "bool": {
      "must": {
        "match": { "chunk_text": "비밀번호 규칙" }
      },
      "filter": {
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
    }
  }
}
```

---

## 청크 레벨 권한 메타

검색 필터는 `document_chunk` 단위로 동작한다.
`raw_document`의 권한 메타가 각 청크에 **복사**되어 저장되는 이유가 여기에 있다.

```
raw_document
  access_scope = DEPT
  department_code = infra
         │
         ▼ (chunk 생성 시 복사)
document_chunk (chunk_no=1)
  access_scope = DEPT
  department_code = infra

document_chunk (chunk_no=2)
  access_scope = DEPT
  department_code = infra
```

청크마다 권한 메타를 갖고 있어야 OpenSearch에서 청크 단위 필터링이 가능하다.

---

## PoC 권한 범위

| 기능 | PoC 포함 여부 |
|------|--------------|
| 경로 기반 access_scope 추출 | ✅ 포함 |
| PUBLIC 검색 | ✅ 포함 |
| PRIVATE 검색 (본인만) | ✅ 포함 |
| DEPT 검색 (부서 기준) | ✅ 포함 |
| AD/LDAP 연동 | ❌ 미포함 (PoC 이후) |
| 문서별 개별 ACL | ❌ 미포함 (PoC 이후) |
| 그룹 기반 권한 | ❌ 미포함 (PoC 이후) |

---

## 향후 확장 포인트

1. **AD/LDAP 연동**: 사용자 부서·그룹 정보를 디렉터리 서버에서 실시간 조회
2. **문서별 ACL**: `raw_document` 수준에서 개별 사용자 목록 지정
3. **태그 기반 권한**: 경로 외에 문서 태그로 추가 접근 제어
4. **동적 부서 구조**: 조직 개편 시 경로 재맵핑 정책

---

## 권한 정책 변경 시 주의사항

경로 기반 권한은 **파일 이동이 곧 권한 변경**을 의미한다.

- NAS에서 파일이 `/public/` → `/private/user001/` 로 이동되면
  → NAS Scan Worker가 경로 변경을 감지
  → `raw_document`의 `access_scope` 업데이트 필요
  → OpenSearch 색인 재갱신 필요

파일 이동 감지 처리는 PoC 이후 별도 설계가 필요하다.
