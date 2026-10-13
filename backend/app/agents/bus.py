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
from collections.abc import AsyncIterator, Awaitable, Callable
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
    # Position in the recorded stream (None when nothing is recording). Sent as the SSE id,
    # so a reconnecting browser can say where it got to.
    seq: int | None = None

    def to_sse(self) -> str:
        head = f"id: {self.seq}\n" if self.seq is not None else ""
        return f"{head}event: {self.event}\ndata: {json.dumps(self.data, default=str)}\n\n"


# Takes (event name, data), stores it and returns its position in the stream.
Recorder = Callable[[str, dict[str, Any]], Awaitable[int]]
# Housekeeping for the people at the controls, not part of the week's story.
UNRECORDED_KINDS = frozenset({"reset", "demo_action"})


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
        # Set by the running app (see `StreamRecorder`); tests and scripts leave it off.
        self.recorder: Recorder | None = None
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

    async def announce(self, event: str, data: dict[str, Any]) -> None:
        """Record (when recording is on), then send to everyone connected."""
        seq: int | None = None
        if self.recorder is not None and data.get("kind") not in UNRECORDED_KINDS:
            try:
                seq = await self.recorder(event, data)
            except Exception:
                # The week matters more than its recording.
                logger.exception("Could not record a %s stream event", event)
        self.broadcast(BusEvent(event, data, seq))

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
        await self.announce("agent_message", message_dict(message))
        if self.pace_seconds > 0:
            owner_side = from_agent.startswith("owner:") or to_agent.startswith("owner:")
            await asyncio.sleep(self.pace_seconds / 12 if owner_side else self.pace_seconds)
        return message

    async def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """EventSink for the money engine: PayPal events on the live stream."""
        await self.announce("paypal", {"kind": kind, "at": self.clock.now().isoformat(), **payload})

    # -- SSE ------------------------------------------------------------------------------

    async def sse(
        self,
        heartbeat: float = HEARTBEAT_SECONDS,
        missed: Callable[[], Awaitable[list[BusEvent]]] | None = None,
    ) -> AsyncIterator[str]:
        """The stream for one browser. `missed` loads what a reconnecting browser didn't
        get; it runs after subscribing, so nothing can fall between the two."""
        queue = self.subscribe()
        try:
            yield BusEvent("hello", {"at": self.clock.now().isoformat()}).to_sse()
            caught_up_to = 0
            if missed is not None:
                for event in await missed():
                    caught_up_to = max(caught_up_to, event.seq or 0)
                    yield event.to_sse()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event.seq is not None and event.seq <= caught_up_to:
                    continue  # already sent as part of the catch-up
                yield event.to_sse()
        finally:
            self.unsubscribe(queue)
