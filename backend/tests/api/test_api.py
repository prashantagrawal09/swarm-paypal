"""HTTP API: read endpoints, owner endpoints and demo controls."""

from __future__ import annotations

import httpx
import pytest

from app.api.deps import runtime_dep
from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def client(db, runtime, world):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[runtime_dep] = lambda: runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as api:
        yield api, app


async def test_overview_and_shops(client):
    api, _ = client
    overview = (await api.get("/api/overview")).json()
    assert overview["week"] == "2026-10-12" and len(overview["steps"]) == 8
    assert overview["stats"]["books_balanced"] is True
    shops = (await api.get("/api/shops")).json()
    assert len(shops) == 12 and {s["mode"] for s in shops} == {"SIMULATED"}
    detail = (await api.get("/api/shops/cafe-mei")).json()
    assert detail["usual_weekly"]["milk-full-cream-1l"] == 34
    assert (await api.get("/api/shops/nope")).status_code == 404


async def test_shop_detail_explains_the_forecast(client):
    api, _ = client
    shop = (await api.get("/api/shops/uncle-tan-noodles")).json()
    forecast = shop["forecast"]
    assert forecast["note"].startswith("Based on your last 4 weeks")
    assert "rain on Thursday" in forecast["note"]
    assert all(item["predicted"] > 0 and item["explanation"] for item in forecast["items"])


async def test_products_group_brand_variants(client):
    api, _ = client
    products = {p["product"]: p for p in (await api.get("/api/products")).json()}
    milk = products["milk-full-cream-1l"]
    assert milk["category"] == "DAIRY" and len(milk["skus"]) >= 2
    assert {"sku", "brand", "supplier"} <= set(milk["skus"][0])


async def test_supplier_api_never_reveals_floors(client):
    api, _ = client
    detail = (await api.get("/api/suppliers/freshdairy")).json()
    assert detail["catalog"] and "floor" not in str(detail).lower()
    assert "192" not in str([t for c in detail["catalog"] for t in c["tiers"]])


async def test_demo_week_through_the_api(client):
    api, _ = client
    for _ in range(5):
        response = await api.post("/api/demo/advance")
        assert response.status_code == 200, response.text
    groups = (await api.get("/api/group-orders")).json()
    assert len(groups) == 4
    dairy = next(g for g in groups if g["category"] == "DAIRY")
    assert dairy["final_landed_cents"] < dairy["opening_landed_cents"]
    assert dairy["ladder"][0]["tiers"] and dairy["saved_cents"] > 0
    detail = (await api.get(f"/api/group-orders/{dairy['id']}")).json()
    assert [i["check_status"] for i in detail["invoices"]] == ["REJECTED", "APPROVED"]
    payments = (await api.get("/api/payments", params={"limit": 200})).json()
    assert {p["kind"] for p in payments} >= {"AUTHORIZATION", "CAPTURE", "PAYOUT"}
    ledger = (await api.get("/api/ledger")).json()
    assert ledger["invariant_gap_cents"] == 0 and ledger["unbalanced_transactions"] == 0
    orders = (await api.get("/api/shops/cafe-mei/orders")).json()
    assert any(
        o["qty_delivered"] is not None and o["qty_delivered"] < o["qty_requested"] for o in orders
    )
    inbox = (await api.get("/api/owners/cafe-mei/inbox")).json()
    assert any(m["type"] == "CHARGED" for m in inbox)


async def test_owner_endpoints(client):
    api, _ = client
    await api.post("/api/demo/advance")  # Monday
    response = await api.post("/api/owners/cafe-mei/messages", json={"text": "report"})
    assert response.status_code == 200
    inbox = (await api.get("/api/owners/cafe-mei/inbox")).json()
    assert inbox[-1]["type"] == "WEEKLY_REPORT"
    bad = await api.post(
        "/api/owners/cafe-mei/photo", files={"photo": ("x.txt", b"hi", "text/plain")}
    )
    assert bad.status_code == 415


async def test_injections_and_reset(client):
    api, _ = client
    response = await api.post("/api/demo/inject", json={"kind": "surplus", "params": {"qty": 5}})
    assert response.json()["scenario"]["qty"] == 5
    assert (await api.post("/api/demo/inject", json={"kind": "nope"})).status_code == 422


async def test_demo_key_and_demo_mode_guards(client):
    api, app = client
    from pydantic import SecretStr

    app.dependency_overrides[get_settings] = lambda: Settings(demo_panel_key=SecretStr("k"))
    assert (await api.post("/api/demo/advance")).status_code == 401
    assert (await api.post("/api/demo/advance", headers={"X-Demo-Key": "k"})).status_code == 200
    app.dependency_overrides[get_settings] = lambda: Settings(demo_mode=False)
    assert (await api.post("/api/demo/reset")).status_code == 403


async def test_owner_phone_and_connect_are_owner_only_outside_demo_mode(client, runtime):
    from datetime import UTC, datetime

    from pydantic import SecretStr

    from app.security import sign

    api, app = client
    production = Settings(demo_mode=False, secret_key=SecretStr("s3cret"))
    app.dependency_overrides[get_settings] = lambda: production
    runtime.settings = production
    assert (await api.get("/api/owners/cafe-mei/inbox")).status_code == 403
    assert (
        await api.post("/api/owners/cafe-mei/actions", json={"action_id": "x"})
    ).status_code == 403
    assert (await api.post("/api/connect/cafe-mei/start")).status_code == 403
    forged = sign(production, "bakery-lim", datetime.now(UTC), "connect")
    response = await api.post("/api/connect/cafe-mei/start", json={"token": forged})
    assert response.status_code == 403
    token = sign(production, "cafe-mei", runtime.clock.now(), "connect")
    response = await api.post("/api/connect/cafe-mei/start", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["order_id"]
