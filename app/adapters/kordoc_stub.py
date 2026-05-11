"""Legacy import path: UTF-8 text/md stub only. Prefer `RoutingParser` for multi-format ingest."""

from __future__ import annotations

from app.adapters.parsers.text_stub import TextStubParser

# Historical name used by early PoC imports and docs.
KordocStubParser = TextStubParser

__all__ = ["KordocStubParser"]
