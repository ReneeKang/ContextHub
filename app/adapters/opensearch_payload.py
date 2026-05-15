"""
OpenSearch chunk document and query **shapes** shared by indexer and chat adapters.

No HTTP client here — see ``opensearch_stub.py`` (no I/O) and ``opensearch_client.py`` (HTTP ``SearchClient``).
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

# Fields expected on every indexed chunk document (`_source` / bulk index body).
# Aligns with `docs/search-index.md` and `IndexerService._chunk_source_document`.
REQUIRED_CHUNK_INDEX_FIELDS: frozenset[str] = frozenset(
    {
        "chunk_id",
        "raw_document_id",
        "original_filename",
        "inbox_path",
        "file_ext",
        "chunk_no",
        "section_title",
        "heading_path",
        "page_no",
        "chunk_text",
        "chunk_char_count",
        "chunk_token_estimate",
        "chunk_metadata_json",
        "access_scope",
        "owner_id",
        "department_code",
        "created_at",
    }
)

_WILDCARD_ESCAPE_RE = re.compile(r"([\\*?])")


class OpenSearchChunkDocument(TypedDict, total=False):
    """Typed chunk `_source` for index / bulk API (string UUIDs for keyword fields)."""

    chunk_id: str
    raw_document_id: str
    original_filename: str
    inbox_path: str
    file_ext: str
    chunk_no: int
    section_title: str | None
    heading_path: str | None
    page_no: int | None
    chunk_text: str
    chunk_char_count: int
    chunk_token_estimate: int
    chunk_metadata_json: dict[str, Any]
    access_scope: str
    owner_id: str | None
    department_code: str | None
    created_at: str | None
    # Phase 2+ hybrid:
    # chunk_embedding: list[float]


def validate_chunk_index_document(document: dict[str, Any]) -> None:
    """Raise ValueError if payload is missing required fields (indexer contract)."""
    missing = REQUIRED_CHUNK_INDEX_FIELDS - document.keys()
    if missing:
        msg = f"chunk index document missing fields: {sorted(missing)}"
        raise ValueError(msg)


def _escape_wildcard_query(term: str) -> str:
    """Escape ``*`` and ``?`` for OpenSearch ``wildcard`` queries."""
    return _WILDCARD_ESCAPE_RE.sub(r"\\\1", term)


def build_permission_filter_clause(principal_user_id: str, department_codes: tuple[str, ...]) -> dict[str, Any]:
    """
    Build the `bool` **filter** clause (inside query.bool.filter) for access control.

    Same logic as SQL in `DbChunkSearchClient` and as JSON in `docs/search-index.md`.
    Must be combined with `must` text/vector clauses; never applied only after search hits.
    """
    should: list[dict[str, Any]] = [
        {"term": {"access_scope": "PUBLIC"}},
    ]
    if department_codes:
        should.append(
            {
                "bool": {
                    "must": [
                        {"term": {"access_scope": "DEPT"}},
                        {"terms": {"department_code": list(department_codes)}},
                    ]
                }
            }
        )
    should.append(
        {
            "bool": {
                "must": [
                    {"term": {"access_scope": "PRIVATE"}},
                    {"term": {"owner_id": principal_user_id}},
                ]
            }
        }
    )
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _cross_fields_multi_match(query: str) -> dict[str, Any]:
    """
    BM25 across nori-analyzed fields: all analyzed terms must match somewhere (AND).

    Filename and inbox path are boosted above body text so queries like ``과업대비표``
    prefer ``ID_A01_과업대비표`` over unrelated PDFs that only mention the term in body.
    """
    return {
        "multi_match": {
            "query": query,
            "fields": [
                "original_filename.nori^6.5",
                "inbox_path^6.0",
                "section_title^2.8",
                "heading_path^2.6",
                "chunk_text^1.2",
            ],
            "type": "cross_fields",
            "operator": "and",
            "tie_breaker": 0.03,
        }
    }


def _meta_match_should_clauses(query: str) -> list[dict[str, Any]]:
    """
    High-boost clauses for filename / path (keyword wildcard + phrase on analyzed fields).

    Complements ``cross_fields`` recall; especially helps Korean filename tokens and path segments.
    """
    q = (query or "").strip()
    if not q:
        return []

    ql = q.lower()
    clauses: list[dict[str, Any]] = []

    if len(ql) <= 4096:
        clauses.append({"term": {"heading_path.kw": {"value": ql, "boost": 8.0}}})

    if len(ql) <= 256:
        esc = _escape_wildcard_query(ql)
        pattern = f"*{esc}*"
        clauses.append(
            {
                "wildcard": {
                    "original_filename": {
                        "value": pattern,
                        "boost": 28.0,
                        "case_insensitive": True,
                    }
                }
            }
        )
        clauses.append(
            {
                "wildcard": {
                    "inbox_path.kw": {
                        "value": pattern,
                        "boost": 24.0,
                        "case_insensitive": True,
                    }
                }
            }
        )

    clauses.append(
        {
            "match_phrase": {
                "original_filename.nori": {
                    "query": q,
                    "boost": 22.0,
                    "slop": 0,
                }
            }
        }
    )
    clauses.append(
        {
            "match_phrase": {
                "inbox_path": {
                    "query": q,
                    "boost": 20.0,
                    "slop": 1,
                }
            }
        }
    )
    clauses.append(
        {
            "match_phrase": {
                "section_title": {
                    "query": q,
                    "boost": 6.0,
                    "slop": 1,
                }
            }
        }
    )
    return clauses


def build_keyword_search_body(
    *,
    query: str,
    top_k: int,
    principal_user_id: str,
    department_codes: tuple[str, ...],
    include_highlight: bool = True,
) -> dict[str, Any]:
    """
    Keyword search body: BM25 with filename/path-heavy ``should`` clauses, permission **filter**,
    optional ``highlight``.

    At least one ``should`` clause must match (``minimum_should_match: 1``): cross-field AND recall
    or a strong filename/path wildcard/phrase hit.
    """
    perm = build_permission_filter_clause(principal_user_id, department_codes)
    q = (query or "").strip()

    if not q:
        root_bool: dict[str, Any] = {
            "filter": [perm],
            "must_not": [{"match_all": {}}],
        }
    else:
        should_clauses: list[dict[str, Any]] = [_cross_fields_multi_match(q)]
        should_clauses.extend(_meta_match_should_clauses(q))
        root_bool = {
            "filter": [perm],
            "should": should_clauses,
            "minimum_should_match": 1,
        }

    body: dict[str, Any] = {
        "size": top_k,
        "track_total_hits": False,
        "query": {"bool": root_bool},
        "_source": [
            "chunk_id",
            "raw_document_id",
            "original_filename",
            "inbox_path",
            "section_title",
            "heading_path",
            "page_no",
            "chunk_text",
            "chunk_char_count",
            "chunk_token_estimate",
            "access_scope",
            "chunk_no",
        ],
    }

    if include_highlight and q:
        body["highlight"] = {
            "require_field_match": False,
            "number_of_fragments": 3,
            "fragment_size": 180,
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {
                "chunk_text": {},
                "section_title": {"number_of_fragments": 1, "fragment_size": 256},
                "heading_path": {"number_of_fragments": 1, "fragment_size": 512},
                "inbox_path": {"number_of_fragments": 1, "fragment_size": 512},
                "original_filename.nori": {"number_of_fragments": 1, "fragment_size": 256},
            },
        }
    return body


def build_delete_by_raw_document_query(raw_document_id: str) -> dict[str, Any]:
    """DELETE BY QUERY body for admin exclude / reindex cleanup."""
    return {"query": {"term": {"raw_document_id": raw_document_id}}}
