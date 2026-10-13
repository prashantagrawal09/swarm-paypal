"""Forecasts, pooling, the award rule, substitutions and delivery."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.enums import Category, ForecastStatus, GroupOrderStatus
from app.db.models import DemandForecast, Supplier
from app.features import demand, group_buy
from app.features.group_buy import QuoteSummary, choose_winner
from app.money import rules
from tests.conftest import DEMO_WEEK
from tests.helpers import prepare_week, shops_by_code

pytestmark = pytest.mark.db


async def test_forecasts_use_the_four_week_average(db, world):
    shops = await shops_by_code(db)
    forecasts = await demand.forecast_shop(db, shops["cafe-mei"], DEMO_WEEK)
    milk = next(f for f in forecasts if f.product_code == "milk-full-cream-1l")
    assert milk.weeks_used == 4
    assert milk.predicted_qty == round(milk.average_qty * milk.multiplier)
    assert "last 4 weeks averaged" in milk.explanation
    assert await demand.propose_week(db, DEMO_WEEK) > 0
    assert await demand.propose_week(db, DEMO_WEEK) == 0  # idempotent


async def test_weather_outlook_moves_the_forecast_by_each_shops_rain_sensitivity(db, world):
    shops = await shops_by_code(db)
    outlook = demand.week_outlook(DEMO_WEEK)
    assert {demand.DAY_NAMES[d] for d, c in outlook.items() if c == "rainy"} == {
        "Thursday",
        "Friday",
        "Saturday",
    }
    hawker = demand.weather_effect(shops["uncle-tan-noodles"], DEMO_WEEK)  # rain factor 0.80
    tea = demand.weather_effect(shops["teh-time"], DEMO_WEEK)  # rain factor 1.10
    assert hawker.multiplier < 1 < tea.multiplier
    assert hawker.summary == "rain on Thursday, Friday and Saturday"
    # A week with no outlook is a usual week.
    assert (
        demand.weather_effect(shops["uncle-tan-noodles"], DEMO_WEEK.replace(day=5)).multiplier == 1
    )
    forecasts = await demand.forecast_shop(db, shops["uncle-tan-noodles"], DEMO_WEEK)
    assert all("for rain on Thursday" in f.explanation for f in forecasts)
    assert "less" in demand.week_note(forecasts)


def test_weather_effect_weights_busy_days_more(monkeypatch):
    """Rain on a busy Saturday costs more than rain on a quiet Monday."""
    from datetime import date
    from types import SimpleNamespace

    shop = SimpleNamespace(
        opening_hours={"days": "Daily"},
        preferences={"traffic": {"rain_factor": 0.8, "weekend_lift": 1.5}},
    )
    base = demand.demand_config()
    week = date(2026, 11, 16)

    def effect(rainy_day: str) -> float:
        config = {**base, "weather_outlook": {rainy_day: "rainy"}}
        monkeypatch.setattr(demand, "demand_config", lambda: config)
        return demand.weather_effect(shop, week).multiplier  # type: ignore[arg-type]

    assert effect("2026-11-21") < effect("2026-11-16") < 1


async def test_confirm_change_and_skip(db, world, clock):
    shops = await shops_by_code(db)
    await demand.propose_week(db, DEMO_WEEK)
    mei = shops["cafe-mei"]
    rows = await demand.confirm_week(db, mei.id, DEMO_WEEK, clock.now())
    changed = rows[0]
    assert changed.status == ForecastStatus.CONFIRMED
    await demand.skip_week(db, shops["teh-time"].id, DEMO_WEEK, clock.now())
    skipped = list(
        await db.scalars(
            select(DemandForecast).where(DemandForecast.shop_id == shops["teh-time"].id)
        )
    )
    assert {row.status for row in skipped} == {ForecastStatus.SKIPPED}


async def test_pooling_makes_one_group_order_per_category(db, world, clock):
    groups = await prepare_week(db, DEMO_WEEK, clock)
    assert set(groups) == set(Category)
    dairy = await group_buy.load_group(db, groups[Category.DAIRY].id)
    pooled = group_buy.pooled_quantities(dairy)
    assert pooled["milk-full-cream-1l"] > 250  # twelve shops' milk becomes one big order
    assert len(dairy.shop_orders) == 12
    again = await group_buy.pool_week(db, DEMO_WEEK, clock.now())
    assert {g.id for g in again} == {g.id for g in groups.values()}


def test_award_rule_lowest_landed_cost_among_reliable_suppliers():
    def quote(code: str, reliability: int, price: int, fee: int) -> QuoteSummary:
        return QuoteSummary(uuid.uuid4(), code, reliability, {"milk": price}, {"milk": 100}, fee)

    cheap_unreliable = quote("risky", 70, 150, 0)
    a = quote("a", 90, 200, 3000)
    b = quote("b", 95, 200, 3000)
    c = quote("c", 88, 199, 3200)
    assert choose_winner([cheap_unreliable, a, c]).supplier_code == "a"  # 23000 vs 23100
    assert choose_winner([a, b]).supplier_code == "b"  # tie -> more reliable
    assert choose_winner([cheap_unreliable]) is None


async def test_award_maps_lines_and_respects_brand_preferences(db, world, clock):
    groups = await prepare_week(db, DEMO_WEEK, clock)
    result = await group_buy.award_at_list_prices(db, groups[Category.DAIRY].id)
    assert result is not None and result.supplier_code == "johorfarm"
    excluded = {(e["shop"], e["product"]) for e in result.excluded}
    assert ("sunrise-bakes", "milk-full-cream-1l") in excluded
    dairy = await group_buy.load_group(db, groups[Category.DAIRY].id)
    assert dairy.status == GroupOrderStatus.AWARDED
    assert sum(so.delivery_share_cents for so in dairy.shop_orders) == dairy.delivery_fee_cents
    for so in dairy.shop_orders:
        for line in so.lines:
            assert line.item.brand in ("Farm Gold", "Kampung Gold", "Anchorvale")
            assert line.agreed_unit_price_cents <= line.alone_unit_price_cents
    savings = group_buy.savings_for_group(dairy)
    assert all(s.saved_cents > 0 for s in savings)


async def test_award_refuses_prices_below_the_floor(db, world, clock):
    groups = await prepare_week(db, DEMO_WEEK, clock)
    johor = await db.scalar(select(Supplier).where(Supplier.code == "johorfarm"))
    with pytest.raises(rules.RuleViolation) as exc:
        await group_buy.apply_award(
            db,
            groups[Category.DAIRY].id,
            johor.id,
            {"milk-full-cream-1l": 150, "eggs-tray-30": 800, "butter-250g": 405},
        )
    assert exc.value.code == "BELOW_FLOOR"


async def test_suppliers_that_cannot_supply_everything_decline(db, world, clock):
    offers, declined = await group_buy.supplier_offers(db, ["tomatoes-1kg", "lettuce-1kg"])
    assert [o.supplier.code for o in offers] == ["johorfarm"]
    assert {s.code for s, _ in declined} == {"freshdairy", "packpro"}


async def test_a_forecast_carries_the_weeks_it_is_based_on(db, world):
    from app.db.models import Shop
    from app.features import demand

    shop = await db.scalar(select(Shop).where(Shop.code == "cafe-mei"))
    forecasts = await demand.forecast_shop(db, shop, DEMO_WEEK)
    assert forecasts
    for forecast in forecasts:
        assert len(forecast.history) == forecast.weeks_used == demand.LOOKBACK_WEEKS
        assert all(qty > 0 for qty in forecast.history)
        # The average the explanation quotes is the average of exactly these weeks.
        assert forecast.average_qty == round(sum(forecast.history) / len(forecast.history), 1)
