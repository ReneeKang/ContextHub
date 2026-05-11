"""
HTTP-backed ``SearchClient`` for OpenSearch (keyword search + index/delete).

* Permission filter is embedded in the search query via ``build_keyword_search_body`` (no post-filter).
* Requires ``Settings.opensearch_base_url`` when ``SEARCH_BACKEND=opensearch``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.exceptions import OpenSearchException
from opensearchpy.helpers import bulk

from app.adapters.opensearch_payload import (
    build_delete_by_raw_document_query,
    build_keyword_search_body,
    validate_chunk_index_document,
)
from app.adapters.search_protocol import PermissionPrincipal, SearchClient, SearchHit
from app.config.settings import Settings

log = logging.getLogger("contexthub.opensearch_client")


def opensearch_client_from_settings(settings: Settings) -> OpenSearch:
    """Build a synchronous OpenSearch client (PostgreSQL dev stack; single-node HTTP typical)."""
    raw = (settings.opensearch_base_url or "").strip()
    if not raw:
        raise ValueError("OPENSEARCH_BASE_URL is required when SEARCH_BACKEND=opensearch")
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise ValueError(f"Invalid OPENSEARCH_BASE_URL (missing host): {raw!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 9200)
    use_ssl = parsed.scheme == "https"
    client = OpenSearch(
        hosts=[{"host": parsed.hostname, "port": port}],
        http_compress=True,
        use_ssl=use_ssl,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        timeout=60,
        max_retries=2,
        retry_on_timeout=True,
    )
    return client


class OpenSearchHttpClient(SearchClient):
    """Real OpenSearch: ``index`` / ``search`` / ``delete_by_query`` over HTTP."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: OpenSearch | None = None

    def _os(self) -> OpenSearch:
        if self._client is None:
            self._client = opensearch_client_from_settings(self._settings)
        return self._client

    def search(
        self,
        *,
        query: str,
        top_k: int,
        principal: PermissionPrincipal,
        index_name: str,
    ) -> list[SearchHit]:
        if not (query or "").strip():
            log.info("OpenSearch search skipped (empty query) index=%r", index_name)
            return []
        body = build_keyword_search_body(
            query=query,
            top_k=top_k,
            principal_user_id=principal.user_id,
            department_codes=principal.department_codes,
            include_highlight=self._settings.opensearch_search_highlight,
        )
        client = self._os()
        explain = self._settings.opensearch_search_explain
        params = {"explain": "true"} if explain else None
        try:
            resp = client.search(index=index_name, body=body, params=params)
        except OpenSearchException:
            log.exception(
                "OpenSearch search failed index=%r base_url=%r",
                index_name,
                self._settings.opensearch_base_url,
            )
            raise
        hits = resp.get("hits", {}).get("hits", []) or []
        if explain and hits:
            ex0 = hits[0].get("_explanation")
            if ex0 is not None:
                log.debug(
                    "OpenSearch explain (first hit _id=%s): %s",
                    hits[0].get("_id"),
                    json.dumps(ex0, ensure_ascii=False)[:12000],
                )
        out: list[SearchHit] = []
        for h in hits:
            src = h.get("_source") or {}
            hl_raw = h.get("highlight") or {}
            highlights = {k: list(v) for k, v in hl_raw.items()} if hl_raw else None
            try:
                out.append(
                    SearchHit(
                        chunk_id=UUID(str(src["chunk_id"])),
                        raw_document_id=UUID(str(src["raw_document_id"])),
                        original_filename=str(src.get("original_filename") or ""),
                        chunk_no=int(src.get("chunk_no") or 0),
                        section_title=src.get("section_title"),
                        page_no=(int(pn) if (pn := src.get("page_no")) is not None else None),
                        chunk_text=str(src.get("chunk_text") or ""),
                        access_scope=str(src.get("access_scope") or "PUBLIC"),
                        score=float(h.get("_score") or 0.0),
                        highlights=highlights,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("skip malformed hit _id=%r err=%s src_keys=%s", h.get("_id"), exc, list(src.keys()))
                continue
        log.info(
            "OpenSearch search index=%r query_len=%s hits=%s explain=%s highlight=%s",
            index_name,
            len(query or ""),
            len(out),
            explain,
            self._settings.opensearch_search_highlight,
        )
        return out

    def index_chunk_document(
        self,
        *,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
    ) -> None:
        validate_chunk_index_document(document)
        client = self._os()
        try:
            client.index(index=index_name, id=doc_id, body=document, refresh=False)
        except OpenSearchException:
            log.exception(
                "OpenSearch index failed index=%r doc_id=%r base_url=%r",
                index_name,
                doc_id,
                self._settings.opensearch_base_url,
            )
            raise
        log.debug("OpenSearch indexed index=%r doc_id=%r", index_name, doc_id)

    def delete_chunks_for_document(self, *, index_name: str, raw_document_id: UUID) -> None:
        body = build_delete_by_raw_document_query(str(raw_document_id))
        client = self._os()
        try:
            client.delete_by_query(index=index_name, body=body, refresh=True, conflicts="proceed")
        except OpenSearchException:
            log.exception(
                "OpenSearch delete_by_query failed index=%r raw_document_id=%r base_url=%r",
                index_name,
                raw_document_id,
                self._settings.opensearch_base_url,
            )
            raise
        log.info(
            "OpenSearch delete_by_query done index=%r raw_document_id=%r",
            index_name,
            raw_document_id,
        )


def bulk_index_chunk_documents(
    client: OpenSearch,
    *,
    index_name: str,
    documents: Iterable[tuple[str, dict[str, Any]]],
    refresh: bool | str = False,
) -> tuple[int, int]:
    """
    Bulk index many chunks (``helpers.bulk``). Not part of ``SearchClient``; for batch jobs / future tuning.

    Returns ``(success_count, error_item_count)`` (errors may be partial rows when ``raise_on_error=False``).
    """
    actions: list[dict[str, Any]] = []
    for doc_id, document in documents:
        validate_chunk_index_document(document)
        actions.append({"_index": index_name, "_id": doc_id, "_source": document})
    if not actions:
        return 0, 0
    try:
        ok, errors = bulk(client, actions, refresh=refresh, raise_on_error=False)
    except OpenSearchException:
        log.exception("OpenSearch bulk index failed index=%r batch_size=%s", index_name, len(actions))
        raise
    err_list = errors if isinstance(errors, list) else []
    err_n = len(err_list)
    if err_n:
        log.warning("OpenSearch bulk completed with errors index=%r ok=%s errors=%s", index_name, ok, err_n)
    return int(ok or 0), err_n
