# 프롬프트 전략

## 문서 목적

- 왜 프롬프트를 별도 모듈로 분리해야 하는지
- RAG 프롬프트의 올바른 구조
- 에이전트별 프롬프트 관리 전략
- 절대 하지 말아야 할 패턴

---

## 왜 PromptBuilder를 분리해야 하는가

### 이유 1: 프롬프트는 코드가 아니라 정책이다

프롬프트는 LLM의 동작을 결정하는 가장 중요한 입력이다.
그러나 Usecase나 API 핸들러 안에 문자열로 박혀 있으면:

- 프롬프트를 수정하려면 코드를 열어야 한다
- 어떤 에이전트가 어떤 프롬프트를 쓰는지 한눈에 볼 수 없다
- 프롬프트 변경이 배포와 묶인다

프롬프트를 별도 모듈(`prompts/`)에 모아두면
정책 변경과 코드 변경을 분리할 수 있다.

### 이유 2: 컨텍스트 조립 로직이 복잡해진다

단순해 보이지만 실제 RAG 프롬프트 조립은 다음을 처리해야 한다.

- 청크 수가 많으면 LLM 컨텍스트 한도를 초과한다 → 토큰 수 기반 청크 선택
- 청크마다 출처(파일명, 섹션, 페이지)를 포함해야 한다 → 포맷 규칙 필요
- 시스템 프롬프트와 사용자 메시지를 분리해야 한다 → role 구조

이 로직이 Usecase 안에 있으면 Usecase가 비대해진다.

### 이유 3: 에이전트마다 다른 프롬프트가 필요하다

| 에이전트 | 특화 프롬프트 |
|---------|-------------|
| NasRagAgent | 사내 문서 기반 응답, 출처 명시, 모르면 모른다고 |
| LogAnalysisAgent | 로그 패턴 해석, 기술적 설명 |
| StandardsReviewAgent | 표준 조항 참조, 준수 여부 판단 |
| SqlDataAgent | SQL 결과 해석, 수치 설명 |

공통 부분은 공유하고, 에이전트별 특화 부분은 분리한다.

---

## 프롬프트 구조

### RAG 프롬프트 기본 구조

```
messages = [
    { "role": "system",    "content": <시스템 프롬프트> },
    { "role": "user",      "content": <컨텍스트 + 질문> }
]
```

단일 문자열로 전체를 합치지 않는다.
`system` role은 LLM이 "이 에이전트가 무엇인지"를 이해하는 부분이다.
`user` role은 실제 컨텍스트와 질문이다.

---

### 시스템 프롬프트 (NasRagAgent)

```python
NAS_RAG_SYSTEM_PROMPT = """당신은 사내 문서를 기반으로 질문에 답하는 어시스턴트입니다.

답변 규칙:
1. 반드시 제공된 문서 컨텍스트만 근거로 답변합니다.
2. 컨텍스트에 없는 내용은 "제공된 문서에서 확인할 수 없습니다"라고 답합니다.
3. 추측하거나 외부 지식으로 보완하지 않습니다.
4. 답변 끝에 근거 문서를 "[출처: 파일명 > 섹션명]" 형식으로 명시합니다.
5. 여러 문서가 근거인 경우 모두 나열합니다.
"""
```

**설계 원칙:**

- 짧고 명확하게. 길수록 LLM이 규칙을 혼동한다.
- "하라"보다 "하지 마라"를 명시하는 것이 효과적이다.
- 출처 형식을 구체적으로 지정한다. LLM이 임의 형식으로 출처를 생성하면 파싱이 어렵다.

---

### 사용자 메시지 (컨텍스트 + 질문)

```python
USER_PROMPT_TEMPLATE = """\
아래 문서 내용을 참고하여 질문에 답변해주세요.

---
{context_blocks}
---

질문: {question}
"""
```

**`context_blocks` 포맷:**

```python
CHUNK_BLOCK_TEMPLATE = """\
[출처: {filename} > {section_title} (p.{page_no})]
{chunk_text}
"""
```

청크마다 출처를 앞에 붙인다.
LLM이 어떤 내용이 어느 문서에서 왔는지 알 수 있어야
출처를 정확하게 답변에 포함할 수 있다.

---

## PromptBuilder 구현

```python
# app/chat/prompts/nas_rag_prompt.py

from dataclasses import dataclass
from ..schemas import RetrievedChunk


@dataclass
class BuiltPrompt:
    messages: list[dict]          # LLMRequest.messages 형식
    included_chunk_ids: list[str] # 실제 포함된 청크 (토큰 한도로 잘린 경우 추적용)
    estimated_tokens: int


class NasRagPromptBuilder:

    MAX_CONTEXT_CHARS = 6000      # 토큰 추정: 한국어 1자 ≈ 1.5~2 토큰

    def build(self, chunks: list[RetrievedChunk], question: str) -> BuiltPrompt:
        selected, total_chars = self._select_chunks(chunks)
        context_blocks = self._build_context(selected)
        user_content = USER_PROMPT_TEMPLATE.format(
            context_blocks=context_blocks,
            question=question,
        )
        return BuiltPrompt(
            messages=[
                {"role": "system", "content": NAS_RAG_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            included_chunk_ids=[c.chunk_id for c in selected],
            estimated_tokens=total_chars // 2,   # 한국어 거친 추정
        )

    def _select_chunks(self, chunks: list[RetrievedChunk]) -> tuple[list, int]:
        selected, total = [], 0
        for chunk in chunks:
            chunk_len = len(chunk.chunk_text)
            if total + chunk_len > self.MAX_CONTEXT_CHARS:
                break
            selected.append(chunk)
            total += chunk_len
        return selected, total

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        blocks = []
        for chunk in chunks:
            block = CHUNK_BLOCK_TEMPLATE.format(
                filename=chunk.original_filename,
                section_title=chunk.section_title or "본문",
                page_no=chunk.page_no or "-",
                chunk_text=chunk.chunk_text,
            )
            blocks.append(block)
        return "\n\n".join(blocks)
```

---

## 모듈 구조

```
app/
└─ chat/
    └─ prompts/
        ├─ __init__.py
        ├─ base.py                  # PromptBuilder ABC (향후 공통 인터페이스)
        ├─ nas_rag_prompt.py        # NasRagAgent 프롬프트
        ├─ log_analysis_prompt.py   # LogAnalysisAgent 프롬프트 (향후)
        └─ standards_prompt.py      # StandardsReviewAgent 프롬프트 (향후)
```

에이전트별 프롬프트 파일을 분리한다.
한 파일에 모든 에이전트 프롬프트를 넣으면 관리가 어렵다.

---

## 프롬프트 설계 원칙

### 1. 출처 명시를 강제한다

RAG 시스템에서 hallucination의 주요 원인은 LLM이 컨텍스트 외부 지식을 사용하는 것이다.
시스템 프롬프트에서 "컨텍스트만 사용"과 "출처 명시"를 동시에 요구하면
LLM이 컨텍스트를 벗어나기 어렵게 된다.

### 2. "모른다"는 답을 허용한다

```python
# 시스템 프롬프트에 반드시 포함:
"컨텍스트에 없는 내용은 '제공된 문서에서 확인할 수 없습니다'라고 답합니다."
```

LLM이 "모른다"고 답하는 것을 허용하지 않으면 hallucination이 발생한다.
**틀린 답보다 모른다는 답이 낫다.**

### 3. temperature는 낮게 유지한다

RAG 응답은 창의성보다 정확성이 중요하다.

```python
LLMRequest(
    messages=prompt.messages,
    temperature=0.1,    # 기본값. 0.0은 완전히 결정론적이지만 너무 딱딱할 수 있음
    max_tokens=2048,
)
```

### 4. 청크 순서는 관련성 순서를 유지한다

검색 결과는 관련성 점수 순으로 반환된다.
프롬프트에 청크를 넣을 때 이 순서를 유지한다.
관련성 높은 청크가 먼저 올수록 LLM이 더 정확하게 참조한다.

### 5. 청크 간 구분을 명확히 한다

```
[출처: A.pdf > 보안 정책]
...내용...

[출처: B.pdf > 비밀번호 규칙]
...내용...
```

구분이 불명확하면 LLM이 청크 경계를 혼동하여 잘못된 출처를 생성한다.

---

## 토큰 한도 관리 전략

### 현재 (MVP)

문자 수 기반 근사치로 청크를 선택한다.

```python
MAX_CONTEXT_CHARS = 6000  # 한국어 약 3000~4000 토큰에 해당
```

한계를 초과하면 하위 청크(관련성 낮은 청크)를 제외한다.
잘린 청크 목록은 `BuiltPrompt.included_chunk_ids`에 기록한다.

### 향후

- 실제 토크나이저(tiktoken, sentencepiece)로 정확한 토큰 수 계산
- 시스템 프롬프트 + 컨텍스트 + 질문 + 예상 출력의 합산 관리
- 모델별 컨텍스트 윈도우 크기를 설정으로 관리

---

## 절대 하지 말아야 할 패턴

### 패턴 1: Usecase 안에 프롬프트 문자열 직접 작성

```python
# 금지
class NasRagUsecase:
    async def run(self, ...):
        prompt = f"다음 내용을 보고 {question}에 답해줘: {' '.join(c.text for c in chunks)}"
        ...
```

**문제**: 프롬프트 변경이 Usecase 코드 변경과 묶인다. 재사용 불가.

---

### 패턴 2: 시스템 프롬프트와 사용자 메시지를 하나의 문자열로 합치기

```python
# 금지
single_prompt = system_prompt + "\n\n" + context + "\n\n" + question
request = LLMRequest(messages=[{"role": "user", "content": single_prompt}])
```

**문제**: OpenAI API와 vLLM은 `system` role을 별도로 처리한다.
합치면 instruction following 품질이 저하된다.

---

### 패턴 3: 청크 내용 전체를 하나의 문자열로 concat

```python
# 금지
context = "\n".join([c.chunk_text for c in chunks])
```

**문제**: 출처 정보가 없다. LLM이 어떤 내용이 어느 문서에서 왔는지 모른다.
출처 명시가 불가능하다.

---

### 패턴 4: 프롬프트를 DB나 설정 파일에서 동적으로 로드

```python
# 금지 (PoC 단계에서)
system_prompt = db.get("nas_rag_system_prompt")
```

**문제**: PoC 단계에서 불필요한 복잡도. 프롬프트 버전 관리가 코드 버전 관리와 분리된다.
→ 코드 리뷰에서 프롬프트 변경을 검토할 수 없다.

프롬프트는 코드 안에 상수로 관리하고, git으로 버전을 추적한다.
프롬프트 관리 시스템(LangSmith, PromptLayer 등)은 Phase 3 이후 도입한다.

---

### 패턴 5: LLM 응답에서 출처를 파싱으로 추출

```python
# 금지
# LLM이 "[출처: A.pdf]" 형식으로 출처를 응답에 포함하고
# 애플리케이션이 정규식으로 파싱
sources = re.findall(r'\[출처: (.+?)\]', llm_response.text)
```

**문제**: LLM이 출처 형식을 정확히 지키지 않으면 파싱이 실패한다.
출처는 검색된 청크 목록에서 직접 추출한다. LLM에게 출처 형식 생성을 맡기지 않는다.

**올바른 방법**: LLM 응답 텍스트와 별도로, 검색된 청크 목록을 `sources`로 반환한다.

```python
# 올바른 방법
return ChatResult(
    answer=llm_response.text,           # LLM이 생성한 텍스트
    sources=extract_sources(chunks),    # 검색된 청크에서 직접 추출
)
```

---

## 향후 에이전트 추가 시 프롬프트 확장

새 에이전트를 추가할 때:

1. `app/chat/prompts/` 아래 새 파일 추가
2. 해당 에이전트의 시스템 프롬프트, 컨텍스트 포맷, `PromptBuilder` 구현
3. 새 `Usecase`에서 해당 `PromptBuilder`를 주입받아 사용

기존 `NasRagPromptBuilder`는 변경하지 않는다.

```
app/chat/prompts/
├─ nas_rag_prompt.py          # NasRagAgent용
├─ log_analysis_prompt.py     # 향후: 로그 컨텍스트 포맷이 다름
└─ standards_prompt.py        # 향후: 표준 조항 비교 포맷이 다름
```

에이전트마다 컨텍스트 포맷이 다르기 때문에 `PromptBuilder`를 공유하면 안 된다.
공통 인터페이스(`PromptBuilder ABC`)만 공유한다.
