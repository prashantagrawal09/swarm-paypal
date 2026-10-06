"""Money engine flows against the simulated PayPal (and one REAL shop via respx)."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.config import Settings
from app.db.enums import (
    ApprovalStatus,
    Category,
    GroupOrderStatus,
    PaymentKind,
    PaymentStatus,
    PayPalModeEnum,
    ShopOrderStatus,
    SwapKind,
    SwapStatus,
)
from app.db.models import ApprovalRequest, Item, Payment, ShopOrder, SwapOffer
from app.features import group_buy
from app.money import ledger, rules
from app.money.amount import Money
from app.money.engine import MoneyEngine, NeedsOwnerApproval
from app.paypal.accounts import GatewayRegistry
from app.paypal.errors import PayPalUnprocessableError
from app.paypal.simulated import SimulatedPayPalClient
from tests.conftest import DEMO_WEEK
from tests.helpers import awarded, payment_count, shops_by_code

pytestmark = pytest.mark.db


async def assert_books_balance(db, engine: MoneyEngine) -> None:
    assert await ledger.unbalanced_transactions(db) == []
    assert await ledger.platform_invariant_gap(db) == 0
    assert (
        -(await ledger.balance(db, ledger.PLATFORM_HOLDS)) == await engine.outstanding_holds_cents()
    )


def sim(registry: GatewayRegistry) -> SimulatedPayPalClient:
    gateway = registry.platform("SIMULATED")
    assert isinstance(gateway, SimulatedPayPalClient)
    return gateway


async def deliver_and_capture(db, engine, group, clock, delivered=None):
    await group_buy.record_delivery(db, group.id, clock.now(), delivered)
    return await engine.capture_group_order(group.id)


# ---------------------------------------------------------------------------------------


async def test_happy_path_hold_capture_payout(db, world, clock, engine, events):
    group = await awarded(db, DEMO_WEEK, clock, Category.PACKAGING)
    shops = len(group.shop_orders)
    holds = await engine.place_holds(group.id)
    assert holds.count(ShopOrderStatus.AUTHORIZED) == shops
    await assert_books_balance(db, engine)

    clock.advance(days=1)
    captures = await deliver_and_capture(db, engine, group, clock)
    assert captures.count(ShopOrderStatus.CAPTURED) == shops
    payment = await engine.payout_supplier(group.id)
    assert payment is not None and payment.status == PaymentStatus.COMPLETED

    group = await group_buy.load_group(db, group.id)
    assert group.status == GroupOrderStatus.SETTLED
    gross = sum(so.captured_amount_cents for so in group.shop_orders)
    assert payment.amount_cents == gross - gross * 200 // 10_000
    assert await ledger.balance(db, ledger.PLATFORM_FEES) == -(gross * 200 // 10_000)
    assert all(so.status == ShopOrderStatus.SETTLED for so in group.shop_orders)
    await assert_books_balance(db, engine)
    assert {"hold_placed", "captured", "supplier_paid"} <= set(events.kinds())


async def test_short_delivery_captures_only_what_arrived(db, world, clock, engine, registry):
    group = await awarded(db, DEMO_WEEK, clock, Category.PACKAGING)
    so, line = group.shop_orders[0], group.shop_orders[0].lines[0]
    line_price, short_qty = line.agreed_unit_price_cents, line.qty_requested - 1
    await engine.place_holds(group.id)
    captures = await deliver_and_capture(db, engine, group, clock, {line.id: short_qty})

    so = await db.get(ShopOrder, so.id, populate_existing=True)
    assert so.captured_amount_cents < so.hold_amount_cents
    assert so.captured_amount_cents <= so.hold_amount_cents - line_price
    auth = await sim(registry).get_authorization(so.authorization_id)
    assert auth.status == "CAPTURED"  # final_capture released the rest
    payout = await engine.payout_supplier(group.id)
    assert payout is not None
    assert payout.amount_cents < sum(o.amount_cents for o in captures.outcomes) + 1
    await assert_books_balance(db, engine)


async def test_one_failed_authorization_does_not_stop_the_others(
    db, world, clock, engine, registry
):
    group = await awarded(db, DEMO_WEEK, clock, Category.PACKAGING)
    shops = len(group.shop_orders)
    sim(registry).fail_next(
        "orders.create",
        PayPalUnprocessableError("declined", status_code=422, name="UNPROCESSABLE_ENTITY"),
    )
    result = await engine.place_holds(group.id)
    assert result.count(ShopOrderStatus.FAILED) == 1
    assert result.count(ShopOrderStatus.AUTHORIZED) == shops - 1
    group = await group_buy.load_group(db, group.id)
    assert group.status == GroupOrderStatus.HELD
    failed = next(so for so in group.shop_orders if so.status == ShopOrderStatus.FAILED)
    assert failed.failure_reason

    retried = await engine.place_hold(failed.id)
    assert retried.status == ShopOrderStatus.AUTHORIZED and retried.attempts == 2
    keys = list(await db.scalars(select(Payment.status).where(Payment.related_id == failed.id)))
    assert sorted(keys) == [PaymentStatus.COMPLETED, PaymentStatus.FAILED]
    await assert_books_balance(db, engine)


async def test_spending_limit_needs_the_owner(db, world, clock, engine):
    group = await awarded(db, DEMO_WEEK, clock, Category.DAIRY)
    so = group.shop_orders[0]
    so.shop.weekly_spend_limit_cents = 1000
    await db.commit()
    so_id = so.id
    with pytest.raises(NeedsOwnerApproval):
        await engine.place_hold(so_id)
    approval = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.related_id == so_id))
    assert approval is not None and approval.status == ApprovalStatus.PENDING
    assert "over your weekly limit" in approval.question
    assert (await db.get(ShopOrder, so_id)).status == ShopOrderStatus.PENDING

    approval.status = ApprovalStatus.APPROVED
    await db.commit()
    held = await engine.place_hold(so_id)
    assert held.status == ShopOrderStatus.AUTHORIZED


async def test_cancelled_order_voids_every_hold(db, world, clock, engine, registry):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    cancelled = await engine.cancel_group_order(group.id, reason="Supplier truck broke down")
    assert cancelled.status == GroupOrderStatus.CANCELLED
    group = await group_buy.load_group(db, group.id)
    assert {so.status for so in group.shop_orders} == {ShopOrderStatus.VOIDED}
    for so in group.shop_orders:
        assert (await sim(registry).get_authorization(so.authorization_id)).status == "VOIDED"
    assert await ledger.balance(db, ledger.PLATFORM_HOLDS) == 0
    await assert_books_balance(db, engine)


async def test_late_delivery_reauthorizes_before_capturing(db, world, clock, engine, events):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    group = await group_buy.load_group(db, group.id)
    first = {so.id: so.authorization_id for so in group.shop_orders}
    clock.advance(days=4)  # past the 3-day honor period
    await deliver_and_capture(db, engine, group, clock)
    group = await group_buy.load_group(db, group.id)
    for so in group.shop_orders:
        assert so.status == ShopOrderStatus.CAPTURED
        assert so.authorization_id != first[so.id]
    reauths = await db.scalar(
        select(func.count()).where(Payment.kind == PaymentKind.REAUTHORIZATION)
    )
    assert reauths == len(group.shop_orders)
    assert "hold_reauthorized" in events.kinds()
    await assert_books_balance(db, engine)


async def test_expired_hold_is_replaced_by_a_new_one(db, world, clock, engine):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    clock.advance(days=30)
    await deliver_and_capture(db, engine, group, clock)
    group = await group_buy.load_group(db, group.id)
    assert {so.status for so in group.shop_orders} == {ShopOrderStatus.CAPTURED}
    reholds = await db.scalar(
        select(func.count()).where(Payment.idempotency_key.startswith("rehold:"))
    )
    assert reholds == len(group.shop_orders)


async def test_refunds_after_payout_keep_the_books_straight(db, world, clock, engine):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await deliver_and_capture(db, engine, group, clock)
    await engine.payout_supplier(group.id)
    so = (await group_buy.load_group(db, group.id)).shop_orders[0]
    so_id = so.id

    payment = await engine.refund_shop_order(
        so_id, amount_cents=300, reason="Bruised tomatoes", refund_key="claim-1"
    )
    assert payment.kind == PaymentKind.REFUND
    again = await engine.refund_shop_order(
        so_id, amount_cents=300, reason="Bruised tomatoes", refund_key="claim-1"
    )
    assert again.id == payment.id  # same claim, same refund, no second charge back
    so = await db.get(ShopOrder, so_id, populate_existing=True)
    assert so.refunded_amount_cents == 300 and so.status == ShopOrderStatus.REFUNDED
    # The supplier was already paid, so it now owes the platform (debit balance).
    assert await ledger.balance(db, "supplier:johorfarm:payable") == 300
    with pytest.raises(rules.RuleViolation):
        await engine.refund_shop_order(
            so.id, amount_cents=so.captured_amount_cents, reason="x", refund_key="claim-2"
        )
    await assert_books_balance(db, engine)


async def test_every_step_is_idempotent(db, world, clock, engine, registry):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await deliver_and_capture(db, engine, group, clock)
    await engine.payout_supplier(group.id)
    before = (await payment_count(db), len(sim(registry).state.captures))

    await engine.place_holds(group.id)
    await engine.capture_group_order(group.id)
    with pytest.raises(rules.RuleViolation):
        await engine.payout_supplier(group.id)  # already settled
    assert (await payment_count(db), len(sim(registry).state.captures)) == before


async def test_crash_after_paypal_answered_is_recovered_without_double_charge(
    db, world, clock, engine, registry
):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await group_buy.record_delivery(db, group.id, clock.now())
    so = (await group_buy.load_group(db, group.id)).shop_orders[0]
    so_id, auth_id, hold = so.id, so.authorization_id, so.hold_amount_cents
    key = f"capture:{so_id}:{auth_id}"
    # PayPal processed the capture, then the process died before recording it.
    paypal_side = await sim(registry).capture_authorization(
        auth_id, amount=Money(hold), final_capture=True, idempotency_key=key
    )
    db.add(
        Payment(
            kind=PaymentKind.CAPTURE,
            status=PaymentStatus.PENDING,
            paypal_mode=PayPalModeEnum.SIMULATED,
            account="platform",
            related_type="shop_order",
            related_id=so_id,
            amount_cents=hold,
            currency="SGD",
            idempotency_key=key,
            raw={},
        )
    )
    await db.commit()

    recovered = await engine.capture_shop_order(so_id)
    assert recovered.capture_id == paypal_side.id
    assert len(sim(registry).state.captures) == 1
    await assert_books_balance(db, engine)


async def test_withheld_money_is_paid_later(db, world, clock, engine):
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    await engine.place_holds(group.id)
    await deliver_and_capture(db, engine, group, clock)
    first = await engine.payout_supplier(group.id, withhold_cents=500)
    group = await group_buy.load_group(db, group.id)
    assert group.status == GroupOrderStatus.PARTIALLY_SETTLED
    second = await engine.payout_supplier(group.id)
    group = await group_buy.load_group(db, group.id)
    assert group.status == GroupOrderStatus.SETTLED
    assert [p["gross_cents"] for p in group.summary["payouts"]][1] == 500
    assert first.id != second.id
    await assert_books_balance(db, engine)


async def test_swap_charges_the_buyer_and_pays_the_seller(db, world, clock, engine):
    shops = await shops_by_code(db)
    milk = await db.scalar(select(Item).where(Item.sku == "MILK-FC-1L-MEADOW"))
    swap = SwapOffer(
        kind=SwapKind.SURPLUS,
        from_shop_id=shops["cafe-mei"].id,
        to_shop_id=shops["teh-time"].id,
        item_id=milk.id,
        qty=8,
        price_cents=1200,
        expires_at=clock.now() + timedelta(days=2),
        status=SwapStatus.ACCEPTED,
        food_saved_grams=8 * 1050,
    )
    db.add(swap)
    await db.commit()
    await engine.authorize_swap(swap.id)
    await assert_books_balance(db, engine)
    done = await engine.complete_swap(swap.id)
    assert done.status == SwapStatus.COMPLETED
    assert await ledger.balance(db, "shop:cafe-mei:sales") == -1200
    assert await ledger.balance(db, "shop:teh-time:paypal") == -1200
    assert await ledger.balance(db, "shop:cafe-mei:receivable") == 0
    await engine.complete_swap(swap.id)  # idempotent
    assert await ledger.balance(db, "shop:cafe-mei:sales") == -1200
    await assert_books_balance(db, engine)


async def test_real_shop_goes_through_the_paypal_rest_api(db, world, clock, monkeypatch):
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_ID", "cid")
    monkeypatch.setenv("PAYPAL_PLATFORM_CLIENT_SECRET", "secret")
    group = await awarded(db, DEMO_WEEK, clock, Category.PRODUCE)
    real = group.shop_orders[0]
    real.shop.paypal_mode = PayPalModeEnum.REAL
    real.shop.vault_id = "VAULT-REAL-1"
    real.paypal_mode = PayPalModeEnum.REAL
    await db.commit()
    real_id = real.id

    http = httpx.AsyncClient()
    engine = MoneyEngine(db, GatewayRegistry(Settings(), clock=clock, http=http), clock)
    with respx.mock(base_url="https://api-m.sandbox.paypal.com", assert_all_called=True) as paypal:
        paypal.post("/v1/oauth2/token").respond(200, json={"access_token": "T", "expires_in": 3600})
        order = paypal.post("/v2/checkout/orders").respond(
            201,
            json={
                "id": "ORDER-R1",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "authorizations": [
                                {
                                    "id": "AUTH-R1",
                                    "status": "CREATED",
                                    "amount": {"currency_code": "SGD", "value": "1.00"},
                                }
                            ]
                        }
                    }
                ],
            },
        )
        capture = paypal.post("/v2/payments/authorizations/AUTH-R1/capture").mock(
            side_effect=lambda request: httpx.Response(
                201,
                json={
                    "id": "CAP-R1",
                    "status": "COMPLETED",
                    "amount": json.loads(request.content)["amount"],
                },
            )
        )
        await engine.place_holds(group.id)
        await group_buy.record_delivery(db, group.id, clock.now())
        await engine.capture_group_order(group.id)

    await http.aclose()
    real = await db.get(ShopOrder, real_id, populate_existing=True)
    assert real.status == ShopOrderStatus.CAPTURED and real.capture_id == "CAP-R1"
    sent = json.loads(order.calls.last.request.content)
    assert sent["payment_source"] == {"paypal": {"vault_id": "VAULT-REAL-1"}}
    assert (
        sent["purchase_units"][0]["amount"]["value"]
        == Money(real.hold_amount_cents).to_paypal_value()
    )
    assert order.calls.last.request.headers["PayPal-Request-Id"] == f"hold:{real.id}:1"
    assert capture.calls.last.request.headers["PayPal-Request-Id"] == f"capture:{real.id}:AUTH-R1"
    group = await group_buy.load_group(db, group.id)
    others = [so for so in group.shop_orders if so.id != real_id]
    assert all(so.capture_id.startswith("SIM-") for so in others)
