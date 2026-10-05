"""PayPal webhook endpoint: verify the signature with PayPal, then hand the event on.

Verification uses PayPal's verify-webhook-signature API with the exact raw request body.
Unverified deliveries get HTTP 400 so they are never processed. Storing event IDs for
exactly-once processing and updating payments arrive with the data model (phase 2).

In development, verified deliveries are also saved under `backend/var/webhooks/` so
`scripts/paypal_smoke.py --webhook-capture <file>` can re-verify a real event later.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.paypal.accounts import get_platform_gateway
from app.paypal.errors import PayPalError
from app.paypal.interface import PayPalGateway, WebhookHeaders

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


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    gateway: Annotated[PayPalGateway, Depends(get_platform_gateway)],
) -> dict[str, str]:
    if not settings.paypal_webhook_id:
        raise HTTPException(status_code=503, detail="PAYPAL_WEBHOOK_ID is not configured")
    raw_body = await request.body()
    try:
        headers = WebhookHeaders.from_mapping(request.headers)
        event = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not await verify_delivery(gateway, headers, raw_body, settings.paypal_webhook_id):
        logger.warning("Rejected unverified webhook %s", headers.transmission_id)
        raise HTTPException(status_code=400, detail="Webhook signature could not be verified")

    if settings.app_env == "development":
        save_capture(headers, raw_body, event)
    logger.info("Verified PayPal webhook %s %s", event.get("id"), event.get("event_type"))
    return {
        "status": "verified",
        "event_id": str(event.get("id", "")),
        "event_type": str(event.get("event_type", "")),
    }
