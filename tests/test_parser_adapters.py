"""Parser routing and format adapters (xlsx, kordoc CLI bridge)."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from app.adapters.parser_protocol import ParseRequest
from app.adapters.parsers.kordoc_cli import KordocCliParser
from app.adapters.parsers.routing import RoutingParser
from app.adapters.parsers.xlsx_openpyxl import XlsxOpenpyxlParser


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "과업대비표"
    ws.append(["항목", "값"])
    ws.append(["문서", "ID_A01_과업대비표"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_routing_xlsx_uses_openpyxl() -> None:
    router = RoutingParser()
    req = ParseRequest(
        file_bytes=_xlsx_bytes(),
        file_ext="xlsx",
        original_filename="ID_A01_과업대비표.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    out = router.parse(req)
    assert out.parser_name == "openpyxl"
    assert "과업대비표" in out.markdown_text
    assert "ID_A01_과업대비표" in out.markdown_text


def test_routing_pptx_explicit_error() -> None:
    router = RoutingParser()
    with pytest.raises(ValueError, match="PPTX"):
        router.parse(
            ParseRequest(
                file_bytes=b"x",
                file_ext="pptx",
                original_filename="deck.pptx",
            )
        )


def test_kordoc_cli_maps_json_to_parse_result(tmp_path) -> None:
    payload = {
        "ok": True,
        "markdown_text": "# HWP\n\n본문",
        "blocks_json": [{"type": "paragraph", "text": "본문"}],
        "metadata_json": {"title": "t"},
        "page_count": 2,
        "parser_name": "kordoc",
        "parser_version": "kordoc-1.0.0",
    }

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return R()

    parser = KordocCliParser(cli_argv=["node", "fake.mjs"], timeout_seconds=5.0)
    req = ParseRequest(file_bytes=b"hwp-bytes", file_ext="hwp", original_filename="a.hwp")
    with patch("app.adapters.parsers.kordoc_cli.subprocess.run", side_effect=fake_run):
        with patch("app.adapters.parsers.kordoc_cli.os.unlink"):
            out = parser.parse(req)
    assert out.parser_name == "kordoc"
    assert "본문" in out.markdown_text
    assert out.page_count == 2


def test_xlsx_openpyxl_parser_direct() -> None:
    out = XlsxOpenpyxlParser().parse(
        ParseRequest(
            file_bytes=_xlsx_bytes(),
            file_ext="xlsx",
            original_filename="ID_A01_과업대비표.xlsx",
        )
    )
    assert out.parser_name == "openpyxl"
    assert "## 과업대비표" in out.markdown_text
