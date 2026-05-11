from enum import StrEnum


class IngestStatus(StrEnum):
    RECEIVED = "RECEIVED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


class ParseStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class ChunkStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class DocumentPipelineIndexStatus(StrEnum):
    """Aggregate index stage on `raw_document.index_status` (document-level)."""

    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class ChunkIndexStatus(StrEnum):
    """Per-chunk indexing state on `document_chunk.index_status`."""

    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class DocumentIndexRecordStatus(StrEnum):
    """Row in `document_index_status` (history of one index attempt)."""

    DONE = "DONE"
    FAILED = "FAILED"


class AccessScope(StrEnum):
    PUBLIC = "PUBLIC"
    DEPT = "DEPT"
    PRIVATE = "PRIVATE"


class SourceType(StrEnum):
    NAS = "NAS"
