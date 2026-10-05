"""ORM models. Tables arrive in Phase 2 (data model and money engine).

Alembic imports this module so every model registered on `Base.metadata` is visible to
autogenerate.
"""

from app.db.base import Base

__all__ = ["Base"]
