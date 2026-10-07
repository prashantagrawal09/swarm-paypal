"""Emergency borrow (F5): "Out of eggs, need 30 now" is solved by a neighbour in minutes.

1. The requester's agent asks every shop within 500 m that normally stocks enough of the
   product.
2. The first neighbour to say yes wins. Price is code: what it costs the helper plus a 10%
   convenience premium.
3. Payment is instant (hold and capture straight away, then a payout to the helper), and
   the requester gets pickup instructions with the walking time. Everyone else hears it's
   sorted.
Simulated neighbours answer straight away; real ones get an "I can help" button.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.enums import PayPalModeEnum, SwapKind, SwapStatus
from app.db.models import Item, Shop, SwapOffer
from app.features import actions as act
from app.features.context import Ctx
from app.features.neighbours import distance_m, neighbours, reference_price, shop_item, uses
from app.features.products import describe
from app.money import rules
from app.money.amount import Money
from app.money.engine import NeedsOwnerApproval

EMERGENCY_RADIUS_M = 500
PREMIUM_BPS = 1000


def emergency_unit_price(cost_cents: int) -> int:
    return cost_cents * (10_000 + PREMIUM_BPS) // 10_000


async def request(ctx: Ctx, requester_code: str, product: str, qty: int) -> SwapOffer:
    requester = await ctx.shop(requester_code)
    if qty <= 0:
        raise rules.RuleViolation("INVALID_QTY", "Quantity must be positive")
    item = await shop_item(ctx, requester, product)
    estimate = emergency_unit_price(await reference_price(ctx, requester, product))
    helpers = [
        n
        for n in await neighbours(ctx, requester, EMERGENCY_RADIUS_M)
        if uses(n.shop, product) >= qty
    ]
    swap = SwapOffer(
        kind=SwapKind.EMERGENCY,
        to_shop_id=requester.id,
        item_id=item.id,
        qty=qty,
        price_cents=estimate * qty,
        currency=requester.currency,
        expires_at=ctx.now() + timedelta(hours=2),
        status=SwapStatus.OPEN,
        details={
            "product": product,
            "requested_wall_at": datetime.now(UTC).isoformat(),
            "helpers": [{"shop": n.shop.code, "distance_m": n.distance_m} for n in helpers],
        },
    )
    ctx.session.add(swap)
    await ctx.session.commit()
    what = describe(product, qty)
    conversation = f"emergency:{swap.id}"
    if not helpers:
        await ctx.say_to_owner(
            requester,
            f"Nobody within 500 m usually stocks {what}. Sorry!",
            kind="EMERGENCY_NO_HELPERS",
        )
        swap.status = SwapStatus.EXPIRED
        await ctx.session.commit()
        return swap
    await ctx.say_to_owner(
        requester,
        f"🆘 On it. Asking {len(helpers)} neighbour{'s' if len(helpers) > 1 else ''} within "
        f"500 m for {what}.",
        kind="EMERGENCY_SENT",
        conversation=conversation,
    )
    for near in helpers:
        await ctx.bus.publish(
            ctx.session,
            conversation_id=conversation,
            from_agent=f"shop:{requester.code}",
            to_agent=f"shop:{near.shop.code}",
            type="EMERGENCY_REQUEST",
            text=f"{requester.name} urgently needs {what}, {near.walk_minutes} min away. "
            "Can you spare it?",
            payload={"swap_id": str(swap.id), "qty": qty, "distance_m": near.distance_m},
        )
        if near.shop.paypal_mode == PayPalModeEnum.REAL:
            await ctx.say_to_owner(
                near.shop,
                f"🆘 {requester.name} ({near.walk_minutes} min walk) has run out and needs "
                f"{what} now. You'd get about {Money(estimate * qty)}. Can you help?",
                kind="EMERGENCY_REQUEST",
                ref=swap.id.hex,
                conversation=conversation,
                actions=[
                    act.action(act.EMERGENCY, "help", swap.id, "I can help", "primary"),
                    act.action(act.EMERGENCY, "no", swap.id, "Not now"),
                ],
            )
    for near in helpers:
        if near.shop.paypal_mode == PayPalModeEnum.SIMULATED:
            try:
                return await accept(ctx, swap.id, near.shop.code)
            except (rules.RuleViolation, NeedsOwnerApproval):
                break
    return swap


async def accept(ctx: Ctx, swap_id: uuid.UUID, helper_code: str) -> SwapOffer:
    swap = await ctx.session.scalar(
        select(SwapOffer)
        .where(SwapOffer.id == swap_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if swap is None:
        raise LookupError("Request not found")
    helper = await ctx.shop(helper_code)
    if swap.status != SwapStatus.OPEN:
        await ctx.session.commit()
        await ctx.say_to_owner(
            helper, "Thanks! Someone closer already sorted it.", kind="EMERGENCY_SORTED"
        )
        return swap
    requester = await ctx.session.get(Shop, swap.to_shop_id)
    item = await ctx.session.get(Item, swap.item_id)
    assert requester is not None and item is not None
    product = swap.details["product"]
    unit = emergency_unit_price(await reference_price(ctx, helper, product))
    swap.from_shop_id = helper.id
    swap.price_cents = unit * swap.qty
    swap.status = SwapStatus.ACCEPTED
    swap.food_saved_grams = 0
    await ctx.session.commit()
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"emergency:{swap.id}",
        from_agent=f"shop:{helper.code}",
        to_agent=f"shop:{requester.code}",
        type="HELP",
        text="We've got it. Come over!",
        payload={"swap_id": str(swap.id)},
    )
    try:
        await ctx.engine.authorize_swap(swap.id)
        swap = await ctx.engine.complete_swap(swap.id)
    except (rules.RuleViolation, NeedsOwnerApproval):
        swap.from_shop_id, swap.status = None, SwapStatus.OPEN
        swap.details = {**swap.details, "pending_helper": helper.code}
        await ctx.session.commit()
        raise
    elapsed = datetime.now(UTC) - datetime.fromisoformat(swap.details["requested_wall_at"])
    swap.details = {
        **swap.details,
        "seconds_to_sorted": round(elapsed.total_seconds(), 1),
        "unit_price_cents": unit,
    }
    await ctx.session.commit()
    metres = distance_m(requester, helper)
    minutes = max(1, round(metres / 80))
    what = describe(product, swap.qty)
    await ctx.say_to_owner(
        requester,
        f"✅ Sorted! {helper.name} has {what} for you. Paid {Money(swap.price_cents)} from your "
        f"PayPal. Pick up at {helper.address}, about {minutes} min walk ({metres} m).",
        kind="EMERGENCY_SORTED",
        extra={"swap_id": str(swap.id), "helper": helper.code},
    )
    await ctx.say_to_owner(
        helper,
        f"🙌 Thanks for helping {requester.name}! {Money(swap.price_cents)} is on its way to "
        f"your PayPal. They'll pick up {what} in a few minutes.",
        kind="EMERGENCY_HELPED",
        extra={"swap_id": str(swap.id)},
    )
    for entry in swap.details.get("helpers", []):
        if entry["shop"] not in (helper.code,):
            other = await ctx.shop(entry["shop"])
            if other.paypal_mode == PayPalModeEnum.REAL:
                await ctx.say_to_owner(
                    other,
                    f"{requester.name} is sorted now, thanks anyway!",
                    kind="EMERGENCY_SORTED",
                )
    return swap
