"""NFC normalization for Korean metadata / search (macOS NFD filenames vs NFC queries)."""

from __future__ import annotations

import unicodedata
from unittest.mock import MagicMock

from app.chat.retrieval_query import normalize_retrieval_query_pair
from app.indexer.service import _chunk_source_document
from app.unicode_normalize import normalize_nfc


def test_normalize_nfc_hangul_nfd_to_nfc() -> None:
    nfc = "과업대비표"
    nfd = unicodedata.normalize("NFD", nfc)
    assert normalize_nfc(nfd) == nfc


def test_nfc_filename_matches_nfc_search_term() -> None:
    """Simulate DB/OpenSearch alignment: stored NFC name contains NFC query from user."""
    nfd_stored = unicodedata.normalize("NFD", "ID_A01_과업대비표.xlsx")
    stored_as_if_scanner = normalize_nfc(nfd_stored)
    user_query = "과업대비표"
    assert user_query in stored_as_if_scanner


def test_retrieval_query_pair_nfc_after_stopword_strip() -> None:
    """NFD 입력은 검색용 문자열을 NFC로 맞춘 뒤 불용어 제거한다."""
    q_nfd = unicodedata.normalize("NFD", "과업대비표 알려줘")
    final, applied = normalize_retrieval_query_pair(q_nfd)
    assert final == "과업대비표"
    assert applied is True


def test_chunk_index_payload_normalizes_fields() -> None:
    raw = MagicMock()
    raw.original_filename = unicodedata.normalize("NFD", "과업대비표.xlsx")
    raw.inbox_path = unicodedata.normalize("NFD", r"public\docs\과업.xlsx")
    raw.file_ext = "xlsx"

    chunk = MagicMock()
    chunk.chunk_id = MagicMock()
    chunk.raw_document_id = MagicMock()
    chunk.chunk_no = 1
    chunk.section_title = unicodedata.normalize("NFD", "표 제목")
    chunk.heading_path = unicodedata.normalize("NFD", "1장/개요")
    chunk.page_no = None
    chunk.chunk_text = unicodedata.normalize("NFD", "본문내용")
    chunk.chunk_char_count = 4
    chunk.chunk_token_estimate = 1
    chunk.chunk_metadata_json = {}
    chunk.access_scope = MagicMock()
    chunk.access_scope.value = "PUBLIC"
    chunk.owner_id = None
    chunk.department_code = None
    chunk.created_at = None

    doc = _chunk_source_document(chunk, raw)
    assert doc["original_filename"] == normalize_nfc(raw.original_filename)
    assert doc["inbox_path"] == normalize_nfc(raw.inbox_path.replace("\\", "/"))
    assert doc["section_title"] == normalize_nfc(chunk.section_title)
    assert doc["heading_path"] == normalize_nfc(chunk.heading_path)
    assert doc["chunk_text"] == normalize_nfc(chunk.chunk_text)
    assert doc["chunk_char_count"] == len(doc["chunk_text"])


def test_opensearch_body_query_is_nfc() -> None:
    from app.adapters.opensearch_payload import build_keyword_search_body

    nfd_q = unicodedata.normalize("NFD", "과업대비표")
    body = build_keyword_search_body(
        query=nfd_q,
        top_k=5,
        principal_user_id="u",
        department_codes=(),
        include_highlight=False,
    )
    inner = body["query"]["bool"]["should"][0]["multi_match"]["query"]
    assert inner == unicodedata.normalize("NFC", "과업대비표")


def test_db_chunk_search_normalizes_query_before_tokenize() -> None:
    """ILIKE tokens use NFC so Mac NFD DB rows match after scanner/indexer healing."""
    from app.adapters.db_chunk_search import _tokenize_question

    q_nfd = unicodedata.normalize("NFD", "과업대비표")
    terms = _tokenize_question(normalize_nfc(q_nfd.strip()))
    assert terms == ["과업대비표"]


def test_markdown_chunk_piece_fields_are_nfc() -> None:
    from app.chunker.markdown_chunk import build_chunks_from_markdown

    nfd_heading = unicodedata.normalize("NFD", "과업개요")
    md = f"# {nfd_heading}\n\n본문입니다."
    nfd_fn = unicodedata.normalize("NFD", "과업대비표.xlsx")
    pieces = build_chunks_from_markdown(md, fallback_filename=nfd_fn)
    assert len(pieces) >= 1
    p0 = pieces[0]
    assert p0.section_title == unicodedata.normalize("NFC", nfd_heading)
    assert p0.heading_path == unicodedata.normalize("NFC", nfd_heading)
    assert p0.text == unicodedata.normalize("NFC", "본문입니다.")
