"""Discover groups by document; filename-strong hits should rank above body-only hits."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat.discovery_service import run_discover
from app.chat.schemas import DiscoverRequest
from app.config.settings import Settings


def _hit(
    *,
    raw_document_id: uuid.UUID,
    original_filename: str,
    score: float,
    highlights: dict[str, list[str]] | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        raw_document_id=raw_document_id,
        original_filename=original_filename,
        chunk_no=1,
        section_title="Sec",
        page_no=None,
        chunk_text="body",
        access_scope="PUBLIC",
        score=score,
        highlights=highlights,
    )


class _FixedSearch(SearchClient):
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    def search(self, *, query: str, top_k: int, principal: PermissionPrincipal, index_name: str) -> list[SearchHit]:
        _ = query, top_k, principal, index_name
        return list(self._hits)

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError


def _doc_row(rid: uuid.UUID, *, original_filename: str, inbox_path: str) -> MagicMock:
    _ = rid
    row = MagicMock()
    row.original_filename = original_filename
    row.inbox_path = inbox_path
    row.stored_path = inbox_path
    row.access_scope = MagicMock(value="PUBLIC")
    return row


def test_discover_prefers_gwabe_daebi_filename_document_over_body_only_pdf() -> None:
    """Simulates search backend returning a higher score for the 과업대비표 filename doc."""
    rid_a01 = uuid.uuid4()
    rid_p05 = uuid.uuid4()
    path_a01 = "public/projects/sanrim-platform/02_분석/ID_A01_과업대비표"
    search = _FixedSearch(
        [
            _hit(
                raw_document_id=rid_p05,
                original_filename="ID_P05_산림공간디지털플랫폼구축.pdf",
                score=12.0,
                highlights={"chunk_text": ["<em>과업대비표</em> 언급"]},
            ),
            _hit(
                raw_document_id=rid_a01,
                original_filename="ID_A01_과업대비표.xlsx",
                score=48.0,
                highlights={
                    "original_filename.nori": ["<em>ID_A01_과업대비표</em>.xlsx"],
                    "inbox_path": [f"<em>{path_a01}</em>"],
                },
            ),
            _hit(
                raw_document_id=rid_a01,
                original_filename="ID_A01_과업대비표.xlsx",
                score=35.0,
            ),
        ]
    )
    meta = {
        rid_a01: _doc_row(
            rid_a01,
            original_filename="ID_A01_과업대비표.xlsx",
            inbox_path=path_a01,
        ),
        rid_p05: _doc_row(
            rid_p05,
            original_filename="ID_P05_산림공간디지털플랫폼구축.pdf",
            inbox_path="public/projects/sanrim-platform/ID_P05_산림공간디지털플랫폼구축.pdf",
        ),
    }
    settings = Settings()
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(
            MagicMock(),
            settings,
            search,
            PermissionPrincipal("u", ("infra",)),
            DiscoverRequest(question="과업대비표", top_k=30),
        )

    assert out.document_count == 2
    assert out.documents[0].raw_document_id == rid_a01
    assert "과업대비표" in out.documents[0].original_filename
    assert out.documents[0].top_score == 48.0
    mc = out.documents[0].matched_chunks[0]
    assert mc.highlights is not None
    assert "original_filename.nori" in mc.highlights or "inbox_path" in mc.highlights
