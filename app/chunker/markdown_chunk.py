"""
Markdown chunking: heading hierarchy, paragraph boundaries, length split with overlap,
and merge of overly short adjacent chunks.

See `docs/chunking-strategy.md` for strategy; keep functions pure where possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.unicode_normalize import normalize_nfc, normalize_nfc_optional

# Tunables (keyword PoC; overlap helps boundary recall for future RAG)
CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP = 130
CHUNK_MIN_MERGE_CHARS = 100
CHUNK_TOKEN_DIVISOR = 4

_CHUNKING_VERSION = 2


@dataclass(frozen=True, slots=True)
class ChunkPiece:
    """One persisted chunk candidate."""

    text: str
    section_title: str | None
    heading_path: str | None = None
    source_page: int | None = None


_HEADING_LINE = re.compile(r"^#{1,6}\s*(.+)$")
_PAGE_TITLE = re.compile(r"^Page\s+(\d+)\s*$", re.IGNORECASE)
_SINGLE_ATX_LINE = re.compile(r"^#{1,6}\s+\S.*$")


def extract_heading_title(first_line: str) -> str | None:
    m = _HEADING_LINE.match(first_line.strip())
    if not m:
        return None
    return normalize_nfc(m.group(1).strip())


def estimate_token_count(text: str) -> int:
    """Rough token count without tiktoken (Latin-centric heuristic)."""
    if not text:
        return 0
    return max(1, (len(text) + CHUNK_TOKEN_DIVISOR - 1) // CHUNK_TOKEN_DIVISOR)


def _refine_split_end(text: str, start: int, hard_end: int) -> int:
    """Prefer breaks at paragraph / line / sentence within the tail of the window."""
    if hard_end >= len(text):
        return hard_end
    span = hard_end - start
    if span < 120:
        return hard_end
    win_start = max(start, hard_end - min(420, span))
    window = text[win_start:hard_end]
    for sep in ("\n\n", "\n", ". ", "。", " "):
        idx = window.rfind(sep)
        if idx == -1:
            continue
        pos = win_start + idx + len(sep)
        if pos - start >= max(64, int(span * 0.32)):
            return pos
    return hard_end


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
        hard_end = min(start + max_chars, n)
        split_end = _refine_split_end(text, start, hard_end)
        if split_end <= start:
            split_end = hard_end
        chunk = text[start:split_end].strip()
        if chunk:
            parts.append(chunk)
        if split_end >= n:
            break
        start = max(split_end - overlap, start + 1)
    return parts


def primary_segments(markdown_text: str) -> list[str]:
    """
    1st-level split: markdown ATX headings at line start, then blank-line paragraphs within each.

    Order: split on heading boundaries, then split each block by double newlines.
    """
    t = markdown_text.replace("\r\n", "\n").strip()
    if not t:
        return []

    heading_blocks = re.split(r"(?m)(?=^#{1,6}\s)", t)
    pieces: list[str] = []
    for block in heading_blocks:
        block = block.strip()
        if not block:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n+", block) if p.strip()]
        i = 0
        while i < len(paras):
            cur = paras[i]
            if _SINGLE_ATX_LINE.match(cur) and i + 1 < len(paras):
                nxt = paras[i + 1]
                if not _SINGLE_ATX_LINE.match(nxt):
                    pieces.append(f"{cur}\n\n{nxt}")
                    i += 2
                    continue
            pieces.append(cur)
            i += 1
    return pieces


def split_leading_atx_headings(segment: str) -> tuple[list[str], str]:
    """
    Consume consecutive ATX heading lines at the start of *segment*.

    Returns (heading_titles_in order, remainder body).
    """
    lines = segment.replace("\r\n", "\n").split("\n")
    titles: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        m = _HEADING_LINE.match(raw.strip())
        if not m:
            break
        titles.append(normalize_nfc(m.group(1).strip()))
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
    body = "\n".join(lines[i:]).strip()
    return titles, body


def source_page_from_titles(titles: list[str]) -> int | None:
    """Infer PDF logical page from a title like 'Page 12' (pypdf markdown)."""
    for t in reversed(titles):
        m = _PAGE_TITLE.match(t.strip())
        if m:
            return int(m.group(1))
    return None


def merge_adjacent_short_chunks(
    pieces: list[ChunkPiece],
    *,
    min_chars: int = CHUNK_MIN_MERGE_CHARS,
    max_merged_chars: int = CHUNK_MAX_CHARS,
) -> list[ChunkPiece]:
    """
    Merge consecutive chunks that share the same heading context when at least one
    side is short and the combined size stays under max_merged_chars.
    """
    if not pieces:
        return []
    out: list[ChunkPiece] = []
    i = 0
    while i < len(pieces):
        cur = pieces[i]
        i += 1
        while i < len(pieces):
            nxt = pieces[i]
            same_ctx = cur.heading_path == nxt.heading_path and cur.source_page == nxt.source_page
            combined = len(cur.text) + 2 + len(nxt.text)
            short_side = len(cur.text) < min_chars or len(nxt.text) < min_chars
            if same_ctx and short_side and combined <= max_merged_chars:
                cur = ChunkPiece(
                    text=normalize_nfc(cur.text + "\n\n" + nxt.text),
                    section_title=cur.section_title,
                    heading_path=cur.heading_path,
                    source_page=cur.source_page,
                )
                i += 1
            else:
                break
        out.append(cur)
    return out


def section_title_for_segment(segment: str, *, fallback_filename: str | None) -> str | None:
    """Infer section title from first line heading, else None (caller may use filename)."""
    first_line = segment.split("\n", 1)[0]
    title = extract_heading_title(first_line)
    if title:
        return title
    return normalize_nfc_optional(fallback_filename)


def build_chunks_from_markdown(
    markdown_text: str,
    *,
    fallback_filename: str | None,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP,
    min_merge_chars: int = CHUNK_MIN_MERGE_CHARS,
) -> list[ChunkPiece]:
    """
    Produce ordered chunk pieces with heading_path, section_title, and optional source_page.

    Empty input → empty list (caller decides FAILED vs skip).
    """
    segments = primary_segments(markdown_text)
    if not segments:
        return []

    raw_pieces: list[ChunkPiece] = []
    carried_path: str | None = None
    carried_page: int | None = None
    for seg in segments:
        titles, body = split_leading_atx_headings(seg)
        if not body.strip():
            if titles:
                carried_path = " > ".join(titles)
                carried_page = source_page_from_titles(titles)
            continue

        if titles:
            heading_path = " > ".join(titles)
            leaf = titles[-1]
            source_page = source_page_from_titles(titles)
            carried_path = heading_path
            carried_page = source_page
        else:
            heading_path = carried_path
            source_page = carried_page
            leaf = None
        base_title = leaf or section_title_for_segment(seg, fallback_filename=fallback_filename)
        if base_title is None and fallback_filename:
            base_title = normalize_nfc(fallback_filename)

        long_parts = split_long_segment(body, max_chars=max_chars, overlap=overlap)
        for i, part in enumerate(long_parts):
            part = part.strip()
            if not part:
                continue
            title = base_title
            if i > 0 and base_title:
                title = normalize_nfc(f"{base_title} (continued)")
            elif i > 0 and fallback_filename:
                title = normalize_nfc(f"{fallback_filename} (continued)")
            raw_pieces.append(
                ChunkPiece(
                    text=normalize_nfc(part),
                    section_title=normalize_nfc_optional(title),
                    heading_path=normalize_nfc_optional(heading_path),
                    source_page=source_page,
                )
            )

    return merge_adjacent_short_chunks(raw_pieces, min_chars=min_merge_chars, max_merged_chars=max_chars)


def chunk_metadata_for_piece() -> dict[str, Any]:
    """Stable metadata blob stored on each row (extensible for vectors later)."""
    return {
        "chunking_version": _CHUNKING_VERSION,
        "max_chars": CHUNK_MAX_CHARS,
        "overlap_chars": CHUNK_OVERLAP,
        "min_merge_chars": CHUNK_MIN_MERGE_CHARS,
    }
