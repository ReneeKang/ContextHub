from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.db.enums import (
    ChunkStatus,
    DocumentPipelineIndexStatus,
    IngestStatus,
    ParseStatus,
    SourceType,
)
from app.db.models.raw_document import RawDocument
from app.db.models.raw_document_scan_state import RawDocumentScanState
from app.scanner.permissions import extract_permission_meta
from app.unicode_normalize import normalize_nfc


log = logging.getLogger("contexthub.scanner")


@dataclass(slots=True)
class ScannerRunStats:
    """Per-cycle scanner metrics (observable in worker logs)."""

    files_seen: int = 0
    already_registered: int = 0
    awaiting_stabilization: int = 0
    registered_received: int = 0
    registered_duplicate: int = 0
    permission_errors: int = 0


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _should_skip_path(path: Path, inbox: Path) -> bool:
    try:
        rel = path.relative_to(inbox)
    except ValueError:
        return True
    for part in rel.parts:
        if part.startswith("."):
            return True
        if part in {"__pycache__", ".git"}:
            return True
    return False


def _resolve_inbox_root(settings: Settings) -> Path:
    root = Path(settings.nas_inbox_root).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    else:
        root = root.resolve()
    return root


class ScannerService:
    """NAS scan worker: discover files, stabilize, hash, register `raw_document` rows."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def run_once(self) -> ScannerRunStats:
        stats = ScannerRunStats()
        inbox = _resolve_inbox_root(self._settings)
        nas_root = str(inbox)

        if not inbox.is_dir():
            log.warning("NAS_INBOX_ROOT is not a directory or missing: %s", inbox)
            return stats

        candidates: list[Path] = []
        for path in inbox.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip_path(path, inbox):
                continue
            candidates.append(path)
        candidates.sort()
        stats.files_seen = len(candidates)
        log.info("found %s candidate files under %s", stats.files_seen, inbox)

        now = datetime.now(UTC)

        for path in candidates:
            stored_path = str(path.resolve())

            existing_doc = self._session.scalar(
                select(RawDocument).where(RawDocument.stored_path == stored_path)
            )
            if existing_doc is not None:
                stats.already_registered += 1
                # Heal legacy rows (e.g. Mac NFD before scanner NFC) so DB matches NFC search/ILIKE.
                nfc_name = normalize_nfc(path.name)
                nfc_rel = normalize_nfc(path.relative_to(inbox).as_posix())
                if existing_doc.original_filename != nfc_name or existing_doc.inbox_path != nfc_rel:
                    existing_doc.original_filename = nfc_name
                    existing_doc.inbox_path = nfc_rel
                    log.info(
                        "normalized raw_document to NFC (filename/path) raw_document_id=%s",
                        existing_doc.raw_document_id,
                    )
                continue

            try:
                rel = normalize_nfc(path.relative_to(inbox).as_posix())
                scope, owner_id, dept = extract_permission_meta(nas_inbox_root=nas_root, stored_path=stored_path)
            except ValueError as exc:
                log.warning("permission extract failed for %s: %s", stored_path, exc)
                stats.permission_errors += 1
                continue

            st = path.stat()
            size = st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC)

            row = self._session.scalar(
                select(RawDocumentScanState).where(RawDocumentScanState.file_path == stored_path)
            )

            if row is None:
                self._session.add(
                    RawDocumentScanState(
                        file_path=stored_path,
                        file_size=size,
                        mtime=mtime,
                        stable=False,
                        last_checked_at=now,
                    )
                )
                stats.awaiting_stabilization += 1
                log.debug("first sight (await stabilize): %s", stored_path)
                continue

            row.last_checked_at = now

            if row.file_size != size or row.mtime != mtime:
                row.file_size = size
                row.mtime = mtime
                row.stable = False
                stats.awaiting_stabilization += 1
                log.debug("file changed, reset stabilization: %s", stored_path)
                continue

            row.stable = True

            digest = _sha256_file(path)
            original_filename = normalize_nfc(path.name)
            ext = path.suffix.lower().lstrip(".") or "txt"

            canonical = self._session.scalar(
                select(RawDocument).where(
                    RawDocument.sha256_hash == digest,
                    RawDocument.ingest_status == IngestStatus.RECEIVED,
                ).limit(1)
            )

            if canonical is not None:
                dup = RawDocument(
                    source_type=SourceType.NAS,
                    inbox_path=rel,
                    stored_path=stored_path,
                    original_filename=original_filename,
                    file_ext=ext,
                    file_size=size,
                    sha256_hash=digest,
                    access_scope=scope,
                    owner_id=owner_id,
                    department_code=dept,
                    ingest_status=IngestStatus.DUPLICATE,
                    duplicate_of_raw_document_id=canonical.raw_document_id,
                    parse_status=ParseStatus.DONE,
                    chunk_status=ChunkStatus.DONE,
                    index_status=DocumentPipelineIndexStatus.DONE,
                )
                self._session.add(dup)
                stats.registered_duplicate += 1
                log.info("registered DUPLICATE (same sha256 as %s): %s", canonical.raw_document_id, stored_path)
                continue

            doc = RawDocument(
                source_type=SourceType.NAS,
                inbox_path=rel,
                stored_path=stored_path,
                original_filename=original_filename,
                file_ext=ext,
                file_size=size,
                sha256_hash=digest,
                access_scope=scope,
                owner_id=owner_id,
                department_code=dept,
                ingest_status=IngestStatus.RECEIVED,
                parse_status=ParseStatus.PENDING,
                chunk_status=ChunkStatus.PENDING,
                index_status=DocumentPipelineIndexStatus.PENDING,
            )
            self._session.add(doc)
            stats.registered_received += 1
            log.info("registered RECEIVED: %s sha256=%s...", stored_path, digest[:12])

        if stats.awaiting_stabilization and not stats.registered_received:
            log.info(
                "stabilization pending for %s file(s); run `python -m app.workers` again "
                "without changing files to register raw_document rows",
                stats.awaiting_stabilization,
            )

        return stats
