"""OpenSearch keyword query shape for filename/path-heavy discover search."""

from __future__ import annotations

import json

import pytest

from app.adapters.opensearch_payload import (
    build_keyword_search_body,
    validate_chunk_index_document,
)


def _minimal_chunk_doc() -> dict:
    return {
        "chunk_id": "c1",
        "raw_document_id": "d1",
        "original_filename": "ID_A01_과업대비표.xlsx",
        "inbox_path": "public/projects/sanrim-platform/02_분석/ID_A01_과업대비표",
        "file_ext": "xlsx",
        "chunk_no": 1,
        "section_title": "개요",
        "heading_path": "개요",
        "page_no": 1,
        "chunk_text": "본문",
        "chunk_char_count": 2,
        "chunk_token_estimate": 1,
        "chunk_metadata_json": {},
        "access_scope": "PUBLIC",
        "owner_id": None,
        "department_code": None,
        "created_at": "2026-05-11T10:00:00Z",
    }


def test_chunk_index_requires_inbox_path() -> None:
    doc = _minimal_chunk_doc()
    validate_chunk_index_document(doc)
    missing = dict(doc)
    del missing["inbox_path"]
    with pytest.raises(ValueError, match="inbox_path"):
        validate_chunk_index_document(missing)


def test_discover_query_boosts_filename_over_body() -> None:
    body = build_keyword_search_body(
        query="과업대비표",
        top_k=30,
        principal_user_id="u1",
        department_codes=(),
    )
    should = body["query"]["bool"]["should"]
    mm = next(c for c in should if "multi_match" in c)
    fields = mm["multi_match"]["fields"]
    filename_boost = next(f for f in fields if f.startswith("original_filename.nori"))
    body_boost = next(f for f in fields if f.startswith("chunk_text"))
    assert float(filename_boost.split("^", 1)[1]) > float(body_boost.split("^", 1)[1])


def test_discover_query_includes_filename_path_wildcard_and_phrase() -> None:
    body = build_keyword_search_body(
        query="과업대비표",
        top_k=10,
        principal_user_id="u1",
        department_codes=("infra",),
    )
    blob = json.dumps(body, ensure_ascii=False)
    assert "original_filename" in blob
    assert "inbox_path" in blob
    assert "match_phrase" in blob
    assert "*과업대비표*" in blob or "\\*과업대비표\\*" in blob

    should = body["query"]["bool"]["should"]
    wildcards = [
        c
        for c in should
        if "wildcard" in c
        and ("original_filename" in c["wildcard"] or "inbox_path.kw" in c["wildcard"])
    ]
    assert len(wildcards) >= 2

    phrases = [c for c in should if "match_phrase" in c]
    phrase_fields = set()
    for p in phrases:
        phrase_fields.update(p["match_phrase"].keys())
    assert "original_filename.nori" in phrase_fields
    assert "inbox_path" in phrase_fields


def test_discover_query_highlight_includes_path_and_filename() -> None:
    body = build_keyword_search_body(
        query="과업대비표",
        top_k=5,
        principal_user_id="u1",
        department_codes=(),
        include_highlight=True,
    )
    hl_fields = body["highlight"]["fields"]
    assert "original_filename.nori" in hl_fields
    assert "inbox_path" in hl_fields
