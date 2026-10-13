"""HTTP API: read endpoints, owner endpoints and demo controls."""

from __future__ import annotations

import httpx
import pytest

from app.api.deps import runtime_dep
from app.config import Settings, get_settings
from app.db.base import stamp_rows_with
from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
async def client(db, runtime, world):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[runtime_dep] = lambda: runtime
    stamp_rows_with(lambda: runtime.clock.now())  # as the running app does
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as api:
            yield api, app
    finally:
        stamp_rows_with(None)


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

    # Every cent the shops were charged is accounted for: suppliers, neighbours, refunds,
    # the fee, or still owed.
    flow = (await api.get("/api/money-flow")).json()
    assert flow["charged_cents"] == sum(s["charged_cents"] for s in flow["shops"]) > 0
    assert flow["suppliers_cents"] == sum(s["paid_cents"] for s in flow["suppliers"]) > 0
    assert flow["fee_cents"] > 0 and flow["owed_cents"] >= 0
    assert flow["charged_cents"] == (
        flow["suppliers_cents"]
        + flow["neighbours_cents"]
        + flow["refunds_cents"]
        + flow["fee_cents"]
        + flow["owed_cents"]
    )


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


async def test_paced_steps_run_in_the_background(db, runtime, world, test_database_url):
    """One paced step, then the rest of the week, each on its own database sessions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.demo import controls
    from app.features.context import Ctx

    engine = create_async_engine(test_database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await controls.run_paced(runtime, steps=1, sessions=sessions, pace=0)
        state = await controls.state(Ctx(db, runtime))
        assert [s["status"] for s in state["steps"]][:2] == ["done", "next"]
        assert runtime.bus.pace_seconds == 0  # pacing is switched off again afterwards

        await controls.run_paced(runtime, steps=None, sessions=sessions, pace=0)
        db.expire_all()
        state = await controls.state(Ctx(db, runtime))
        assert all(s["status"] == "done" for s in state["steps"])
        assert state["log"][0]["action"] == "week_complete"
    finally:
        await engine.dispose()


async def test_timeline_is_the_recorded_week_and_reset_clears_it(
    client, runtime, test_database_url
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.agents.recorder import StreamRecorder

    engine = create_async_engine(test_database_url, poolclass=NullPool)
    runtime.bus.recorder = StreamRecorder(
        async_sessionmaker(engine, expire_on_commit=False), runtime.clock.now
    )
    api, _ = client
    try:
        assert (await api.get("/api/timeline")).json()["events"] == []

        await api.post("/api/demo/advance")  # Monday
        body = (await api.get("/api/timeline")).json()
        kinds = [e["data"].get("kind") or e["data"].get("type") for e in body["events"]]
        assert kinds[0] == "step_started" and kinds[-1] == "step_finished"
        assert kinds.count("WEEKLY_NEEDS") == 12
        assert "demo_action" not in kinds
        # Each step ends with where the week stands, so a replay can show that moment's totals.
        assert body["events"][-1]["data"]["stats"]["books_balanced"] is True
        assert body["week"] == "2026-10-12"
        assert body["last_seq"] == body["events"][-1]["seq"]
        seqs = [e["seq"] for e in body["events"]]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        newer = (await api.get("/api/timeline", params={"after": body["last_seq"]})).json()
        assert newer == {"week": "2026-10-12", "last_seq": body["last_seq"], "events": []}
        other = (await api.get("/api/timeline", params={"week": "2026-10-05"})).json()
        assert other["events"] == []

        assert (await api.post("/api/demo/reset")).status_code == 200
        assert (await api.get("/api/timeline")).json()["events"] == []
    finally:
        await engine.dispose()


async def test_a_damage_claim_from_the_panel_waits_for_a_person_then_refunds(client):
    api, _ = client
    claim_now = {"kind": "damage_claim", "params": {}, "now": True}

    # Nothing has been delivered yet: the rule says why, instead of a server error.
    early = await api.post("/api/demo/inject", json=claim_now)
    assert early.status_code == 409
    assert "Run Thursday's settlement first" in early.json()["detail"]

    for _step in range(5):  # Monday to Thursday's settlement
        await api.post("/api/demo/advance")
    filed = (await api.post("/api/demo/inject", json=claim_now)).json()
    assert filed["scenario"] == {
        "shop": "bakery-lim",
        "product": "eggs-tray-30",
        "qty": 2,
        "scheduled": False,  # reporting one now doesn't add one to the week
    }
    # No photo came with it, so nobody is refunded until a person has looked.
    assert filed["claim"]["decision"] == "ESCALATED_OPERATOR"
    waiting = (await api.get("/api/claims", params={"open_only": True})).json()
    assert [c["id"] for c in waiting] == [filed["claim"]["id"]]
    row = waiting[0]
    assert row["shop"]["code"] == "bakery-lim" and row["qty"] == 2
    # The queue says what is being asked for, in words and in money, and why a person has it.
    assert row["what"] == "2 trays of eggs" and row["amount_cents"] == 2 * 775
    assert row["assessment"]["decision_reason"].startswith("No photo came with this claim")
    before = (await api.get("/api/overview")).json()["stats"]
    assert before["refunds_cents"] == 0

    decided = await api.post(
        f"/api/demo/claims/{filed['claim']['id']}/decide", json={"approve": True}
    )
    assert decided.json()["decision"] == "REFUNDED"
    refund = decided.json()["refund"]
    assert refund["amount_cents"] == 1550 and refund["mode"] == "SIMULATED" and refund["paypal_id"]
    after = (await api.get("/api/overview")).json()["stats"]
    assert after["refunds_cents"] == 2 * 775  # two trays of eggs at the agreed price
    assert after["books_balanced"] is True
    usage = {row["key"]: row for row in (await api.get("/api/paypal-usage")).json()}
    assert usage["refund"]["simulated"] == 1 and usage["refund"]["amount_cents"] == 1550


async def test_a_claim_scheduled_from_the_panel_holds_money_back_on_thursday(client):
    api, _ = client
    armed = await api.post(
        "/api/demo/inject", json={"kind": "damage_claim", "params": {"scheduled": True}}
    )
    assert armed.json()["scenario"]["scheduled"] is True and "claim" not in armed.json()
    assert (await api.get("/api/demo/state")).json()["scenario"]["damage_claim"]["scheduled"]

    for _step in range(5):  # Monday to Thursday's settlement
        await api.post("/api/demo/advance")
    waiting = (await api.get("/api/claims", params={"open_only": True})).json()
    assert [(c["shop"]["code"], c["what"], c["amount_cents"]) for c in waiting] == [
        ("bakery-lim", "2 trays of eggs", 1550)
    ]
    flow = (await api.get("/api/money-flow")).json()
    assert flow["owed_cents"] == 1550 and flow["refunds_cents"] == 0  # held, not yet moved

    async def dairy_invoice() -> dict:
        rows = (await api.get("/api/suppliers/johorfarm/invoices")).json()
        return next(r for r in rows if r["paid"] and r["number"].endswith("DAI-R2"))

    def claim_effects(row: dict) -> tuple[int, int, int]:
        return row["held_cents"], row["credited_cents"], row["owed_back_cents"]

    assert claim_effects(await dairy_invoice()) == (1550, 0, 0)

    await api.post(f"/api/demo/claims/{waiting[0]['id']}/decide", json={"approve": True})
    flow = (await api.get("/api/money-flow")).json()
    assert flow["owed_cents"] == 0 and flow["refunds_cents"] == 1550
    assert (await api.get("/api/overview")).json()["stats"]["books_balanced"] is True
    assert claim_effects(await dairy_invoice()) == (0, 1550, 0)

    # A second claim on the same order, upheld after the supplier has been paid: that part is
    # owed back, and it is not mixed up with what was held.
    late = await api.post(
        "/api/demo/inject",
        json={
            "kind": "damage_claim",
            "params": {"shop": "cafe-mei", "product": "milk-full-cream-1l", "qty": 3},
            "now": True,
        },
    )
    assert late.json()["claim"]["amount_cents"] == 3 * 186
    assert claim_effects(await dairy_invoice()) == (0, 1550, 0)  # nothing left to hold
    await api.post(f"/api/demo/claims/{late.json()['claim']['id']}/decide", json={"approve": True})
    assert claim_effects(await dairy_invoice()) == (0, 1550, 558)
    assert (await api.get("/api/money-flow")).json()["owed_cents"] == -558
    assert (await api.get("/api/overview")).json()["stats"]["books_balanced"] is True

    # Reset puts the week back to its script: nothing scheduled.
    await api.post("/api/demo/reset")
    assert (await api.get("/api/demo/state")).json()["scenario"]["damage_claim"] == {
        "shop": "bakery-lim",
        "product": "eggs-tray-30",
        "qty": 2,
        "scheduled": False,
    }


async def test_saved_scenarios_pick_up_surprises_added_later(client, db):
    from app.db.app_state import set_state
    from app.features.week import SCENARIO_KEY

    api, _ = client
    await set_state(db, SCENARIO_KEY, {"surplus": None, "emergency": {"shop": "teh-time"}})
    await db.commit()
    scenario = (await api.get("/api/demo/state")).json()["scenario"]
    assert scenario["damage_claim"]["shop"] == "bakery-lim"  # filled in from the defaults
    assert scenario["surplus"] is None  # switched off on purpose: stays off
    assert scenario["emergency"] == {"shop": "teh-time"}
