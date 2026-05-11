"""HWP / HWPX: not implemented; fail fast at parse stage."""

from __future__ import annotations

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient


class HwpPlaceholderParser(ParserClient):
    def parse(self, request: ParseRequest) -> ParseResult:
        _ = request
        raise ValueError(
            "HWP/HWPX parsing is not implemented in this PoC (placeholder only; no kordoc wire-up). "
            "Use admin reprocess after a future adapter exists."
        )
