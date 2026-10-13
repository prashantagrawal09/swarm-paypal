"""Delivery confirmation, surplus swaps, emergencies, claims, flash deals, approvals, connect."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agents.claims_agent import ClaimAssessment
from app.db.enums import (
    ApprovalStatus,
    Category,
    ClaimDecision,
    ClaimType,
    FlashDealStatus,
    ShopOrderStatus,
    SwapStatus,
)
from app.db.models import ApprovalRequest, GroupOrderLine, Shop, ShopOrder
from app.features import (
    approvals,
    claims,
    connect,
    delivery,
    emergency_borrow,
    flash_deals,
    group_buy,
    surplus_swap,
)
from app.features.surplus_swap import surplus_unit_price
from app.features.week import WeekRunner
from app.llm.client import ScriptedLLM
from app.money import ledger, rules
from tests.conftest import DEMO_WEEK
from tests.helpers import awarded

pytestmark = pytest.mark.db


async def books_ok(db):
    assert await ledger.unbalanced_transactions(db) == []
    assert await ledger.platform_invariant_gap(db) == 0


def test_surplus_pricing_gets_cheaper_near_expiry():
    assert surplus_unit_price(200, 5) == 160
    assert surplus_unit_price(200, 2) == 130
    assert surplus_unit_price(200, 1) == 100
    assert surplus_unit_price(200, 0, min_share=0.6) == 120


async def test_delivery_confirmation_and_partial_capture(db, world, ctx, clock):
    group = await awarded(db, DEMO_WEEK, clock, Category.PACKAGING)
    await ctx.engine.place_holds(group.id)
    assert await delivery.dispatch(ctx, group.id) == len(group.shop_orders)
    group = await group_buy.load_group(db, group.id)
    so = group.shop_orders[0]
    product = so.lines[0].item.product_code
    ordered = so.lines[0].qty_requested
    words = {
        "paper-cups-12oz-50": "cups",
        "lids-50": "lids",
        "napkins-100": "napkins",
        "takeaway-box-50": "boxes",
    }[product]
    parsed = delivery.parse_delivered(f"only {ordered - 2} {words} came", so)
    assert parsed == {product: ordered - 2}
    with pytest.raises(rules.RuleViolation):
        delivery.parse_delivered("no idea", so)
    await delivery.confirm(ctx, so.id, parsed)
    result = await delivery.finalize(ctx, group.id)
    assert result.count(ShopOrderStatus.CAPTURED) == len(group.shop_orders)
    so = await db.get(ShopOrder, so.id, populate_existing=True)
    assert so.captured_amount_cents < so.hold_amount_cents
    await books_ok(db)


async def _through_settlement(ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    for key in ("forecasts", "negotiation", "holds", "delivery", "settlement"):
        await runner.run(key)


async def test_surplus_offer_goes_to_a_neighbour_and_pays_the_seller(db, world, ctx):
    await _through_settlement(ctx)
    swap = await surplus_swap.offer(
        ctx, "brew-lab", "milk-full-cream-1l", 6, ctx.now().date() + timedelta(days=1)
    )
    assert swap.status == SwapStatus.COMPLETED
    assert swap.details["discount_pct"] >= 45
    assert swap.to_shop_id is not None and swap.food_saved_grams == 6 * 1050
    seller = await db.scalar(select(Shop).where(Shop.code == "brew-lab"))
    assert await ledger.balance(db, f"shop:{seller.code}:sales") == -swap.price_cents
    await books_ok(db)


async def test_emergency_is_sorted_by_the_nearest_neighbour(db, world, ctx):
    await _through_settlement(ctx)
    swap = await emergency_borrow.request(ctx, "kopi-corner", "eggs-tray-30", 1)
    assert swap.status == SwapStatus.COMPLETED
    assert swap.details["seconds_to_sorted"] < 120
    helper = await db.get(Shop, swap.from_shop_id)
    requester = await db.get(Shop, swap.to_shop_id)
    from app.features.neighbours import distance_m

    assert distance_m(helper, requester) <= emergency_borrow.EMERGENCY_RADIUS_M
    await books_ok(db)


async def test_claim_with_clear_photo_is_refunded(db, world, ctx, runtime):
    await _through_settlement(ctx)
    runtime.llm = ScriptedLLM(
        {
            "claims_agent.assess": ClaimAssessment(
                issue_type="DAMAGED",
                claim_supported=True,
                confidence=0.95,
                qty_affected=1,
                evidence="One cracked tray.",
            )
        }
    )
    lines = await claims.claimable_lines(ctx, "nasi-lemak-hub")
    eggs = next(line for line in lines if line.item.product_code == "eggs-tray-30")
    claim = await claims.file_claim(
        ctx,
        "nasi-lemak-hub",
        eggs.id,
        ClaimType.DAMAGED,
        1,
        "cracked tray",
        b"fake-jpeg",
        "image/jpeg",
    )
    assert claim.decision == ClaimDecision.AUTO_REFUNDED
    assert claim.photo_url and claim.photo_url.startswith("/api/media/")
    await books_ok(db)


async def test_unclear_claim_goes_to_supplier_then_operator(db, world, ctx, runtime):
    await _through_settlement(ctx)
    runtime.llm = ScriptedLLM(
        {
            "claims_agent.assess": ClaimAssessment(
                issue_type="DAMAGED",
                claim_supported=True,
                confidence=0.7,
                qty_affected=2,
                evidence="Some damage.",
            )
        }
    )
    lines = await claims.claimable_lines(ctx, "bakery-lim")
    butter = next(line for line in lines if line.item.product_code == "butter-250g")
    claim = await claims.file_claim(
        ctx, "bakery-lim", butter.id, ClaimType.DAMAGED, 2, "dented", b"fake-jpeg", "image/jpeg"
    )
    assert claim.decision == ClaimDecision.REFUNDED  # not sure enough for auto; supplier accepted
    big = next(line for line in lines if line.item.product_code == "eggs-tray-30")
    runtime.llm = ScriptedLLM(
        {
            "claims_agent.assess": ClaimAssessment(
                issue_type="DAMAGED",
                claim_supported=False,
                confidence=0.6,
                qty_affected=0,
                evidence="Hard to tell.",
            )
        }
    )
    disputed = await claims.file_claim(
        ctx, "bakery-lim", big.id, ClaimType.DAMAGED, 1, "?", b"fake-jpeg", "image/jpeg"
    )
    assert disputed.decision == ClaimDecision.ESCALATED_OPERATOR
    resolved = await claims.operator_decision(ctx, disputed.id, approve=True, note="Checked")
    assert resolved.decision == ClaimDecision.REFUNDED
    await books_ok(db)


async def test_flash_deal_purchase(db, world, ctx):
    await _through_settlement(ctx)
    deal = await flash_deals.post(ctx, "johorfarm", "TOMATO-1KG-CAMERON", 20, 40)
    assert deal.price_cents >= 320  # never below the supplier floor
    if deal.taken_qty == 0:
        deal = await flash_deals.buy(ctx, deal.id, "little-pasta", 5)
    assert deal.taken_qty > 0
    with pytest.raises(rules.RuleViolation):
        await flash_deals.buy(ctx, deal.id, "little-pasta", 999)
    deal = await flash_deals.buy(ctx, deal.id, "green-bowl", deal.qty_available - deal.taken_qty)
    assert deal.status == FlashDealStatus.SOLD_OUT
    await books_ok(db)


async def test_over_limit_approval_resumes_the_hold(db, world, ctx, clock):
    group = await awarded(db, DEMO_WEEK, clock, Category.DAIRY)
    so = group.shop_orders[0]
    so.shop.weekly_spend_limit_cents = 500
    await db.commit()
    so_id = so.id
    await ctx.engine.place_holds(group.id)
    approval = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.related_id == so_id))
    assert approval.status == ApprovalStatus.PENDING
    await approvals.decide_over_limit(ctx, approval.id, True, "owner")
    assert (
        await db.get(ShopOrder, so_id, populate_existing=True)
    ).status == ShopOrderStatus.AUTHORIZED


async def test_connect_paypal_simulated(db, world, ctx):
    shop = await db.scalar(select(Shop).where(Shop.code == "cafe-mei"))
    shop.vault_id = None
    await db.commit()
    started = await connect.start(ctx, "cafe-mei")
    assert "sim_order=" in started["approve_url"]
    await connect.simulated_approve(ctx, "cafe-mei", started["order_id"])
    done = await connect.complete(ctx, "cafe-mei", started["order_id"])
    assert done["connected"]
    shop = await db.get(Shop, shop.id, populate_existing=True)
    assert shop.vault_id and shop.vault_id.startswith("SIM-VAULT-")
    with pytest.raises(ValueError):
        await connect.complete(ctx, "cafe-mei", "SIM-ORDER-999999")


async def test_lines_belong_to_their_shop(db, world, ctx):
    await _through_settlement(ctx)
    other = await db.scalar(
        select(GroupOrderLine)
        .join(GroupOrderLine.shop_order)
        .where(ShopOrder.shop.has(code="brew-lab"))
    )
    with pytest.raises(rules.RuleViolation):
        await claims.file_claim(ctx, "cafe-mei", other.id, ClaimType.SHORT, 1)


async def test_flash_deal_times_are_local_and_ended_deals_say_so(db, world, ctx, runtime):
    """The deal message used to show the UTC hour as if it were Singapore time, and the API
    went on calling a deal open days after it had ended."""
    from sqlalchemy import select

    from app.api.world import flash_deal_list
    from app.clock import local_time
    from app.db.models import AgentMessage

    deal = await flash_deals.post(ctx, "johorfarm", "TOMATO-1KG-CAMERON", 20, 40, hours=8)
    message = await db.scalar(select(AgentMessage).where(AgentMessage.type == "FLASH_DEAL"))
    ends = local_time(deal.expires_at)
    assert f"until {ends:%H:%M}" in message.text
    assert ends.utcoffset().total_seconds() == 8 * 3600  # Singapore, not UTC

    listed = (await flash_deal_list(ctx))[0]
    assert listed["status"] == "OPEN"
    runtime.clock.advance(hours=9)
    listed = (await flash_deal_list(ctx))[0]
    assert listed["status"] == "EXPIRED"
