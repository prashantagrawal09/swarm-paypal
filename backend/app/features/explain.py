"""Worked examples for the home page: what pooling does to a price, and what a short
delivery does to a charge.

Nothing here is special to the website. Every number comes from `app.money.pricing`, the
same functions the week itself runs on, applied to the neighbourhood's usual milk order.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.agents.base import DECISION_PREFIX
from app.db.enums import Category
from app.db.models import (
    AgentMessage,
    AuditLog,
    GroupOrder,
    Item,
    Shop,
    Supplier,
    SupplierItem,
)
from app.features.context import Ctx
from app.features.products import wording
from app.money import pricing

PRODUCT = "milk-full-cream-1l"
# The shop the examples start from (and whose delivery the second example follows).
HERO = "cafe-mei"
# The negotiation the decision example prefers: the one that includes the product above.
EXAMPLE_CATEGORY = "dairy"


async def worked_examples(ctx: Ctx) -> dict[str, Any] | None:
    """The pooling table (1 shop, 2 shops, ...) and the short-delivery table (0 units
    arrived, 1 unit, ...), or None when the demo world isn't seeded."""
    session = ctx.session
    offers = (
        await session.execute(
            select(SupplierItem, Item, Supplier)
            .join(Item, Item.id == SupplierItem.item_id)
            .join(Supplier, Supplier.id == SupplierItem.supplier_id)
            .where(Item.product_code == PRODUCT)
        )
    ).all()
    shops = [
        shop
        for shop in await session.scalars(select(Shop).order_by(Shop.name))
        if int(shop.preferences.get("usual_weekly", {}).get(PRODUCT, 0)) > 0
    ]
    if not offers or not shops:
        return None

    # The catalogue whose price is lowest once everyone buys together.
    supplier_item, item, supplier = min(
        offers,
        key=lambda row: (
            pricing.parse_tiers(row[0].price_tiers)[-1].unit_price_cents,
            row[2].code,
        ),
    )
    tiers = pricing.parse_tiers(supplier_item.price_tiers)
    usual = {shop.code: int(shop.preferences["usual_weekly"][PRODUCT]) for shop in shops}
    shops.sort(key=lambda shop: (shop.code != HERO, shop.name))

    steps = []
    pooled_qty = 0
    alone_cents = 0
    for count, shop in enumerate(shops, start=1):
        qty = usual[shop.code]
        pooled_qty += qty
        # Alone, a shop pays the tier its own order reaches.
        alone_cents += pricing.line_total(pricing.tier_unit_price(tiers, qty), qty)
        unit = pricing.tier_unit_price(tiers, pooled_qty)
        pooled_cents = pricing.line_total(unit, pooled_qty)
        steps.append(
            {
                "shops": count,
                "joined": {"code": shop.code, "name": shop.name, "qty": qty},
                "qty": pooled_qty,
                "unit_price_cents": unit,
                "pooled_cents": pooled_cents,
                "alone_cents": alone_cents,
                "saved_cents": alone_cents - pooled_cents,
            }
        )

    # One shop's order out of the pooled one: its hold, and the charge for what arrives.
    hero = next((shop for shop in shops if shop.code == HERO), shops[0])
    ordered = usual[hero.code]
    unit = pricing.tier_unit_price(tiers, pooled_qty)
    shares = pricing.split_delivery_fee(
        supplier.delivery_fee_cents,
        [
            pricing.DeliveryStop(
                shop.code, usual[shop.code] * item.unit_weight_grams, shop.latitude, shop.longitude
            )
            for shop in shops
        ],
    )
    share = shares[hero.code]
    hold = pricing.order_amount([(ordered, unit)], share)
    rows = []
    for delivered in range(ordered + 1):
        arrived_share = pricing.delivered_share(
            share, ordered * item.unit_weight_grams, delivered * item.unit_weight_grams
        )
        charged = pricing.order_amount([(delivered, unit)], arrived_share)
        rows.append(
            {"delivered": delivered, "charged_cents": charged, "released_cents": hold - charged}
        )

    w = wording(PRODUCT)
    return {
        "product": {"code": PRODUCT, "name": w.name, "unit": w.unit, "units": w.units},
        "supplier": {"code": supplier.code, "name": supplier.name},
        "pooling": {
            "tiers": [
                {"min_qty": tier.min_qty, "unit_price_cents": tier.unit_price_cents}
                for tier in tiers
            ],
            "steps": steps,
        },
        "delivery": {
            "shop": {"code": hero.code, "name": hero.name},
            "ordered": ordered,
            "unit_price_cents": unit,
            "delivery_fee_cents": supplier.delivery_fee_cents,
            "delivery_share_cents": share,
            "hold_cents": hold,
            "rows": rows,
        },
    }


async def decision_example(ctx: Ctx) -> dict[str, Any] | None:
    """A real decision from this week to show on the home page: the last-round quote with
    the most options on the table. None until a negotiation has happened.

    Only for the demo: a supplier's options are private to its owner (see the decision API).
    """
    if not ctx.runtime.settings.demo_mode:
        return None
    session = ctx.session
    rows = [
        row
        for row in await session.scalars(
            select(AuditLog)
            .where(AuditLog.action == f"{DECISION_PREFIX}quote")
            .order_by(AuditLog.seq.desc())
            .limit(60)
        )
        if row.details.get("options") and row.details.get("message_id")
    ]
    if not rows:
        return None

    def richness(row: AuditLog) -> tuple[int, int]:
        return int(row.details.get("round") or 0), len(row.details["options"])

    best = max(richness(row) for row in rows)
    candidates = [row for row in rows if richness(row) == best]
    messages = {
        str(m.id): m
        for m in await session.scalars(
            select(AgentMessage).where(
                AgentMessage.id.in_([uuid.UUID(row.details["message_id"]) for row in candidates])
            )
        )
    }
    candidates = [row for row in candidates if row.details["message_id"] in messages]
    if not candidates:
        return None
    # Of equally rich decisions, the one about the product the other examples use (milk).
    record = max(
        candidates,
        key=lambda row: (
            messages[row.details["message_id"]].conversation_id.endswith(f":{EXAMPLE_CATEGORY}"),
            row.seq,
        ),
    )
    message = messages[record.details["message_id"]]
    supplier = await session.scalar(
        select(Supplier).where(Supplier.code == record.actor.split(":", 1)[-1])
    )
    order_id = None
    try:  # "negotiation:<week>:<category>"
        _, week, category = message.conversation_id.split(":")
        order_id = await session.scalar(
            select(GroupOrder.id).where(
                GroupOrder.week_start == date.fromisoformat(week),
                GroupOrder.category == Category(category.upper()),
            )
        )
    except ValueError:
        pass
    return {
        "message_id": str(message.id),
        "text": message.text,
        "supplier": {
            "code": supplier.code if supplier else record.actor,
            "name": supplier.name if supplier else record.actor,
        },
        "order_id": str(order_id) if order_id else None,
        "round": record.details.get("round"),
        "options": record.details["options"],
        "chosen": record.details.get("chosen"),
        "chosen_by": record.details.get("chosen_by"),
        "checked": record.details.get("checked", []),
    }
