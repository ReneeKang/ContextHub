from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SearchBackendLiteral = Literal["db", "opensearch_stub"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://contexthub:contexthub@127.0.0.1:5433/contexthub",
        alias="DATABASE_URL",
    )
    # Relative paths resolve from the process working directory (run workers from repo root).
    nas_inbox_root: str = Field(default="local_nas/chatbot_docs", alias="NAS_INBOX_ROOT")
    scan_interval_seconds: int = Field(default=60, alias="SCAN_INTERVAL_SECONDS")
    search_index_name: str = Field(default="contexthub_chunks", alias="SEARCH_INDEX_NAME")
    #: Chat (and future workers): `db` = PostgreSQL chunk search; `opensearch_stub` = same `SearchClient` API, no HTTP (payload/query shape only).
    search_backend: SearchBackendLiteral = Field(default="db", alias="SEARCH_BACKEND")
    opensearch_base_url: str | None = Field(
        default=None,
        alias="OPENSEARCH_BASE_URL",
        description="Reserved for real OpenSearch client (e.g. https://localhost:9200). Unused while stub.",
    )
    parser_name: str = Field(
        default="routing",
        alias="PARSER_NAME",
        description="Fallback parser_name when adapter omits it; per-format engines set their own name.",
    )
    parser_version: str = Field(default="stub-0.0.0", alias="PARSER_VERSION")


@lru_cache
def get_settings() -> Settings:
    return Settings()
