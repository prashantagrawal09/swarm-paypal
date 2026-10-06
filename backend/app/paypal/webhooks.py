"""PayPal webhooks: verify the signature with PayPal, store the event once, reconcile payments.

1. Verification uses PayPal's verify-webhook-signature API with the exact raw request body;
   unverified deliveries get HTTP 400 and are never stored or processed.
2. Each event is stored once, keyed by PayPal's event ID (unique). A redelivery of the same
   event returns 200 "duplicate" without being processed again.
3. Processing reconciles our `payments` rows with PayPal's view (for example a capture
   PayPal later DENIED is marked FAILED and flagged on the shop order) and writes an audit
   entry. Our own ledger stays the primary record; webhooks confirm or flag it.

In development, verified deliveries are also saved under `backend/var/webhooks/` so
`scripts/paypal_smoke.py --webhook-capture <file>` can re-verify a real event later.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.config import Settings, get_settings
from app.db.enums import PaymentKind, PaymentStatus
from app.db.models import AuditLog, Payment, ShopOrder, WebhookEvent
from app.db.session import get_session
from app.paypal.accounts import get_platform_gateway
from app.paypal.errors import PayPalError
from app.paypal.interface import PayPalGateway, WebhookHeaders
from app.runtime import get_clock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

CAPTURE_DIR = Path(__file__).resolve().parents[2] / "var" / "webhooks"


async def verify_delivery(
    gateway: PayPalGateway,
    headers: WebhookHeaders,
    raw_body: bytes,
    webhook_id: str,
) -> bool:
    try:
        return await gateway.verify_webhook_signature(
            headers=headers, raw_body=raw_body, webhook_id=webhook_id
        )
    except PayPalError as exc:
        logger.warning("Webhook verification call failed: %s", exc)
        return False


def save_capture(headers: WebhookHeaders, raw_body: bytes, event: dict[str, Any]) -> Path:
    """Write a verified delivery to disk so it can be replayed into the verify API."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / f"{event.get('id', headers.transmission_id)}.json"
    path.write_text(
        json.dumps({"headers": headers.to_mapping(), "body": raw_body.decode()}, indent=2)
    )
    return path


def load_capture(path: Path) -> tuple[WebhookHeaders, bytes]:
    data = json.loads(path.read_text())
    return WebhookHeaders.from_mapping(data["headers"]), data["body"].encode()


# ---------------------------------------------------------------------------------------
# Exactly-once processing
# ---------------------------------------------------------------------------------------


async def record_event(session: AsyncSession, event: dict[str, Any]) -> WebhookEvent | None:
    """Store the event. Returns None if this event ID was already stored (a redelivery)."""
    statement = (
        insert(WebhookEvent)
        .values(
            paypal_event_id=str(event["id"]),
            event_type=str(event.get("event_type", "")),
            payload=event,
        )
        .on_conflict_do_nothing(index_elements=[WebhookEvent.paypal_event_id])
        .returning(WebhookEvent.id)
    )
    new_id = (await session.execute(statement)).scalar_one_or_none()
    if new_id is None:
        return None
    return await session.get(WebhookEvent, new_id)


async def _payment(
    session: AsyncSession, paypal_id: str | None, *kinds: PaymentKind
) -> Payment | None:
    if not paypal_id:
        return None
    query = select(Payment).where(Payment.paypal_id == paypal_id)
    if kinds:
        query = query.where(Payment.kind.in_(kinds))
    return await session.scalar(query.order_by(Payment.created_at.desc()))


async def process_event(session: AsyncSession, row: WebhookEvent, now: datetime) -> str:
    """Reconcile one stored event with our payments. Returns a short outcome."""
    event = row.payload
    event_type = row.event_type
    resource: dict[str, Any] = event.get("resource") or {}
    resource_id = resource.get("id")
    outcome = "ignored"

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        payment = await _payment(
            session, resource_id, PaymentKind.CAPTURE, PaymentKind.SWAP_PAYMENT
        )
        outcome = _confirm(payment, "capture confirmed")
    elif event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
        payment = await _payment(
            session, resource_id, PaymentKind.CAPTURE, PaymentKind.SWAP_PAYMENT
        )
        if payment is None:
            outcome = "no matching payment"
        else:
            payment.status = PaymentStatus.FAILED
            payment.error = f"PayPal reported {event_type}"
            shop_order = await session.scalar(
                select(ShopOrder).where(ShopOrder.capture_id == resource_id)
            )
            if shop_order is not None:
                shop_order.failure_reason = "PayPal denied this capture after it was made"
            outcome = "capture denied: payment marked FAILED"
    elif event_type == "PAYMENT.CAPTURE.PENDING":
        outcome = "capture pending at PayPal"
    elif event_type == "PAYMENT.CAPTURE.REFUNDED":
        payment = await _payment(session, resource_id, PaymentKind.REFUND)
        outcome = _confirm(payment, "refund confirmed")
    elif event_type == "PAYMENT.AUTHORIZATION.CREATED":
        payment = await _payment(session, resource_id, PaymentKind.AUTHORIZATION)
        outcome = _confirm(payment, "hold confirmed")
    elif event_type == "PAYMENT.AUTHORIZATION.VOIDED":
        payment = await _payment(session, resource_id, PaymentKind.VOID)
        outcome = _confirm(payment, "void confirmed")
    elif event_type.startswith("PAYMENT.PAYOUTSBATCH."):
        batch_id = (resource.get("batch_header") or {}).get("payout_batch_id")
        payment = await _payment(session, batch_id, PaymentKind.PAYOUT)
        if event_type.endswith(".DENIED") and payment is not None:
            payment.status = PaymentStatus.FAILED
            payment.error = "PayPal denied the payout batch"
            outcome = "payout denied: payment marked FAILED"
        else:
            outcome = _confirm(payment, f"payout batch {event_type.rsplit('.', 1)[-1].lower()}")
    elif event_type.startswith("PAYMENT.PAYOUTS-ITEM."):
        payment = await _payment(session, resource.get("payout_batch_id"), PaymentKind.PAYOUT)
        status = event_type.rsplit(".", 1)[-1]
        if payment is None:
            outcome = "no matching payment"
        else:
            payment.raw = {**payment.raw, "item_status": status}
            outcome = f"payout item {status.lower()}"
    elif event_type in ("CHECKOUT.ORDER.APPROVED", "VAULT.PAYMENT-TOKEN.CREATED"):
        outcome = "noted"

    row.processed_at = now
    row.outcome = outcome
    session.add(
        AuditLog(
            actor="paypal:webhook",
            action=event_type,
            details={
                "event_id": row.paypal_event_id,
                "resource_id": resource_id,
                "outcome": outcome,
            },
            created_at=now,
        )
    )
    return outcome


def _confirm(payment: Payment | None, message: str) -> str:
    if payment is None:
        return "no matching payment"
    if payment.status != PaymentStatus.COMPLETED:
        payment.status = PaymentStatus.COMPLETED
    return message


async def handle_event(session: AsyncSession, event: dict[str, Any], now: datetime) -> str:
    row = await record_event(session, event)
    if row is None:
        await session.commit()
        return "duplicate"
    outcome = await process_event(session, row, now)
    await session.commit()
    return outcome


# ---------------------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------------------


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    gateway: Annotated[PayPalGateway, Depends(get_platform_gateway)],
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> dict[str, str]:
    if not settings.paypal_webhook_id:
        raise HTTPException(status_code=503, detail="PAYPAL_WEBHOOK_ID is not configured")
    raw_body = await request.body()
    try:
        headers = WebhookHeaders.from_mapping(request.headers)
        event = json.loads(raw_body)
        if not isinstance(event, dict) or "id" not in event:
            raise ValueError("Webhook body is not a PayPal event")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not await verify_delivery(gateway, headers, raw_body, settings.paypal_webhook_id):
        logger.warning("Rejected unverified webhook %s", headers.transmission_id)
        raise HTTPException(status_code=400, detail="Webhook signature could not be verified")

    if settings.app_env == "development":
        save_capture(headers, raw_body, event)
    outcome = await handle_event(session, event, clock.now())
    logger.info("PayPal webhook %s %s: %s", event.get("id"), event.get("event_type"), outcome)
    return {
        "status": "duplicate" if outcome == "duplicate" else "processed",
        "event_id": str(event.get("id", "")),
        "event_type": str(event.get("event_type", "")),
        "outcome": outcome,
    }
