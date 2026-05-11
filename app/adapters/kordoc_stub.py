from __future__ import annotations

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient


class KordocStubParser(ParserClient):
    """Stub parser standing in for kordoc. Swap with a real client in `ParserService`."""

    def parse(self, request: ParseRequest) -> ParseResult:
        ext = request.file_ext.lower().strip().lstrip(".")
        parser_version = "stub-0.0.0"

        if ext in {"txt", "md", "markdown"}:
            text = _decode_utf8(request.file_bytes)
            blocks = _simple_blocks_from_text(text)
            meta = {
                "source": "stub",
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
                parser_version=parser_version,
            )

        # TODO: call real kordoc for pdf/docx/hwp
        return ParseResult(
            markdown_text="",
            blocks_json=[],
            metadata_json={"source": "stub", "original_filename": request.original_filename, "note": "unsupported ext"},
            page_count=None,
            parser_version=parser_version,
        )


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _simple_blocks_from_text(text: str) -> list[dict[str, object]]:
    """Minimal block tree for PoC (structure-based chunking later)."""
    blocks: list[dict[str, object]] = []
    for line in text.splitlines():
        blocks.append({"type": "paragraph", "text": line})
    return blocks
