"""Owner conversations: buttons, typed answers, free text and photos."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.claims_agent import ClaimAssessment
from app.db.enums import ApprovalKind, ClaimDecision, ForecastStatus, ShopOrderStatus, SwapStatus
from app.db.models import AgentMessage, ApprovalRequest, Claim, DemandForecast, ShopOrder, SwapOffer
from app.features.week import WeekRunner
from app.llm.client import ScriptedLLM
from app.owners.service import OwnerService, parse_changes
from tests.conftest import DEMO_WEEK
from tests.helpers import shops_by_code

pytestmark = pytest.mark.db


async def owner_messages(db, code):
    rows = await db.scalars(
        select(AgentMessage)
        .where(AgentMessage.to_agent == f"owner:{code}")
        .order_by(AgentMessage.seq)
    )
    return list(rows)


def test_parse_changes():
    assert parse_changes("milk 40, eggs 0 and 3 butter") == {
        "milk-full-cream-1l": 40,
        "eggs-tray-30": 0,
        "butter-250g": 3,
    }


async def test_weekly_change_flow(db, world, ctx):
    shop = (await shops_by_code(db))["cafe-mei"]
    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    message = (await owner_messages(db, "cafe-mei"))[-1]
    change = next(a["id"] for a in message.payload["actions"] if a["label"] == "Change")
    service = OwnerService(ctx)
    await service.handle_action("cafe-mei", change)
    await service.handle_text("cafe-mei", "milk 40, oil 0")
    rows = list(await db.scalars(select(DemandForecast).where(DemandForecast.shop_id == shop.id)))
    assert {r.status for r in rows} == {ForecastStatus.CONFIRMED}
    replies = [m.text for m in await owner_messages(db, "cafe-mei")]
    assert any("Send me the changes" in t for t in replies) and any(
        "Confirmed" in t for t in replies
    )
    answered = await db.get(AgentMessage, message.id, populate_existing=True)
    assert answered.payload["answered"] == change


async def test_skip_and_free_text_intents(db, world, ctx):
    shop = (await shops_by_code(db))["teh-time"]
    await ctx.shop_agent(shop).weekly_proposal(db, DEMO_WEEK)
    service = OwnerService(ctx)
    await service.handle_text("teh-time", "need extra milk this week")
    milk = await db.scalar(
        select(DemandForecast)
        .where(DemandForecast.shop_id == shop.id)
        .order_by(DemandForecast.predicted_qty.desc())
    )
    assert "Done:" in (await owner_messages(db, "teh-time"))[-1].text
    await service.handle_text("teh-time", "we're closed, skip this week")
    statuses = set(
        await db.scalars(select(DemandForecast.status).where(DemandForecast.shop_id == shop.id))
    )
    assert statuses == {ForecastStatus.SKIPPED}
    approval = await db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.kind == ApprovalKind.WEEKLY_NEEDS)
    )
    assert approval.status.value == "REJECTED"
    assert milk is not None


async def test_delivery_short_by_text_then_emergency_then_photo_claim(db, world, ctx, runtime):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds"):
        await runner.run(key)
    from app.db.models import GroupOrder
    from app.features import delivery
    from app.features.group_buy import load_group

    dairy = await db.scalar(select(GroupOrder).where(GroupOrder.category == "DAIRY"))
    await delivery.dispatch(ctx, dairy.id)
    message = next(
        m for m in reversed(await owner_messages(db, "toast-and-co")) if m.type == "DELIVERY"
    )
    short = next(a["id"] for a in message.payload["actions"] if "missing" in a["label"])
    service = OwnerService(ctx)
    await service.handle_action("toast-and-co", short)
    await service.handle_text("toast-and-co", "milk 20")
    await delivery.finalize(ctx, dairy.id)
    group = await load_group(db, dairy.id)
    toast = next(so for so in group.shop_orders if so.shop.code == "toast-and-co")
    milk = next(line for line in toast.lines if line.item.product_code == "milk-full-cream-1l")
    assert milk.qty_delivered == 20 and toast.status == ShopOrderStatus.CAPTURED

    await service.handle_text("kopi-corner", "Out of eggs, need 30 now")
    emergency = await db.scalar(select(SwapOffer))
    assert emergency.status == SwapStatus.COMPLETED and emergency.qty == 1

    runtime.llm = ScriptedLLM(
        {
            "claims_agent.assess": ClaimAssessment(
                issue_type="DAMAGED",
                claim_supported=True,
                confidence=0.9,
                qty_affected=1,
                evidence="Leaking carton",
            )
        }
    )
    await service.handle_photo(
        "toast-and-co", b"jpeg", "image/jpeg", "milk carton leaking, 1 damaged"
    )
    claim = await db.scalar(select(Claim))
    assert claim.decision == ClaimDecision.AUTO_REFUNDED


async def test_help_and_report(db, world, ctx):
    service = OwnerService(ctx)
    await service.handle_text("cafe-mei", "help")
    await service.handle_text("cafe-mei", "report")
    texts = [m.text for m in await owner_messages(db, "cafe-mei")]
    assert any("I'm your Swarm agent" in t for t in texts)
    assert any("Your Swarm week" in t for t in texts)
    assert not await db.scalar(select(ShopOrder))


async def test_a_photo_claim_is_about_the_product_named_not_the_latest_charge(
    db, world, ctx, runtime
):
    """A bare photo used to be filed against whichever order was charged last, so "2 trays
    of eggs cracked" refunded a line of the packaging order."""
    from app.db.models import GroupOrderLine, Item

    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)
    charged = list(
        await db.scalars(
            select(ShopOrder)
            .join(ShopOrder.shop)
            .where(ShopOrder.captured_amount_cents > 0)
            .order_by(ShopOrder.captured_at.desc())
        )
    )
    shops = await shops_by_code(db)
    mine = [so for so in charged if so.shop_id == shops["bakery-lim"].id]
    assert len(mine) > 1  # several deliveries were charged, dairy not the last of them

    await OwnerService(ctx).handle_photo(
        "bakery-lim", b"jpeg", "image/jpeg", "2 trays of eggs arrived cracked"
    )
    claim = await db.scalar(select(Claim))
    line = await db.get(GroupOrderLine, claim.group_order_line_id)
    item = await db.get(Item, line.item_id)
    assert item.product_code == "eggs-tray-30" and claim.qty_affected == 2
    # No model looked at the photo, so a person decides; nothing is refunded yet.
    assert claim.decision == ClaimDecision.ESCALATED_OPERATOR and claim.refund_payment_id is None

    from app.features import claims

    refunded = await claims.operator_decision(ctx, claim.id, approve=True)
    assert refunded.decision == ClaimDecision.REFUNDED
    assert refunded.amount_cents == 2 * line.agreed_unit_price_cents
