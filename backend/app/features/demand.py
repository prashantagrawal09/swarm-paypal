"""Demand prediction (F6): what each shop will need next week.

Simple and explainable on purpose: the average of the last four weeks a shop bought each
product (before Swarm from purchase history, after Swarm from its group-order lines), times
two multipliers from `seed/data/demand.json`:

- weather: the coming week's outlook against the usual mix of weather. Each trading day
  counts by how busy it normally is (weekday factors, plus the shop's weekend lift), and a
  rainy day costs a shop its own rain factor (a hawker loses more than a tea house);
- holiday: a week with a public holiday sells more.

The explanation is a plain sentence; the shop agent's language model may rephrase it for the
owner, but the number always comes from this code.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ForecastStatus, GroupOrderStatus, ShopStatus
from app.db.models import DemandForecast, GroupOrder, GroupOrderLine, Item, PurchaseHistory, Shop
from app.features.products import describe

CONFIG_PATH = Path(__file__).resolve().parents[1] / "seed" / "data" / "demand.json"
LOOKBACK_WEEKS = 4
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OPEN_DAYS = {
    "Daily": {0, 1, 2, 3, 4, 5, 6},
    "Tue-Sun": {1, 2, 3, 4, 5, 6},
    "Mon-Sat": {0, 1, 2, 3, 4, 5},
}


@lru_cache
def demand_config() -> dict[str, Any]:
    config: dict[str, Any] = json.loads(CONFIG_PATH.read_text())
    return config


@dataclass(frozen=True)
class ProductForecast:
    product_code: str
    item_id: uuid.UUID
    item_name: str
    unit: str
    predicted_qty: int
    average_qty: float
    weeks_used: int
    holiday: str | None
    explanation: str
    weather: str | None = None
    multiplier: float = 1.0
    # What the shop used in each of the weeks the forecast is based on, oldest first.
    history: tuple[int, ...] = ()


def holiday_in_week(week_start: date) -> str | None:
    holidays: dict[str, str] = demand_config()["holidays"]
    for offset in range(7):
        name = holidays.get((week_start + timedelta(days=offset)).isoformat())
        if name:
            return name
    return None


def open_days(shop: Shop) -> set[int]:
    return OPEN_DAYS.get(str(shop.opening_hours.get("days", "Daily")), OPEN_DAYS["Daily"])


def week_outlook(week_start: date) -> dict[int, str]:
    """Forecast conditions for the week's days (weekday index -> condition), where known."""
    outlook: dict[str, str] = demand_config().get("weather_outlook", {})
    days = {}
    for offset in range(7):
        condition = outlook.get((week_start + timedelta(days=offset)).isoformat())
        if condition:
            days[offset] = condition
    return days


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


@dataclass(frozen=True)
class WeatherEffect:
    multiplier: float
    summary: str | None  # "rain on Thursday, Friday and Saturday"


def weather_effect(shop: Shop, week_start: date) -> WeatherEffect:
    """How the coming week's weather should move this shop's orders versus a usual week."""
    outlook = week_outlook(week_start)
    trading = open_days(shop)
    if not any(day in trading for day in outlook):
        return WeatherEffect(1.0, None)
    config = demand_config()
    traffic = shop.preferences.get("traffic", {})
    rain = float(traffic.get("rain_factor", config["weather"]["rainy"]))
    lift = float(traffic.get("weekend_lift", 1.0))
    p_rain = float(config["weather_weights"]["rainy"])
    usual = 1 - p_rain + p_rain * rain  # the weather mix already in the history
    weighted = total = 0.0
    for day in sorted(trading):
        weight = config["weekday_factors"][day] * (lift if day >= 5 else 1.0)
        condition = outlook.get(day)
        factor = rain if condition == "rainy" else 1.0 if condition else usual
        weighted += weight * factor
        total += weight
    rainy = [
        DAY_NAMES[day] for day in sorted(outlook) if outlook[day] == "rainy" and day in trading
    ]
    summary = f"rain on {_join(rainy)}" if rainy else "a dry week"
    return WeatherEffect(round(weighted / total / usual, 4), summary)


async def weekly_history(
    session: AsyncSession, shop_id: uuid.UUID, before: date
) -> dict[str, dict[date, int]]:
    """Quantity per product per week: pre-Swarm purchases plus Swarm group-order lines."""
    history: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    purchases = await session.execute(
        select(Item.product_code, PurchaseHistory.week_start, PurchaseHistory.qty)
        .join(Item, Item.id == PurchaseHistory.item_id)
        .where(PurchaseHistory.shop_id == shop_id, PurchaseHistory.week_start < before)
    )
    for product, week, qty in purchases.all():
        history[product][week] += qty
    lines = await session.execute(
        select(
            Item.product_code,
            GroupOrder.week_start,
            GroupOrderLine.qty_requested,
            GroupOrderLine.qty_delivered,
        )
        .join(Item, Item.id == GroupOrderLine.item_id)
        .join(GroupOrder, GroupOrder.id == GroupOrderLine.group_order_id)
        .where(
            GroupOrderLine.shop_id == shop_id,
            GroupOrder.week_start < before,
            GroupOrder.status != GroupOrderStatus.CANCELLED,
        )
    )
    for product, week, requested, delivered in lines.all():
        history[product][week] += delivered if delivered is not None else requested
    return history


async def forecast_shop(
    session: AsyncSession, shop: Shop, week_start: date
) -> list[ProductForecast]:
    history = await weekly_history(session, shop.id, week_start)
    holiday = holiday_in_week(week_start)
    holiday_factor = demand_config()["holiday_week_factor"] if holiday else 1.0
    weather = weather_effect(shop, week_start)
    factor = holiday_factor * weather.multiplier
    preferred: dict[str, str] = shop.preferences.get("preferred_skus", {})
    items = {
        item.sku: item
        for item in await session.scalars(select(Item).where(Item.sku.in_(preferred.values())))
    }
    forecasts = []
    for product, sku in sorted(preferred.items()):
        weeks = sorted(history.get(product, {}).items())[-LOOKBACK_WEEKS:]
        if not weeks or sku not in items:
            continue
        average = sum(qty for _, qty in weeks) / len(weeks)
        predicted = max(1, round(average * factor))
        item = items[sku]
        explanation = (
            f"About {describe(product, predicted)}: your last "
            f"{len(weeks)} weeks averaged {average:.0f}"
        )
        change = round((weather.multiplier - 1) * 100)
        if weather.summary and change:
            explanation += (
                f", {'plus' if change > 0 else 'minus'} {abs(change)}% for {weather.summary}"
            )
        if holiday:
            explanation += f", plus {round((holiday_factor - 1) * 100)}% for {holiday}"
        forecasts.append(
            ProductForecast(
                product_code=product,
                item_id=item.id,
                item_name=item.name,
                unit=item.unit,
                predicted_qty=predicted,
                average_qty=round(average, 1),
                weeks_used=len(weeks),
                holiday=holiday,
                weather=weather.summary,
                multiplier=round(factor, 4),
                explanation=explanation + ".",
                history=tuple(qty for _, qty in weeks),
            )
        )
    return forecasts


async def propose_week(session: AsyncSession, week_start: date) -> int:
    """Create PROPOSED forecasts for every active shop. Idempotent."""
    existing = {
        (shop_id, item_id)
        for shop_id, item_id in (
            await session.execute(
                select(DemandForecast.shop_id, DemandForecast.item_id).where(
                    DemandForecast.week_start == week_start
                )
            )
        ).all()
    }
    created = 0
    shops = await session.scalars(select(Shop).where(Shop.status == ShopStatus.ACTIVE))
    for shop in shops:
        for forecast in await forecast_shop(session, shop, week_start):
            if (shop.id, forecast.item_id) in existing:
                continue
            session.add(
                DemandForecast(
                    shop_id=shop.id,
                    week_start=week_start,
                    item_id=forecast.item_id,
                    predicted_qty=forecast.predicted_qty,
                    explanation=forecast.explanation,
                    details={
                        "product_code": forecast.product_code,
                        "average_qty": forecast.average_qty,
                        "weeks_used": forecast.weeks_used,
                        "holiday": forecast.holiday,
                        "weather": forecast.weather,
                        "multiplier": forecast.multiplier,
                    },
                )
            )
            created += 1
    await session.commit()
    return created


async def confirm_week(
    session: AsyncSession,
    shop_id: uuid.UUID,
    week_start: date,
    now: datetime,
    overrides: dict[uuid.UUID, int] | None = None,
) -> list[DemandForecast]:
    """Owner confirms the forecast (optionally changing quantities; 0 skips an item)."""
    overrides = overrides or {}
    forecasts = list(
        await session.scalars(
            select(DemandForecast).where(
                DemandForecast.shop_id == shop_id, DemandForecast.week_start == week_start
            )
        )
    )
    for forecast in forecasts:
        if forecast.status != ForecastStatus.PROPOSED:
            continue
        qty = overrides.get(forecast.item_id, forecast.predicted_qty)
        if qty < 0:
            raise ValueError("Quantities cannot be negative")
        forecast.confirmed_qty = qty
        forecast.confirmed_at = now
        forecast.status = ForecastStatus.CONFIRMED if qty > 0 else ForecastStatus.SKIPPED
    await session.commit()
    return forecasts


async def skip_week(
    session: AsyncSession, shop_id: uuid.UUID, week_start: date, now: datetime
) -> None:
    forecasts = await session.scalars(
        select(DemandForecast).where(
            DemandForecast.shop_id == shop_id,
            DemandForecast.week_start == week_start,
            DemandForecast.status == ForecastStatus.PROPOSED,
        )
    )
    for forecast in forecasts:
        forecast.status = ForecastStatus.SKIPPED
        forecast.confirmed_qty = 0
        forecast.confirmed_at = now
    await session.commit()


def week_note(forecasts: list[ProductForecast]) -> str:
    """One plain line on why this week's numbers are what they are."""
    if not forecasts:
        return ""
    first = forecasts[0]
    weeks = max(f.weeks_used for f in forecasts)
    note = f"Based on your last {weeks} weeks"
    change = round((first.multiplier - 1) * 100)
    reasons = []
    if first.weather and first.weather != "a dry week":
        reasons.append(f"{first.weather} expected")
    if first.holiday:
        reasons.append(first.holiday)
    if reasons and change:
        note += (
            f"; {' and '.join(reasons)}, so about {abs(change)}% {'more' if change > 0 else 'less'}"
        )
    elif first.weather == "a dry week" and change:
        note += f"; a dry week ahead, so about {abs(change)}% more"
    return note + "."
