"""
OpenSearch chunk document and query **shapes** shared by indexer and chat adapters.

No HTTP client here — see ``opensearch_stub.py`` (no I/O) and ``opensearch_client.py`` (HTTP ``SearchClient``).
"""

from __future__ import annotations

from typing import Any, TypedDict


# Fields expected on every indexed chunk document (`_source` / bulk index body).
# Aligns with `docs/search-index.md` and `IndexerService._chunk_source_document`.
REQUIRED_CHUNK_INDEX_FIELDS: frozenset[str] = frozenset(
    {
        "chunk_id",
        "raw_document_id",
        "original_filename",
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


class OpenSearchChunkDocument(TypedDict, total=False):
    """Typed chunk `_source` for index / bulk API (string UUIDs for keyword fields)."""

    chunk_id: str
    raw_document_id: str
    original_filename: str
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
    BM25 across shared nori-analyzed fields: all analyzed terms must match somewhere (AND).

    ``heading_path.kw`` is excluded here (keyword); boosted separately via ``term`` when the
    normalized query equals the stored breadcrumb.
    """
    return {
        "multi_match": {
            "query": query,
            "fields": [
                "chunk_text^3.2",
                "section_title^2.9",
                "heading_path^2.7",
                "original_filename.nori^3.0",
            ],
            "type": "cross_fields",
            "operator": "and",
            "tie_breaker": 0.03,
        }
    }


def build_keyword_search_body(
    *,
    query: str,
    top_k: int,
    principal_user_id: str,
    department_codes: tuple[str, ...],
    include_highlight: bool = True,
) -> dict[str, Any]:
    """
    Keyword search body: BM25 ``cross_fields`` + AND operator, permission **filter** context,
    optional ``highlight``, optional exact ``heading_path.kw`` boost (normalized lowercase).

    Hybrid / vector: add ``should`` knn or ``rescore`` in a later phase; keep ``filter`` unchanged.
    """
    perm = build_permission_filter_clause(principal_user_id, department_codes)
    q = (query or "").strip()

    if not q:
        # Caller should usually short-circuit; this keeps the bool shape valid (no hits).
        root_bool: dict[str, Any] = {
            "filter": [perm],
            "must_not": [{"match_all": {}}],
        }
    else:
        should_clauses: list[dict[str, Any]] = []
        if len(q) <= 4096:
            should_clauses.append(
                {"term": {"heading_path.kw": {"value": q.lower(), "boost": 10.0}}},
            )
        root_bool = {
            "must": [_cross_fields_multi_match(q)],
            "filter": [perm],
            "minimum_should_match": 0,
        }
        if should_clauses:
            root_bool["should"] = should_clauses

    body: dict[str, Any] = {
        "size": top_k,
        "track_total_hits": False,
        "query": {"bool": root_bool},
        "_source": [
            "chunk_id",
            "raw_document_id",
            "original_filename",
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
                "original_filename.nori": {"number_of_fragments": 1, "fragment_size": 256},
            },
        }
    return body


def build_delete_by_raw_document_query(raw_document_id: str) -> dict[str, Any]:
    """DELETE BY QUERY body for admin exclude / reindex cleanup."""
    return {"query": {"term": {"raw_document_id": raw_document_id}}}
