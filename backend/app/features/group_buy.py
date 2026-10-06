"""Weekly group buy (F1): pool confirmed needs, price them, award, deliver.

The deterministic half of the hero flow:
- `pool_week` turns confirmed forecasts into one group order per category.
- `list_quote` prices a supplier's offer at its tier prices for the pooled quantity.
- `choose_winner` applies the award rule: lowest landed cost (items + delivery) among
  suppliers whose reliability is above the threshold; ties go to the more reliable one.
- `apply_award` fixes the agreed prices, maps every shop line onto the winner's SKU (only
  where the owner's brand preferences allow it) and splits the delivery fee.
- `record_delivery` stores what arrived, which the money engine then captures.

Negotiation (agents lowering prices round by round) sits on top of this in the coordinator.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import at_local
from app.db.enums import Category, ForecastStatus, GroupOrderStatus, ShopOrderStatus
from app.db.models import (
    DemandForecast,
    GroupOrder,
    GroupOrderLine,
    Item,
    Shop,
    ShopOrder,
    Supplier,
    SupplierItem,
)
from app.features.products import names
from app.money import pricing, rules
from app.money.states import advance_group_order

RELIABILITY_THRESHOLD = 85
COMPARED_ATTRIBUTES = ("type", "volume_ml", "count", "weight_g", "size", "size_oz")


# ---------------------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------------------


async def pool_week(
    session: AsyncSession, week_start: date, now: datetime, platform_fee_bps: int = 200
) -> list[GroupOrder]:
    """Create (or extend) one group order per category from confirmed forecasts."""
    rows = await session.execute(
        select(DemandForecast, Item, Shop)
        .join(Item, Item.id == DemandForecast.item_id)
        .join(Shop, Shop.id == DemandForecast.shop_id)
        .where(
            DemandForecast.week_start == week_start,
            DemandForecast.status == ForecastStatus.CONFIRMED,
        )
        .order_by(Shop.code, Item.sku)
    )
    by_category: dict[Category, list[tuple[DemandForecast, Item, Shop]]] = defaultdict(list)
    for forecast, item, shop in rows.all():
        by_category[item.category].append((forecast, item, shop))

    groups = []
    for category, entries in sorted(by_category.items()):
        group = await session.scalar(
            select(GroupOrder)
            .where(GroupOrder.week_start == week_start, GroupOrder.category == category)
            .options(selectinload(GroupOrder.shop_orders))
        )
        if group is None:
            group = GroupOrder(
                week_start=week_start,
                category=category,
                status=GroupOrderStatus.COLLECTING,
                deadline_at=at_local(week_start + timedelta(days=1), 12, 0),
                platform_fee_bps=platform_fee_bps,
                currency=entries[0][2].currency,
                summary={},
            )
            session.add(group)
            await session.flush()
            existing_shops: set[uuid.UUID] = set()
        elif group.status != GroupOrderStatus.COLLECTING:
            groups.append(group)
            continue
        else:
            existing_shops = {so.shop_id for so in group.shop_orders}

        shop_orders: dict[uuid.UUID, ShopOrder] = {}
        for forecast, item, shop in entries:
            if shop.id in existing_shops or not forecast.confirmed_qty:
                continue
            if shop.id not in shop_orders:
                shop_orders[shop.id] = ShopOrder(
                    group_order_id=group.id,
                    shop_id=shop.id,
                    status=ShopOrderStatus.PENDING,
                    paypal_mode=shop.paypal_mode,
                )
                session.add(shop_orders[shop.id])
                await session.flush()
            session.add(
                GroupOrderLine(
                    group_order_id=group.id,
                    shop_order_id=shop_orders[shop.id].id,
                    shop_id=shop.id,
                    item_id=item.id,
                    qty_requested=forecast.confirmed_qty,
                )
            )
        groups.append(group)
    await session.commit()
    return groups


async def load_group(session: AsyncSession, group_id: uuid.UUID) -> GroupOrder:
    group = await session.scalar(
        select(GroupOrder)
        .where(GroupOrder.id == group_id)
        .options(
            selectinload(GroupOrder.awarded_supplier),
            selectinload(GroupOrder.shop_orders).selectinload(ShopOrder.shop),
            selectinload(GroupOrder.shop_orders)
            .selectinload(ShopOrder.lines)
            .selectinload(GroupOrderLine.item),
        )
        .execution_options(populate_existing=True)
    )
    if group is None:
        raise LookupError(f"Group order {group_id} not found")
    return group


def pooled_quantities(group: GroupOrder) -> dict[str, int]:
    """Total quantity per product across all shops in the group order."""
    totals: dict[str, int] = defaultdict(int)
    for so in group.shop_orders:
        for line in so.lines:
            totals[line.item.product_code] += line.qty_requested
    return dict(sorted(totals.items()))


def pooled_weight_grams(group: GroupOrder) -> int:
    return sum(
        line.qty_requested * line.item.unit_weight_grams
        for so in group.shop_orders
        for line in so.lines
    )


# ---------------------------------------------------------------------------------------
# Offers, quotes and the award rule
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierOffer:
    """What one supplier can sell for a group order: its SKU for every pooled product."""

    supplier: Supplier
    items: dict[str, SupplierItem]

    def tiers(self, product: str) -> list[pricing.PriceTier]:
        return pricing.parse_tiers(self.items[product].price_tiers)

    def floor(self, product: str) -> int:
        return self.items[product].floor_price_cents

    def list_price(self, product: str, qty: int) -> int:
        return pricing.tier_unit_price(self.tiers(product), qty)


async def supplier_offers(
    session: AsyncSession, products: list[str]
) -> tuple[list[SupplierOffer], list[tuple[Supplier, str]]]:
    """Suppliers able to supply every product, and those that cannot (with the reason)."""
    suppliers = list(
        await session.scalars(
            select(Supplier)
            .options(selectinload(Supplier.items).selectinload(SupplierItem.item))
            .order_by(Supplier.code)
        )
    )
    offers, declined = [], []
    for supplier in suppliers:
        catalog = supplier_catalog(supplier)
        missing = [product for product in products if product not in catalog]
        if missing:
            declined.append((supplier, f"we don't carry {names(missing)}"))
            continue
        offers.append(SupplierOffer(supplier, {product: catalog[product] for product in products}))
    return offers, declined


@dataclass(frozen=True)
class QuoteSummary:
    supplier_id: uuid.UUID
    supplier_code: str
    reliability: int
    unit_prices: dict[str, int]
    quantities: dict[str, int]
    delivery_fee_cents: int

    @property
    def items_total_cents(self) -> int:
        return sum(self.unit_prices[p] * qty for p, qty in self.quantities.items())

    @property
    def landed_total_cents(self) -> int:
        return self.items_total_cents + self.delivery_fee_cents


def list_quote(offer: SupplierOffer, quantities: dict[str, int]) -> QuoteSummary:
    """The supplier's opening position: tier prices for the pooled quantity."""
    return QuoteSummary(
        supplier_id=offer.supplier.id,
        supplier_code=offer.supplier.code,
        reliability=offer.supplier.reliability_score,
        unit_prices={p: offer.list_price(p, qty) for p, qty in quantities.items()},
        quantities=dict(quantities),
        delivery_fee_cents=offer.supplier.delivery_fee_cents,
    )


def choose_winner(
    quotes: list[QuoteSummary], threshold: int = RELIABILITY_THRESHOLD
) -> QuoteSummary | None:
    """Award rule: lowest landed cost among reliable suppliers; ties to the more reliable."""
    eligible = [quote for quote in quotes if quote.reliability >= threshold]
    if not eligible:
        return None
    return min(eligible, key=lambda q: (q.landed_total_cents, -q.reliability, q.supplier_code))


# ---------------------------------------------------------------------------------------
# Award
# ---------------------------------------------------------------------------------------


def supplier_catalog(supplier: Supplier) -> dict[str, SupplierItem]:
    """One SKU per product for a supplier. With several brands of the same product, the
    one that is cheapest at volume (its lowest tier price) is offered; ties by SKU."""
    catalog: dict[str, SupplierItem] = {}
    for si in sorted(supplier.items, key=lambda s: s.item.sku):
        product = si.item.product_code
        best = catalog.get(product)
        if best is None or _volume_price(si) < _volume_price(best):
            catalog[product] = si
    return catalog


def _volume_price(si: SupplierItem) -> int:
    return pricing.parse_tiers(si.price_tiers)[-1].unit_price_cents


def shop_accepts(shop: Shop, target: Item, current: Item) -> tuple[bool, str]:
    """May this shop's line be switched to `target` (the winner's SKU)?"""
    preferences = shop.preferences or {}
    accepted = (preferences.get("accepted_brands") or {}).get(target.product_code)
    if accepted is not None:
        if target.brand in accepted:
            return True, ""
        return False, f"only accepts {', '.join(accepted)}"
    if target.sku == current.sku:
        return True, ""
    if not preferences.get("allow_substitutes", True):
        return False, f"does not accept substitutes for {current.brand}"
    for key in COMPARED_ATTRIBUTES:
        both = key in current.attributes and key in target.attributes
        if both and current.attributes[key] != target.attributes[key]:
            return False, f"{target.brand} differs in {key}"
    return True, ""


@dataclass
class AwardResult:
    group_order_id: uuid.UUID
    supplier_code: str
    unit_prices: dict[str, int]
    excluded: list[dict[str, Any]] = field(default_factory=list)
    shares: dict[str, int] = field(default_factory=dict)


async def apply_award(
    session: AsyncSession,
    group_id: uuid.UUID,
    supplier_id: uuid.UUID,
    unit_prices: dict[str, int],
    *,
    rounds: int = 0,
    summary: dict[str, Any] | None = None,
) -> AwardResult:
    """Fix prices, map lines to the winner's SKUs, split delivery. Prices are re-validated
    against the supplier's floors and stock here, whatever produced them."""
    group = await load_group(session, group_id)
    supplier = await session.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(selectinload(Supplier.items).selectinload(SupplierItem.item))
    )
    if supplier is None:
        raise LookupError("Supplier not found")
    if group.status == GroupOrderStatus.COLLECTING:
        group.status = advance_group_order(group.status, GroupOrderStatus.NEGOTIATING)
    catalog = supplier_catalog(supplier)
    result = AwardResult(group.id, supplier.code, dict(unit_prices))

    for product, price in unit_prices.items():
        if product not in catalog:
            raise rules.RuleViolation("NOT_STOCKED", f"{supplier.name} does not sell {product}")
        if price < catalog[product].floor_price_cents:
            raise rules.RuleViolation("BELOW_FLOOR", f"{product} priced below the supplier floor")

    awarded_qty: dict[str, int] = defaultdict(int)
    for so in list(group.shop_orders):
        for line in list(so.lines):
            product = line.item.product_code
            target = catalog[product].item
            ok, reason = shop_accepts(so.shop, target, line.item)
            if not ok:
                result.excluded.append(
                    {
                        "shop": so.shop.code,
                        "product": product,
                        "brand": target.brand,
                        "reason": f"{so.shop.name} {reason}",
                    }
                )
                so.lines.remove(line)
                continue
            line.item_id = target.id
            line.item = target
            line.agreed_unit_price_cents = unit_prices[product]
            line.alone_unit_price_cents = pricing.tier_unit_price(
                pricing.parse_tiers(catalog[product].price_tiers), line.qty_requested
            )
            awarded_qty[product] += line.qty_requested
        if not so.lines:
            group.shop_orders.remove(so)

    for product, qty in awarded_qty.items():
        rules.check_stock(qty, catalog[product].stock_limit)

    stops = [
        pricing.DeliveryStop(
            key=str(so.id),
            weight_grams=sum(line.qty_requested * line.item.unit_weight_grams for line in so.lines),
            latitude=so.shop.latitude,
            longitude=so.shop.longitude,
        )
        for so in group.shop_orders
    ]
    shares = pricing.split_delivery_fee(supplier.delivery_fee_cents, stops)
    for so in group.shop_orders:
        so.delivery_share_cents = shares[str(so.id)]
        result.shares[so.shop.code] = shares[str(so.id)]

    group.awarded_supplier_id = supplier.id
    group.delivery_fee_cents = supplier.delivery_fee_cents
    group.negotiation_rounds = rounds
    group.status = advance_group_order(group.status, GroupOrderStatus.AWARDED)
    group.summary = {
        **group.summary,
        **(summary or {}),
        "awarded_supplier": supplier.code,
        "unit_prices": unit_prices,
        "awarded_quantities": dict(awarded_qty),
        "excluded": result.excluded,
        "delivery_shares": result.shares,
    }
    await session.commit()
    return result


async def award_at_list_prices(session: AsyncSession, group_id: uuid.UUID) -> AwardResult | None:
    """No negotiation: award at tier prices to the award-rule winner (fallback path)."""
    group = await load_group(session, group_id)
    quantities = pooled_quantities(group)
    if not quantities:
        return None
    offers, _ = await supplier_offers(session, list(quantities))
    quotes = [list_quote(offer, quantities) for offer in offers]
    winner = choose_winner(quotes)
    if winner is None:
        return None
    return await apply_award(
        session,
        group.id,
        winner.supplier_id,
        winner.unit_prices,
        summary={"pooled_quantities": quantities, "method": "list prices"},
    )


# ---------------------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------------------


async def start_delivery(session: AsyncSession, group_id: uuid.UUID) -> GroupOrder:
    group = await load_group(session, group_id)
    if group.status == GroupOrderStatus.HELD:
        group.status = advance_group_order(group.status, GroupOrderStatus.OUT_FOR_DELIVERY)
        await session.commit()
    return group


async def record_delivery(
    session: AsyncSession,
    group_id: uuid.UUID,
    now: datetime,
    delivered: dict[uuid.UUID, int] | None = None,
) -> GroupOrder:
    """Store what arrived. Lines not mentioned arrived in full; shops without a hold get
    nothing (they are not paying)."""
    delivered = delivered or {}
    group = await start_delivery(session, group_id)
    if group.status != GroupOrderStatus.OUT_FOR_DELIVERY:
        raise rules.RuleViolation("NOT_OUT_FOR_DELIVERY", f"Group order is {group.status}")
    for so in group.shop_orders:
        for line in so.lines:
            if so.status != ShopOrderStatus.AUTHORIZED:
                line.qty_delivered = 0
                continue
            qty = delivered.get(line.id, line.qty_requested)
            if not 0 <= qty <= line.qty_requested:
                raise rules.RuleViolation("INVALID_QTY", "Delivered quantity out of range")
            line.qty_delivered = qty
    group.status = advance_group_order(group.status, GroupOrderStatus.DELIVERED)
    group.delivered_at = now
    await session.commit()
    return group


# ---------------------------------------------------------------------------------------
# Savings versus buying alone
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ShopSavings:
    shop_code: str
    paid_cents: int
    alone_cents: int

    @property
    def saved_cents(self) -> int:
        return self.alone_cents - self.paid_cents


def savings_for_group(group: GroupOrder) -> list[ShopSavings]:
    """Per shop: what this order costs through Swarm versus buying the same quantity alone
    from the same supplier (its own tier price plus a whole delivery fee)."""
    results = []
    for so in group.shop_orders:
        if not so.lines or any(line.agreed_unit_price_cents is None for line in so.lines):
            continue
        paid = pricing.order_amount(
            [(line.qty_requested, line.agreed_unit_price_cents or 0) for line in so.lines],
            so.delivery_share_cents,
        )
        alone = pricing.order_amount(
            [(line.qty_requested, line.alone_unit_price_cents or 0) for line in so.lines],
            group.delivery_fee_cents,
        )
        results.append(ShopSavings(so.shop.code, paid, alone))
    return results
