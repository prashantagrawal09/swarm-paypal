"""Claims: an owner reports a short, damaged, expired or wrong delivery with a photo.

The claims agent assesses the photo and code decides (see `agents/claims_agent.py`):
clear and small claims are refunded through PayPal on the spot; the rest go to the
supplier's agent (accepts clear cases up to S$100, otherwise disputes) and then to a
person in the demo panel. Open claims hold back that much from the supplier's payout.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.enums import ClaimDecision, ClaimType, GroupOrderStatus, ShopOrderStatus
from app.db.models import Claim, GroupOrder, GroupOrderLine, MediaBlob, Shop, ShopOrder
from app.features import invoice_checker
from app.features.context import Ctx
from app.features.products import describe
from app.money import rules
from app.money.amount import Money

SUPPLIER_ACCEPT_LIMIT_CENTS = 10_000
CLAIMABLE = (ShopOrderStatus.CAPTURED, ShopOrderStatus.SETTLED, ShopOrderStatus.REFUNDED)


async def store_photo(ctx: Ctx, data: bytes, content_type: str, shop_id: uuid.UUID | None) -> str:
    blob = MediaBlob(content_type=content_type, size_bytes=len(data), data=data, shop_id=shop_id)
    ctx.session.add(blob)
    await ctx.session.flush()
    return f"/api/media/{blob.id}"


async def claimable_lines(ctx: Ctx, shop_code: str) -> list[GroupOrderLine]:
    """Lines from this shop's most recent paid deliveries, newest first."""
    shop = await ctx.shop(shop_code)
    rows = await ctx.session.scalars(
        select(GroupOrderLine)
        .join(ShopOrder, ShopOrder.id == GroupOrderLine.shop_order_id)
        .join(GroupOrder, GroupOrder.id == ShopOrder.group_order_id)
        .where(
            ShopOrder.shop_id == shop.id,
            ShopOrder.status.in_(CLAIMABLE),
            GroupOrderLine.qty_delivered > 0,
        )
        .options(selectinload(GroupOrderLine.item))
        .order_by(GroupOrder.week_start.desc())
        .limit(10)
    )
    return list(rows)


async def file_claim(
    ctx: Ctx,
    shop_code: str,
    line_id: uuid.UUID,
    claim_type: ClaimType,
    qty: int,
    description: str = "",
    photo: bytes | None = None,
    media_type: str | None = None,
    photo_url: str | None = None,
) -> Claim:
    """`photo_url`: the photo is already stored (sent before the owner said what was wrong)."""
    shop = await ctx.shop(shop_code)
    line = await ctx.session.get(GroupOrderLine, line_id)
    if line is None or line.shop_id != shop.id:
        raise rules.RuleViolation("NOT_YOUR_ORDER", "That order line isn't yours")
    shop_order = await ctx.session.get(ShopOrder, line.shop_order_id)
    assert shop_order is not None
    if shop_order.status not in CLAIMABLE:
        raise rules.RuleViolation("NOT_PAID", "You can claim once a delivery has been charged")
    if qty <= 0 or qty > (line.qty_delivered or 0):
        raise rules.RuleViolation("INVALID_QTY", "Claim at most what was delivered")
    if photo_url is None and photo is not None and media_type:
        photo_url = await store_photo(ctx, photo, media_type, shop.id)
    claim = Claim(
        shop_id=shop.id,
        shop_order_id=shop_order.id,
        group_order_line_id=line.id,
        type=claim_type,
        qty_affected=qty,
        description=description[:1000],
        photo_url=photo_url,
    )
    ctx.session.add(claim)
    await ctx.session.commit()
    claim = await ctx.claims_agent().process(ctx.session, ctx.engine, claim.id, photo, media_type)
    if claim.decision == ClaimDecision.ESCALATED_SUPPLIER:
        claim = await supplier_review(ctx, claim.id)
    if claim.decision in invoice_checker.OPEN_CLAIMS and claim.amount_cents > 0:
        await _tell_coordinator(ctx, claim, shop, line)
    return claim


async def _tell_coordinator(ctx: Ctx, claim: Claim, shop: Shop, line: GroupOrderLine) -> None:
    """An open claim puts money at stake: say so where the other agents can see it."""
    group = await ctx.session.scalar(
        select(GroupOrder)
        .join(ShopOrder, ShopOrder.group_order_id == GroupOrder.id)
        .where(ShopOrder.id == claim.shop_order_id)
        .options(selectinload(GroupOrder.awarded_supplier))
    )
    supplier = group.awarded_supplier if group else None
    if group is None or supplier is None:
        return
    await ctx.session.refresh(line, ["item"])
    unpaid = group.status not in (GroupOrderStatus.SETTLED, GroupOrderStatus.PARTIALLY_SETTLED)
    what = describe(line.item.product_code, claim.qty_affected)
    amount = Money(claim.amount_cents)
    await ctx.bus.publish(
        ctx.session,
        # With the order's invoice and payout, which is what it changes.
        conversation_id=f"invoice:{group.id}",
        from_agent="claims:swarm",
        to_agent="coordinator:swarm",
        type="CLAIM_OPEN",
        text=(
            f"{shop.name} reports {what} {claim.type.value.lower().replace('_', ' ')}. I can't "
            f"settle it myself, so a person will decide. "
            + (
                f"Hold {amount} back from {supplier.name}'s payout until then."
                if unpaid
                else f"{amount} is at stake; {supplier.name} has already been paid for this order."
            )
        ),
        payload={
            "claim_id": str(claim.id),
            "amount_cents": claim.amount_cents,
            "supplier": supplier.code,
            "held_back": unpaid,
        },
    )


async def report_damage(
    ctx: Ctx, shop_code: str, product: str, qty: int, *, note: str = ""
) -> Claim | None:
    """An owner says some of `product` from their latest charged delivery arrived damaged, and
    sends no photo, so a person decides. None when no such delivery has been charged yet."""
    lines = await claimable_lines(ctx, shop_code)
    line = next((item for item in lines if item.item.product_code == product), None)
    if line is None:
        return None
    qty = max(1, min(qty, line.qty_delivered or 0))
    said = f"{describe(product, qty)} arrived damaged."
    # The owner's side of the chat, so their phone shows what the agent is answering.
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"owner:{shop_code}",
        from_agent=f"owner:{shop_code}",
        to_agent=f"shop:{shop_code}",
        type="OWNER_REPLY",
        text=said[0].upper() + said[1:],
        payload={"simulated_owner": True},
    )
    description = f"{said} {note}".strip()
    return await file_claim(ctx, shop_code, line.id, ClaimType.DAMAGED, qty, description)


async def _settle_up(ctx: Ctx, claim: Claim) -> None:
    """A decided claim no longer holds anything back from the supplier's payout."""
    shop_order = await ctx.session.get(ShopOrder, claim.shop_order_id)
    if shop_order is not None:
        await invoice_checker.release_withheld(
            ctx,
            shop_order.group_order_id,
            refunded_cents=claim.amount_cents if claim.refund_payment_id else 0,
        )


async def supplier_review(ctx: Ctx, claim_id: uuid.UUID) -> Claim:
    """The supplier's agent policy: accept clear, modest claims; dispute the rest."""
    claim = await ctx.session.get(Claim, claim_id, populate_existing=True)
    assert claim is not None
    shop_order = await ctx.session.scalar(
        select(ShopOrder)
        .where(ShopOrder.id == claim.shop_order_id)
        .options(
            selectinload(ShopOrder.group_order).selectinload(GroupOrder.awarded_supplier),
            selectinload(ShopOrder.shop),
        )
    )
    assert shop_order is not None
    supplier = shop_order.group_order.awarded_supplier
    supported = bool(claim.ai_assessment.get("claim_supported"))
    accepts = supported and 0 < claim.amount_cents <= SUPPLIER_ACCEPT_LIMIT_CENTS
    conversation = f"claim:{claim.id}"
    supplier_id = f"supplier:{supplier.code}" if supplier else "supplier"
    await ctx.bus.publish(
        ctx.session,
        conversation_id=conversation,
        from_agent="claims:swarm",
        to_agent=supplier_id,
        type="CLAIM",
        text=(
            f"{shop_order.shop.name} reports {claim.qty_affected} unit(s) "
            f"{claim.type.value.lower()}. Evidence: "
            f"{claim.ai_assessment.get('evidence', 'n/a')}"
        ),
        payload={"claim_id": str(claim.id), "amount_cents": claim.amount_cents},
    )
    if accepts:
        await ctx.bus.publish(
            ctx.session,
            conversation_id=conversation,
            from_agent=supplier_id,
            to_agent="claims:swarm",
            type="CLAIM_ACCEPTED",
            text=f"Sorry about that. We accept; please refund {Money(claim.amount_cents)}.",
        )
        return await _refund(ctx, claim, ClaimDecision.REFUNDED, "Supplier accepted the claim")
    await ctx.bus.publish(
        ctx.session,
        conversation_id=conversation,
        from_agent=supplier_id,
        to_agent="claims:swarm",
        type="CLAIM_DISPUTED",
        text="We'd like a person to look at this one.",
    )
    claim.decision = ClaimDecision.ESCALATED_OPERATOR
    claim.resolution_note = "Supplier disputed; waiting for the Swarm operator."
    await ctx.session.commit()
    return claim


async def operator_decision(ctx: Ctx, claim_id: uuid.UUID, approve: bool, note: str = "") -> Claim:
    claim = await ctx.session.get(Claim, claim_id, populate_existing=True)
    if claim is None:
        raise LookupError("Claim not found")
    if claim.decision not in (
        ClaimDecision.ESCALATED_OPERATOR,
        ClaimDecision.ESCALATED_SUPPLIER,
        ClaimDecision.PENDING,
    ):
        return claim
    if approve:
        if claim.amount_cents <= 0:
            line = await ctx.session.get(GroupOrderLine, claim.group_order_line_id)
            claim.amount_cents = claim.qty_affected * (
                (line.agreed_unit_price_cents or 0) if line else 0
            )
        return await _refund(ctx, claim, ClaimDecision.REFUNDED, note or "Approved by the operator")
    claim.decision = ClaimDecision.REJECTED
    claim.resolution_note = note or "Rejected by the operator"
    await ctx.session.commit()
    await _settle_up(ctx, claim)
    owner = await ctx.session.get(Shop, claim.shop_id)
    if owner is not None:
        await ctx.say_to_owner(
            owner,
            f"Your claim was reviewed and not upheld: {claim.resolution_note}",
            kind="CLAIM_DECISION",
        )
    return claim


async def _refund(ctx: Ctx, claim: Claim, decision: ClaimDecision, note: str) -> Claim:
    payment = await ctx.engine.refund_shop_order(
        claim.shop_order_id,
        amount_cents=claim.amount_cents,
        reason=f"Claim: {claim.type.value.lower()}",
        refund_key=f"claim:{claim.id}",
    )
    claim.refund_payment_id = payment.id
    claim.decision = decision
    claim.resolution_note = note
    await ctx.session.commit()
    await _settle_up(ctx, claim)
    owner = await ctx.session.get(Shop, claim.shop_id)
    if owner is not None:
        await ctx.say_to_owner(
            owner,
            f"↩️ Refunded {Money(claim.amount_cents)} to your PayPal for the "
            f"{claim.type.value.lower()} items. {note}.",
            kind="CLAIM_REFUNDED",
            extra={"claim_id": str(claim.id), "paypal_id": payment.paypal_id},
        )
    return claim


async def stored_photo(ctx: Ctx, url: str) -> tuple[bytes, str] | None:
    """A photo stored by `store_photo`, by its URL: its bytes and media type."""
    try:
        blob = await ctx.session.get(MediaBlob, uuid.UUID(url.rsplit("/", 1)[-1]))
    except ValueError:
        return None
    return (blob.data, blob.content_type) if blob is not None else None
