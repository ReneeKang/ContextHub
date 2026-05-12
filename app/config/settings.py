from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SearchBackendLiteral = Literal["db", "opensearch_stub", "opensearch"]
LlmBackendLiteral = Literal["mock", "openai_compat"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+psycopg://contexthub:contexthub@127.0.0.1:5433/contexthub",
        alias="DATABASE_URL",
    )
    # Relative paths resolve from the process working directory (run workers from repo root).
    nas_inbox_root: str = Field(default="local_nas/chatbot_docs", alias="NAS_INBOX_ROOT")
    scan_interval_seconds: int = Field(default=60, alias="SCAN_INTERVAL_SECONDS")
    search_index_name: str = Field(default="contexthub_chunks", alias="SEARCH_INDEX_NAME")
    #: ``db`` = PostgreSQL chunk search; ``opensearch_stub`` = validate/log only (no HTTP); ``opensearch`` = HTTP client.
    search_backend: SearchBackendLiteral = Field(default="db", alias="SEARCH_BACKEND")
    opensearch_base_url: str | None = Field(
        default=None,
        alias="OPENSEARCH_BASE_URL",
        description="OpenSearch HTTP base URL (e.g. http://127.0.0.1:9201 with default Compose host port). Required when SEARCH_BACKEND=opensearch.",
    )
    #: Log first-hit ``_explanation`` at DEBUG after search (verbose).
    opensearch_search_explain: bool = Field(default=False, alias="OPENSEARCH_SEARCH_EXPLAIN")
    #: Include ``highlight`` in search body (OpenSearch only).
    opensearch_search_highlight: bool = Field(default=True, alias="OPENSEARCH_SEARCH_HIGHLIGHT")
    parser_name: str = Field(
        default="routing",
        alias="PARSER_NAME",
        description="Fallback parser_name when adapter omits it; per-format engines set their own name.",
    )
    parser_version: str = Field(default="stub-0.0.0", alias="PARSER_VERSION")

    #: When ``True``, always use mock LLM (ignores ``LLM_BACKEND`` for HTTP).
    llm_mock_mode: bool = Field(default=True, alias="LLM_MOCK_MODE")
    llm_backend: LlmBackendLiteral = Field(default="mock", alias="LLM_BACKEND")
    openai_compat_base_url: str | None = Field(
        default=None,
        alias="OPENAI_COMPAT_BASE_URL",
        description="OpenAI-compatible API base, e.g. https://api.openai.com/v1 (no path suffix).",
    )
    openai_compat_api_key: str | None = Field(default=None, alias="OPENAI_COMPAT_API_KEY")
    #: HTTP read timeout (seconds) for ``OpenAICompatLLMClient`` (``urllib.request.urlopen``).
    openai_compat_timeout_seconds: float = Field(default=120.0, alias="OPENAI_COMPAT_TIMEOUT_SECONDS")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
