"""Document discovery: group SearchHit by raw_document_id (MVP)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.chat import deps as chat_deps
from app.chat.discovery_service import infer_project_key, run_discover
from app.chat.schemas import DiscoverRequest
from app.config.settings import Settings
from app.main import app


def test_infer_project_key_sanrim_slug() -> None:
    assert infer_project_key(r"C:\inbox\projects\sanrim-platform\doc.pdf") == "sanrim-platform"
    assert infer_project_key("/mnt/nas/projects/sanrim-platform/a/b.txt") == "sanrim-platform"
    assert infer_project_key("/no/project/here.txt") is None


def _hit(
    *,
    chunk_id: uuid.UUID | None = None,
    raw_document_id: uuid.UUID | None = None,
    chunk_no: int = 1,
    section_title: str | None = "Sec",
    score: float = 1.0,
    highlights: dict[str, list[str]] | None = None,
) -> SearchHit:
    cid = chunk_id or uuid.uuid4()
    rid = raw_document_id or uuid.uuid4()
    return SearchHit(
        chunk_id=cid,
        raw_document_id=rid,
        original_filename="f.txt",
        chunk_no=chunk_no,
        section_title=section_title,
        page_no=None,
        chunk_text="SECRET_CHUNK_BODY_DO_NOT_LEAK",
        access_scope="PUBLIC",
        score=score,
        highlights=highlights,
    )


class _FixedSearch(SearchClient):
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        self.last_query = query
        self.last_top_k = top_k
        _ = principal, index_name
        return list(self._hits)

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError


def _fake_db() -> Generator[MagicMock, None, None]:
    yield MagicMock()


def _settings() -> Settings:
    return Settings(
        llm_mock_mode=True,
        search_backend="db",
        enable_retrieval_debug=False,
        database_url="postgresql+psycopg://x@127.0.0.1:5433/x",
    )


def _doc_row(rid: uuid.UUID, inbox_path: str, stored_path: str = "/stored/x") -> SimpleNamespace:
    return SimpleNamespace(raw_document_id=rid, inbox_path=inbox_path, stored_path=stored_path)


@pytest.fixture
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_run_discover_groups_same_raw_document_id() -> None:
    rid = uuid.uuid4()
    h1 = _hit(raw_document_id=rid, chunk_no=1, score=10.0, section_title="A")
    h2 = _hit(raw_document_id=rid, chunk_no=2, score=5.0, section_title="B")
    search = _FixedSearch([h1, h2])
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    assert out.document_count == 1
    assert out.documents[0].matched_chunk_count == 2
    assert out.documents[0].top_score == 10.0


def test_run_discover_top_score_is_max() -> None:
    rid = uuid.uuid4()
    search = _FixedSearch(
        [
            _hit(raw_document_id=rid, chunk_no=1, score=3.0),
            _hit(raw_document_id=rid, chunk_no=2, score=18.8),
            _hit(raw_document_id=rid, chunk_no=3, score=7.0),
        ]
    )
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    assert out.documents[0].top_score == 18.8


def test_representative_sections_deduped_max_three() -> None:
    rid = uuid.uuid4()
    hits = [
        _hit(raw_document_id=rid, chunk_no=i, score=float(10 - i), section_title="Same")
        for i in range(1, 6)
    ]
    hits.append(_hit(raw_document_id=rid, chunk_no=10, score=1.0, section_title="Other"))
    hits.append(_hit(raw_document_id=rid, chunk_no=11, score=0.5, section_title="Third"))
    search = _FixedSearch(hits)
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    secs = out.documents[0].representative_sections
    assert secs == ["Same", "Other", "Third"]


def test_chunk_fetch_size_scales_with_document_top_k() -> None:
    from app.chat.discovery_service import chunk_fetch_size

    assert chunk_fetch_size(10) == 100
    assert chunk_fetch_size(3) == 50
    assert chunk_fetch_size(6) == 60


class _TopKSliceSearch(SearchClient):
    """Simulates backends that return only the top-N chunk hits by score."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._sorted = sorted(hits, key=lambda h: h.score, reverse=True)
        self.last_top_k: int | None = None

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        self.last_top_k = top_k
        _ = query, principal, index_name
        return self._sorted[:top_k]

    def index_chunk_document(self, **kwargs: object) -> None:
        raise AssertionError

    def delete_chunks_for_document(self, **kwargs: object) -> None:
        raise AssertionError


def test_discover_returns_multiple_documents_when_one_doc_dominates_chunk_ranks() -> None:
    """With top_k=10 documents, chunk fetch must be large enough to surface other docs."""
    rid_dom = uuid.uuid4()
    rid_b = uuid.uuid4()
    rid_c = uuid.uuid4()
    hits: list[SearchHit] = []
    for i in range(30):
        hits.append(
            _hit(
                raw_document_id=rid_dom,
                chunk_no=i + 1,
                score=100.0 - i * 0.1,
                section_title=f"dom-{i}",
            )
        )
    hits.append(
        _hit(
            raw_document_id=rid_b,
            chunk_no=1,
            score=5.0,
            section_title="doc-b",
            highlights={"section_title": ["과업대비표"]},
        )
    )
    hits.append(
        _hit(
            raw_document_id=rid_c,
            chunk_no=1,
            score=4.0,
            section_title="doc-c",
            highlights={"heading_path": ["과업대비표"]},
        )
    )

    search = _TopKSliceSearch(hits)
    meta = {
        rid_dom: _doc_row(rid_dom, "public/v09.pdf"),
        rid_b: _doc_row(rid_b, "public/ID_A01_과업대비표.xlsx"),
        rid_c: _doc_row(rid_c, "public/ID_B02_과업대비표.xlsx"),
    }
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(
            MagicMock(),
            _settings(),
            search,
            PermissionPrincipal("u", ()),
            DiscoverRequest(question="과업대비표", top_k=10),
        )

    assert search.last_top_k == 100
    assert out.document_count >= 3
    returned = {d.raw_document_id for d in out.documents}
    assert rid_b in returned
    assert rid_c in returned
    dom = next(d for d in out.documents if d.raw_document_id == rid_dom)
    assert dom.matched_chunk_count == 30
    assert len(dom.matched_chunks) == 5


def test_discover_drops_low_score_no_highlight_irrelevant_document() -> None:
    """과업대비표: strong hits with highlights stay; weak tailing PDF without highlight is dropped."""
    rid_a01_1 = uuid.uuid4()
    rid_a01_2 = uuid.uuid4()
    rid_a01_3 = uuid.uuid4()
    rid_p05 = uuid.uuid4()
    hl = {"section_title": ["<em>과업대비표</em>"]}
    hits = [
        _hit(raw_document_id=rid_a01_1, chunk_no=1, score=122.0, highlights=hl),
        _hit(raw_document_id=rid_a01_2, chunk_no=1, score=118.0, highlights=hl),
        _hit(raw_document_id=rid_a01_3, chunk_no=1, score=117.0, highlights=hl),
        _hit(
            raw_document_id=rid_p05,
            chunk_no=1,
            score=1.033,
            section_title="무관",
            highlights=None,
        ),
    ]
    search = _FixedSearch(hits)
    meta = {
        rid_a01_1: _doc_row(rid_a01_1, "public/ID_A01_과업대비표_1.xlsx"),
        rid_a01_2: _doc_row(rid_a01_2, "public/ID_A01_과업대비표_2.xlsx"),
        rid_a01_3: _doc_row(rid_a01_3, "public/ID_A01_과업대비표_3.xlsx"),
        rid_p05: _doc_row(rid_p05, "public/ID_P05_테일러링내역서.pdf"),
    }
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(
            MagicMock(),
            _settings(),
            search,
            PermissionPrincipal("u", ()),
            DiscoverRequest(question="과업대비표", top_k=10),
        )

    assert out.document_count == 3
    returned = {d.raw_document_id for d in out.documents}
    assert rid_p05 not in returned
    assert {rid_a01_1, rid_a01_2, rid_a01_3} == returned
    scores = sorted((d.top_score for d in out.documents), reverse=True)
    assert scores == [122.0, 118.0, 117.0]


def test_discover_caps_document_count_at_top_k() -> None:
    hits = [_hit(raw_document_id=uuid.uuid4(), chunk_no=1, score=float(10 - i)) for i in range(15)]
    search = _TopKSliceSearch(hits)
    meta = {h.raw_document_id: _doc_row(h.raw_document_id, f"/p/{i}.txt") for i, h in enumerate(hits)}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(
            MagicMock(),
            _settings(),
            search,
            PermissionPrincipal("u", ()),
            DiscoverRequest(question="q", top_k=10),
        )
    assert out.document_count == 10
    assert search.last_top_k == 100


def test_matched_chunks_capped_and_sorted_by_score() -> None:
    rid = uuid.uuid4()
    hits = [_hit(raw_document_id=rid, chunk_no=i, score=float(i), section_title=f"S{i}") for i in range(1, 8)]
    search = _FixedSearch(hits)
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    mc = out.documents[0].matched_chunks
    assert len(mc) == 5
    scores = [m.score for m in mc]
    assert scores == [7.0, 6.0, 5.0, 4.0, 3.0]


def test_project_key_from_inbox_path() -> None:
    rid = uuid.uuid4()
    search = _FixedSearch([_hit(raw_document_id=rid, score=1.0)])
    inbox = "/nas/inbox/projects/sanrim-platform/out/doc.pdf"
    meta = {rid: _doc_row(rid, inbox)}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    assert out.documents[0].project_key == "sanrim-platform"
    assert "sanrim-platform" in out.documents[0].path


def test_normalization_applied_and_retrieval_query_differs() -> None:
    rid = uuid.uuid4()
    search = _FixedSearch([_hit(raw_document_id=rid, score=1.0)])
    meta = {rid: _doc_row(rid, "")}
    body = DiscoverRequest(question="방화벽 포트 오픈 설명해줘")
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), body)
    assert out.normalization_applied is True
    assert out.original_query == "방화벽 포트 오픈 설명해줘"
    assert out.retrieval_query == "방화벽 포트 오픈"
    assert search.last_query == "방화벽 포트 오픈"


def test_response_has_no_full_chunk_body_field_or_leak() -> None:
    rid = uuid.uuid4()
    search = _FixedSearch([_hit(raw_document_id=rid, score=1.0, highlights={"chunk_text": ["tiny"]})])
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    dumped = out.model_dump(mode="json")
    blob = json.dumps(dumped)
    assert "SECRET_CHUNK_BODY" not in blob
    for mc in out.documents[0].matched_chunks:
        flat = mc.model_dump(exclude_none=True, exclude={"highlights"})
        assert "chunk_text" not in flat
        assert mc.highlights is None or "chunk_text" not in mc.highlights


def test_discover_highlights_exclude_chunk_text_keep_metadata() -> None:
    rid = uuid.uuid4()
    search = _FixedSearch(
        [
            _hit(
                raw_document_id=rid,
                score=1.0,
                highlights={
                    "chunk_text": ["LEAK_BODY_HIGHLIGHT"],
                    "section_title": ["  방화벽  "],
                    "original_filename": ["spec.pdf"],
                },
            )
        ]
    )
    meta = {rid: _doc_row(rid, "")}
    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        out = run_discover(MagicMock(), _settings(), search, PermissionPrincipal("u", ()), DiscoverRequest(question="q"))
    mc = out.documents[0].matched_chunks[0]
    assert mc.highlights is not None
    assert "chunk_text" not in mc.highlights
    assert "LEAK_BODY_HIGHLIGHT" not in json.dumps(out.model_dump(mode="json"))
    assert mc.highlights.get("section_title") == ["방화벽"]
    assert "original_filename" in mc.highlights


@pytest.mark.usefixtures("_clear_overrides")
def test_discover_api_and_log_no_chunk_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    rid = uuid.uuid4()
    search = _FixedSearch(
        [
            _hit(
                raw_document_id=rid,
                score=9.0,
                highlights={"chunk_text": ["LOG_SHOULD_NOT_CONTAIN_THIS"], "section_title": ["t"]},
            )
        ]
    )
    meta = {rid: _doc_row(rid, "/projects/sanrim-platform/x.txt")}

    app.dependency_overrides[chat_deps.get_db] = _fake_db
    app.dependency_overrides[chat_deps.get_search_client] = lambda: search
    app.dependency_overrides[chat_deps.get_settings_dep] = _settings

    with patch("app.chat.discovery_service._load_raw_documents", return_value=meta):
        client = TestClient(app)
        resp = client.post("/api/v1/chat/discover", json={"question": "hello", "top_k": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert "SECRET_CHUNK_BODY" not in json.dumps(data)
    for doc in data["documents"]:
        for ch in doc["matched_chunks"]:
            assert "chunk_text" not in ch
            hl = ch.get("highlights")
            if hl is not None:
                assert "chunk_text" not in hl

    discover_msgs = [r.getMessage() for r in caplog.records if "chat_discover" in r.getMessage()]
    assert discover_msgs, "expected chat_discover log"
    payload = json.loads(discover_msgs[0].split("chat_discover ", 1)[1])
    assert payload["document_count"] == 1
    assert payload["retrieved_document_ids"] == [str(rid)]
    assert payload["top_scores"] == [9.0]
    assert "SECRET_CHUNK_BODY" not in discover_msgs[0]
    assert "LOG_SHOULD_NOT_CONTAIN_THIS" not in discover_msgs[0]
