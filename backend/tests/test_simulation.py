"""Four simulated weeks with all twelve shops (SWARM_SPEC section 11).

Every week runs Monday to Sunday with the things that go wrong in real life: short
deliveries, a failed authorization, owners asked about their spending limit (approving
some, refusing others), a cancelled order, a late delivery that needs reauthorization,
refunds for claims, money withheld from a payout and released later, and a surplus swap.
After every week the books must balance and no capture may exceed its hold.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.clock import at_local
from app.db.enums import (
    ApprovalKind,
    ApprovalStatus,
    Category,
    GroupOrderStatus,
    PaymentKind,
    PaymentStatus,
    ShopOrderStatus,
    SwapKind,
    SwapStatus,
)
from app.db.models import ApprovalRequest, GroupOrder, Item, Payment, ShopOrder, SwapOffer
from app.features import group_buy
from app.money import ledger, rules
from app.money.engine import MoneyEngine
from app.paypal.errors import PayPalUnprocessableError
from app.paypal.simulated import SimulatedPayPalClient
from tests.conftest import DEMO_WEEK
from tests.helpers import prepare_week, shops_by_code

pytestmark = pytest.mark.db

WEEKS = 4


async def check_books(db, engine: MoneyEngine, sim: SimulatedPayPalClient) -> None:
    assert await ledger.unbalanced_transactions(db) == []
    assert await ledger.platform_invariant_gap(db) == 0
    assert (
        -(await ledger.balance(db, ledger.PLATFORM_HOLDS)) == await engine.outstanding_holds_cents()
    )
    over = await db.scalar(
        select(func.count()).where(ShopOrder.captured_amount_cents > ShopOrder.hold_amount_cents)
    )
    assert over == 0
    for auth in sim.state.authorizations.values():
        assert auth.captured_cents <= auth.amount.cents
    for capture in sim.state.captures.values():
        assert capture.refunded_cents <= capture.amount.cents


async def check_spending_limits(db, engine: MoneyEngine, week) -> None:
    for shop in (await shops_by_code(db)).values():
        committed = await engine.committed_this_week(shop.id, week)
        approved = await db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.shop_id == shop.id,
                ApprovalRequest.kind == ApprovalKind.OVER_LIMIT,
                ApprovalRequest.status == ApprovalStatus.APPROVED,
            )
        )
        extra = sum(int(a.payload["over_by_cents"]) for a in approved)
        assert committed <= shop.weekly_spend_limit_cents + extra, shop.code


async def test_four_weeks_twelve_shops(db, world, clock, engine, registry):
    rng = random.Random(41)
    sim = registry.platform("SIMULATED")
    assert isinstance(sim, SimulatedPayPalClient)
    totals = {"holds": 0, "captures": 0, "short": 0, "approvals": 0, "refused": 0, "swaps": 0}

    for week_index in range(WEEKS):
        week = DEMO_WEEK + timedelta(weeks=week_index)

        # Monday and Tuesday: forecasts, confirmations, pooling, award.
        clock.set(at_local(week, 9))
        groups = await prepare_week(db, week, clock)
        clock.set(at_local(week + timedelta(days=1), 15))
        for group in groups.values():
            await group_buy.award_at_list_prices(db, group.id)

        # Wednesday: holds.
        clock.set(at_local(week + timedelta(days=2), 9))
        if week_index == 1:
            sim.fail_next(
                "orders.create", PayPalUnprocessableError("Card declined", status_code=422)
            )
        for group in groups.values():
            result = await engine.place_holds(group.id)
            totals["holds"] += result.count(ShopOrderStatus.AUTHORIZED)
        approvals = list(
            await db.scalars(
                select(ApprovalRequest)
                .join(ShopOrder, ShopOrder.id == ApprovalRequest.related_id)
                .where(ApprovalRequest.status == ApprovalStatus.PENDING)
            )
        )
        for approval in approvals:
            if week_index % 2 == 0:
                approval.status = ApprovalStatus.APPROVED
                await db.commit()
                await engine.place_hold(approval.related_id)
                totals["approvals"] += 1
            else:
                approval.status = ApprovalStatus.REJECTED
                await db.commit()
                await engine.void_shop_order(approval.related_id, reason="Owner said not this week")
                totals["refused"] += 1
        for group in groups.values():
            group = await group_buy.load_group(db, group.id)
            if group.status == GroupOrderStatus.AWARDED:  # nobody could be held
                await engine.cancel_group_order(group.id, reason="No holds")
        if week_index == 2:
            await engine.cancel_group_order(groups[Category.PRODUCE].id, reason="Flooded farm road")
        await check_books(db, engine, sim)

        # Thursday: deliveries (packaging arrives late in week 4), captures.
        for category, group in groups.items():
            group = await group_buy.load_group(db, group.id)
            if group.status != GroupOrderStatus.HELD:
                continue
            late = week_index == 3 and category == Category.PACKAGING
            clock.set(at_local(week + timedelta(days=7 if late else 3), 10))
            delivered = {}
            for so in group.shop_orders:
                for line in so.lines:
                    if so.status == ShopOrderStatus.AUTHORIZED and rng.random() < 0.15:
                        delivered[line.id] = max(0, line.qty_requested - rng.randint(1, 3))
                        totals["short"] += 1
            await group_buy.record_delivery(db, group.id, clock.now(), delivered)
            captured = await engine.capture_group_order(group.id)
            totals["captures"] += captured.count(ShopOrderStatus.CAPTURED)
        await check_books(db, engine, sim)

        # Claims: refund part of one captured order in weeks 1 and 3.
        if week_index in (0, 2):
            so = await db.scalar(
                select(ShopOrder)
                .join(GroupOrder)
                .where(GroupOrder.week_start == week, ShopOrder.status == ShopOrderStatus.CAPTURED)
                .order_by(ShopOrder.captured_amount_cents.desc())
            )
            await engine.refund_shop_order(
                so.id,
                amount_cents=so.captured_amount_cents // 5,
                reason="Damaged on arrival",
                refund_key=f"claim-week-{week_index}",
            )

        # Settlement: pay suppliers (withhold some in week 2, release it next week).
        for category, group in groups.items():
            group = await group_buy.load_group(db, group.id)
            if group.status == GroupOrderStatus.DELIVERED:
                withhold = 1000 if (week_index == 1 and category == Category.DAIRY) else 0
                await engine.payout_supplier(group.id, withhold_cents=withhold)
        if week_index == 2:
            previous = await db.scalar(
                select(GroupOrder).where(
                    GroupOrder.week_start == week - timedelta(weeks=1),
                    GroupOrder.category == Category.DAIRY,
                )
            )
            await engine.payout_supplier(previous.id)

        # Friday: one surplus swap between neighbours.
        clock.set(at_local(week + timedelta(days=4), 16))
        shops = list((await shops_by_code(db)).values())
        seller, buyer = rng.sample(shops, 2)
        milk = await db.scalar(select(Item).where(Item.sku == "MILK-FC-1L-MEADOW"))
        swap = SwapOffer(
            kind=SwapKind.SURPLUS,
            from_shop_id=seller.id,
            to_shop_id=buyer.id,
            item_id=milk.id,
            qty=6,
            price_cents=900,
            expires_at=clock.now() + timedelta(days=1),
            status=SwapStatus.ACCEPTED,
            food_saved_grams=6 * 1050,
        )
        db.add(swap)
        await db.commit()
        try:
            await engine.authorize_swap(swap.id)
            await engine.complete_swap(swap.id)
            totals["swaps"] += 1
        except rules.RuleViolation:
            swap.status = SwapStatus.CANCELLED  # buyer over its limit; nobody is charged
            pending = await db.scalars(
                select(ApprovalRequest).where(ApprovalRequest.related_id == swap.id)
            )
            for approval in pending:
                approval.status = ApprovalStatus.EXPIRED
            await db.commit()

        # Sunday: the books.
        clock.set(at_local(week + timedelta(days=6), 20))
        await check_books(db, engine, sim)
        await check_spending_limits(db, engine, week)

    # Across all four weeks.
    statuses = set(await db.scalars(select(GroupOrder.status)))
    assert statuses <= {GroupOrderStatus.SETTLED, GroupOrderStatus.CANCELLED}
    assert totals["holds"] > 100 and totals["captures"] > 100 and totals["short"] > 5
    assert totals["approvals"] + totals["refused"] > 0
    reauths = await db.scalar(
        select(func.count()).where(Payment.kind == PaymentKind.REAUTHORIZATION)
    )
    assert reauths > 0
    failed = await db.scalar(select(func.count()).where(Payment.status == PaymentStatus.FAILED))
    assert failed == 1
    fees = -(await ledger.balance(db, ledger.PLATFORM_FEES))
    assert await ledger.balance(db, ledger.PLATFORM_CLEARING) == fees > 0
