"""Demand prediction (F6): what each shop will need next week.

Simple and explainable on purpose: the average of the last four weeks a shop bought each
product (before Swarm from purchase history, after Swarm from its group-order lines), times
a holiday factor from `seed/data/demand.json` when the coming week has a public holiday.
The explanation is a plain sentence; a language model may rephrase it later, but the
number always comes from this code.
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

CONFIG_PATH = Path(__file__).resolve().parents[1] / "seed" / "data" / "demand.json"
LOOKBACK_WEEKS = 4


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


def holiday_in_week(week_start: date) -> str | None:
    holidays: dict[str, str] = demand_config()["holidays"]
    for offset in range(7):
        name = holidays.get((week_start + timedelta(days=offset)).isoformat())
        if name:
            return name
    return None


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
    factor = demand_config()["holiday_week_factor"] if holiday else 1.0
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
            f"About {predicted} x {item.unit} of {item.name.lower()}: your last "
            f"{len(weeks)} weeks averaged {average:.0f}"
        )
        if holiday:
            explanation += f", plus {round((factor - 1) * 100)}% for {holiday}"
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
                explanation=explanation + ".",
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
