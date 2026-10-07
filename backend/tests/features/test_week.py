"""A whole demo week, Monday to Sunday, through the week runner."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db.enums import (
    GroupOrderStatus,
    InvoiceCheckStatus,
    PaymentKind,
    ShopOrderStatus,
    SwapKind,
    SwapStatus,
)
from app.db.models import (
    AgentMessage,
    FlashDeal,
    GroupOrder,
    Invoice,
    Payment,
    ShopOrder,
    SwapOffer,
)
from app.features.week import STEP_KEYS, WeekRunner
from app.money import ledger
from tests.conftest import DEMO_WEEK

pytestmark = pytest.mark.db


async def books_ok(db, ctx):
    assert await ledger.unbalanced_transactions(db) == []
    assert await ledger.platform_invariant_gap(db) == 0
    assert (
        -(await ledger.balance(db, ledger.PLATFORM_HOLDS))
        == await ctx.engine.outstanding_holds_cents()
    )


async def test_full_demo_week(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    results = {}
    for key in STEP_KEYS:
        step, result = await runner.run_next()
        assert step is not None and step.key == key
        results[key] = result
        await books_ok(db, ctx)
    assert await runner.next_step() is None

    assert results["forecasts"]["auto_confirmed"] == 12
    assert set(results["negotiation"]["groups"]) == {"DAIRY", "PACKAGING", "PANTRY", "PRODUCE"}
    assert results["holds"]["flash_deal"] is not None
    deal = await db.get(FlashDeal, uuid.UUID(results["holds"]["flash_deal"]))
    assert deal is not None and deal.taken_qty > 0  # simulated owners took the top-up deal

    short = results["delivery"]["DAIRY"]["short"]
    assert short and short[0]["shop"] == "cafe-mei" and short[0]["delivered"] < short[0]["ordered"]
    mei = await db.scalar(
        select(ShopOrder)
        .join(GroupOrder)
        .where(GroupOrder.category == "DAIRY")
        .join(ShopOrder.shop)
        .where(ShopOrder.shop.has(code="cafe-mei"))
    )
    assert mei.captured_amount_cents < mei.hold_amount_cents

    dairy_invoices = results["settlement"]["DAIRY"]["invoices"]
    assert [i["status"] for i in dairy_invoices] == ["REJECTED", "APPROVED"]
    assert dairy_invoices[0]["overcharge_cents"] > 0
    rejected = await db.scalar(
        select(Invoice).where(Invoice.check_status == InvoiceCheckStatus.REJECTED)
    )
    assert (
        "agreed" in rejected.check_report["summary"]
        and "overcharge" in rejected.check_report["summary"]
    )
    statuses = set(await db.scalars(select(GroupOrder.status)))
    assert statuses <= {GroupOrderStatus.SETTLED, GroupOrderStatus.PARTIALLY_SETTLED}
    paid = await db.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.paid_payment_id.is_not(None))
    )
    assert paid == 4

    swaps = {s.kind: s for s in await db.scalars(select(SwapOffer))}
    assert swaps[SwapKind.SURPLUS].status == SwapStatus.COMPLETED
    assert swaps[SwapKind.SURPLUS].food_saved_grams == 8 * 1050
    assert swaps[SwapKind.EMERGENCY].status == SwapStatus.COMPLETED
    assert swaps[SwapKind.EMERGENCY].from_shop_id is not None

    assert results["report"]["reports_sent"] == 12
    assert results["report"]["saved_cents"] > 100_000
    reports = await db.scalar(select(func.count()).where(AgentMessage.type == "WEEKLY_REPORT"))
    assert reports == 12
    payouts = await db.scalar(select(func.count()).where(Payment.kind == PaymentKind.PAYOUT))
    assert payouts >= 6  # 4 suppliers settlements + 2 swaps (+ flash deals)
    statuses = set(await db.scalars(select(ShopOrder.status)))
    assert ShopOrderStatus.AUTHORIZED not in statuses


async def test_steps_are_idempotent(db, world, ctx):
    runner = WeekRunner(ctx, DEMO_WEEK)
    await runner.run("forecasts")
    before = await db.scalar(select(func.count()).select_from(AgentMessage))
    again = await runner.run("forecasts")
    assert again["skipped"] is True
    assert await db.scalar(select(func.count()).select_from(AgentMessage)) == before
