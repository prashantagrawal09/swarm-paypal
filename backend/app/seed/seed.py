"""Seed the Tiong Bahru demo world: 12 shops, 3 suppliers, the catalog and 8 weeks of history.

    python -m app.seed.seed                # wipe and reseed (demo week starts next Monday)
    python -m app.seed.seed --week 2026-10-12

Generation is deterministic (fixed random seed), so tests, local runs and the demo video
all see the same world. Shops listed in REAL_SHOP_CODES (and suppliers whose PayPal app
credentials are configured) are marked REAL only when the platform's PayPal credentials are
set; everything else is SIMULATED.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import SwarmClock, at_local
from app.config import Settings, env_value, get_settings
from app.db.app_state import CLOCK_KEY, SIM_PAYPAL_KEY, set_state
from app.db.enums import Category, PayPalModeEnum
from app.db.models import (
    Base,
    Item,
    PurchaseHistory,
    SalesHistory,
    Shop,
    Supplier,
    SupplierItem,
)
from app.money.pricing import parse_tiers, tier_unit_price
from app.paypal.accounts import credentials_for_prefix, platform_credentials, shop_email_key

DATA_DIR = Path(__file__).parent / "data"
HISTORY_WEEKS = 8
RANDOM_SEED = 2026

# The SKU a shop buys by default for each product (unless its preferences say otherwise).
DEFAULT_SKUS = {
    "milk-full-cream-1l": "MILK-FC-1L-MEADOW",
    "eggs-tray-30": "EGGS-30-SUNNYHEN",
    "butter-250g": "BUTTER-250-ANCHORVALE",
    "coffee-beans-1kg": "BEANS-1KG-ROASTWORKS",
    "cooking-oil-2l": "OIL-2L-SUNLITE",
    "paper-cups-12oz-50": "CUPS-12OZ-50-ECOCUP",
    "lids-50": "LIDS-50-ECOCUP",
    "takeaway-box-50": "BOX-50-KRAFTPACK",
    "napkins-100": "NAPKIN-100-SOFTLY",
    "tomatoes-1kg": "TOMATO-1KG-CAMERON",
    "lettuce-1kg": "LETTUCE-1KG-CAMERON",
}

OPEN_DAYS = {
    "Daily": {0, 1, 2, 3, 4, 5, 6},
    "Tue-Sun": {1, 2, 3, 4, 5, 6},
    "Mon-Sat": {0, 1, 2, 3, 4, 5},
}


@dataclass
class SeedResult:
    demo_week_start: date
    shops: int = 0
    suppliers: int = 0
    items: int = 0
    sales_days: int = 0
    purchase_rows: int = 0
    real_shops: list[str] = field(default_factory=list)
    real_suppliers: list[str] = field(default_factory=list)


def load(name: str) -> Any:
    return json.loads((DATA_DIR / f"{name}.json").read_text())


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def preferred_sku(shop_data: dict[str, Any], product_code: str) -> str:
    preferred = shop_data.get("preferences", {}).get("preferred_skus", {})
    return str(preferred.get(product_code) or DEFAULT_SKUS[product_code])


async def reset_database(session: AsyncSession) -> None:
    """Empty every Swarm table (the schema and migrations stay)."""
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    await session.commit()


async def seed_world(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    demo_week_start: date | None = None,
    rng_seed: int = RANDOM_SEED,
    simulate_all: bool = False,
) -> SeedResult:
    settings = settings or get_settings()
    week = demo_week_start or next_monday(date.today())
    if week.weekday() != 0:
        raise ValueError("The demo week must start on a Monday")
    rng = random.Random(rng_seed)
    demand = load("demand")
    result = SeedResult(demo_week_start=week)
    platform_ready = not simulate_all and platform_credentials() is not None
    real_codes = set(settings.real_shop_code_list) if platform_ready else set()

    # -- items --------------------------------------------------------------------------
    items: dict[str, Item] = {}
    for data in load("items"):
        item = Item(**{**data, "category": Category(data["category"])})
        session.add(item)
        items[item.sku] = item
    result.items = len(items)

    # -- suppliers ----------------------------------------------------------------------
    supplier_for_sku: dict[str, tuple[Supplier, SupplierItem]] = {}
    for data in load("suppliers"):
        ref = data["api_credentials_ref"]
        real = platform_ready and credentials_for_prefix(ref) is not None
        supplier = Supplier(
            code=data["code"],
            name=data["name"],
            paypal_mode=PayPalModeEnum.REAL if real else PayPalModeEnum.SIMULATED,
            paypal_email=(env_value(f"{ref}_EMAIL") if real else None)
            or f"{data['code']}@sim.swarm.example",
            api_credentials_ref=ref,
            delivery_days=data["delivery_days"],
            delivery_fee_cents=data["delivery_fee_cents"],
            platform_fee_bps=settings.platform_fee_bps,
            reliability_score=data["reliability_score"],
            depot_latitude=data["depot"][0],
            depot_longitude=data["depot"][1],
            profile=data["profile"],
        )
        session.add(supplier)
        if real:
            result.real_suppliers.append(supplier.code)
        for entry in data["catalog"]:
            tiers = [{"min_qty": q, "unit_price_cents": p} for q, p in entry["tiers"]]
            parse_tiers(tiers)  # validates
            supplier_item = SupplierItem(
                supplier=supplier,
                item=items[entry["sku"]],
                price_tiers=tiers,
                floor_price_cents=entry["floor"],
                stock_limit=entry["stock"],
            )
            session.add(supplier_item)
            supplier_for_sku.setdefault(entry["sku"], (supplier, supplier_item))
        result.suppliers += 1

    # -- shops --------------------------------------------------------------------------
    shops_data = load("shops")
    shops: dict[str, Shop] = {}
    for data in shops_data:
        code = data["code"]
        real = code in real_codes
        email = env_value(shop_email_key(code)) if real else None
        vault = env_value(shop_email_key(code).replace("_EMAIL", "_VAULT_ID")) if real else None
        preferences = dict(data["preferences"])
        preferences["usual_weekly"] = data["usual_weekly"]
        preferences.setdefault("preferred_skus", {})
        for product in data["usual_weekly"]:
            preferences["preferred_skus"].setdefault(product, preferred_sku(data, product))
        shop = Shop(
            code=code,
            name=data["name"],
            owner_name=data["owner_name"],
            address=data["address"],
            latitude=data["location"][0],
            longitude=data["location"][1],
            opening_hours={**data["opening_hours"], "kind": data["kind"]},
            paypal_mode=PayPalModeEnum.REAL if real else PayPalModeEnum.SIMULATED,
            paypal_email=email or f"{code}@sim.swarm.example",
            vault_id=vault if real else f"SIM-VAULT-{code.upper()}",
            weekly_spend_limit_cents=data["weekly_spend_limit_cents"],
            currency=settings.paypal_currency,
            preferences=preferences,
        )
        session.add(shop)
        shops[code] = shop
        if real:
            result.real_shops.append(code)
    result.shops = len(shops)
    await session.flush()

    # -- history ------------------------------------------------------------------------
    first_day = week - timedelta(weeks=HISTORY_WEEKS)
    weekday_factors = demand["weekday_factors"]
    weather_names = list(demand["weather_weights"])
    weather_weights = [demand["weather_weights"][name] for name in weather_names]
    holidays = demand["holidays"]
    daily_weather = {}
    for offset in range(HISTORY_WEEKS * 7):
        day = first_day + timedelta(days=offset)
        daily_weather[day] = rng.choices(weather_names, weather_weights)[0]

    for data in shops_data:
        shop = shops[data["code"]]
        traffic = data["traffic"]
        open_days = OPEN_DAYS[data["opening_hours"]["days"]]
        weekly_activity: dict[date, list[float]] = defaultdict(list)
        for offset in range(HISTORY_WEEKS * 7):
            day = first_day + timedelta(days=offset)
            weather = daily_weather[day]
            is_open = day.weekday() in open_days
            factor = weekday_factors[day.weekday()]
            if day.weekday() >= 5:
                factor *= traffic["weekend_lift"]
            if weather == "rainy":
                factor *= traffic["rain_factor"]
            if day.isoformat() in holidays:
                factor *= demand["holiday_week_factor"]
            factor *= 1 + rng.uniform(-demand["noise"], demand["noise"])
            covers = round(traffic["base_covers"] * factor) if is_open else 0
            metrics: dict[str, Any] = {
                "covers": covers,
                "weather": weather,
                "holiday": day.isoformat() in holidays,
                "open": is_open,
            }
            if data["kind"] in ("cafe", "kopitiam", "specialty coffee", "toast cafe", "tea house"):
                metrics["coffees_sold"] = round(covers * 0.85)
            session.add(SalesHistory(shop_id=shop.id, date=day, metrics=metrics))
            result.sales_days += 1
            weekly_activity[day - timedelta(days=day.weekday())].append(
                covers / traffic["base_covers"] if is_open else 0.0
            )

        for week_begin, activity in sorted(weekly_activity.items()):
            open_count = sum(1 for value in activity if value > 0) or 1
            index = sum(activity) / open_count
            delivery_paid: set[str] = set()
            for product, usual in data["usual_weekly"].items():
                sku = shop.preferences["preferred_skus"][product]
                supplier, supplier_item = supplier_for_sku[sku]
                qty = max(1, round(usual * index * (1 + rng.uniform(-0.06, 0.06))))
                price = tier_unit_price(parse_tiers(supplier_item.price_tiers), qty)
                fee = 0 if supplier.code in delivery_paid else supplier.delivery_fee_cents
                delivery_paid.add(supplier.code)
                session.add(
                    PurchaseHistory(
                        shop_id=shop.id,
                        week_start=week_begin,
                        item_id=items[sku].id,
                        qty=qty,
                        unit_price_cents=price,
                        delivery_fee_cents=fee,
                    )
                )
                result.purchase_rows += 1

    # -- clock and simulator ------------------------------------------------------------
    clock = SwarmClock(at_local(week, 8, 0))
    await set_state(session, CLOCK_KEY, clock.to_dict())
    await session.execute(text("DELETE FROM app_state WHERE key = :key"), {"key": SIM_PAYPAL_KEY})
    await session.commit()
    return result


async def _main(argv: list[str] | None = None) -> None:
    from app.db.session import get_sessionmaker

    parser = argparse.ArgumentParser(description="Wipe and seed the Swarm demo world")
    parser.add_argument("--week", type=date.fromisoformat, help="demo week start (a Monday)")
    args = parser.parse_args(argv)
    async with get_sessionmaker()() as session:
        await reset_database(session)
        result = await seed_world(session, demo_week_start=args.week)
    print(
        f"Seeded {result.shops} shops, {result.suppliers} suppliers, {result.items} items, "
        f"{result.sales_days} days of sales and {result.purchase_rows} purchase rows.\n"
        f"Demo week starts Monday {result.demo_week_start}. "
        f"REAL shops: {', '.join(result.real_shops) or 'none'}; "
        f"REAL suppliers: {', '.join(result.real_suppliers) or 'none'}."
    )


__all__ = ["SeedResult", "reset_database", "seed_world"]


if __name__ == "__main__":
    asyncio.run(_main())
