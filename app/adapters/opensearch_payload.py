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


def build_keyword_search_body(
    *,
    query: str,
    top_k: int,
    principal_user_id: str,
    department_codes: tuple[str, ...],
) -> dict[str, Any]:
    """
    Example OpenSearch request body for chat-style keyword search (BM25 + nori on index mapping).

    Hybrid Phase: add a `should` knn/rescore block; keep this filter as sibling under bool.filter.
    """
    perm = build_permission_filter_clause(principal_user_id, department_codes)
    return {
        "size": top_k,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "chunk_text^2",
                                "section_title^2.5",
                                "heading_path^1.5",
                            ],
                            "type": "best_fields",
                        }
                    }
                ],
                "filter": [perm],
            }
        },
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


def build_delete_by_raw_document_query(raw_document_id: str) -> dict[str, Any]:
    """DELETE BY QUERY body for admin exclude / reindex cleanup."""
    return {"query": {"term": {"raw_document_id": raw_document_id}}}
