"""Agent message bus: every agent-to-agent message is stored, then streamed live.

- `publish()` writes the message to `agent_messages` (the A2A-style log the live board
  replays) and pushes it to every connected Server-Sent Events subscriber.
- `emit()` makes the bus the money engine's event sink, so holds, captures, payouts and
  refunds appear on the same live stream.

Subscribers get a bounded queue; a slow browser loses its oldest events rather than
slowing the agents down.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.db.models import AgentMessage

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0


@dataclass(frozen=True)
class BusEvent:
    event: str
    data: dict[str, Any]

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, default=str)}\n\n"


def message_dict(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "seq": message.seq,
        "conversation_id": message.conversation_id,
        "from": message.from_agent,
        "to": message.to_agent,
        "type": message.type,
        "text": message.text,
        "payload": message.payload,
        "at": message.created_at.isoformat(),
    }


class MessageBus:
    def __init__(self, clock: Clock, queue_size: int = 500) -> None:
        self.clock = clock
        self.queue_size = queue_size
        # Demo playback: pause after each message so the live board can be followed.
        self.pace_seconds = 0.0
        # Moves on every message and event, so read models can tell "nothing has happened".
        self.version = 0
        self._subscribers: set[asyncio.Queue[BusEvent]] = set()

    # -- subscribers ----------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[BusEvent]:
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[BusEvent]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def broadcast(self, event: BusEvent) -> None:
        self.version += 1
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # drop the oldest event for this slow subscriber
            queue.put_nowait(event)

    # -- publishing -----------------------------------------------------------------------

    async def publish(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        from_agent: str,
        to_agent: str,
        type: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            conversation_id=conversation_id,
            from_agent=from_agent,
            to_agent=to_agent,
            type=type,
            text=text,
            payload=payload or {},
            created_at=self.clock.now(),
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        self.broadcast(BusEvent("agent_message", message_dict(message)))
        if self.pace_seconds > 0:
            owner_side = from_agent.startswith("owner:") or to_agent.startswith("owner:")
            await asyncio.sleep(self.pace_seconds / 12 if owner_side else self.pace_seconds)
        return message

    async def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """EventSink for the money engine: PayPal events on the live stream."""
        self.broadcast(
            BusEvent("paypal", {"kind": kind, "at": self.clock.now().isoformat(), **payload})
        )

    # -- SSE ------------------------------------------------------------------------------

    async def sse(self, heartbeat: float = HEARTBEAT_SECONDS) -> AsyncIterator[str]:
        queue = self.subscribe()
        try:
            yield BusEvent("hello", {"at": self.clock.now().isoformat()}).to_sse()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield event.to_sse()
        finally:
            self.unsubscribe(queue)
