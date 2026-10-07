"""Owner approvals: Monday's weekly order and anything over the weekly spending limit (F9).

Over-limit requests can come from a group-order hold, a swap or a flash deal. The owner's
answer resumes exactly that step: approved holds are placed (the engine now allows the
approved excess), refused group orders are voided for that shop, and refused swaps or deals
simply don't happen.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.db.enums import ApprovalKind, ApprovalStatus, SwapKind
from app.db.models import ApprovalRequest, FlashDeal, Shop, ShopOrder, SwapOffer
from app.features import emergency_borrow, flash_deals, surplus_swap
from app.features.context import Ctx
from app.money.amount import Money


async def pending(ctx: Ctx, shop: Shop, kind: ApprovalKind | None = None) -> list[ApprovalRequest]:
    query = select(ApprovalRequest).where(
        ApprovalRequest.shop_id == shop.id, ApprovalRequest.status == ApprovalStatus.PENDING
    )
    if kind is not None:
        query = query.where(ApprovalRequest.kind == kind)
    return list(await ctx.session.scalars(query.order_by(ApprovalRequest.created_at)))


async def decide_over_limit(ctx: Ctx, approval_id: uuid.UUID, approve: bool, by: str) -> str:
    approval = await ctx.session.get(ApprovalRequest, approval_id, populate_existing=True)
    if approval is None or approval.kind != ApprovalKind.OVER_LIMIT:
        raise LookupError("Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        return "Already answered."
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_at = ctx.now()
    approval.decided_by = by
    await ctx.session.commit()
    shop = await ctx.session.get(Shop, approval.shop_id)
    assert shop is not None
    related = approval.related_id
    over = Money(int(approval.payload.get("over_by_cents", 0)))

    shop_order = await ctx.session.get(ShopOrder, related) if related else None
    if shop_order is not None:
        if approve:
            held = await ctx.engine.place_hold(shop_order.id)
            text = (
                f"👍 Approved. Holding {Money(held.hold_amount_cents)} on your PayPal "
                f"({over} over your usual limit, just this once)."
            )
        else:
            await ctx.engine.void_shop_order(shop_order.id, reason="Owner declined: over the limit")
            text = "OK, I've left you out of that order this week."
        await ctx.say_to_owner(shop, text, kind="APPROVAL_DONE")
        return text

    swap = await ctx.session.get(SwapOffer, related) if related else None
    if swap is not None:
        if not approve:
            await ctx.say_to_owner(shop, "OK, skipping that one.", kind="APPROVAL_DONE")
            return "Skipped."
        if swap.kind == SwapKind.SURPLUS:
            await surplus_swap.accept(ctx, swap.id, shop.code)
        else:
            helper = swap.details.get("pending_helper")
            if helper:
                await emergency_borrow.accept(ctx, swap.id, helper)
        return "Approved."

    deal = await ctx.session.get(FlashDeal, related) if related else None
    if deal is not None:
        if approve:
            qty = (deal.details.get("pending") or {}).get(shop.code)
            await flash_deals.buy(ctx, deal.id, shop.code, qty)
            return "Approved."
        await ctx.say_to_owner(shop, "OK, skipping the deal.", kind="APPROVAL_DONE")
        return "Skipped."
    return "Nothing to resume."


async def respond_weekly(
    ctx: Ctx, shop_code: str, verb: str, changes: dict[str, int] | None = None
) -> str:
    """Approve / change / skip next week's proposed order."""
    shop = await ctx.shop(shop_code)
    approvals = await pending(ctx, shop, ApprovalKind.WEEKLY_NEEDS)
    if not approvals:
        return "There's no weekly order waiting for you."
    week = date.fromisoformat(approvals[-1].payload["week"])
    agent = ctx.shop_agent(shop)
    if verb == "skip":
        await agent.skip_week(ctx.session, week)
        text = "No problem, you're skipping this week. 👋"
    else:
        await agent.confirm_needs(ctx.session, week, changes, owner_changed=bool(changes))
        text = "✅ Confirmed. I'll get you the best price with the group on Tuesday."
    await ctx.say_to_owner(shop, text, kind="WEEKLY_CONFIRMED")
    return text
