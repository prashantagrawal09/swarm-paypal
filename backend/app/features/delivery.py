"""Delivery day (F2): owners confirm what arrived, and Swarm charges only for that.

Thursday morning `dispatch` tells every held shop its order is on the way, with buttons:
"All arrived", "Something's missing" (they type what arrived) and "Report a problem".
`confirm` records what the owner says; `finalize` (Thursday afternoon) treats anyone who
did not answer as a full delivery, then the money engine captures each shop's delivered
amount with `final_capture`, releasing the rest of the hold.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.shop_agent import KEYWORDS
from app.db.enums import GroupOrderStatus, ShopOrderStatus
from app.db.models import GroupOrderLine, ShopOrder
from app.features import actions as act
from app.features import group_buy
from app.features.buttons import close_buttons
from app.features.context import Ctx
from app.features.products import describe, describe_all
from app.money import rules
from app.money.amount import Money
from app.money.engine import BatchResult


async def _shop_order(ctx: Ctx, shop_order_id: uuid.UUID) -> ShopOrder:
    so = await ctx.session.scalar(
        select(ShopOrder)
        .where(ShopOrder.id == shop_order_id)
        .options(
            selectinload(ShopOrder.shop),
            selectinload(ShopOrder.group_order),
            selectinload(ShopOrder.lines).selectinload(GroupOrderLine.item),
        )
        .execution_options(populate_existing=True)
    )
    if so is None:
        raise LookupError("Order not found")
    return so


def _quantities(so: ShopOrder) -> dict[str, int]:
    return {line.item.product_code: line.qty_requested for line in so.lines}


async def dispatch(ctx: Ctx, group_id: uuid.UUID) -> int:
    """The truck is on its way: ask every held shop to confirm what arrives."""
    group = await group_buy.start_delivery(ctx.session, group_id)
    if group.status != GroupOrderStatus.OUT_FOR_DELIVERY:
        return 0
    supplier = group.awarded_supplier.name if group.awarded_supplier else "the supplier"
    notified = 0
    for so in group.shop_orders:
        if so.status != ShopOrderStatus.AUTHORIZED or so.delivery_confirmed_at:
            continue
        await ctx.say_to_owner(
            so.shop,
            f"🚚 Your {group.category.lower()} order from {supplier} arrives this morning: "
            f"{describe_all(_quantities(so))}. Tap when it's in, and I'll only charge for "
            "what arrived.",
            kind="DELIVERY",
            ref=so.id.hex,
            actions=[
                act.action(act.DELIVERY, "all", so.id, "All arrived ✓", "primary"),
                act.action(act.DELIVERY, "short", so.id, "Something's missing"),
                act.action(act.DELIVERY, "problem", so.id, "Damaged / wrong item"),
            ],
            extra={"group_order_id": str(group.id), "category": group.category.value},
        )
        notified += 1
    group.summary = {**group.summary, "dispatched_at": ctx.now().isoformat()}
    await ctx.session.commit()
    return notified


def parse_delivered(text: str, so: ShopOrder) -> dict[str, int]:
    """Read "milk 30, eggs 3" / "30 milk" / "9 of 10" into quantities per product.

    A bare number applies to the only line (or raises when the order has several lines).
    """
    ordered = _quantities(so)
    found: dict[str, int] = {}
    for part in re.split(r"[,;\n]|\band\b", text.lower()):
        numbers = re.findall(r"\d+", part)
        if not numbers:
            continue
        product = next(
            (p for p in ordered if any(word in part for word in KEYWORDS.get(p, ()))), None
        )
        if product is None:
            if len(ordered) != 1:
                continue
            product = next(iter(ordered))
        found[product] = int(numbers[0])
    if not found:
        raise rules.RuleViolation(
            "UNREADABLE", "Tell me what arrived, for example: milk 30, eggs 3"
        )
    for product, qty in found.items():
        if qty > ordered[product]:
            raise rules.RuleViolation(
                "TOO_MANY", f"You ordered {describe(product, ordered[product])}; got more?"
            )
    return found


async def confirm(
    ctx: Ctx,
    shop_order_id: uuid.UUID,
    delivered: dict[str, int] | None = None,
    *,
    note: str | None = None,
) -> ShopOrder:
    """Record what arrived (None = everything)."""
    so = await _shop_order(ctx, shop_order_id)
    if so.group_order.status != GroupOrderStatus.OUT_FOR_DELIVERY:
        raise rules.RuleViolation(
            "NOT_OUT_FOR_DELIVERY", "This delivery is already settled: you paid for what arrived."
        )
    if so.status != ShopOrderStatus.AUTHORIZED:
        raise rules.RuleViolation("NOT_HELD", "There is no hold for this order")
    short: list[str] = []
    for line in so.lines:
        product = line.item.product_code
        qty = (
            line.qty_requested if delivered is None else delivered.get(product, line.qty_requested)
        )
        if not 0 <= qty <= line.qty_requested:
            raise rules.RuleViolation("INVALID_QTY", "Delivered quantity out of range")
        line.qty_delivered = qty
        if qty < line.qty_requested:
            short.append(f"{qty} of {describe(product, line.qty_requested)}")
    so.delivery_confirmed_at = ctx.now()
    so.delivery_note = note
    await ctx.session.commit()
    await close_buttons(
        ctx.session, act.DELIVERY, so.id, "short" if short else "all", owner=f"owner:{so.shop.code}"
    )
    if short:
        text = (
            f"Noted: {', '.join(short)}. You'll only pay for what arrived; the rest of "
            "the hold goes back to you this afternoon."
        )
    else:
        text = "Great, everything's in. I'll settle it this afternoon."
    await ctx.say_to_owner(
        so.shop,
        text,
        kind="DELIVERY_CONFIRMED",
        extra={"shop_order_id": str(so.id), "short": short},
    )
    return so


async def finalize(ctx: Ctx, group_id: uuid.UUID) -> BatchResult:
    """Thursday afternoon: unconfirmed = full delivery; capture what arrived for everyone."""
    group = await group_buy.load_group(ctx.session, group_id)
    if group.status == GroupOrderStatus.HELD:
        group = await group_buy.start_delivery(ctx.session, group_id)
    if group.status != GroupOrderStatus.OUT_FOR_DELIVERY:
        return BatchResult()
    confirmed = {
        line.id: line.qty_delivered
        for so in group.shop_orders
        if so.delivery_confirmed_at
        for line in so.lines
        if line.qty_delivered is not None
    }
    await group_buy.record_delivery(ctx.session, group_id, ctx.now(), confirmed)
    result = await ctx.engine.capture_group_order(group_id)
    group = await group_buy.load_group(ctx.session, group_id)
    for so in group.shop_orders:
        # Settled now: a delivery nobody confirmed counts as complete, and can't be answered.
        await close_buttons(ctx.session, act.DELIVERY, so.id, owner=f"owner:{so.shop.code}")
    for so in group.shop_orders:
        if so.status != ShopOrderStatus.CAPTURED:
            continue
        released = so.hold_amount_cents - so.captured_amount_cents
        text = (
            f"💳 Charged {Money(so.captured_amount_cents)} for this week's {group.category.lower()}"
        )
        text += (
            f" (the hold was {Money(so.hold_amount_cents)}; {Money(released)} released "
            "back to you)."
            if released
            else "."
        )
        await ctx.say_to_owner(
            so.shop,
            text,
            kind="CHARGED",
            extra={
                "shop_order_id": str(so.id),
                "captured_cents": so.captured_amount_cents,
                "released_cents": released,
                "paypal_id": so.capture_id,
            },
        )
    return result
