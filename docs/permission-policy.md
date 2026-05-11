# 권한 정책

## 문서 목적

이 문서는 두 가지 목적을 동시에 다룬다.

1. **현재 구현**: PoC 단계에서 동작하는 경로 기반 권한 모델
2. **확장 설계**: 멀티에이전트 운영 플랫폼으로 성장할 때의 권한 아키텍처 방향

현재 구현을 변경하지 않으면서, 미래 구조가 현재 인터페이스와 충돌하지 않도록 설계 방향을 미리 확보하는 것이 핵심이다.

---

## 핵심 원칙 (현재·미래 공통)

> **권한 필터는 반드시 검색 단계에 포함한다.**
>
> 검색 결과를 받은 후 권한으로 걸러내는 방식은 어떤 단계에서도 허용하지 않는다.

이 원칙은 PoC에서도, 멀티에이전트 시스템에서도 동일하게 적용된다.

---

# Part 1. 현재 구현 (PoC)

## 1-1. 권한 모델: PUBLIC / DEPT / PRIVATE

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

| access_scope | 접근 가능 대상 | 경로 패턴 |
|--------------|---------------|-----------|
| `PUBLIC` | 모든 인증된 사용자 | `/public/**` |
| `DEPT` | 해당 부서 구성원 | `/dept/{code}/**` |
| `PRIVATE` | 본인만 | `/private/{uid}/**` |

---

## 1-2. 경로에서 권한 메타 추출

NAS Scan Worker가 파일 경로를 파싱하여 권한 메타를 자동 추출한다.

```python
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

## 1-3. PermissionPrincipal 구조

`chat-api`는 사용자 요청을 받을 때 세션에서 **PermissionPrincipal**을 구성한다.
이 객체가 검색 필터 생성의 유일한 입력이다.

```python
@dataclass
class PermissionPrincipal:
    user_id: str                      # 인증된 사용자 ID
    department_codes: list[str]       # 소속 부서 코드 목록 (현재는 단일, 향후 복수 가능)
```

**현재 구성 방법**: 로그인 세션 또는 JWT 클레임에서 직접 추출.
AD/LDAP 연동은 PoC 이후이므로, 지금은 토큰에 포함된 정보를 그대로 사용한다.

```python
def build_principal(token: dict) -> PermissionPrincipal:
    return PermissionPrincipal(
        user_id=token["sub"],
        department_codes=token.get("dept_codes", []),
    )
```

---

## 1-4. 현재 SQL 필터 방식

PermissionPrincipal로부터 OpenSearch 쿼리 필터를 생성한다.

```python
def build_permission_filter(principal: PermissionPrincipal) -> dict:
    clauses = [
        {"term": {"access_scope": "PUBLIC"}},
    ]
    if principal.department_codes:
        clauses.append({
            "bool": {
                "must": [
                    {"term": {"access_scope": "DEPT"}},
                    {"terms": {"department_code": principal.department_codes}},
                ]
            }
        })
    clauses.append({
        "bool": {
            "must": [
                {"term": {"access_scope": "PRIVATE"}},
                {"term": {"owner_id": principal.user_id}},
            ]
        }
    })
    return {"bool": {"should": clauses, "minimum_should_match": 1}}
```

생성된 필터는 OpenSearch 쿼리의 `filter` 절에 삽입된다.

```json
{
  "query": {
    "bool": {
      "must": { "match": { "chunk_text": "비밀번호 규칙" } },
      "filter": { "<위의 build_permission_filter 결과>" }
    }
  }
}
```

---

## 1-5. 청크 레벨 권한 메타

검색 필터는 `document_chunk` 단위로 동작한다.
`raw_document`의 권한 메타가 각 청크에 **복사**되어 저장되는 이유가 여기에 있다.

```
raw_document
  access_scope = DEPT
  department_code = infra
         │
         ▼ (chunk 생성 시 복사)
document_chunk (chunk_no=1)   →  OpenSearch 색인
  access_scope = DEPT
  department_code = infra

document_chunk (chunk_no=2)   →  OpenSearch 색인
  access_scope = DEPT
  department_code = infra
```

청크마다 권한 메타가 있어야 OpenSearch 쿼리에서 청크 단위 필터링이 가능하다.
문서 단위로만 권한을 갖고 있으면, 검색 결과에서 청크를 개별적으로 제어할 수 없다.

---

## 1-6. 왜 검색 이후가 아니라 검색 단계에서 필터링해야 하는가

이 질문은 PoC 단계뿐 아니라 어떤 규모의 시스템에서도 동일하게 적용된다.

### 잘못된 방식 (절대 금지)

```
1. 사용자 질문 → 전체 OpenSearch 검색 (권한 무관)
2. 검색 결과 수신 (PRIVATE 문서 포함)
3. 애플리케이션에서 권한 확인 후 제거
4. 남은 결과로 LLM 응답 생성
```

**왜 위험한가**

| 문제 | 설명 |
|------|------|
| 정보 노출 경계가 애플리케이션 레이어에 있다 | 검색 엔진은 이미 권한 외 문서를 내려줬다 |
| LLM 컨텍스트 구성 전에 제거해도 늦다 | 검색 결과가 로그, 캐시, 디버그 출력에 남을 수 있다 |
| 멀티에이전트 환경에서 치명적이다 | Agent A의 결과가 Agent B에게 컨텍스트로 전달될 때 필터링 누락 가능 |
| 필터링 버그 발생 시 전체 문서가 노출된다 | 조건 반전 버그 하나로 권한 외 전 문서 접근 가능 |
| top_k 계산이 왜곡된다 | 5개를 요청했는데 권한 외 문서를 제거하면 실제 컨텍스트는 2개가 될 수 있다 |

### 올바른 방식 (필수)

```
1. 사용자 요청 수신
2. PermissionPrincipal 구성 (세션에서)
3. 권한 필터를 포함한 검색 쿼리 구성
4. 검색 엔진이 권한 외 문서를 물리적으로 제외한 결과 반환
5. 반환된 결과는 전부 접근 가능한 문서만 포함
6. LLM 컨텍스트 구성 → 응답
```

**장점**

- 검색 엔진 레벨에서 권한 외 문서를 차단한다. 애플리케이션 버그와 무관하다.
- top_k 결과가 전부 유효한 접근 가능 문서다.
- 로그, 캐시, 디버그 출력에 권한 외 내용이 남지 않는다.
- 멀티에이전트 환경에서 각 에이전트가 독립적으로 권한 필터를 적용할 수 있다.

---

# Part 2. 현재 단순 구조를 유지하는 이유

## 2-1. 조기 ACL 시스템 구현의 위험성

복잡한 ACL 시스템을 PoC 단계에서 구현하면 다음 문제가 발생한다.

| 문제 | 결과 |
|------|------|
| 권한 모델이 먼저 만들어지고 요구사항이 나중에 나온다 | 실제 요구사항과 맞지 않는 구조가 고착된다 |
| 권한 테이블이 늘어날수록 문서 반입·파싱·색인 로직이 복잡해진다 | 핵심 파이프라인 검증이 늦어진다 |
| 권한 관련 버그가 파이프라인 전체를 막는다 | PoC 자체가 실패한다 |
| 운영 경험 없이 그룹·역할 체계를 설계하면 틀릴 가능성이 높다 | 나중에 전면 재설계 필요 |

## 2-2. 현재 PoC가 검증해야 할 것

PoC의 목표는 권한 시스템을 완성하는 것이 아니다.

```
✅ NAS → 파싱 → 청킹 → 색인 → 검색 → LLM 응답 파이프라인이 동작하는가
✅ 권한 필터를 검색 단계에 포함하는 구조가 성립하는가
✅ 상태 기반 단계 분리가 운영 가시성을 제공하는가

❌ 그룹·역할·프로젝트 기반 정교한 ACL이 동작하는가  ← PoC 범위 아님
```

## 2-3. 확장 가능한 인터페이스 유지 전략

현재 구조가 단순하더라도 향후 확장 시 **인터페이스를 깨지 않도록** 설계 포인트를 미리 잡아둔다.

| 현재 | 향후 확장 방향 | 변경 범위 |
|------|--------------|----------|
| `PermissionPrincipal(user_id, department_codes)` | `group_ids`, `role`, `rank` 필드 추가 | `PermissionPrincipal` 클래스 확장 |
| `build_permission_filter()` | 그룹·역할 조건 clause 추가 | 함수 내부만 수정 |
| `raw_document.access_scope` | `dataset_id`, `project_id` 필드 추가 | DB 컬럼 추가 + 마이그레이션 |
| OpenSearch 인덱스 | 권한 필드 추가 | 재색인 필요 |
| `document_chunk` 권한 메타 | 그룹·프로젝트 ID 필드 추가 | DB 컬럼 추가 |

핵심은 `build_permission_filter(principal)` 함수가 PermissionPrincipal만 받고,
내부 구현을 교체할 수 있는 단일 진입점으로 유지되는 것이다.

---

# Part 3. 향후 확장 아키텍처

> 이 섹션은 **설계 방향**이다. 지금 구현하지 않는다.
> 현재 구조를 깨지 않고 단계적으로 추가하는 방향으로 기술한다.

## 3-1. 확장 대상 엔티티

운영형 RAG/Agent 플랫폼에서 권한 제어가 필요한 엔티티는 다음과 같다.

```
사용자(user)
  ├─ 그룹(group)            ex. 보안팀, 프로젝트A팀
  ├─ 역할(role)             ex. ADMIN, EDITOR, VIEWER
  └─ 직급(rank)             ex. 임원, 팀장, 사원

문서 자원(resource)
  ├─ dataset                문서 집합 단위
  ├─ raw_document           개별 문서
  └─ document_chunk         청크 (검색 단위)

에이전트 자원
  ├─ agent                  특정 LLM 에이전트
  └─ agent_tool             에이전트가 사용하는 도구

프로젝트(project)
  └─ dataset, agent를 묶는 작업 단위
```

---

## 3-2. 확장된 PermissionPrincipal

현재의 `PermissionPrincipal`을 확장하되, 현재 필드는 유지한다.

```python
@dataclass
class PermissionPrincipal:
    # 현재 구현 (PoC)
    user_id: str
    department_codes: list[str]

    # Phase 2 확장
    group_ids: list[str] = field(default_factory=list)   # 소속 그룹 ID 목록
    role: str | None = None                               # 역할 (ADMIN / EDITOR / VIEWER)
    rank: str | None = None                               # 직급 코드 (임원 전용 문서 접근 등)

    # Phase 3 확장
    project_ids: list[str] = field(default_factory=list) # 참여 프로젝트 ID 목록
    accessible_dataset_ids: list[str] = field(default_factory=list)  # 명시적 접근 허용 데이터셋
```

`build_permission_filter(principal)` 함수는 이 객체를 받아 필터 clause를 생성한다.
현재는 `user_id`, `department_codes`만 사용하고, 나머지는 비어 있으면 clause를 추가하지 않는다.

---

## 3-3. 엔티티 관계 구조 (향후)

```
user ─────────── group
  │                │
  │                ├── dataset   (그룹이 접근 가능한 문서 집합)
  │                └── agent     (그룹이 사용 가능한 에이전트)
  │
  ├── role ──────── agent        (역할 기반 에이전트 접근)
  │
  └── project ──── dataset       (프로젝트에 포함된 데이터셋)
                └── agent        (프로젝트에 배정된 에이전트)
```

### user ↔ group

```
user_group_membership
  user_id       VARCHAR
  group_id      VARCHAR
  joined_at     TIMESTAMPTZ
```

사용자는 복수의 그룹에 속할 수 있다.
그룹은 `department`보다 유연하다. 조직도와 무관한 프로젝트팀, 태스크포스 등을 표현할 수 있다.

### group ↔ dataset

```
dataset_group_permission
  dataset_id    UUID
  group_id      VARCHAR
  permission    VARCHAR   -- READ | WRITE | ADMIN
```

특정 그룹에게 특정 데이터셋 접근 권한을 부여한다.
`dataset`은 `raw_document`의 논리적 묶음이다.

### group ↔ agent

```
agent_group_permission
  agent_id      UUID
  group_id      VARCHAR
  permission    VARCHAR   -- USE | CONFIGURE | ADMIN
```

특정 에이전트를 사용할 수 있는 그룹을 지정한다.

### project ↔ document

```
project_document_scope
  project_id      UUID
  raw_document_id UUID     -- 또는 dataset_id
  added_at        TIMESTAMPTZ
```

프로젝트 범위 내에서만 특정 문서가 검색 가능하도록 제한한다.
"이 에이전트는 프로젝트 A 관련 문서만 참조한다"는 제약을 표현한다.

### role 기반 agent 접근

```python
# 역할(role) 기반 에이전트 접근 제어 예시

AGENT_ROLE_REQUIREMENTS = {
    "finance-agent":    ["FINANCE_VIEWER", "ADMIN"],
    "legal-agent":      ["LEGAL_REVIEWER", "ADMIN"],
    "hr-agent":         ["HR_STAFF", "ADMIN"],
    "general-agent":    ["*"],   # 모든 역할 허용
}

def can_access_agent(principal: PermissionPrincipal, agent_id: str) -> bool:
    required_roles = AGENT_ROLE_REQUIREMENTS.get(agent_id, [])
    if "*" in required_roles:
        return True
    return principal.role in required_roles
```

---

## 3-4. dataset / document ACL

현재는 경로 기반 `access_scope`로 문서 권한을 관리한다.
운영 플랫폼에서는 문서·데이터셋 단위의 세밀한 ACL이 필요하다.

```
raw_document
  ├── access_scope (현재): PUBLIC | DEPT | PRIVATE
  ├── dataset_id (추가):   소속 데이터셋 ID
  └── acl_overrides (추가): 명시적 허용/거부 목록
```

```python
# 향후 ACL 구조 예시

@dataclass
class DocumentACL:
    raw_document_id: str
    allow_user_ids: list[str]    # 명시적 허용 사용자
    deny_user_ids: list[str]     # 명시적 거부 사용자 (allow보다 우선)
    allow_group_ids: list[str]   # 명시적 허용 그룹
    allow_role: str | None       # 최소 역할 요구사항
    allow_rank: str | None       # 최소 직급 요구사항
```

**ACL 우선순위 (향후)**

```
deny_user_ids 명시 거부  >  allow_user_ids 명시 허용  >
allow_group_ids 그룹 허용  >  allow_role 역할 허용  >
access_scope 경로 기반  >  기본 거부
```

---

## 3-5. 멀티에이전트 접근 제어

여러 에이전트가 협력하는 시스템에서는 **에이전트가 문서에 접근할 때도 권한 검증**이 필요하다.

### 문제 상황

```
사용자(일반 VIEWER)
  → Orchestrator Agent 호출
    → Sub-agent A (finance 데이터 접근)
      → Sub-agent B (법무 문서 검색)  ← 사용자는 법무 문서 접근 불가
```

사용자 권한이 에이전트 체인을 통해 확장되는 것을 막아야 한다.

### 원칙

1. **에이전트는 사용자 권한을 상속하되 확장할 수 없다.**
   - 사용자가 VIEWER면 에이전트도 VIEWER 권한으로만 검색한다.
   - 에이전트 자체 권한이 높아도 사용자 권한을 초과할 수 없다.

2. **에이전트 호출 시 PermissionPrincipal을 명시적으로 전달한다.**
   - 에이전트가 직접 세션에서 권한을 읽지 않는다.
   - 권한 컨텍스트는 항상 명시적으로 주입된다.

3. **각 에이전트는 독립적으로 권한 필터를 적용한다.**
   - Orchestrator가 필터를 적용했다고 Sub-agent가 생략하지 않는다.
   - 각 검색 호출마다 권한 필터를 포함한다.

```python
# 멀티에이전트 권한 전달 예시 (향후 구조)

class AgentContext:
    principal: PermissionPrincipal   # 원본 사용자 권한, 변경 불가
    agent_id: str
    session_id: str
    project_id: str | None

def sub_agent_search(context: AgentContext, query: str) -> list[Chunk]:
    # context.principal은 항상 원본 사용자 권한
    permission_filter = build_permission_filter(context.principal)
    return opensearch.search(query, filter=permission_filter)
```

---

## 3-6. 직급(rank) 기반 접근 제어

일부 문서는 직급 기반으로 접근을 제한해야 한다.

```python
# 직급 계층 정의 예시

RANK_HIERARCHY = {
    "EXECUTIVE": 5,
    "DIRECTOR":  4,
    "MANAGER":   3,
    "SENIOR":    2,
    "STAFF":     1,
}

def meets_rank_requirement(principal: PermissionPrincipal, required_rank: str) -> bool:
    user_level = RANK_HIERARCHY.get(principal.rank, 0)
    required_level = RANK_HIERARCHY.get(required_rank, 999)
    return user_level >= required_level
```

이 기반으로 "임원 이상만 접근 가능한 문서"를 검색 필터에 포함할 수 있다.

---

## 3-7. 향후 OpenSearch 필터 확장 방향

현재 필터 구조를 유지하면서 clause를 추가하는 방식으로 확장한다.

```python
def build_permission_filter(principal: PermissionPrincipal) -> dict:
    clauses = []

    # 현재 구현 (PoC) ──────────────────────────────────
    clauses.append({"term": {"access_scope": "PUBLIC"}})

    if principal.department_codes:
        clauses.append({
            "bool": {
                "must": [
                    {"term":  {"access_scope": "DEPT"}},
                    {"terms": {"department_code": principal.department_codes}},
                ]
            }
        })

    clauses.append({
        "bool": {
            "must": [
                {"term": {"access_scope": "PRIVATE"}},
                {"term": {"owner_id": principal.user_id}},
            ]
        }
    })

    # Phase 2 확장 ─────────────────────────────────────
    if principal.group_ids:
        clauses.append({
            "bool": {
                "must": [
                    {"term":  {"access_scope": "GROUP"}},
                    {"terms": {"allowed_group_ids": principal.group_ids}},
                ]
            }
        })

    if principal.accessible_dataset_ids:
        clauses.append({
            "terms": {"dataset_id": principal.accessible_dataset_ids}
        })

    # Phase 3 확장 ─────────────────────────────────────
    if principal.project_ids:
        clauses.append({
            "terms": {"project_id": principal.project_ids}
        })

    if principal.rank:
        clauses.append({
            "bool": {
                "must": [
                    {"term":   {"access_scope": "RANK_RESTRICTED"}},
                    {"range":  {"required_rank_level": {"lte": RANK_HIERARCHY.get(principal.rank, 0)}}},
                ]
            }
        })

    return {"bool": {"should": clauses, "minimum_should_match": 1}}
```

`build_permission_filter` 함수 시그니처는 변하지 않는다.
PermissionPrincipal에 필드가 추가되고, 함수 내부에 clause가 추가되는 방식이다.

---

# Part 4. 권한 확장 로드맵

| Phase | 범위 | 주요 변경 |
|-------|------|----------|
| **PoC** | PUBLIC / DEPT / PRIVATE 경로 기반 | 현재 구현 완료 |
| **Phase 2** | 그룹(group) 기반 권한 | `group_ids` 추가, `dataset_group_permission` 테이블 |
| **Phase 2** | 데이터셋(dataset) 단위 접근 제어 | `dataset_id` 컬럼 추가, 재색인 |
| **Phase 2** | AD/LDAP 연동 | PermissionPrincipal 구성 시 디렉터리 조회 |
| **Phase 3** | 역할(role) 기반 에이전트 접근 | `agent_group_permission` 테이블, role 체계 |
| **Phase 3** | 프로젝트(project) 범위 제한 | `project_document_scope` 테이블 |
| **Phase 3** | 직급(rank) 기반 문서 접근 | `required_rank_level` 색인 필드 |
| **Phase 4** | 멀티에이전트 권한 체인 | `AgentContext` 도입, 에이전트별 권한 위임 정책 |
| **Phase 4** | 문서별 개별 ACL | `DocumentACL`, deny 목록 지원 |

---

# Part 5. 현재 구현 범위 정리

| 기능 | 현재 구현 | 향후 |
|------|----------|------|
| 경로 기반 access_scope 자동 추출 | ✅ | — |
| PUBLIC 검색 | ✅ | — |
| DEPT 검색 | ✅ | — |
| PRIVATE 검색 | ✅ | — |
| PermissionPrincipal 구조 | ✅ (user_id + dept) | 필드 추가 |
| build_permission_filter() 단일 진입점 | ✅ | 내부 확장 |
| 검색 단계 권한 필터 적용 | ✅ | 동일 원칙 유지 |
| 그룹 기반 권한 | ❌ | Phase 2 |
| 데이터셋 ACL | ❌ | Phase 2 |
| AD/LDAP 연동 | ❌ | Phase 2 |
| 역할(role) 기반 에이전트 접근 | ❌ | Phase 3 |
| 프로젝트 범위 제한 | ❌ | Phase 3 |
| 직급(rank) 기반 접근 | ❌ | Phase 3 |
| 멀티에이전트 권한 체인 | ❌ | Phase 4 |
| 문서별 개별 ACL | ❌ | Phase 4 |

---

## 권한 정책 변경 시 주의사항

경로 기반 권한은 **파일 이동이 곧 권한 변경**을 의미한다.

```
/public/ → /private/user001/ 로 파일 이동 시:
  1. NAS Scan Worker가 경로 변경 감지
  2. raw_document.access_scope = 'PRIVATE', owner_id = 'user001' 갱신
  3. document_chunk의 권한 메타 전체 갱신
  4. OpenSearch 해당 청크 재색인
```

파일 이동 감지 처리는 PoC 이후 별도 설계가 필요하다.
PoC 기간에는 파일 이동 시 수동으로 재처리하거나, 이동을 금지하는 운영 정책을 적용한다.
