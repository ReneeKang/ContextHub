from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    parser_name: str = Field(default="kordoc", alias="PARSER_NAME")
    parser_version: str = Field(default="stub-0.0.0", alias="PARSER_VERSION")


@lru_cache
def get_settings() -> Settings:
    return Settings()
