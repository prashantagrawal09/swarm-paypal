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
) -> list[dict[str, Any]]:
    """The conversation log, oldest first (use `after_seq` to page forward)."""
    query = select(AgentMessage).where(AgentMessage.seq > after_seq)
    if conversation_id:
        query = query.where(AgentMessage.conversation_id == conversation_id)
    rows = await session.scalars(query.order_by(AgentMessage.seq).limit(limit))
    return [message_dict(row) for row in rows]
