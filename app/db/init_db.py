"""
Development-only database bootstrap.

Uses SQLAlchemy ``Base.metadata.create_all()`` to create tables from ORM models.

**Not for production:** there is no migration history, no drift detection, and
``create_all`` will not alter or drop existing columns/tables. For production,
use Alembic (or another migration tool) once the schema has stabilized.
"""

from __future__ import annotations

# Import models so their tables are registered on Base.metadata before create_all.
import app.db.models  # noqa: F401

from app.db.base import Base
from app.db.session import get_engine


def init_dev_database() -> None:
    """Create all tables defined on ``Base`` if they do not exist (dev / local PoC)."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def main() -> None:
    init_dev_database()
    print("Dev DB tables created (create_all).")


if __name__ == "__main__":
    main()
