"""Live endpoints: the Server-Sent Events stream and the agent conversation log."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bus import MessageBus, message_dict
from app.db.models import AgentMessage
from app.db.session import get_session
from app.runtime import get_bus

router = APIRouter(prefix="/api", tags=["live"])


@router.get("/stream")
async def stream(bus: Annotated[MessageBus, Depends(get_bus)]) -> StreamingResponse:
    """Agent messages and PayPal events as they happen (text/event-stream)."""
    return StreamingResponse(
        bus.sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
