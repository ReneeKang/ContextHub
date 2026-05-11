"""DOCX via python-docx: paragraphs and light heading inference from styles."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO

from docx import Document
from docx.text.paragraph import Paragraph

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient

log = logging.getLogger("contexthub.parser.docx")


def _python_docx_version() -> str:
    try:
        return version("python-docx")
    except PackageNotFoundError:
        return "unknown"


def _paragraph_to_markdown_line(p: Paragraph) -> str | None:
    text = (p.text or "").strip()
    if not text:
        return None
    style_name = (p.style.name if p.style else "") or ""

    if style_name == "Title":
        return f"# {text}"

    if style_name.startswith("Heading"):
        parts = style_name.split()
        level = 1
        if len(parts) >= 2 and parts[-1].isdigit():
            level = min(max(int(parts[-1]), 1), 6)
        return f"{'#' * level} {text}"

    # List paragraphs (minimal): keep as plain text
    return text


class DocxPythonDocxParser(ParserClient):
    def parse(self, request: ParseRequest) -> ParseResult:
        try:
            doc = Document(BytesIO(request.file_bytes))
        except Exception as exc:
            raise ValueError(f"Invalid or unreadable DOCX: {exc}") from exc

        lines: list[str] = []
        blocks: list[dict[str, object]] = []

        for p in doc.paragraphs:
            md_line = _paragraph_to_markdown_line(p)
            if md_line is None:
                continue
            lines.append(md_line)
            style_name = (p.style.name if p.style else "") or ""
            blocks.append(
                {
                    "type": "paragraph",
                    "style": style_name,
                    "text_preview": md_line[:200],
                }
            )

        md = "\n\n".join(lines)
        ver = _python_docx_version()
        meta: dict[str, object] = {
            "engine": "python-docx",
            "python_docx_version": ver,
            "original_filename": request.original_filename,
            "paragraphs_indexed": len(blocks),
        }
        log.info(
            "python-docx parsed filename=%r paragraphs=%s markdown_chars=%s",
            request.original_filename,
            len(blocks),
            len(md),
        )
        return ParseResult(
            markdown_text=md,
            blocks_json=blocks,
            metadata_json=meta,
            page_count=1 if md else None,
            parser_version=f"python-docx-{ver}",
            parser_name="python-docx",
        )
