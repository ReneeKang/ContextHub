"""UTF-8 text / markdown: PoC stub (no external libs)."""

from __future__ import annotations

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient

_STUB_VERSION = "stub-0.0.0"


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _simple_blocks_from_text(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for line in text.splitlines():
        blocks.append({"type": "paragraph", "text": line})
    return blocks


class TextStubParser(ParserClient):
    """Plain text and markdown: decode as UTF-8, one block per line."""

    def parse(self, request: ParseRequest) -> ParseResult:
        text = _decode_utf8(request.file_bytes)
        blocks = _simple_blocks_from_text(text)
        meta = {
            "engine": "stub-text",
            "original_filename": request.original_filename,
            "encoding": "utf-8",
        }
        line_count = len(text.splitlines()) if text else 0
        page_count = 1 if text else 0
        if line_count > 0:
            meta["line_count"] = line_count
        return ParseResult(
            markdown_text=text,
            blocks_json=blocks,
            metadata_json=meta,
            page_count=page_count,
            parser_version=_STUB_VERSION,
            parser_name="stub-text",
        )
