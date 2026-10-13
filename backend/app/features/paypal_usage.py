"""Which PayPal capabilities Swarm has used so far, with the evidence: how many completed
calls of each kind, through the real sandbox and through the simulator, how much money they
moved, and the latest PayPal ID. Read-only, for the money page."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db.enums import PaymentKind, PaymentStatus, PayPalModeEnum
from app.db.models import Invoice, Payment, Shop, WebhookEvent
from app.features.context import Ctx

# One row per capability, in the order money moves through them. `call` is the REST call
# behind it (see app/paypal/client.py); `kinds` are the payment rows that count as evidence.
CAPABILITIES: list[dict[str, Any]] = [
    {
        "key": "vault",
        "name": "Vault",
        "use": "The owner approves once; after that the agent can place holds without a login.",
        "call": "POST /v2/checkout/orders (save PayPal for later)",
        "when": "When an owner connects PayPal",
    },
    {
        "key": "authorize",
        "name": "Orders: authorize",
        "use": "Each shop's share of a deal is held on its PayPal, not taken.",
        "call": "POST /v2/checkout/orders/{id}/authorize",
        "when": "Wednesday, once the deals are agreed",
        "kinds": [PaymentKind.AUTHORIZATION],
    },
    {
        "key": "capture",
        "name": "Payments: capture",
        "use": "Only what was delivered is charged, as the final capture; the rest is released.",
        "call": "POST /v2/payments/authorizations/{id}/capture",
        "when": "Thursday, when deliveries arrive",
        "kinds": [PaymentKind.CAPTURE, PaymentKind.SWAP_PAYMENT],
    },
    {
        "key": "void",
        "name": "Void",
        "use": "A cancelled order, or nothing delivered: the whole hold is released.",
        "call": "POST /v2/payments/authorizations/{id}/void",
        "when": "Only if an order is cancelled or nothing arrives",
        "kinds": [PaymentKind.VOID],
    },
    {
        "key": "reauthorize",
        "name": "Reauthorize",
        "use": "A hold older than three days is refreshed before it is captured.",
        "call": "POST /v2/payments/authorizations/{id}/reauthorize",
        "when": "Only if a hold is over three days old at delivery",
        "kinds": [PaymentKind.REAUTHORIZATION],
    },
    {
        "key": "refund",
        "name": "Refunds",
        "use": "Damage claims go back to the original payment.",
        "call": "POST /v2/payments/captures/{id}/refund",
        "when": "Only when a claim is upheld",
        "kinds": [PaymentKind.REFUND],
    },
    {
        "key": "payouts",
        "name": "Payouts",
        "use": "Suppliers are paid less the platform fee; neighbours are paid for surplus.",
        "call": "POST /v1/payments/payouts",
        "when": "Thursday, after each invoice passes its check",
        "kinds": [PaymentKind.PAYOUT],
    },
    {
        "key": "invoicing",
        "name": "Invoicing",
        "use": "Supplier agents bill through PayPal; every line is checked before paying.",
        "call": "POST /v2/invoicing/invoices (through the PayPal Agent Toolkit)",
        "when": "Thursday, after delivery",
    },
    {
        "key": "webhooks",
        "name": "Webhooks",
        "use": "Events are verified with PayPal before Swarm's books trust them.",
        "call": "POST /v1/notifications/verify-webhook-signature",
        "when": "Needs sandbox keys and a public address",
    },
]


# How far back to look for each capability's latest call.
RECENT_PAYMENTS = 500


def _empty() -> dict[str, Any]:
    return {"real": 0, "simulated": 0, "amount_cents": 0, "latest": None}


async def usage(ctx: Ctx) -> list[dict[str, Any]]:
    session = ctx.session
    evidence: dict[str, dict[str, Any]] = {row["key"]: _empty() for row in CAPABILITIES}

    def count(key: str, mode: PayPalModeEnum, n: int, amount: int = 0) -> None:
        slot = evidence[key]
        slot["real" if mode == PayPalModeEnum.REAL else "simulated"] += n
        slot["amount_cents"] += amount

    by_kind = {kind: row["key"] for row in CAPABILITIES for kind in row.get("kinds", [])}
    totals = await session.execute(
        select(
            Payment.kind,
            Payment.paypal_mode,
            func.count(),
            func.coalesce(func.sum(Payment.amount_cents), 0),
        )
        .where(Payment.status == PaymentStatus.COMPLETED)
        .group_by(Payment.kind, Payment.paypal_mode)
    )
    for kind, mode, n, amount in totals.all():
        if kind in by_kind:
            count(by_kind[kind], mode, int(n), int(amount))

    # The most recent completed call of each kind, as something to look up in the sandbox.
    recent = await session.execute(
        select(Payment.kind, Payment.paypal_id, Payment.paypal_mode, Payment.created_at)
        .where(Payment.status == PaymentStatus.COMPLETED, Payment.paypal_id.is_not(None))
        .order_by(Payment.created_at.desc())
        .limit(RECENT_PAYMENTS)
    )
    for kind, paypal_id, mode, at in recent.all():
        key = by_kind.get(kind)
        if key and evidence[key]["latest"] is None:  # newest first: the first seen wins
            evidence[key]["latest"] = {
                "paypal_id": paypal_id,
                "mode": mode.value,
                "at": at.isoformat(),
            }

    connected = await session.execute(
        select(Shop.paypal_mode, func.count())
        .where(Shop.vault_id.is_not(None))
        .group_by(Shop.paypal_mode)
    )
    for mode, n in connected.all():
        count("vault", mode, int(n))

    invoices = await session.execute(
        select(Invoice.paypal_mode, func.count(), func.coalesce(func.sum(Invoice.total_cents), 0))
        .where(Invoice.paypal_invoice_id.is_not(None))
        .group_by(Invoice.paypal_mode)
    )
    for mode, n, amount in invoices.all():
        count("invoicing", mode, int(n), int(amount))
    newest_invoice = (
        await session.execute(
            select(Invoice.paypal_invoice_id, Invoice.paypal_mode, Invoice.created_at)
            .where(Invoice.paypal_invoice_id.is_not(None))
            .order_by(Invoice.created_at.desc())
            .limit(1)
        )
    ).first()
    if newest_invoice:
        evidence["invoicing"]["latest"] = {
            "paypal_id": newest_invoice[0],
            "mode": newest_invoice[1].value,
            "at": newest_invoice[2].isoformat(),
        }

    # Only verified deliveries are stored, and they only come from the real sandbox.
    verified = await session.scalar(select(func.count()).select_from(WebhookEvent))
    evidence["webhooks"]["real"] = int(verified or 0)

    return [
        {
            "key": row["key"],
            "name": row["name"],
            "use": row["use"],
            "call": row["call"],
            "when": row["when"],
            **evidence[row["key"]],
        }
        for row in CAPABILITIES
    ]
