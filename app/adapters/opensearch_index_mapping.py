"""
OpenSearch index **settings + mappings** for chunk documents (keyword search, no vectors).

The default Docker image does **not** ship the `analysis-nori` plugin; text fields use a small
`standard` + `lowercase` custom analyzer until nori is installed (see `docs/search-index.md`).
"""

from __future__ import annotations

from typing import Any


def chunk_index_create_body() -> dict[str, Any]:
    """
    Body for ``indices.create(index=..., body=...)`` — single-node dev defaults.

    ``source_page`` is an alias to ``page_no`` for query/_source symmetry with product language.
    """
    return {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "1s",
            },
            "analysis": {
                "analyzer": {
                    "chunk_text_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "raw_document_id": {"type": "keyword"},
                "original_filename": {"type": "keyword"},
                "file_ext": {"type": "keyword"},
                "chunk_no": {"type": "integer"},
                "section_title": {
                    "type": "text",
                    "analyzer": "chunk_text_analyzer",
                },
                "heading_path": {
                    "type": "text",
                    "analyzer": "chunk_text_analyzer",
                },
                "page_no": {"type": "integer"},
                "source_page": {"type": "alias", "path": "page_no"},
                "chunk_char_count": {"type": "integer"},
                "chunk_token_estimate": {"type": "integer"},
                "chunk_metadata_json": {"type": "object", "enabled": True},
                "chunk_text": {
                    "type": "text",
                    "analyzer": "chunk_text_analyzer",
                },
                "access_scope": {"type": "keyword"},
                "owner_id": {"type": "keyword"},
                "department_code": {"type": "keyword"},
                "created_at": {"type": "date", "ignore_malformed": True},
            }
        },
    }
