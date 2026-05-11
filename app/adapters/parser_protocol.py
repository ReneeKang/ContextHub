from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ParseRequest:
    """Input to a document parser implementation (e.g. kordoc)."""

    file_bytes: bytes
    file_ext: str
    original_filename: str
    #: Optional MIME from caller or `mimetypes.guess_type(original_filename)`; routing prefers this when set.
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Normalized parser output stored in `document_parse_result`."""

    markdown_text: str
    blocks_json: list[Any] | dict[str, Any]
    metadata_json: dict[str, Any] | None
    page_count: int | None
    parser_version: str
    #: Logical engine name persisted on `document_parse_result.parser_name` (falls back to settings when None).
    parser_name: str | None = None


@runtime_checkable
class ParserClient(Protocol):
    """Pluggable parser: kordoc today, another engine tomorrow."""

    def parse(self, request: ParseRequest) -> ParseResult: ...
