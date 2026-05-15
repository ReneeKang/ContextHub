"""Analyze generate retrieval hits for 과업대비표 v0.9 xlsx."""
from __future__ import annotations

from collections import Counter
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from app.adapters.search_backend import search_client_for_chat
from app.adapters.search_protocol import PermissionPrincipal
from app.chat.retrieval_query import normalize_retrieval_query_pair
from app.config.settings import get_settings
from app.db.session import get_session_factory

load_dotenv()
RID = UUID("ff1c33e2-2936-47ee-9743-7614612c8669")
TOP_K = 5

factory = get_session_factory()
session = factory()
settings = get_settings()
search = search_client_for_chat(session, settings)
q, _ = normalize_retrieval_query_pair("과업대비표")
hits = search.search(
    query=q,
    top_k=TOP_K,
    principal=PermissionPrincipal("stub-user", ()),
    index_name=settings.search_index_name,
)
hits = [h for h in hits if h.raw_document_id == RID]

print(f"=== TOP {TOP_K} CHUNKS (generate default) ===")
for i, h in enumerate(hits, 1):
    preview = (h.chunk_text or "").replace("\n", " ")[:200]
    print(f"\n--- #{i} chunk_no={h.chunk_no} score={h.score:.3f}")
    print(f"section_title={h.section_title!r}")
    print(f"heading_path={getattr(h, 'heading_path', None)!r}")
    print(f"chars={len(h.chunk_text or '')} preview={preview!r}...")
    if h.highlights:
        print(f"highlights_keys={list(h.highlights.keys())}")

# DB: sheet/section distribution for this doc
engine = create_engine(settings.database_url)
sql = text(
    """
    SELECT chunk_no, section_title, heading_path, chunk_char_count,
           left(chunk_text, 300) AS preview
    FROM document_chunk
    WHERE raw_document_id = :rid
    ORDER BY chunk_no
    LIMIT 15
    """
)
with engine.connect() as conn:
    rows = conn.execute(sql, {"rid": str(RID)}).fetchall()
print("\n=== FIRST 15 CHUNKS IN DB (by chunk_no) ===")
for r in rows:
    print(f"no={r[0]} sec={r[1]!r} path={r[2]!r} chars={r[3]}")

sql2 = text(
    """
    SELECT section_title, count(*) AS n, avg(chunk_char_count)::int AS avg_chars
    FROM document_chunk
    WHERE raw_document_id = :rid
    GROUP BY section_title
    ORDER BY n DESC
    LIMIT 20
    """
)
with engine.connect() as conn:
    dist = conn.execute(sql2, {"rid": str(RID)}).fetchall()
print("\n=== SECTION DISTRIBUTION ===")
for r in dist:
    print(f"  {r[0]!r}: {r[1]} chunks, avg_chars={r[2]}")

# parse result size
sql3 = text(
    """
    SELECT length(markdown_text), parser_name, page_count
    FROM document_parse_result dpr
    JOIN raw_document rd ON rd.raw_document_id = dpr.raw_document_id
    WHERE rd.raw_document_id = :rid
    ORDER BY dpr.created_at DESC NULLS LAST
    LIMIT 1
    """
)
with engine.connect() as conn:
    pr = conn.execute(sql3, {"rid": str(RID)}).fetchone()
if pr:
    print(f"\n=== PARSE RESULT markdown_chars={pr[0]} parser={pr[1]} sheets={pr[2]}")

session.close()
