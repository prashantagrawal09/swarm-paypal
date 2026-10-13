"""The money page's capability table must be evidence, not a brochure."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.enums import PaymentKind, PaymentStatus
from app.db.models import Payment, Shop
from app.features import paypal_usage
from app.features.context import Ctx
from app.features.week import WeekRunner
from tests.conftest import DEMO_WEEK

pytestmark = pytest.mark.db


async def test_before_the_week_only_the_saved_wallets_count(db, world, runtime):
    rows = {row["key"]: row for row in await paypal_usage.usage(Ctx(db, runtime))}
    assert list(rows) == [row["key"] for row in paypal_usage.CAPABILITIES]
    assert rows["vault"]["simulated"] == 12 and rows["vault"]["real"] == 0
    for key in ("authorize", "capture", "void", "refund", "payouts", "invoicing", "webhooks"):
        assert rows[key]["real"] == 0 and rows[key]["simulated"] == 0
        assert rows[key]["latest"] is None
    assert all(row["call"].startswith("POST /v") for row in rows.values())


async def test_after_a_week_every_count_matches_the_payments_table(db, world, runtime):
    ctx = Ctx(db, runtime)
    runner = WeekRunner(ctx, DEMO_WEEK)
    while await runner.next_step() is not None:
        await runner.run_next()

    rows = {row["key"]: row for row in await paypal_usage.usage(ctx)}

    async def completed(*kinds: PaymentKind) -> tuple[int, int]:
        n, amount = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                    Payment.status == PaymentStatus.COMPLETED, Payment.kind.in_(kinds)
                )
            )
        ).one()
        return int(n), int(amount)

    for key, kinds in {
        "authorize": (PaymentKind.AUTHORIZATION,),
        "capture": (PaymentKind.CAPTURE, PaymentKind.SWAP_PAYMENT),
        "payouts": (PaymentKind.PAYOUT,),
    }.items():
        n, amount = await completed(*kinds)
        assert n > 0
        assert rows[key]["simulated"] == n and rows[key]["real"] == 0
        assert rows[key]["amount_cents"] == amount
        assert rows[key]["latest"]["paypal_id"].startswith("SIM-")
        assert rows[key]["latest"]["mode"] == "SIMULATED"

    # Every completed PayPal call is counted in exactly one row.
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status == PaymentStatus.COMPLETED)
        )
        or 0
    )
    counted = sum(
        rows[key]["real"] + rows[key]["simulated"]
        for key in ("authorize", "capture", "void", "reauthorize", "refund", "payouts")
    )
    assert counted == total

    # Five invoices went through PayPal Invoicing (one was rejected and reissued).
    assert rows["invoicing"]["simulated"] == 5 and rows["invoicing"]["latest"] is not None
    assert rows["vault"]["simulated"] == int(
        await db.scalar(select(func.count()).select_from(Shop)) or 0
    )
