"""Swarm Clock: the single source of "now" for the whole backend.

Nothing in Swarm reads the system clock directly. Production uses `SystemClock`; tests and
the demo use `SwarmClock`, which can be set and advanced so a demo can move through a
week (Monday forecasts ... Sunday report) in minutes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


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

    def to_dict(self) -> dict[str, str]:
        return {"now": self._now.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> SwarmClock:
        return cls(datetime.fromisoformat(data["now"]))

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


# ---------------------------------------------------------------------------------------
# Business calendar. Shops live in Singapore, so "Monday" means Monday in Singapore.
# ---------------------------------------------------------------------------------------

BUSINESS_TZ = ZoneInfo("Asia/Singapore")

# What the swarm does on each day of the week (SWARM_SPEC 6.6).
WEEK_PLAN: dict[int, tuple[str, str]] = {
    0: ("Monday", "Forecasts: each shop agent proposes next week's needs"),
    1: ("Tuesday", "Pooling and negotiation with supplier agents"),
    2: ("Wednesday", "PayPal holds on every participating shop"),
    3: ("Thursday", "Delivery: capture what actually arrived"),
    4: ("Friday", "Surplus swaps between neighbours"),
    5: ("Saturday", "Emergency borrowing"),
    6: ("Sunday", "Weekly savings report"),
}


def local_time(instant: datetime) -> datetime:
    return _as_utc(instant).astimezone(BUSINESS_TZ)


def week_start(instant: datetime) -> date:
    """The Monday (Singapore time) of the week containing `instant`."""
    local = local_time(instant)
    return (local - timedelta(days=local.weekday())).date()


def at_local(day: date, hour: int = 9, minute: int = 0) -> datetime:
    """A Singapore wall-clock time on `day`, as UTC."""
    return datetime.combine(day, time(hour, minute), tzinfo=BUSINESS_TZ).astimezone(UTC)


def week_day(instant: datetime) -> tuple[str, str]:
    """(day name, what happens today) for the Swarm week plan."""
    return WEEK_PLAN[local_time(instant).weekday()]
