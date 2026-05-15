"""
Unicode NFC normalization for cross-platform Korean text and paths.

macOS (HFS+/APFS) often surfaces filenames as NFD; Windows/Linux typically NFC.
Normalizing to NFC at storage and query time keeps ``ILIKE`` / keyword search aligned.
"""

from __future__ import annotations

import unicodedata


def normalize_nfc(s: str) -> str:
    """Apply Unicode NFC (composed) normalization; empty string stays empty."""
    if not s:
        return s
    return unicodedata.normalize("NFC", s)


def normalize_nfc_optional(s: str | None) -> str | None:
    """NFC for optional string fields; ``None`` unchanged."""
    if s is None:
        return None
    return unicodedata.normalize("NFC", s)
