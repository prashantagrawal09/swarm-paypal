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


@pytest.mark.db
async def test_new_rows_take_the_swarm_clock_time(db, world):
    from sqlalchemy import select

    from app.db.base import stamp_rows_with
    from app.db.enums import Category
    from app.db.models import Item

    swarm_now = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
    stamp_rows_with(lambda: swarm_now)
    try:
        first = Item(
            sku="T-1",
            product_code="t",
            name="T1",
            brand="b",
            category=Category.DAIRY,
            unit="u",
            unit_weight_grams=1,
            shelf_life_days=1,
            attributes={},
        )
        second = Item(
            sku="T-2",
            product_code="t",
            name="T2",
            brand="b",
            category=Category.DAIRY,
            unit="u",
            unit_weight_grams=1,
            shelf_life_days=1,
            attributes={},
        )
        db.add_all([first, second])
        await db.commit()
        stamped = {
            i.sku: i.created_at
            for i in await db.scalars(select(Item).where(Item.product_code == "t"))
        }
        assert stamped["T-1"] == swarm_now
        assert stamped["T-2"] > stamped["T-1"]  # same instant, still in creation order
    finally:
        stamp_rows_with(None)
