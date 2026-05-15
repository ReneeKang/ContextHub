"""Retrieval ranking explanation: highlight-derived fields and safe logs (no chunk bodies)."""

from __future__ import annotations

import json
import uuid

from app.adapters.search_protocol import SearchHit
from app.chat.retrieval_debug import (
    build_retrieval_debug_for_response,
    build_retrieval_debug_log_record,
    highlight_terms_from_highlights,
    matched_fields_from_highlights,
    rank_hits_for_retrieval_debug,
)


def test_matched_fields_sorted_keys() -> None:
    raw = {"section_title": ["x"], "chunk_text": ["y"], "original_filename.nori": ["z"]}
    assert matched_fields_from_highlights(raw) == ["chunk_text", "original_filename.nori", "section_title"]


def test_matched_fields_empty_when_no_highlights() -> None:
    assert matched_fields_from_highlights(None) == []
    assert matched_fields_from_highlights({}) == []


def test_highlight_terms_extracts_em_spans_and_splits() -> None:
    raw = {
        "chunk_text": ["앞글자 <em>산림</em> 디지털 <em>플랫폼</em> 뒤"],
        "section_title": ["<em>방화벽,포트</em>"],
    }
    terms = highlight_terms_from_highlights(raw)
    assert "산림" in terms
    assert "플랫폼" in terms
    assert "방화벽" in terms
    assert "포트" in terms
    assert terms == list(dict.fromkeys(terms))


def test_highlight_terms_empty_without_em_tags() -> None:
    assert highlight_terms_from_highlights({"chunk_text": ["plain fragment without tags"]}) == []


def test_rank_hits_document_rank_by_top_score_chunk_rank_in_order() -> None:
    d1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
    d2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
    c1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    c2 = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    c3 = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    hits = [
        SearchHit(
            chunk_id=c1,
            raw_document_id=d2,
            original_filename="b.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text="BODY_B1",
            access_scope="PUBLIC",
            score=5.0,
            highlights={"chunk_text": ["<em>z</em>"]},
        ),
        SearchHit(
            chunk_id=c2,
            raw_document_id=d1,
            original_filename="a.txt",
            chunk_no=2,
            section_title=None,
            page_no=None,
            chunk_text="BODY_A1",
            access_scope="PUBLIC",
            score=10.0,
            highlights=None,
        ),
        SearchHit(
            chunk_id=c3,
            raw_document_id=d1,
            original_filename="a.txt",
            chunk_no=3,
            section_title=None,
            page_no=None,
            chunk_text="BODY_A2",
            access_scope="PUBLIC",
            score=7.0,
            highlights={"section_title": ["<em>제목</em>"]},
        ),
    ]
    ranked = rank_hits_for_retrieval_debug(hits)
    assert ranked[0].chunk_rank == 1 and ranked[0].document_rank == 2
    assert ranked[1].chunk_rank == 2 and ranked[1].document_rank == 1
    assert ranked[2].chunk_rank == 3 and ranked[2].document_rank == 1


def test_log_record_chunk_ranking_omits_chunk_text() -> None:
    secret = "ONLY_IN_CHUNK_TEXT_FIELD_" * 20
    cid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    rid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    hits = [
        SearchHit(
            chunk_id=cid,
            raw_document_id=rid,
            original_filename="x.txt",
            chunk_no=1,
            section_title=None,
            page_no=None,
            chunk_text=secret,
            access_scope="PUBLIC",
            score=9.9,
            highlights={"chunk_text": [f"prefix <em>safe_kw</em> suffix"]},
        )
    ]
    rec = build_retrieval_debug_log_record(
        original_query="q",
        retrieval_query="q",
        normalization_applied=False,
        retrieval_backend="opensearch",
        top_k=5,
        hits=hits,
        retrieval_latency_ms=12,
    )
    dumped = json.dumps(rec, ensure_ascii=False)
    assert secret not in dumped
    assert "chunk_ranking" in rec
    cr0 = rec["chunk_ranking"][0]
    assert cr0["chunk_id"] == str(cid)
    assert cr0["score"] == 9.9
    assert cr0["matched_fields"] == ["chunk_text"]
    assert cr0["highlight_terms"] == ["safe_kw"]
    assert cr0["document_rank"] == 1
    assert cr0["chunk_rank"] == 1
    assert "highlights" not in cr0


def test_debug_response_chunks_include_ranking_fields() -> None:
    cid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    rid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    hits = [
        SearchHit(
            chunk_id=cid,
            raw_document_id=rid,
            original_filename="x.txt",
            chunk_no=1,
            section_title="섹션",
            page_no=2,
            chunk_text="NEVER_SERIALIZE_THIS_BODY",
            access_scope="PUBLIC",
            score=3.0,
            highlights={"original_filename.nori": ["<em>보고</em>서.hwp"]},
        )
    ]
    info = build_retrieval_debug_for_response(
        original_query="orig",
        retrieval_query="ret",
        normalization_applied=True,
        retrieval_backend="opensearch",
        top_k=5,
        hits=hits,
        retrieval_latency_ms=1,
    )
    d = info.model_dump(mode="json")
    blob = json.dumps(d, ensure_ascii=False)
    assert "NEVER_SERIALIZE_THIS_BODY" not in blob
    ch0 = d["chunks"][0]
    assert ch0["chunk_rank"] == 1
    assert ch0["document_rank"] == 1
    assert ch0["matched_fields"] == ["original_filename.nori"]
    assert "보고" in ch0["highlight_terms"] or "서" in ch0["highlight_terms"]
