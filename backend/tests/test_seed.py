"""The seeded Tiong Bahru world."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db.enums import PayPalModeEnum
from app.db.models import Item, PurchaseHistory, SalesHistory, Shop, Supplier, SupplierItem
from app.money.pricing import parse_tiers
from app.seed.seed import reset_database, seed_world
from tests.conftest import DEMO_WEEK

pytestmark = pytest.mark.db


async def test_world_has_the_spec_shape(db, world):
    assert (world.shops, world.suppliers, world.items) == (12, 3, 16)
    assert world.sales_days == 12 * 56
    assert await db.scalar(select(func.count()).select_from(SalesHistory)) == 12 * 56
    assert await db.scalar(select(func.count()).select_from(PurchaseHistory)) == world.purchase_rows
    shops = list(await db.scalars(select(Shop)))
    assert all(shop.paypal_mode == PayPalModeEnum.SIMULATED for shop in shops)
    assert all(shop.vault_id and shop.vault_id.startswith("SIM-VAULT-") for shop in shops)
    for si in await db.scalars(select(SupplierItem)):
        tiers = parse_tiers(si.price_tiers)
        assert si.floor_price_cents < tiers[-1].unit_price_cents  # floors stay secret, below list


async def test_brand_variants_share_a_product_code(db, world):
    milks = list(await db.scalars(select(Item).where(Item.product_code == "milk-full-cream-1l")))
    assert {milk.brand for milk in milks} == {"Meadowfresh", "Hilltop", "Farm Gold"}
    assert len({milk.attributes["type"] for milk in milks}) == 1


async def test_seeding_is_deterministic(db):
    first = await seed_world(db, settings=Settings(), demo_week_start=DEMO_WEEK, simulate_all=True)
    totals_one = await db.scalar(select(func.sum(PurchaseHistory.qty)))
    await reset_database(db)
    second = await seed_world(db, settings=Settings(), demo_week_start=DEMO_WEEK, simulate_all=True)
    totals_two = await db.scalar(select(func.sum(PurchaseHistory.qty)))
    assert first.purchase_rows == second.purchase_rows
    assert totals_one == totals_two


async def test_real_modes_follow_configuration(db, monkeypatch):
    for key, value in {
        "PAYPAL_PLATFORM_CLIENT_ID": "cid",
        "PAYPAL_PLATFORM_CLIENT_SECRET": "secret",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_ID": "fid",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET": "fsecret",
        "PAYPAL_SUPPLIER_FRESHDAIRY_EMAIL": "fresh@example.com",
        "PAYPAL_SHOP_CAFE_MEI_EMAIL": "mei@example.com",
        "PAYPAL_SHOP_CAFE_MEI_VAULT_ID": "VAULT-MEI",
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("PAYPAL_SUPPLIER_PACKPRO_CLIENT_ID", "PAYPAL_SUPPLIER_JOHORFARM_CLIENT_ID"):
        monkeypatch.setenv(key, "")
    result = await seed_world(
        db, settings=Settings(real_shop_codes="cafe-mei,brew-lab"), demo_week_start=DEMO_WEEK
    )
    assert result.real_shops == ["cafe-mei", "brew-lab"]
    assert result.real_suppliers == ["freshdairy"]
    mei = await db.scalar(select(Shop).where(Shop.code == "cafe-mei"))
    assert mei is not None and mei.vault_id == "VAULT-MEI" and mei.paypal_email == "mei@example.com"
    brew = await db.scalar(select(Shop).where(Shop.code == "brew-lab"))
    assert brew is not None and brew.vault_id is None  # must connect PayPal first
    fresh = await db.scalar(select(Supplier).where(Supplier.code == "freshdairy"))
    assert fresh is not None and fresh.paypal_email == "fresh@example.com"
