from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.adapters.db_chunk_search import DbChunkSearchClient
from app.adapters.search_protocol import PermissionPrincipal
from app.config.settings import Settings, get_settings
from app.db.session import get_db as _get_db


def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


def get_settings_dep() -> Settings:
    return get_settings()


def get_search_client(db: Session = Depends(get_db)) -> DbChunkSearchClient:
    """
    PoC: PostgreSQL chunk search with SQL permission filter (OpenSearch stand-in).

    Later: switch to OpenSearch-backed client implementing the same `SearchClient` protocol.
    """
    return DbChunkSearchClient(db)


def get_stub_chat_principal() -> PermissionPrincipal:
    """TODO: derive from Bearer token / session; never trust client-sent scopes."""
    return PermissionPrincipal(user_id="stub-user", department_codes=())
