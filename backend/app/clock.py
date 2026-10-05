"""Swarm Clock: the single source of "now" for the whole backend.

Nothing in Swarm reads the system clock directly. Production uses `SystemClock`; tests and
the demo use `SwarmClock`, which can be set and advanced so a demo can move through a
week (Monday forecasts ... Sunday report) in minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """Real wall-clock time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SwarmClock:
    """A controllable clock. Starts at a fixed instant and only moves when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = _as_utc(start) if start else datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, instant: datetime) -> None:
        self._now = _as_utc(instant)

    def advance(self, *, days: float = 0, hours: float = 0, minutes: float = 0) -> datetime:
        delta = timedelta(days=days, hours=hours, minutes=minutes)
        if delta < timedelta(0):
            raise ValueError("The Swarm Clock only moves forward")
        self._now += delta
        return self._now


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Swarm Clock needs timezone-aware datetimes")
    return value.astimezone(UTC)
