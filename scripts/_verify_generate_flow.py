"""Integration check: discover + generate for 과업대비표 (local dev)."""
from __future__ import annotations

import json
import uuid

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.adapters.search_backend import search_client_for_chat
from app.agents.nas_rag import run_nas_rag_generate
from app.adapters.search_protocol import PermissionPrincipal
from app.chat.discovery_service import run_discover
from app.chat.schemas import ChatGenerateRequest, DiscoverRequest
from app.config.settings import get_settings
from app.db.session import get_session_factory

load_dotenv()
settings = get_settings()
settings = settings.model_copy(update={"enable_retrieval_debug": True})

DOC_IDS = [
    uuid.UUID("ff1c33e2-2936-47ee-9743-7614612c8669"),
    uuid.UUID("bae358a9-222f-4add-a766-c5b1c0b9ea38"),
    uuid.UUID("c213a7ab-aae9-4083-b036-f56980fa6d25"),
]
QUESTION = "과업대비표"


def main() -> None:
    factory = get_session_factory()
    session: Session = factory()
    try:
        search = search_client_for_chat(session, settings)
        principal = PermissionPrincipal(user_id="stub-user", department_codes=())
        disc = run_discover(
            session,
            settings,
            search,
            principal,
            DiscoverRequest(question=QUESTION, top_k=10),
        )
        print("=== DISCOVER ===")
        print(f"document_count={disc.document_count}")
        for d in disc.documents:
            print(
                f"  {d.raw_document_id} score={d.top_score:.3f} "
                f"chunks={d.matched_chunk_count} file={d.original_filename!r}"
            )

        for label, ids in [("1-doc", DOC_IDS[:1]), ("3-doc", DOC_IDS)]:
            print(f"\n=== GENERATE ({label}) ===")
            body = ChatGenerateRequest(
                question=QUESTION,
                document_ids=ids,
                top_k=5,
            )
            out = run_nas_rag_generate(session, settings, search, principal, body)
            print(f"selected_document_ids={out.selected_document_ids}")
            print(f"filtered_retrieval_count={out.filtered_retrieval_count}")
            src_docs = {str(s.raw_document_id) for s in out.sources}
            print(f"source_document_ids={sorted(src_docs)}")
            allowed = {str(u) for u in ids}
            extra = src_docs - allowed
            print(f"sources_within_selection={not extra} extra={extra or '-'}")
            if out.debug:
                print(f"debug.retrieval_count={out.debug.retrieval_count}")
                for ch in out.debug.chunks[:5]:
                    print(
                        f"  chunk_rank={ch.chunk_rank} doc_rank={ch.document_rank} "
                        f"score={ch.score} fields={ch.matched_fields} terms={ch.highlight_terms[:3]}"
                    )
            print(f"answer_preview={out.answer[:200]!r}...")
    finally:
        session.close()


if __name__ == "__main__":
    main()
