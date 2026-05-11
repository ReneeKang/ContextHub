"""Path-based permission extraction (see `docs/permission-policy.md`)."""

from __future__ import annotations

from app.db.enums import AccessScope


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def extract_permission_meta(*, nas_inbox_root: str, stored_path: str) -> tuple[AccessScope, str | None, str | None]:
    """
    Derive (access_scope, owner_id, department_code) from a file path under the official inbox root.

    Layout (relative to inbox root):
    - public/**  -> PUBLIC
    - dept/{code}/** -> DEPT + department_code
    - private/{uid}/** -> PRIVATE + owner_id
    """
    root = _norm_path(nas_inbox_root)
    full = _norm_path(stored_path)
    if not full.startswith(root):
        msg = f"Path is not under NAS_INBOX_ROOT: {stored_path!r}"
        raise ValueError(msg)
    rel = full[len(root) :].lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if not parts:
        msg = f"Empty relative path under inbox: {stored_path!r}"
        raise ValueError(msg)

    top = parts[0].lower()
    if top == "public":
        return AccessScope.PUBLIC, None, None
    if top == "dept":
        if len(parts) < 2:
            msg = f"DEPT path must include department segment: {stored_path!r}"
            raise ValueError(msg)
        return AccessScope.DEPT, None, parts[1]
    if top == "private":
        if len(parts) < 2:
            msg = f"PRIVATE path must include owner segment: {stored_path!r}"
            raise ValueError(msg)
        return AccessScope.PRIVATE, parts[1], None

    msg = f"Unknown inbox path layout (expected public|dept|private): {stored_path!r}"
    raise ValueError(msg)
