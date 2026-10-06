"""Event sink used by the money engine and agents to announce what just happened.

The live board subscribes to these (via the message bus and SSE). Tests use
`RecordingEventSink` to assert on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class EventSink(Protocol):
    async def emit(self, kind: str, payload: dict[str, Any]) -> None: ...


class NullEventSink:
    async def emit(self, kind: str, payload: dict[str, Any]) -> None:
        return None


@dataclass
class RecordingEventSink:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def emit(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]
