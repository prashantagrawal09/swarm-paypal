"""Live endpoints: the Server-Sent Events stream and the agent conversation log."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import DECISION_PREFIX
from app.agents.bus import BusEvent, MessageBus, message_dict
from app.agents.recorder import as_dict, recorded
from app.clock import Clock, week_start
from app.config import Settings, get_settings
from app.db.models import AgentMessage, AuditLog, StreamEvent
from app.db.session import get_session, get_sessionmaker
from app.runtime import get_bus, get_clock

router = APIRouter(prefix="/api", tags=["live"])


MAX_CATCH_UP = 500


@router.get("/stream")
async def stream(
    bus: Annotated[MessageBus, Depends(get_bus)],
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Agent messages and PayPal events as they happen (text/event-stream).

    A browser that reconnects sends the ID of the last event it received; it first gets
    everything recorded since, then carries on live.
    """
    missed = None
    if last_event_id and last_event_id.isdigit():
        after = int(last_event_id)

        async def missed() -> list[BusEvent]:
            async with get_sessionmaker()() as session:
                rows = await recorded(session, after=after, limit=MAX_CATCH_UP)
            return [BusEvent(row.event, row.data, row.seq) for row in rows]

    return StreamingResponse(
        bus.sse(missed=missed),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/timeline")
async def timeline(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    week: date | None = None,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The recorded stream of one week, oldest first: this week, or the last recorded week
    when this one hasn't started, or the `week` asked for.

    The watch page plays it back: same events, same order as they were sent live. `after`
    returns only what was recorded since that position.
    """
    if week is None:
        week = week_start(clock.now())
        rows = await recorded(session, week=week, after=after)
        if not rows and after == 0:
            # Nothing this week yet (a new week has just begun): offer the last one recorded.
            latest = await session.scalar(select(func.max(StreamEvent.week_start)))
            if latest is not None and latest != week:
                week = latest
                rows = await recorded(session, week=week)
    else:
        rows = await recorded(session, week=week, after=after)
    return {
        "week": str(week),
        "last_seq": rows[-1].seq if rows else after,
        "events": [as_dict(row) for row in rows],
    }


@router.get("/agent-messages")
async def agent_messages(
    session: Annotated[AsyncSession, Depends(get_session)],
    conversation_id: str | None = None,
    after_seq: int = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    tail: bool = False,
    agents_only: bool = False,
) -> list[dict[str, Any]]:
    """The conversation log, oldest first. `after_seq` pages forward; `tail` returns the most
    recent `limit` messages; `agents_only` leaves out owner chats."""
    query = select(AgentMessage).where(AgentMessage.seq > after_seq)
    if conversation_id:
        query = query.where(AgentMessage.conversation_id == conversation_id)
    if agents_only:
        query = query.where(
            ~AgentMessage.to_agent.startswith("owner:"),
            ~AgentMessage.from_agent.startswith("owner:"),
        )
    if tail:
        newest = await session.scalars(query.order_by(AgentMessage.seq.desc()).limit(limit))
        return [message_dict(row) for row in reversed(list(newest))]
    rows = await session.scalars(query.order_by(AgentMessage.seq).limit(limit))
    return [message_dict(row) for row in rows]


@router.get("/agent-messages/{message_id}/decision")
async def message_decision(
    message_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """How the decision behind a message was reached: the options code allowed, who chose
    (the language model, the built-in policy, or a rule), and the rules the choice passed.

    A supplier's options are its own business. They are shown in the demo, which lets you
    look inside every agent; outside demo mode they are left out.
    """
    row = await session.scalar(
        select(AuditLog)
        .where(
            AuditLog.action.startswith(DECISION_PREFIX),
            AuditLog.details["message_id"].astext == str(message_id),
        )
        .order_by(AuditLog.seq.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No decision is recorded for this message")
    details = {k: v for k, v in row.details.items() if k != "message_id"}
    kind = row.action.removeprefix(DECISION_PREFIX)
    private = kind == "quote"
    if private and not settings.demo_mode:
        details.pop("options", None)
    return {
        "message_id": str(message_id),
        "actor": row.actor,
        "kind": kind,
        "at": row.created_at.isoformat(),
        "private": private,
        **details,
    }
