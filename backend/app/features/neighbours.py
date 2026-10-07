"""Shared helpers for shop-to-shop features: who is nearby, what a product costs a shop,
and how far a walk is."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import select

from app.db.enums import ShopStatus
from app.db.models import GroupOrder, GroupOrderLine, Item, Shop, SupplierItem
from app.features.context import Ctx
from app.money.pricing import haversine_m, parse_tiers, tier_unit_price

WALK_METRES_PER_MINUTE = 80


@dataclass(frozen=True)
class Neighbour:
    shop: Shop
    distance_m: int

    @property
    def walk_minutes(self) -> int:
        return max(1, math.ceil(self.distance_m / WALK_METRES_PER_MINUTE))


def distance_m(a: Shop, b: Shop) -> int:
    return round(haversine_m(a.latitude, a.longitude, b.latitude, b.longitude))


async def neighbours(ctx: Ctx, shop: Shop, radius_m: int) -> list[Neighbour]:
    shops = await ctx.session.scalars(
        select(Shop).where(Shop.id != shop.id, Shop.status == ShopStatus.ACTIVE)
    )
    found = [Neighbour(other, distance_m(shop, other)) for other in shops]
    return sorted((n for n in found if n.distance_m <= radius_m), key=lambda n: n.distance_m)


def uses(shop: Shop, product: str) -> int:
    """How much of a product the shop usually buys per week (0 = it doesn't)."""
    return int((shop.preferences.get("usual_weekly") or {}).get(product, 0))


async def shop_item(ctx: Ctx, shop: Shop, product: str) -> Item:
    """The SKU this shop actually has: its latest delivered brand, else its preferred one."""
    latest = await ctx.session.scalar(
        select(Item)
        .join(GroupOrderLine, GroupOrderLine.item_id == Item.id)
        .join(GroupOrder, GroupOrder.id == GroupOrderLine.group_order_id)
        .where(GroupOrderLine.shop_id == shop.id, Item.product_code == product)
        .order_by(GroupOrder.week_start.desc())
    )
    if latest is not None:
        return latest
    sku = (shop.preferences.get("preferred_skus") or {}).get(product)
    item = await ctx.session.scalar(select(Item).where(Item.sku == sku)) if sku else None
    if item is None:
        item = await ctx.session.scalar(select(Item).where(Item.product_code == product))
    if item is None:
        raise LookupError(f"Unknown product {product}")
    return item


async def reference_price(ctx: Ctx, shop: Shop, product: str) -> int:
    """What one unit costs this shop today: its latest agreed group price, else the
    single-unit list price of its usual brand."""
    agreed = await ctx.session.scalar(
        select(GroupOrderLine.agreed_unit_price_cents)
        .join(Item, Item.id == GroupOrderLine.item_id)
        .join(GroupOrder, GroupOrder.id == GroupOrderLine.group_order_id)
        .where(
            GroupOrderLine.shop_id == shop.id,
            Item.product_code == product,
            GroupOrderLine.agreed_unit_price_cents.is_not(None),
        )
        .order_by(GroupOrder.week_start.desc())
    )
    if agreed:
        return int(agreed)
    item = await shop_item(ctx, shop, product)
    supplier_item = await ctx.session.scalar(
        select(SupplierItem).where(SupplierItem.item_id == item.id)
    )
    if supplier_item is None:
        raise LookupError(f"Nobody sells {product}")
    return tier_unit_price(parse_tiers(supplier_item.price_tiers), 1)
