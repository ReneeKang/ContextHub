"""
HWP/HWPX via external **kordoc** (Node subprocess).

Wraps CLI stdout JSON into ContextHub ``ParseResult``. Does not embed kordoc logic in Python.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from shutil import which

from app.adapters.parser_protocol import ParseRequest, ParseResult, ParserClient
from app.config.settings import get_settings

log = logging.getLogger("contexthub.parser.kordoc")


def default_kordoc_cli_argv() -> list[str] | None:
    """
    Resolve default CLI: ``node <repo>/tools/kordoc-cli/parse.mjs`` when present.

    Override entirely with env ``KORDOC_CLI_COMMAND`` (shell string, e.g. ``node path/to/parse.mjs``).
    """
    raw = (os.environ.get("KORDOC_CLI_COMMAND") or "").strip()
    if raw:
        return raw.split()

    node = which("node")
    if not node:
        return None
    script = Path(__file__).resolve().parents[3] / "tools" / "kordoc-cli" / "parse.mjs"
    if script.is_file():
        return [node, str(script)]
    return None


def _normalize_ext(file_ext: str) -> str:
    return (file_ext or "").lower().strip().lstrip(".")


class KordocCliParser(ParserClient):
    """Invoke kordoc through a subprocess CLI; map JSON response → ``ParseResult``."""

    def __init__(
        self,
        *,
        cli_argv: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        if cli_argv is not None:
            self._cli_argv = cli_argv
        elif settings.kordoc_cli_command:
            self._cli_argv = settings.kordoc_cli_command.split()
        else:
            self._cli_argv = default_kordoc_cli_argv()
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.kordoc_cli_timeout_seconds
        )

    def parse(self, request: ParseRequest) -> ParseResult:
        ext = _normalize_ext(request.file_ext)
        if ext not in {"hwp", "hwpx"}:
            raise ValueError(f"kordoc adapter supports hwp/hwpx only, got ext={ext!r}")

        if not self._cli_argv:
            raise ValueError(
                "kordoc CLI is not configured (set KORDOC_CLI_COMMAND or install Node and "
                "tools/kordoc-cli/parse.mjs). HWP/HWPX requires kordoc."
            )

        suffix = f".{ext}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(request.file_bytes)
            tmp_path = tmp.name

        try:
            cmd = [
                *self._cli_argv,
                "--input",
                tmp_path,
                "--ext",
                ext,
                "--filename",
                request.original_filename or f"document{suffix}",
            ]
            log.info("kordoc cli invoke argv=%s", cmd[:3])
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip() or f"exit code {proc.returncode}"
            raise ValueError(f"kordoc CLI failed: {detail}")

        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"kordoc CLI returned invalid JSON: {exc}") from exc

        if payload.get("ok") is not True:
            raise ValueError(str(payload.get("error") or "kordoc reported failure"))

        markdown = str(payload.get("markdown_text") or "")
        blocks = payload.get("blocks_json")
        if blocks is None:
            blocks = []
        if not isinstance(blocks, (list, dict)):
            blocks = []

        meta = payload.get("metadata_json")
        if meta is not None and not isinstance(meta, dict):
            meta = {"raw": meta}
        if isinstance(meta, dict):
            meta = {**meta, "engine": "kordoc", "cli": self._cli_argv[0] if self._cli_argv else "?"}
        else:
            meta = {"engine": "kordoc"}

        page_count = payload.get("page_count")
        if page_count is not None:
            try:
                page_count = int(page_count)
            except (TypeError, ValueError):
                page_count = None

        parser_version = str(payload.get("parser_version") or "kordoc-cli-unknown")
        parser_name = str(payload.get("parser_name") or "kordoc")

        return ParseResult(
            markdown_text=markdown,
            blocks_json=blocks,
            metadata_json=meta,
            page_count=page_count,
            parser_version=parser_version,
            parser_name=parser_name,
        )
