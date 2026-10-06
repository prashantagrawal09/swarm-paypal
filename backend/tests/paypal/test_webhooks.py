"""The PayPal webhook endpoint: verified deliveries only, each event processed once."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.config import Settings, get_settings
from app.db.enums import PaymentKind, PaymentStatus, PayPalModeEnum
from app.db.models import AuditLog, Payment, WebhookEvent
from app.db.session import get_session
from app.main import create_app
from app.paypal import webhooks
from app.paypal.accounts import get_platform_gateway
from app.runtime import get_clock

pytestmark = pytest.mark.db


def event(event_id: str, event_type: str, resource: dict) -> bytes:
    return json.dumps({"id": event_id, "event_type": event_type, "resource": resource}).encode()


@pytest.fixture
def make_api(sim, db, clock, tmp_path, monkeypatch):
    monkeypatch.setattr(webhooks, "CAPTURE_DIR", tmp_path)

    def build(webhook_id: str | None = "WH-ID", app_env: str = "development") -> httpx.AsyncClient:
        app = create_app()
        settings = Settings(paypal_webhook_id=webhook_id, app_env=app_env)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_platform_gateway] = lambda: sim
        app.dependency_overrides[get_session] = lambda: db
        app.dependency_overrides[get_clock] = lambda: clock
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return build


async def post(api, sim, raw: bytes, webhook_id: str = "WH-ID") -> httpx.Response:
    return await api.post(
        "/webhooks/paypal", content=raw, headers=sim.sign_webhook(raw, webhook_id).to_mapping()
    )


async def test_verified_event_is_processed_once(make_api, sim, db, tmp_path):
    raw = event("WH-1", "PAYMENT.AUTHORIZATION.CREATED", {"id": "AUTH-1"})
    async with make_api() as api:
        first = await post(api, sim, raw)
        again = await post(api, sim, raw)
    assert first.status_code == 200 and first.json()["status"] == "processed"
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    rows = (await db.execute(WebhookEvent.__table__.select())).all()
    assert len(rows) == 1
    saved_headers, saved_body = webhooks.load_capture(tmp_path / "WH-1.json")
    assert saved_body == raw
    assert await sim.verify_webhook_signature(
        headers=saved_headers, raw_body=saved_body, webhook_id="WH-ID"
    )


async def test_denied_capture_marks_the_payment_failed(make_api, sim, db):
    payment = Payment(
        kind=PaymentKind.CAPTURE,
        status=PaymentStatus.COMPLETED,
        paypal_mode=PayPalModeEnum.REAL,
        account="platform",
        paypal_id="CAP-9",
        related_type="shop_order",
        related_id=uuid.uuid4(),
        amount_cents=1000,
        currency="SGD",
        idempotency_key="capture:x",
        raw={},
    )
    db.add(payment)
    await db.commit()
    async with make_api() as api:
        response = await post(api, sim, event("WH-2", "PAYMENT.CAPTURE.DENIED", {"id": "CAP-9"}))
    assert response.json()["outcome"] == "capture denied: payment marked FAILED"
    await db.refresh(payment)
    assert payment.status == PaymentStatus.FAILED
    audit = (await db.execute(AuditLog.__table__.select())).all()
    assert len(audit) == 1


async def test_tampered_delivery_is_rejected(make_api, sim, db):
    raw = event("WH-3", "PAYMENT.CAPTURE.COMPLETED", {"id": "A1"})
    headers = sim.sign_webhook(raw, "WH-ID").to_mapping()
    async with make_api() as api:
        response = await api.post(
            "/webhooks/paypal", content=raw.replace(b"A1", b"A2"), headers=headers
        )
    assert response.status_code == 400
    assert not (await db.execute(WebhookEvent.__table__.select())).all()


async def test_missing_headers_are_rejected(make_api):
    async with make_api() as api:
        response = await api.post("/webhooks/paypal", content=b'{"id": "x"}')
    assert response.status_code == 400


async def test_unconfigured_webhook_id_is_a_503(make_api, sim):
    async with make_api(webhook_id=None) as api:
        response = await post(api, sim, event("WH-4", "X", {}))
    assert response.status_code == 503


async def test_captures_are_only_written_in_development(make_api, sim, tmp_path):
    async with make_api(app_env="production") as api:
        response = await post(api, sim, event("WH-5", "CHECKOUT.ORDER.APPROVED", {"id": "O"}))
    assert response.status_code == 200
    assert response.json()["outcome"] == "noted"
    assert not list(tmp_path.iterdir())
