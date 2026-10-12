"""Where a week's money went: shops -> Swarm's PayPal balance -> suppliers, neighbours,
refunds and the platform fee.

Read-only. Built from completed payments and the fee postings in the ledger, so it is the
same money the engine moved; the parts always add back up to what the shops were charged.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.clock import at_local
from app.db.enums import PaymentKind, PaymentStatus
from app.db.models import LedgerEntry, Payment, Shop, Supplier
from app.features.context import Ctx
from app.money import ledger

CHARGES = (PaymentKind.CAPTURE, PaymentKind.SWAP_PAYMENT)


async def week_flow(ctx: Ctx, week: date) -> dict[str, Any]:
    session = ctx.session
    start = at_local(week, 0)
    end = start + timedelta(days=7)
    rows = await session.execute(
        select(
            Payment.kind,
            Payment.shop_id,
            Payment.supplier_id,
            func.sum(Payment.amount_cents),
        )
        .where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= start,
            Payment.created_at < end,
        )
        .group_by(Payment.kind, Payment.shop_id, Payment.supplier_id)
    )
    charged: dict[uuid.UUID, int] = defaultdict(int)
    refunded: dict[uuid.UUID, int] = defaultdict(int)
    received: dict[uuid.UUID, int] = defaultdict(int)  # neighbours paid for surplus / help
    supplier_paid: dict[uuid.UUID, int] = defaultdict(int)
    for kind, shop_id, supplier_id, total in rows.all():
        amount = int(total or 0)
        if kind in CHARGES and shop_id:
            charged[shop_id] += amount
        elif kind == PaymentKind.REFUND and shop_id:
            refunded[shop_id] += amount
        elif kind == PaymentKind.PAYOUT and supplier_id:
            supplier_paid[supplier_id] += amount
        elif kind == PaymentKind.PAYOUT and shop_id:
            received[shop_id] += amount

    fee = await session.scalar(
        select(
            func.coalesce(func.sum(LedgerEntry.credit_cents), 0)
            - func.coalesce(func.sum(LedgerEntry.debit_cents), 0)
        ).where(
            LedgerEntry.account == ledger.PLATFORM_FEES,
            LedgerEntry.booked_at >= start,
            LedgerEntry.booked_at < end,
        )
    )
    fee_cents = int(fee or 0)

    shops = {s.id: s for s in await session.scalars(select(Shop).order_by(Shop.name))}
    suppliers = {s.id: s for s in await session.scalars(select(Supplier).order_by(Supplier.name))}
    charged_total = sum(charged.values())
    refunds_total = sum(refunded.values())
    neighbours_total = sum(received.values())
    suppliers_total = sum(supplier_paid.values())
    return {
        "week": str(week),
        "charged_cents": charged_total,
        "suppliers_cents": suppliers_total,
        "neighbours_cents": neighbours_total,
        "refunds_cents": refunds_total,
        "fee_cents": fee_cents,
        # Still in Swarm's PayPal balance: owed to suppliers (unsettled orders, open claims).
        "owed_cents": charged_total
        - suppliers_total
        - neighbours_total
        - refunds_total
        - fee_cents,
        "held_cents": await ctx.engine.outstanding_holds_cents(),
        "shops": [
            {
                "code": shop.code,
                "name": shop.name,
                "mode": shop.paypal_mode.value,
                "charged_cents": charged[shop.id],
                "refunded_cents": refunded[shop.id],
                "received_cents": received[shop.id],
            }
            for shop in shops.values()
            if charged[shop.id] or refunded[shop.id] or received[shop.id]
        ],
        "suppliers": [
            {
                "code": supplier.code,
                "name": supplier.name,
                "mode": supplier.paypal_mode.value,
                "paid_cents": supplier_paid[supplier.id],
            }
            for supplier in suppliers.values()
            if supplier_paid[supplier.id]
        ],
    }
