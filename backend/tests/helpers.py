"""Helpers shared by database tests."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import SwarmClock
from app.db.enums import Category
from app.db.models import GroupOrder, Payment, Shop
from app.features import demand, group_buy


async def shops_by_code(db: AsyncSession) -> dict[str, Shop]:
    return {shop.code: shop for shop in await db.scalars(select(Shop))}


async def prepare_week(
    db: AsyncSession,
    week: date,
    clock: SwarmClock,
    overrides: dict[str, dict[uuid.UUID, int]] | None = None,
) -> dict[Category, GroupOrder]:
    """Monday (forecast + confirm) and Tuesday (pool) for every shop."""
    overrides = overrides or {}
    await demand.propose_week(db, week)
    for code, shop in (await shops_by_code(db)).items():
        await demand.confirm_week(db, shop.id, week, clock.now(), overrides.get(code))
    groups = await group_buy.pool_week(db, week, clock.now())
    return {group.category: group for group in groups}


async def awarded(
    db: AsyncSession, week: date, clock: SwarmClock, category: Category
) -> GroupOrder:
    groups = await prepare_week(db, week, clock)
    await group_buy.award_at_list_prices(db, groups[category].id)
    return await group_buy.load_group(db, groups[category].id)


async def payment_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Payment)) or 0)
