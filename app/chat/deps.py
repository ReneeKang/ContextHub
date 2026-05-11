from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.adapters.search_backend import search_client_for_chat
from app.adapters.search_protocol import PermissionPrincipal, SearchClient
from app.chat.schemas import ChatQueryRequest
from app.config.settings import Settings, get_settings
from app.db.session import get_db as _get_db


def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


def get_settings_dep() -> Settings:
    return get_settings()


def get_search_client(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> SearchClient:
    """
    `SEARCH_BACKEND=db` (default): `DbChunkSearchClient` — SQL permission filter.

    `SEARCH_BACKEND=opensearch_stub`: `OpenSearchSearchClient` — logs query JSON; **returns no hits** (no cluster).
    """
    return search_client_for_chat(db, settings)


def resolve_stub_principal_for_chat(body: ChatQueryRequest) -> PermissionPrincipal:
    """
    PoC stub user (no real auth). `user_id` is fixed; `department_codes` come from the request
    when `test_department_codes` is set (Swagger / local tests only).

    Permission rules (when `SEARCH_BACKEND=db`, enforced in SQL via `DbChunkSearchClient`):
    - PUBLIC: always allowed
    - DEPT: chunk `department_code` must be in `department_codes`
    - PRIVATE: chunk `owner_id` must equal `user_id` (stub-user)

    When `SEARCH_BACKEND=opensearch_stub`, chat search returns no hits; principal is still logged
    for future OpenSearch query assembly (`opensearch_payload.build_permission_filter_clause`).
    """
    if body.test_department_codes:
        codes = tuple(
            str(c).strip() for c in body.test_department_codes if c is not None and str(c).strip()
        )
        return PermissionPrincipal(user_id="stub-user", department_codes=codes)
    return PermissionPrincipal(user_id="stub-user", department_codes=())
