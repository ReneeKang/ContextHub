"""Generation context chunk previews in retrieval debug."""

from __future__ import annotations

import uuid

from app.adapters.search_protocol import SearchHit
from app.chat.retrieval_debug import (
    GENERATION_CONTEXT_PREVIEW_MAX_CHARS,
    build_generation_context_chunks,
    chunk_text_preview,
)


def test_chunk_text_preview_truncates_at_300() -> None:
    body = "A" * 400
    out = chunk_text_preview(body)
    assert len(out) == GENERATION_CONTEXT_PREVIEW_MAX_CHARS + 1
    assert out.endswith("…")
    assert out.startswith("A" * GENERATION_CONTEXT_PREVIEW_MAX_CHARS)


def test_build_generation_context_chunks_fields() -> None:
    cid = uuid.uuid4()
    rid = uuid.uuid4()
    hit = SearchHit(
        chunk_id=cid,
        raw_document_id=rid,
        original_filename="ID_A01.xlsx",
        chunk_no=3,
        section_title="3. 과업대비표",
        page_no=None,
        chunk_text="| header row only |",
        access_scope="PUBLIC",
        score=122.5,
        highlights=None,
    )
    rows = build_generation_context_chunks([hit])
    assert len(rows) == 1
    row = rows[0]
    assert row.chunk_id == cid
    assert row.included_in_prompt is True
    assert row.char_count == len("| header row only |")
    assert row.text_preview == "| header row only |"
