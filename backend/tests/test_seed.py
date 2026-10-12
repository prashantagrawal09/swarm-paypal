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


async def test_connections_survive_a_demo_reset(db, monkeypatch):
    """A reset reseeds everything, but nobody should have to connect PayPal or Telegram
    again because someone pressed Reset."""
    from app.db.models import TelegramChat
    from app.demo.controls import remember_connections, restore_connections

    for key, value in {
        "PAYPAL_PLATFORM_CLIENT_ID": "cid",
        "PAYPAL_PLATFORM_CLIENT_SECRET": "secret",
        "PAYPAL_SHOP_CAFE_MEI_VAULT_ID": "VAULT-FROM-ENV",
        "PAYPAL_SHOP_BREW_LAB_VAULT_ID": "",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings(real_shop_codes="cafe-mei,brew-lab")
    await seed_world(db, settings=settings, demo_week_start=DEMO_WEEK)

    async def shop(code: str) -> Shop:
        found = await db.scalar(select(Shop).where(Shop.code == code))
        assert found is not None
        return found

    # Brew Lab's owner connects PayPal in the app; Café Mei's reconnects with a newer wallet;
    # a simulated shop's owner links Telegram.
    brew, mei, kopi = await shop("brew-lab"), await shop("cafe-mei"), await shop("kopi-corner")
    brew.vault_id, brew.paypal_email = "VAULT-CONNECTED", "sb-brew@personal.example.com"
    mei.vault_id = "VAULT-RECONNECTED"
    kopi.telegram_chat_id = 4242
    db.add(TelegramChat(chat_id=4242, shop_id=kopi.id, first_name="Kim", state={"step": "x"}))
    db.add(TelegramChat(chat_id=77, shop_id=None, username="visitor", state={}))
    await db.commit()
    old_kopi_id = kopi.id

    kept = await remember_connections(db)
    await reset_database(db)
    await seed_world(db, settings=settings, demo_week_start=DEMO_WEEK)
    await restore_connections(db, kept)
    db.expire_all()

    brew, mei, kopi = await shop("brew-lab"), await shop("cafe-mei"), await shop("kopi-corner")
    assert (brew.vault_id, brew.paypal_email) == ("VAULT-CONNECTED", "sb-brew@personal.example.com")
    assert mei.vault_id == "VAULT-RECONNECTED"
    assert kopi.id != old_kopi_id and kopi.telegram_chat_id == 4242
    assert kopi.vault_id == "SIM-VAULT-KOPI-CORNER"  # simulated shops keep the seed's wallet
    chats = {c.chat_id: c for c in (await db.scalars(select(TelegramChat))).all()}
    assert chats[4242].shop_id == kopi.id and chats[4242].state == {}
    assert chats[77].shop_id is None and chats[77].username == "visitor"


async def test_a_saved_paypal_is_dropped_when_the_shop_stops_being_real(db, monkeypatch):
    from app.demo.controls import remember_connections, restore_connections

    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PAYPAL_SHOP_CAFE_MEI_VAULT_ID", "VAULT-MEI")
    await seed_world(db, settings=Settings(real_shop_codes="cafe-mei"), demo_week_start=DEMO_WEEK)

    kept = await remember_connections(db)
    assert kept.wallets["cafe-mei"][0] == "VAULT-MEI"
    await reset_database(db)
    await seed_world(db, settings=Settings(real_shop_codes=""), demo_week_start=DEMO_WEEK)
    await restore_connections(db, kept)

    mei = await db.scalar(select(Shop).where(Shop.code == "cafe-mei"))
    assert mei is not None
    assert mei.paypal_mode == PayPalModeEnum.SIMULATED and mei.vault_id == "SIM-VAULT-CAFE-MEI"
