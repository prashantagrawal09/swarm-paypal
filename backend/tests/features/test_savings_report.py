"""The weekly report's wording follows what actually happened."""

from __future__ import annotations

from datetime import date

import pytest

from app.features.savings import ShopWeek, report_text


def test_surplus_sales_and_emergency_help_are_reported_separately():
    week = ShopWeek("little-pasta", "Little Pasta", date(2026, 10, 12))
    week.help_income_cents = 852
    text = report_text(week, 0)
    assert "Helping a neighbour in a pinch brought in S$8.52." in text
    assert "selling surplus" not in text and "kg of food" not in text

    week.swap_income_cents, week.food_saved_grams = 968, 8400
    text = report_text(week, 0)
    assert "You earned S$9.68 selling surplus (8.4 kg of food saved)." in text


@pytest.mark.db
async def test_batched_reads_agree_with_the_per_shop_rules(db, world, ctx):
    """The live board reads every shop in a few queries; the answers must be exactly what
    the per-shop rules (the ones that enforce limits and write reports) give."""
    from sqlalchemy import select

    from app.db.models import Shop
    from app.features import savings
    from app.features.week import WeekRunner
    from tests.conftest import DEMO_WEEK

    runner = WeekRunner(ctx, DEMO_WEEK)
    while (await runner.run_next())[0] is not None:
        pass

    shops = list(await db.scalars(select(Shop).order_by(Shop.code)))
    reports = await savings.week_reports(ctx, DEMO_WEEK)
    committed = await ctx.engine.committed_by_shop(DEMO_WEEK)
    assert sum(r.total_saved_cents for r in reports.values()) > 0
    for shop in shops:
        single = await savings.shop_week(ctx, shop, DEMO_WEEK)
        assert reports[shop.id].to_dict() == single.to_dict()
        assert committed.get(shop.id, 0) == await ctx.engine.committed_this_week(shop.id, DEMO_WEEK)
    # Someone bought a flash deal and someone bought surplus, so both paths are exercised.
    assert any(r.flash_saved_cents for r in reports.values())
    assert any(r.swap_spent_cents for r in reports.values())


@pytest.mark.db
async def test_read_models_are_shared_until_something_happens(db, world, ctx):
    from app.api.readcache import shared

    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await shared(ctx, "k", compute) == 1
    assert await shared(ctx, "k", compute) == 1  # same moment: reused
    await ctx.bus.emit("anything", {})
    assert await shared(ctx, "k", compute) == 2  # something happened: recomputed
    assert await shared(ctx, "other", compute) == 3  # keys are independent
