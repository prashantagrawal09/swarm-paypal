"""Surplus swap (F4): stock about to expire goes to a neighbour who is running low.

1. The seller's agent prices the surplus by code: a discount off what the stock cost the
   shop, bigger the closer it is to expiry (20% with 4+ days left, 35% with 2-3, 50% on
   the last day), and never below the owner's minimum (50% of cost by default).
2. It offers it to up to three nearby shops (within 800 m) that use the product and accept
   the brand, most in need first.
3. Each buyer's agent applies its owner's rule: accept if the price is at most 85% of what
   the product costs that shop and it fits the weekly limit. Simulated shops answer
   straight away; real shops' owners get Accept / No thanks buttons on Telegram.
4. First acceptance wins: the buyer's PayPal is held; when the seller taps "Handed over",
   the hold is captured and the seller is paid out. Food saved is recorded.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.clock import at_local, local_time, week_start
from app.db.enums import PayPalModeEnum, SwapKind, SwapStatus
from app.db.models import Item, Shop, SwapOffer
from app.features import actions as act
from app.features.buttons import close_buttons
from app.features.context import Ctx
from app.features.group_buy import shop_accepts
from app.features.neighbours import neighbours, reference_price, shop_item, uses
from app.features.products import describe, wording
from app.money import rules
from app.money.amount import Money
from app.money.engine import NeedsOwnerApproval

SURPLUS_RADIUS_M = 800
MAX_CANDIDATES = 3
BUYER_MAX_SHARE = 0.85
DEFAULT_MIN_PRICE_SHARE = 0.5


def surplus_unit_price(
    cost_cents: int, days_left: int, min_share: float = DEFAULT_MIN_PRICE_SHARE
) -> int:
    discount = 0.5 if days_left <= 1 else 0.35 if days_left <= 3 else 0.2
    return max(round(cost_cents * (1 - discount)), round(cost_cents * min_share))


async def offer(
    ctx: Ctx, seller_code: str, product: str, qty: int, expires_on: date | None = None
) -> SwapOffer:
    seller = await ctx.shop(seller_code)
    if qty <= 0:
        raise rules.RuleViolation("INVALID_QTY", "Quantity must be positive")
    today = local_time(ctx.now()).date()
    expires_on = expires_on or today + timedelta(days=2)
    item = await shop_item(ctx, seller, product)
    cost = await reference_price(ctx, seller, product)
    min_share = float(seller.preferences.get("min_surplus_price_share", DEFAULT_MIN_PRICE_SHARE))
    unit = surplus_unit_price(cost, (expires_on - today).days, min_share)
    swap = SwapOffer(
        kind=SwapKind.SURPLUS,
        from_shop_id=seller.id,
        item_id=item.id,
        qty=qty,
        price_cents=unit * qty,
        currency=seller.currency,
        expires_at=at_local(expires_on, 20),
        status=SwapStatus.OPEN,
        food_saved_grams=qty * item.unit_weight_grams,
        details={
            "product": product,
            "unit_price_cents": unit,
            "cost_cents": cost,
            "discount_pct": round(100 * (1 - unit / cost)),
            "expires_on": str(expires_on),
        },
    )
    ctx.session.add(swap)
    await ctx.session.flush()

    candidates = []
    for near in await neighbours(ctx, seller, SURPLUS_RADIUS_M):
        if uses(near.shop, product) and shop_accepts(near.shop, item, item)[0]:
            candidates.append(near)
    candidates.sort(key=lambda n: (-uses(n.shop, product), n.distance_m))
    candidates = candidates[:MAX_CANDIDATES]
    swap.details = {
        **swap.details,
        "candidates": [{"shop": n.shop.code, "distance_m": n.distance_m} for n in candidates],
    }
    await ctx.session.commit()

    what = describe(product, qty)
    price = f"{Money(unit)}/{wording(product).unit} ({swap.details['discount_pct']}% off)"
    conversation = f"swap:{swap.id}"
    if not candidates:
        await ctx.say_to_owner(
            seller,
            f"No neighbour needs {what} right now. I'll keep looking.",
            kind="SURPLUS_NO_TAKERS",
        )
        return swap
    await ctx.say_to_owner(
        seller,
        f"♻️ Offering your {what} (expires {expires_on:%a}) to "
        f"{', '.join(n.shop.name for n in candidates)} at {price}.",
        kind="SURPLUS_POSTED",
        conversation=conversation,
    )
    for near in candidates:
        await ctx.bus.publish(
            ctx.session,
            conversation_id=conversation,
            from_agent=f"shop:{seller.code}",
            to_agent=f"shop:{near.shop.code}",
            type="SURPLUS_OFFER",
            text=f"{seller.name} has {what} expiring {expires_on:%A}, {price}, "
            f"{near.walk_minutes} min walk away. Interested?",
            payload={
                "swap_id": str(swap.id),
                "unit_price_cents": unit,
                "qty": qty,
                "distance_m": near.distance_m,
            },
        )

    for near in candidates:
        decision, reason = await buyer_decision(ctx, near.shop, product, unit, swap)
        if near.shop.paypal_mode == PayPalModeEnum.REAL:
            await ctx.say_to_owner(
                near.shop,
                f"🥛 {seller.name} ({near.walk_minutes} min walk) has {what} expiring "
                f"{expires_on:%a} for {Money(unit * qty)} total, {price}. Want it?",
                kind="SURPLUS_OFFER",
                ref=swap.id.hex,
                conversation=conversation,
                actions=[
                    act.action(act.SWAP_OFFER, "yes", swap.id, "Yes, I'll take it", "primary"),
                    act.action(act.SWAP_OFFER, "no", swap.id, "No thanks"),
                ],
            )
            continue
        await ctx.bus.publish(
            ctx.session,
            conversation_id=conversation,
            from_agent=f"shop:{near.shop.code}",
            to_agent=f"shop:{seller.code}",
            type="ACCEPT" if decision else "DECLINE",
            text=("Yes please, we'll take it." if decision else f"No thanks: {reason}."),
            payload={"swap_id": str(swap.id), "reason": reason},
        )
        if decision:
            try:
                return await accept(ctx, swap.id, near.shop.code)
            except (rules.RuleViolation, NeedsOwnerApproval):
                continue
    return swap


async def buyer_decision(
    ctx: Ctx, buyer: Shop, product: str, unit_price: int, swap: SwapOffer
) -> tuple[bool, str]:
    """The buyer agent's rule, applied in code."""
    cost = await reference_price(ctx, buyer, product)
    if unit_price > cost * BUYER_MAX_SHARE:
        return False, "not cheap enough versus our own price"
    committed = await ctx.engine.committed_this_week(buyer.id, week_start(swap.expires_at))
    check = rules.check_spend_limit(buyer.weekly_spend_limit_cents, committed, swap.price_cents)
    if not check.allowed:
        return False, "over this week's budget"
    return True, ""


async def _swap(ctx: Ctx, swap_id: uuid.UUID, *, lock: bool = False) -> SwapOffer:
    query = (
        select(SwapOffer).where(SwapOffer.id == swap_id).execution_options(populate_existing=True)
    )
    swap = await ctx.session.scalar(query.with_for_update() if lock else query)
    if swap is None:
        raise LookupError("Swap not found")
    return swap


async def accept(ctx: Ctx, swap_id: uuid.UUID, buyer_code: str) -> SwapOffer:
    swap = await _swap(ctx, swap_id, lock=True)
    buyer = await ctx.shop(buyer_code)
    if swap.status != SwapStatus.OPEN or swap.kind != SwapKind.SURPLUS:
        await ctx.session.commit()
        await ctx.say_to_owner(
            buyer, "Too late, someone else took it. I'll catch the next one!", kind="SWAP_TAKEN"
        )
        return swap
    seller = await ctx.session.get(Shop, swap.from_shop_id)
    item = await ctx.session.get(Item, swap.item_id)
    assert seller is not None and item is not None
    swap.to_shop_id = buyer.id
    swap.status = SwapStatus.ACCEPTED
    await ctx.session.commit()
    # This buyer said yes; everyone else's offer is no longer open.
    await close_buttons(ctx.session, act.SWAP_OFFER, swap.id, "yes", owner=f"owner:{buyer.code}")
    await close_buttons(ctx.session, act.SWAP_OFFER, swap.id)
    try:
        await ctx.engine.authorize_swap(swap.id)
    except (rules.RuleViolation, NeedsOwnerApproval):
        swap.to_shop_id, swap.status = None, SwapStatus.OPEN
        await ctx.session.commit()
        raise
    near: dict[str, int] = next(
        (c for c in swap.details.get("candidates", []) if c["shop"] == buyer.code), {}
    )
    minutes = max(1, round(near.get("distance_m", 300) / 80))
    product = swap.details["product"]
    what = describe(product, swap.qty)
    conversation = f"swap:{swap.id}"
    await ctx.say_to_owner(
        buyer,
        f"✅ Deal: {what} from {seller.name} for {Money(swap.price_cents)}. "
        f"Pick up at {seller.address} ({minutes} min walk). I've held the money on your PayPal.",
        kind="SWAP_AGREED",
        conversation=conversation,
    )
    await ctx.say_to_owner(
        seller,
        f"✅ {buyer.name} is taking your {what} for {Money(swap.price_cents)}. "
        "Tap when you've handed it over and the money comes straight to your PayPal.",
        kind="SWAP_AGREED",
        ref=swap.id.hex,
        conversation=conversation,
        actions=[act.action(act.HANDOVER, "done", swap.id, "Handed over ✓", "primary")],
    )
    if seller.paypal_mode == PayPalModeEnum.SIMULATED:
        return await handover(ctx, swap.id)
    return swap


async def decline(ctx: Ctx, swap_id: uuid.UUID, buyer_code: str) -> None:
    buyer = await ctx.shop(buyer_code)
    swap = await _swap(ctx, swap_id)
    seller = await ctx.session.get(Shop, swap.from_shop_id)
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"swap:{swap.id}",
        from_agent=f"shop:{buyer.code}",
        to_agent=f"shop:{seller.code if seller else 'unknown'}",
        type="DECLINE",
        text="No thanks this time.",
    )
    await close_buttons(ctx.session, act.SWAP_OFFER, swap.id, "no", owner=f"owner:{buyer.code}")
    await ctx.say_to_owner(buyer, "No problem, I'll let them know.", kind="SWAP_DECLINED")


async def handover(ctx: Ctx, swap_id: uuid.UUID) -> SwapOffer:
    """Seller handed the goods over: capture the buyer's hold, pay the seller."""
    swap = await _swap(ctx, swap_id)
    if swap.status == SwapStatus.COMPLETED:
        return swap
    swap = await ctx.engine.complete_swap(swap.id)
    buyer = await ctx.session.get(Shop, swap.to_shop_id)
    seller = await ctx.session.get(Shop, swap.from_shop_id)
    assert buyer is not None and seller is not None
    await close_buttons(ctx.session, act.HANDOVER, swap.id, "done", owner=f"owner:{seller.code}")
    kg = swap.food_saved_grams / 1000
    await ctx.say_to_owner(
        seller,
        f"💸 {Money(swap.price_cents)} is on its way to your PayPal. {kg:.1f} kg of food saved "
        "from the bin. Nice one!",
        kind="SWAP_PAID",
        extra={"swap_id": str(swap.id), "food_saved_grams": swap.food_saved_grams},
    )
    await ctx.say_to_owner(
        buyer,
        f"Paid {Money(swap.price_cents)} to {seller.name}. Enjoy!",
        kind="SWAP_PAID",
        extra={"swap_id": str(swap.id)},
    )
    return swap
