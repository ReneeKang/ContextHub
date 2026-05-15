"""Select a format-specific parser by MIME type (preferred) or file extension."""

from __future__ import annotations

import mimetypes

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient
from app.adapters.parsers.docx_python_docx import DocxPythonDocxParser
from app.adapters.parsers.kordoc_cli import KordocCliParser
from app.adapters.parsers.pdf_pypdf import PdfPypdfParser
from app.adapters.parsers.text_stub import TextStubParser
from app.adapters.parsers.xlsx_openpyxl import XlsxOpenpyxlParser


def _normalize_ext(file_ext: str) -> str:
    return (file_ext or "").lower().strip().lstrip(".")


def _effective_mime(request: ParseRequest) -> str | None:
    if request.mime_type:
        return request.mime_type.strip().lower()
    guessed, _ = mimetypes.guess_type(request.original_filename or "")
    return guessed.strip().lower() if guessed else None


class RoutingParser(ParserClient):
    """
    Routes by MIME when available, else by extension.

    * txt / md / markdown → UTF-8 native
    * pdf → pypdf
    * docx → python-docx
    * xlsx → openpyxl
    * hwp / hwpx → kordoc (subprocess CLI)
    * pptx → reserved (explicit error)
    """

    def __init__(self) -> None:
        self._text = TextStubParser()
        self._pdf = PdfPypdfParser()
        self._docx = DocxPythonDocxParser()
        self._xlsx = XlsxOpenpyxlParser()
        self._kordoc = KordocCliParser()

    def parse(self, request: ParseRequest) -> ParseResult:
        ext = _normalize_ext(request.file_ext)
        mime = _effective_mime(request)

        if mime == "application/pdf" or ext == "pdf":
            return self._pdf.parse(request)

        if (
            mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or ext == "docx"
        ):
            return self._docx.parse(request)

        if (
            mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            or ext == "xlsx"
        ):
            return self._xlsx.parse(request)

        if ext in {"hwp", "hwpx"} or (mime and "hwp" in mime):
            return self._kordoc.parse(request)

        if ext in {"txt", "md", "markdown"}:
            return self._text.parse(request)

        if (
            ext == "pptx"
            or mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ):
            raise ValueError(
                f"PPTX parsing is not implemented yet (ext={ext!r}, mime={mime!r}). "
                "Planned: kordoc or dedicated adapter."
            )

        raise ValueError(
            f"Unsupported document type (ext={ext!r}, mime={mime!r}). "
            f"Supported: txt, md, pdf, docx, xlsx, hwp, hwpx."
        )
