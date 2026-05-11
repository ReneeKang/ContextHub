"""
PoC markdown chunking: split by headings / blank lines, then by length with overlap.

See `docs/pipeline-flow.md` — structure-based rules may evolve; keep functions pure for tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Within docs range 1000–1500; overlap within 100–200
CHUNK_MAX_CHARS = 1300
CHUNK_OVERLAP = 150


@dataclass(frozen=True, slots=True)
class ChunkPiece:
    """One persisted chunk candidate."""

    text: str
    section_title: str | None


_HEADING_LINE = re.compile(r"^#{1,6}\s*(.+)$")


def extract_heading_title(first_line: str) -> str | None:
    m = _HEADING_LINE.match(first_line.strip())
    return m.group(1).strip() if m else None


def split_long_segment(text: str, *, max_chars: int, overlap: int) -> list[str]:
    """Split a segment into overlapping windows if longer than max_chars."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    stride = max(max_chars - overlap, 1)
    parts: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        parts.append(text[start:end])
        if end >= n:
            break
        start += stride
    return parts


def primary_segments(markdown_text: str) -> list[str]:
    """
    1st-level split: markdown ATX headings at line start, then blank-line paragraphs within each.

    Order: split on heading boundaries, then split each block by double newlines.
    """
    t = markdown_text.replace("\r\n", "\n").strip()
    if not t:
        return []

    # Split before lines that start with # (ATX heading), keep delimiter inside segment via lookahead split
    heading_blocks = re.split(r"(?m)(?=^#{1,6}\s)", t)
    pieces: list[str] = []
    for block in heading_blocks:
        block = block.strip()
        if not block:
            continue
        for para in re.split(r"\n\s*\n+", block):
            p = para.strip()
            if p:
                pieces.append(p)
    return pieces


def section_title_for_segment(segment: str, *, fallback_filename: str | None) -> str | None:
    """Infer section title from first line heading, else None (caller may use filename)."""
    first_line = segment.split("\n", 1)[0]
    title = extract_heading_title(first_line)
    if title:
        return title
    return fallback_filename


def build_chunks_from_markdown(
    markdown_text: str,
    *,
    fallback_filename: str | None,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP,
) -> list[ChunkPiece]:
    """
    Produce ordered chunk pieces with inferred section titles.

    Empty input → empty list (caller decides FAILED vs skip).
    """
    segments = primary_segments(markdown_text)
    if not segments:
        return []

    out: list[ChunkPiece] = []
    for seg in segments:
        base_title = section_title_for_segment(seg, fallback_filename=fallback_filename)
        long_parts = split_long_segment(seg, max_chars=max_chars, overlap=overlap)
        for i, part in enumerate(long_parts):
            part = part.strip()
            if not part:
                continue
            title = base_title
            if title is None and fallback_filename:
                title = fallback_filename
            if i > 0 and base_title:
                title = f"{base_title} (continued)"
            elif i > 0 and fallback_filename:
                title = f"{fallback_filename} (continued)"
            out.append(ChunkPiece(text=part, section_title=title))
    return out
