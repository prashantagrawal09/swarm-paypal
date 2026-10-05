"""Tests for the Swarm Clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.clock import SwarmClock, SystemClock


def test_swarm_clock_only_moves_when_told():
    start = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    clock = SwarmClock(start)
    assert clock.now() == start
    clock.advance(days=1, hours=2)
    assert clock.now() == start + timedelta(days=1, hours=2)


def test_swarm_clock_refuses_to_go_backwards():
    clock = SwarmClock(datetime(2026, 10, 5, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.advance(days=-1)


def test_swarm_clock_normalises_to_utc_and_rejects_naive_times():
    sgt = timezone(timedelta(hours=8))
    clock = SwarmClock(datetime(2026, 10, 5, 8, 0, tzinfo=sgt))
    assert clock.now() == datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 10, 5))


def test_system_clock_is_timezone_aware():
    assert SystemClock().now().tzinfo is not None
