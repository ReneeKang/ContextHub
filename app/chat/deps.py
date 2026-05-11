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
    """
    PoC fixed principal (no real auth).

    DB search (`DbChunkSearchClient`) applies:
    - PUBLIC: always allowed
    - DEPT: allowed only if `department_codes` contains the chunk's `department_code`
    - PRIVATE: allowed only if `owner_id` matches `user_id`

    Default `department_codes=()` means DEPT-scoped chunks (e.g. `dept/infra/…`) do **not** appear.
    To test infra DEPT documents in Swagger, temporarily use e.g.:
        return PermissionPrincipal(user_id="stub-user", department_codes=("infra",))
    """
    return PermissionPrincipal(user_id="stub-user", department_codes=())
