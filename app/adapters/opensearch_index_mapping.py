"""
OpenSearch index **settings + mappings** for chunk documents (BM25 keyword search; no vectors).

Requires the **analysis-nori** plugin (see ``docker/opensearch/Dockerfile`` and ``docker-compose.yml``).

* **Korean text**: `nori_analyzer` (``nori_tokenizer`` + ``nori_part_of_speech`` + ``lowercase`` for mixed EN).
* **Exact-ish paths / filenames**: ``heading_path.kw`` and ``original_filename`` (keyword) + ``filename_lowercase`` normalizer.
* **Searchable filename**: ``original_filename.nori`` multifield for tokenized queries.
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
                    "nori_analyzer": {
                        "type": "custom",
                        "tokenizer": "nori_tokenizer",
                        "filter": ["lowercase", "nori_part_of_speech"],
                    },
                },
                "normalizer": {
                    "filename_lowercase": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                },
            },
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "raw_document_id": {"type": "keyword"},
                "original_filename": {
                    "type": "keyword",
                    "ignore_above": 512,
                    "normalizer": "filename_lowercase",
                    "fields": {
                        "nori": {
                            "type": "text",
                            "analyzer": "nori_analyzer",
                        }
                    },
                },
                "inbox_path": {
                    "type": "text",
                    "analyzer": "nori_analyzer",
                    "fields": {
                        "kw": {
                            "type": "keyword",
                            "ignore_above": 4096,
                            "normalizer": "filename_lowercase",
                        }
                    },
                },
                "file_ext": {"type": "keyword"},
                "chunk_no": {"type": "integer"},
                "section_title": {
                    "type": "text",
                    "analyzer": "nori_analyzer",
                },
                "heading_path": {
                    "type": "text",
                    "analyzer": "nori_analyzer",
                    "fields": {
                        "kw": {
                            "type": "keyword",
                            "ignore_above": 4096,
                            "normalizer": "filename_lowercase",
                        }
                    },
                },
                "page_no": {"type": "integer"},
                "source_page": {"type": "alias", "path": "page_no"},
                "chunk_char_count": {"type": "integer"},
                "chunk_token_estimate": {"type": "integer"},
                "chunk_metadata_json": {"type": "object", "enabled": True},
                "chunk_text": {
                    "type": "text",
                    "analyzer": "nori_analyzer",
                },
                "access_scope": {"type": "keyword"},
                "owner_id": {"type": "keyword"},
                "department_code": {"type": "keyword"},
                "created_at": {"type": "date", "ignore_malformed": True},
            }
        },
    }
