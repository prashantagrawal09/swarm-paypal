"""Savings report (F7): what Swarm saved each shop this week, and platform-wide totals.

Per shop and week:
- group buys: what the shop paid versus buying the same quantity alone from the same
  supplier (its own tier price plus a whole delivery fee),
- swaps: income from surplus sold; for surplus bought, the saving versus the seller's cost,
- flash deals: list price minus deal price,
- food saved: weight of surplus that went to a neighbour instead of the bin,
- refunds received from claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.clock import week_start
from app.db.enums import (
    GroupOrderStatus,
    PaymentKind,
    PaymentStatus,
    PayPalModeEnum,
    ShopOrderStatus,
    SwapKind,
    SwapStatus,
)
from app.db.models import FlashDeal, GroupOrder, GroupOrderLine, Payment, Shop, ShopOrder, SwapOffer
from app.features.context import Ctx
from app.money import ledger, pricing
from app.money.amount import Money

PAID_STATUSES = (
    ShopOrderStatus.AUTHORIZED,
    ShopOrderStatus.CAPTURED,
    ShopOrderStatus.SETTLED,
    ShopOrderStatus.REFUNDED,
)


@dataclass
class GroupSaving:
    category: str
    supplier: str
    paid_cents: int
    alone_cents: int

    @property
    def saved_cents(self) -> int:
        return self.alone_cents - self.paid_cents


@dataclass
class ShopWeek:
    shop_code: str
    shop_name: str
    week: date
    groups: list[GroupSaving] = field(default_factory=list)
    swap_income_cents: int = 0
    swap_spent_cents: int = 0
    swap_saved_cents: int = 0
    flash_saved_cents: int = 0
    food_saved_grams: int = 0
    refunds_cents: int = 0

    @property
    def group_saved_cents(self) -> int:
        return sum(g.saved_cents for g in self.groups)

    @property
    def total_saved_cents(self) -> int:
        return self.group_saved_cents + self.swap_saved_cents + self.flash_saved_cents

    def to_dict(self) -> dict[str, Any]:
        return {
            "shop": self.shop_code,
            "week": str(self.week),
            "groups": [
                {
                    "category": g.category,
                    "supplier": g.supplier,
                    "paid_cents": g.paid_cents,
                    "alone_cents": g.alone_cents,
                    "saved_cents": g.saved_cents,
                }
                for g in self.groups
            ],
            "group_saved_cents": self.group_saved_cents,
            "swap_income_cents": self.swap_income_cents,
            "swap_spent_cents": self.swap_spent_cents,
            "swap_saved_cents": self.swap_saved_cents,
            "flash_saved_cents": self.flash_saved_cents,
            "food_saved_grams": self.food_saved_grams,
            "refunds_cents": self.refunds_cents,
            "total_saved_cents": self.total_saved_cents,
        }


async def shop_week(ctx: Ctx, shop: Shop, week: date) -> ShopWeek:
    report = ShopWeek(shop.code, shop.name, week)
    orders = await ctx.session.scalars(
        select(ShopOrder)
        .join(GroupOrder, GroupOrder.id == ShopOrder.group_order_id)
        .where(
            ShopOrder.shop_id == shop.id,
            GroupOrder.week_start == week,
            ShopOrder.status.in_(PAID_STATUSES),
        )
        .options(
            selectinload(ShopOrder.lines),
            selectinload(ShopOrder.group_order).selectinload(GroupOrder.awarded_supplier),
        )
    )
    for so in orders:
        group = so.group_order
        delivered = so.captured_amount_cents > 0
        lines = [
            ((line.qty_delivered if delivered else line.qty_requested) or 0, line)
            for line in so.lines
        ]
        paid = so.captured_amount_cents if delivered else so.hold_amount_cents
        alone = pricing.order_amount(
            [(qty, line.alone_unit_price_cents or 0) for qty, line in lines if qty],
            group.delivery_fee_cents,
        )
        report.groups.append(
            GroupSaving(
                group.category.value,
                group.awarded_supplier.name if group.awarded_supplier else "",
                paid,
                alone,
            )
        )
        report.refunds_cents += so.refunded_amount_cents
    swaps = await ctx.session.scalars(
        select(SwapOffer).where(
            SwapOffer.status == SwapStatus.COMPLETED,
            (SwapOffer.from_shop_id == shop.id) | (SwapOffer.to_shop_id == shop.id),
        )
    )
    for swap in swaps:
        if week_start(swap.expires_at) != week and week_start(swap.updated_at) != week:
            continue
        if swap.from_shop_id == shop.id:
            report.swap_income_cents += swap.price_cents
            report.food_saved_grams += swap.food_saved_grams
        else:
            report.swap_spent_cents += swap.price_cents
            if swap.kind == SwapKind.SURPLUS:
                report.swap_saved_cents += (
                    swap.qty * int(swap.details.get("cost_cents", 0)) - swap.price_cents
                )
    deals = await ctx.session.scalars(select(FlashDeal).where(FlashDeal.taken_qty > 0))
    for deal in deals:
        for purchase in deal.details.get("purchases", []):
            if purchase["shop"] == shop.code and purchase["week"] == str(week):
                report.flash_saved_cents += int(purchase.get("saved_cents", 0))
    return report


def report_text(report: ShopWeek, to_date_cents: int) -> str:
    parts = [f"🐝 Your Swarm week: {Money(report.total_saved_cents)} saved."]
    if report.groups:
        parts.append(f"Group buys cost {Money(report.group_saved_cents)} less than buying alone.")
    if report.swap_income_cents:
        parts.append(
            f"You earned {Money(report.swap_income_cents)} selling surplus "
            f"({report.food_saved_grams / 1000:.1f} kg of food saved)."
        )
    if report.swap_saved_cents:
        parts.append(f"Neighbour swaps saved you {Money(report.swap_saved_cents)}.")
    if report.flash_saved_cents:
        parts.append(f"Flash deals saved {Money(report.flash_saved_cents)}.")
    if report.refunds_cents:
        parts.append(f"Refunds received: {Money(report.refunds_cents)}.")
    parts.append(f"Since joining: {Money(to_date_cents)} saved.")
    return " ".join(parts)


async def shop_to_date(ctx: Ctx, shop: Shop) -> int:
    weeks = await ctx.session.scalars(
        select(GroupOrder.week_start).distinct().order_by(GroupOrder.week_start)
    )
    total = 0
    for week in weeks:
        total += (await shop_week(ctx, shop, week)).total_saved_cents
    return total


async def send_reports(ctx: Ctx, week: date) -> int:
    sent = 0
    for shop in await ctx.session.scalars(select(Shop).order_by(Shop.code)):
        report = await shop_week(ctx, shop, week)
        if not report.groups and not report.swap_income_cents and not report.swap_spent_cents:
            continue
        await ctx.say_to_owner(
            shop,
            report_text(report, await shop_to_date(ctx, shop)),
            kind="WEEKLY_REPORT",
            extra={"report": report.to_dict()},
        )
        sent += 1
    return sent


async def platform_summary(ctx: Ctx) -> dict[str, Any]:
    """Headline numbers for the live board."""
    session = ctx.session
    shops = list(await session.scalars(select(Shop)))
    weeks = list(await session.scalars(select(GroupOrder.week_start).distinct()))
    saved = 0
    food = 0
    for shop in shops:
        for week in weeks:
            report = await shop_week(ctx, shop, week)
            saved += report.total_saved_cents
            food += report.food_saved_grams
    negotiation_saved = 0
    for group in await session.scalars(
        select(GroupOrder).where(GroupOrder.status != GroupOrderStatus.CANCELLED)
    ):
        opening = group.summary.get("opening_best_landed_cents")
        final = group.summary.get("final_landed_cents")
        if opening and final:
            negotiation_saved += int(opening) - int(final)

    async def total(kind: PaymentKind, mode: PayPalModeEnum | None = None) -> int:
        query = select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.kind == kind, Payment.status == PaymentStatus.COMPLETED
        )
        if mode is not None:
            query = query.where(Payment.paypal_mode == mode)
        return int(await session.scalar(query) or 0)

    calls = await session.execute(
        select(Payment.paypal_mode, func.count())
        .where(Payment.status == PaymentStatus.COMPLETED)
        .group_by(Payment.paypal_mode)
    )
    by_mode = {mode.value: count for mode, count in calls.all()}
    return {
        "saved_cents": saved,
        "negotiation_saved_cents": negotiation_saved,
        "food_saved_grams": food,
        "captured_cents": await total(PaymentKind.CAPTURE) + await total(PaymentKind.SWAP_PAYMENT),
        "payouts_cents": await total(PaymentKind.PAYOUT),
        "refunds_cents": await total(PaymentKind.REFUND),
        "holds_outstanding_cents": await ctx.engine.outstanding_holds_cents(),
        "fees_cents": -(await ledger.balance(session, ledger.PLATFORM_FEES)),
        "paypal_calls": {"REAL": by_mode.get("REAL", 0), "SIMULATED": by_mode.get("SIMULATED", 0)},
        "books_balanced": (
            await ledger.platform_invariant_gap(session) == 0
            and not await ledger.unbalanced_transactions(session)
        ),
        "shops": len(shops),
        "delivered_lines": int(
            await session.scalar(
                select(func.count())
                .select_from(GroupOrderLine)
                .where(GroupOrderLine.qty_delivered > 0)
            )
            or 0
        ),
    }
