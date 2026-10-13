"""Keeps the live stream: every agent message and PayPal event, in the order it was sent.

Two things read it back. The watch page replays a finished week for each visitor, without
resetting anything or calling PayPal again. And a browser whose connection dropped asks for
what it missed (Server-Sent Events' `Last-Event-ID`) instead of silently skipping it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import week_start
from app.db.models import StreamEvent

KEEP_WEEKS = 4
FIRST_STEP = "forecasts"


class StreamRecorder:
    """Writes one row per event through its own short transaction, so recording never
    depends on (or commits) whatever the caller is in the middle of."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], now: Callable[[], datetime]
    ) -> None:
        self._sessions = sessions
        self._now = now

    async def __call__(self, event: str, data: dict[str, Any]) -> int:
        week = week_start(self._now())
        row = StreamEvent(
            week_start=week,
            event=event,
            # The same shape the browser gets: dates and IDs as strings.
            data=json.loads(json.dumps(data, default=str)),
        )
        async with self._sessions() as session:
            if data.get("kind") == "step_started" and data.get("step") == FIRST_STEP:
                # A new week is starting: let go of weeks nobody will replay any more.
                await session.execute(
                    delete(StreamEvent).where(
                        StreamEvent.week_start < week - timedelta(weeks=KEEP_WEEKS)
                    )
                )
            session.add(row)
            await session.commit()
            return row.seq


def as_dict(row: StreamEvent) -> dict[str, Any]:
    return {"seq": row.seq, "event": row.event, "data": row.data}


async def recorded(
    session: AsyncSession, *, week: date | None = None, after: int = 0, limit: int | None = None
) -> list[StreamEvent]:
    """Recorded events after `after`, oldest first, for one week or (week=None) all of them."""
    query = select(StreamEvent).where(StreamEvent.seq > after).order_by(StreamEvent.seq)
    if week is not None:
        query = query.where(StreamEvent.week_start == week)
    if limit is not None:
        query = query.limit(limit)
    return list(await session.scalars(query))
