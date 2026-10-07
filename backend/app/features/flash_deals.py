"""Supplier flash deals (F8): a supplier clears surplus at a discount; matching shops get a
one-tap offer.

Price is code: the single-unit list price minus the discount, never below the supplier's
floor. Shops that use the product and accept the brand are offered a sensible quantity
(about half their usual weekly need, capped by what is left). Buying charges the shop's
saved PayPal immediately and pays the supplier its share at once.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.clock import week_start
from app.config import get_settings
from app.db.enums import FlashDealStatus, PayPalModeEnum, ShopStatus
from app.db.models import FlashDeal, Item, Shop, SupplierItem
from app.features import actions as act
from app.features.context import Ctx
from app.features.group_buy import shop_accepts
from app.features.neighbours import reference_price, uses
from app.features.products import describe, wording
from app.money import rules
from app.money.amount import Money
from app.money.engine import NeedsOwnerApproval
from app.money.pricing import parse_tiers, tier_unit_price

AUTO_BUY_MAX_SHARE = 0.8
MAX_AUTO_BUYERS = 2


async def post(
    ctx: Ctx, supplier_code: str, sku: str, qty: int, discount_pct: int, hours: int = 8
) -> FlashDeal:
    supplier = await ctx.supplier(supplier_code)
    supplier_item = await ctx.session.scalar(
        select(SupplierItem)
        .join(Item, Item.id == SupplierItem.item_id)
        .where(SupplierItem.supplier_id == supplier.id, Item.sku == sku)
    )
    if supplier_item is None:
        raise rules.RuleViolation("NOT_STOCKED", f"{supplier.name} doesn't sell {sku}")
    item = await ctx.session.get(Item, supplier_item.item_id)
    assert item is not None
    if not 0 < discount_pct < 90 or qty <= 0:
        raise rules.RuleViolation("INVALID_DEAL", "Discount must be 1-89% and quantity positive")
    list_price = tier_unit_price(parse_tiers(supplier_item.price_tiers), 1)
    price, clamped = rules.clamp_to_floor(
        round(list_price * (100 - discount_pct) / 100),
        supplier_item.floor_price_cents,
        context=f"flash deal {sku}",
    )
    deal = FlashDeal(
        supplier_id=supplier.id,
        item_id=item.id,
        qty_available=min(qty, supplier_item.stock_limit),
        price_cents=price,
        list_price_cents=list_price,
        expires_at=ctx.now() + timedelta(hours=hours),
        status=FlashDealStatus.OPEN,
        currency=get_settings().paypal_currency,
        details={
            "discount_pct": round(100 * (1 - price / list_price)),
            "clamped": clamped,
            "purchases": [],
            "product": item.product_code,
        },
    )
    ctx.session.add(deal)
    await ctx.session.commit()
    what = describe(item.product_code, deal.qty_available)
    unit = wording(item.product_code).unit
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"flash:{deal.id}",
        from_agent=f"supplier:{supplier.code}",
        to_agent="shops:all",
        type="FLASH_DEAL",
        text=(
            f"Flash deal: {what} of {item.brand} at {Money(price)}/{unit} "
            f"({deal.details['discount_pct']}% off) until {deal.expires_at:%H:%M}."
        ),
        payload={"deal_id": str(deal.id), "price_cents": price, "list_price_cents": list_price},
    )

    shops = list(await ctx.session.scalars(select(Shop).where(Shop.status == ShopStatus.ACTIVE)))
    matches = [s for s in shops if uses(s, item.product_code) and shop_accepts(s, item, item)[0]]
    matches.sort(key=lambda s: -uses(s, item.product_code))
    auto_buyers = 0
    for shop in matches:
        suggested = suggested_qty(shop, item.product_code, deal.qty_available - deal.taken_qty)
        if suggested <= 0:
            continue
        if shop.paypal_mode == PayPalModeEnum.REAL:
            await ctx.say_to_owner(
                shop,
                f"⚡ {supplier.name} has {item.brand} {wording(item.product_code).name} at "
                f"{Money(price)}/{unit} ({deal.details['discount_pct']}% off) until "
                f"{deal.expires_at:%H:%M}. Want {describe(item.product_code, suggested)} for "
                f"{Money(price * suggested)}?",
                kind="FLASH_DEAL",
                ref=deal.id.hex,
                actions=[
                    act.action(act.FLASH_DEAL, "buy", deal.id, f"Buy {suggested}", "primary"),
                    act.action(act.FLASH_DEAL, "no", deal.id, "Skip"),
                ],
            )
        elif auto_buyers < MAX_AUTO_BUYERS and (
            price <= await reference_price(ctx, shop, item.product_code) * AUTO_BUY_MAX_SHARE
        ):
            try:
                await buy(ctx, deal.id, shop.code, suggested)
                auto_buyers += 1
            except (rules.RuleViolation, NeedsOwnerApproval):
                continue
    return deal


def suggested_qty(shop: Shop, product: str, remaining: int) -> int:
    return min(remaining, max(1, uses(shop, product) // 2))


async def buy(ctx: Ctx, deal_id: uuid.UUID, shop_code: str, qty: int | None = None) -> FlashDeal:
    deal = await ctx.session.scalar(
        select(FlashDeal)
        .where(FlashDeal.id == deal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if deal is None:
        raise LookupError("Deal not found")
    shop = await ctx.shop(shop_code)
    item = await ctx.session.get(Item, deal.item_id)
    assert item is not None
    remaining = deal.qty_available - deal.taken_qty
    if deal.status != FlashDealStatus.OPEN or ctx.now() > deal.expires_at or remaining <= 0:
        await ctx.session.commit()
        raise rules.RuleViolation("DEAL_CLOSED", "Sorry, that deal has closed")
    qty = qty or suggested_qty(shop, item.product_code, remaining)
    if not 0 < qty <= remaining:
        await ctx.session.commit()
        raise rules.RuleViolation("NOT_ENOUGH", f"Only {remaining} left")
    deal.taken_qty += qty
    if deal.taken_qty >= deal.qty_available:
        deal.status = FlashDealStatus.SOLD_OUT
    purchases = deal.details.get("purchases", [])
    amount = qty * deal.price_cents
    sequence = len(purchases) + 1
    deal.details = {
        **deal.details,
        "purchases": [
            *purchases,
            {
                "shop": shop.code,
                "shop_id": str(shop.id),
                "qty": qty,
                "amount_cents": amount,
                "week": str(week_start(ctx.now())),
                "saved_cents": qty * (deal.list_price_cents - deal.price_cents),
            },
        ],
    }
    await ctx.session.commit()
    try:
        await ctx.engine.purchase_now(
            shop_id=shop.id,
            supplier_id=deal.supplier_id,
            amount_cents=amount,
            key=f"flash:{deal.id.hex[:12]}:{sequence}",
            related_id=deal.id,
            memo=f"{shop.name} flash deal: {describe(item.product_code, qty)} of {item.brand}",
        )
    except (rules.RuleViolation, NeedsOwnerApproval):
        deal.taken_qty -= qty
        deal.status = FlashDealStatus.OPEN
        pending = {**(deal.details.get("pending") or {}), shop.code: qty}
        deal.details = {**deal.details, "purchases": purchases, "pending": pending}
        await ctx.session.commit()
        raise
    await ctx.say_to_owner(
        shop,
        f"⚡ Bought {describe(item.product_code, qty)} of {item.brand} for {Money(amount)} "
        f"(saved {Money(qty * (deal.list_price_cents - deal.price_cents))}). It comes with "
        "Thursday's delivery.",
        kind="FLASH_BOUGHT",
        extra={"deal_id": str(deal.id)},
    )
    return deal
