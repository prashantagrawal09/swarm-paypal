"""Declarative base and shared column mixins (UUID primary keys, timestamps)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# Stable constraint names so Alembic autogenerate produces clean, reviewable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------------------
# Business-time stamps
# ---------------------------------------------------------------------------------------
# In demo mode the app runs on the Swarm Clock, so new rows are stamped with its time
# rather than the database's wall clock; otherwise a payment made on "Thursday 08:00"
# would show today's real time. Rows created in the same instant get microsecond steps so
# they still sort in creation order.

_now: Callable[[], datetime] | None = None
_last: datetime | None = None


def stamp_rows_with(now: Callable[[], datetime] | None) -> None:
    """Use `now` for rows' created_at / updated_at (None restores the database defaults)."""
    global _now, _last
    _now, _last = now, None


def _next_stamp(now: datetime) -> datetime:
    global _last
    if _last is not None and timedelta(0) <= _last - now < timedelta(seconds=1):
        now = _last + timedelta(microseconds=1)
    _last = now
    return now


@event.listens_for(Session, "before_flush")
def _stamp_new_rows(session: Session, _context: Any, _instances: Any) -> None:
    if _now is None:
        return
    for obj in session.new:
        if isinstance(obj, Timestamps) and obj.created_at is None:
            obj.created_at = obj.updated_at = _next_stamp(_now())
    for obj in session.dirty:
        if isinstance(obj, Timestamps) and session.is_modified(obj, include_collections=False):
            obj.updated_at = _next_stamp(_now())
