"""
Retrieval-only query normalization (MVP).

``SearchClient.search(..., query=...)`` receives the string from :func:`normalize_retrieval_query`
(or the first element of :func:`normalize_retrieval_query_pair`).
The user's original ``question`` string is unchanged for LLM prompts and UI stubs.
"""

from __future__ import annotations

import re
from typing import Final


def _strip_embedded_question_phrases(text: str) -> str:
    """
    Remove Korean question-style glue phrases that are often written **without** a space
    before the topic (e.g. ``쿠베플로우에 대해 설명해줘`` → tokens would not split ``에 대해``).
    """
    t = text.strip()
    for phrase in ("에 대해서", "에 대해"):
        t = t.replace(phrase, " ")
    return re.sub(r"\s+", " ", t).strip()


# Strip from the right, longest phrase first (repeat until stable).
_RETRIEVAL_SUFFIXES: Final[tuple[str, ...]] = (
    "설명해 주세요",
    "설명해주세요",
    "설명해줘",
    "요약해주세요",
    "요약해줘",
    "정리해주세요",
    "정리해줘",
    "알려주세요",
    "알려줘",
    "무엇인가요",
    "무엇일까요",
    "뭔가요",
    "어떻게 하나요",
    "어떻게해요",
    "어떻게 해",
    "해줘요",
    "해줘",
    "설명",
    "요약해",
    "정리해",
)

# Remove as whole whitespace-delimited tokens after suffix pass.
_TOKEN_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "대해",
        "대해서",
        "설명",
        "알려줘",
        "알려주세요",
        "요약",
        "요약해",
        "요약해줘",
        "요약해주세요",
        "정리",
        "정리해",
        "정리해줘",
        "정리해주세요",
        "무엇인가요",
        "무엇일까요",
        "뭐야",
        "뭔가요",
        "해줘",
        "해주세요",
        "해",
        "하나요",
        "어떻게",
    }
)


def normalize_retrieval_query_pair(question: str) -> tuple[str, bool]:
    """
    Return ``(retrieval_query, normalization_applied)``.

    ``normalization_applied`` is ``True`` iff the string passed to ``SearchClient.search``
    differs from ``question.strip()`` (including token drops / suffix trims).
    """
    original = question.strip()
    if not original:
        return original, False

    q = _strip_embedded_question_phrases(original)
    changed = True
    while changed:
        changed = False
        tail = q.rstrip()
        for suf in sorted(_RETRIEVAL_SUFFIXES, key=len, reverse=True):
            if tail.endswith(suf):
                q = tail[: -len(suf)].rstrip()
                changed = True
                break

    parts = [t for t in re.split(r"\s+", q.strip()) if t]
    filtered = [t for t in parts if t not in _TOKEN_STOPWORDS]
    out = " ".join(filtered).strip()

    final = out if out else original
    applied = final != original
    return final, applied


def normalize_retrieval_query(question: str) -> str:
    """
    Light keyword cleanup for retrieval backends (DB token AND, OpenSearch keyword).

    * Removes common Korean request / filler tokens so e.g. ``… 오픈 설명`` still matches chunks
      that contain ``… 오픈`` without the literal ``설명`` tail.
    * Strips embedded ``에 대해`` / ``에 대해서`` (often glued to the topic without a space) before
      suffix and token passes, e.g. ``쿠베플로우에 대해 설명해줘`` → ``쿠베플로우``.
    * If stripping yields an empty string, returns ``question.strip()`` unchanged.
    """
    text, _ = normalize_retrieval_query_pair(question)
    return text


def format_query_log_snippet(text: str, max_len: int = 400) -> str:
    """Truncate for structured logs (no chunk bodies)."""
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"
