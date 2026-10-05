"""The PayPal webhook endpoint only accepts deliveries PayPal confirms as genuine."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings, get_settings
from app.main import create_app
from app.paypal import webhooks
from app.paypal.accounts import get_platform_gateway

RAW = b'{"id":"WH-7XX","event_type":"PAYMENT.AUTHORIZATION.CREATED","resource":{"id":"A1"}}'


@pytest.fixture
def make_api(sim, tmp_path, monkeypatch):
    monkeypatch.setattr(webhooks, "CAPTURE_DIR", tmp_path)

    def build(webhook_id: str | None = "WH-ID", app_env: str = "development") -> httpx.AsyncClient:
        app = create_app()
        settings = Settings(paypal_webhook_id=webhook_id, app_env=app_env)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_platform_gateway] = lambda: sim
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return build


async def test_verified_delivery_is_accepted_and_captured(make_api, sim, tmp_path):
    headers = sim.sign_webhook(RAW, "WH-ID").to_mapping()
    async with make_api() as api:
        response = await api.post("/webhooks/paypal", content=RAW, headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "status": "verified",
        "event_id": "WH-7XX",
        "event_type": "PAYMENT.AUTHORIZATION.CREATED",
    }
    saved_headers, saved_body = webhooks.load_capture(tmp_path / "WH-7XX.json")
    assert saved_body == RAW
    assert await sim.verify_webhook_signature(
        headers=saved_headers, raw_body=saved_body, webhook_id="WH-ID"
    )


async def test_tampered_delivery_is_rejected(make_api, sim):
    headers = sim.sign_webhook(RAW, "WH-ID").to_mapping()
    async with make_api() as api:
        response = await api.post(
            "/webhooks/paypal", content=RAW.replace(b"A1", b"A2"), headers=headers
        )
    assert response.status_code == 400


async def test_missing_headers_are_rejected(make_api):
    async with make_api() as api:
        response = await api.post("/webhooks/paypal", content=RAW)
    assert response.status_code == 400


async def test_unconfigured_webhook_id_is_a_503(make_api, sim):
    headers = sim.sign_webhook(RAW, "WH-ID").to_mapping()
    async with make_api(webhook_id=None) as api:
        response = await api.post("/webhooks/paypal", content=RAW, headers=headers)
    assert response.status_code == 503


async def test_captures_are_only_written_in_development(make_api, sim, tmp_path):
    headers = sim.sign_webhook(RAW, "WH-ID").to_mapping()
    async with make_api(app_env="production") as api:
        response = await api.post("/webhooks/paypal", content=RAW, headers=headers)
    assert response.status_code == 200
    assert not list(tmp_path.iterdir())
