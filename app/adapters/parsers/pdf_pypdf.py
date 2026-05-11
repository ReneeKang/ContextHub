"""PDF text extraction via pypdf (no OCR)."""

from __future__ import annotations

import logging
from io import BytesIO

import pypdf
from pypdf import PdfReader

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient

log = logging.getLogger("contexthub.parser.pdf")


class PdfPypdfParser(ParserClient):
    def parse(self, request: ParseRequest) -> ParseResult:
        try:
            reader = PdfReader(BytesIO(request.file_bytes), strict=False)
        except Exception as exc:
            raise ValueError(f"Invalid or unreadable PDF: {exc}") from exc

        if getattr(reader, "is_encrypted", False):
            try:
                rc = reader.decrypt("")
            except Exception as exc:
                raise ValueError(f"Encrypted PDF could not be opened: {exc}") from exc
            if rc == 0:
                raise ValueError("Encrypted PDF is not supported in PoC (no password flow).")

        n = len(reader.pages)
        parts: list[str] = []
        blocks: list[dict[str, object]] = []

        for i, page in enumerate(reader.pages):
            raw = page.extract_text() or ""
            t = raw.strip()
            blocks.append({"type": "page", "page_no": i + 1, "char_count": len(raw)})
            if t:
                parts.append(f"## Page {i + 1}\n\n{t}")
            else:
                parts.append(f"## Page {i + 1}\n\n_(no extractable text — OCR not enabled)_")

        md = "\n\n".join(parts) if n else ""
        meta: dict[str, object] = {
            "engine": "pypdf",
            "pypdf_version": pypdf.__version__,
            "page_count": n,
            "original_filename": request.original_filename,
            "ocr": False,
        }
        log.info(
            "pypdf parsed filename=%r pages=%s markdown_chars=%s",
            request.original_filename,
            n,
            len(md),
        )
        return ParseResult(
            markdown_text=md,
            blocks_json=blocks,
            metadata_json=meta,
            page_count=n if n else None,
            parser_version=f"pypdf-{pypdf.__version__}",
            parser_name="pypdf",
        )
