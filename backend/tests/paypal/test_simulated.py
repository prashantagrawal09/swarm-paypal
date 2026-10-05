"""The simulated PayPal must enforce the same money rules as PayPal itself."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.money.amount import Money
from app.paypal.errors import (
    PayPalNotFoundError,
    PayPalServerError,
    PayPalUnprocessableError,
    PayPalValidationError,
)
from app.paypal.interface import (
    CreateOrderRequest,
    InvoiceDraft,
    InvoiceLine,
    PayoutItemRequest,
    PayPalGateway,
)
from app.paypal.simulated import SimulatedPayPalClient


async def _vault(sim: SimulatedPayPalClient) -> str:
    order = await sim.create_order(
        CreateOrderRequest(
            amount=Money(1000),
            reference_id="connect",
            save_payment_method=True,
            return_url="http://r",
            cancel_url="http://c",
        ),
        idempotency_key="connect",
    )
    assert order.status == "PAYER_ACTION_REQUIRED"
    assert order.approve_url and order.id in order.approve_url
    authorized = await sim.authorize_order(order.id, idempotency_key="connect-auth")
    assert authorized.vault is not None and authorized.vault.id
    return authorized.vault.id


async def _hold(sim: SimulatedPayPalClient, cents: int, key: str) -> str:
    vault_id = await _vault(sim) if not sim.state.vaults else next(iter(sim.state.vaults))
    order = await sim.create_order(
        CreateOrderRequest(amount=Money(cents), reference_id=key, vault_id=vault_id),
        idempotency_key=key,
    )
    assert order.status == "COMPLETED"
    assert order.authorization is not None
    return order.authorization.id


def test_satisfies_the_gateway_contract(sim):
    assert isinstance(sim, PayPalGateway)
    assert sim.mode == "SIMULATED"


async def test_ids_are_prefixed_sim(sim):
    auth_id = await _hold(sim, 500, "h1")
    assert auth_id.startswith("SIM-")


async def test_vault_flow_then_buyer_not_present_order(sim):
    vault_id = await _vault(sim)
    order = await sim.create_order(
        CreateOrderRequest(amount=Money(2500), reference_id="go-1", vault_id=vault_id),
        idempotency_key="go-1",
    )
    assert order.status == "COMPLETED"
    assert order.authorization is not None and order.authorization.amount == Money(2500)


async def test_unknown_vault_is_rejected(sim):
    with pytest.raises(PayPalUnprocessableError):
        await sim.create_order(
            CreateOrderRequest(amount=Money(100), reference_id="x", vault_id="nope"),
            idempotency_key="x",
        )


async def test_manual_approval_is_required_when_auto_approve_is_off(sim):
    sim.auto_approve = False
    order = await sim.create_order(
        CreateOrderRequest(
            amount=Money(100),
            reference_id="x",
            save_payment_method=True,
            return_url="http://r",
            cancel_url="http://c",
        ),
        idempotency_key="x",
    )
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.authorize_order(order.id, idempotency_key="x-auth")
    assert exc_info.value.has_issue("ORDER_NOT_APPROVED")
    sim.approve_order(order.id, "owner@cafe-mei.example")
    authorized = await sim.authorize_order(order.id, idempotency_key="x-auth")
    assert authorized.payer_email == "owner@cafe-mei.example"


async def test_partial_final_capture_closes_the_authorization(sim):
    auth_id = await _hold(sim, 1000, "h1")
    capture = await sim.capture_authorization(
        auth_id, amount=Money(900), final_capture=True, idempotency_key="c1"
    )
    assert capture.amount == Money(900)
    auth = await sim.get_authorization(auth_id)
    assert auth.status == "CAPTURED"
    with pytest.raises(PayPalUnprocessableError):
        await sim.capture_authorization(
            auth_id, amount=Money(100), final_capture=True, idempotency_key="c2"
        )


async def test_multiple_partial_captures_up_to_the_authorized_amount(sim):
    auth_id = await _hold(sim, 1000, "h1")
    await sim.capture_authorization(
        auth_id, amount=Money(400), final_capture=False, idempotency_key="a"
    )
    assert (await sim.get_authorization(auth_id)).status == "PARTIALLY_CAPTURED"
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.capture_authorization(
            auth_id, amount=Money(601), final_capture=False, idempotency_key="b"
        )
    assert exc_info.value.has_issue("MAX_CAPTURE_AMOUNT_EXCEEDED")
    await sim.capture_authorization(
        auth_id, amount=Money(600), final_capture=False, idempotency_key="c"
    )
    assert (await sim.get_authorization(auth_id)).status == "CAPTURED"


async def test_capture_is_idempotent(sim):
    auth_id = await _hold(sim, 1000, "h1")
    first = await sim.capture_authorization(
        auth_id, amount=Money(500), final_capture=False, idempotency_key="same"
    )
    again = await sim.capture_authorization(
        auth_id, amount=Money(500), final_capture=False, idempotency_key="same"
    )
    assert first == again
    assert len(sim.state.captures) == 1


async def test_void_rules(sim):
    auth_id = await _hold(sim, 1000, "h1")
    voided = await sim.void_authorization(auth_id, idempotency_key="v1")
    assert voided is not None and voided.status == "VOIDED"
    with pytest.raises(PayPalUnprocessableError):
        await sim.capture_authorization(
            auth_id, amount=Money(1), final_capture=True, idempotency_key="c"
        )

    captured_id = await _hold(sim, 1000, "h2")
    await sim.capture_authorization(
        captured_id, amount=Money(1000), final_capture=True, idempotency_key="c2"
    )
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.void_authorization(captured_id, idempotency_key="v2")
    assert exc_info.value.has_issue("PREVIOUSLY_CAPTURED")


async def test_reauthorize_respects_the_honor_period(sim, clock):
    auth_id = await _hold(sim, 1000, "h1")
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.reauthorize_authorization(auth_id, amount=Money(1000), idempotency_key="r1")
    assert exc_info.value.has_issue("REAUTHORIZATION_TOO_SOON")

    clock.advance(days=3, minutes=1)
    with pytest.raises(PayPalUnprocessableError):
        await sim.reauthorize_authorization(auth_id, amount=Money(1151), idempotency_key="r2")
    new_auth = await sim.reauthorize_authorization(
        auth_id, amount=Money(1150), idempotency_key="r3"
    )
    assert new_auth.id != auth_id
    assert new_auth.status == "CREATED"
    # The old authorization can no longer be captured; the new one can.
    with pytest.raises(PayPalUnprocessableError) as old_capture:
        await sim.capture_authorization(
            auth_id, amount=Money(1), final_capture=True, idempotency_key="x"
        )
    assert old_capture.value.has_issue("AUTHORIZATION_SUPERSEDED")
    await sim.capture_authorization(
        new_auth.id, amount=Money(1150), final_capture=True, idempotency_key="y"
    )


async def test_authorizations_expire_after_29_days(sim, clock):
    auth_id = await _hold(sim, 1000, "h1")
    clock.advance(days=29, minutes=1)
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.capture_authorization(
            auth_id, amount=Money(1), final_capture=True, idempotency_key="c"
        )
    assert exc_info.value.has_issue("AUTHORIZATION_EXPIRED")


async def test_refunds_never_exceed_the_capture(sim):
    auth_id = await _hold(sim, 1000, "h1")
    capture = await sim.capture_authorization(
        auth_id, amount=Money(900), final_capture=True, idempotency_key="c"
    )
    await sim.refund_capture(capture.id, amount=Money(200), idempotency_key="r1")
    assert (await sim.get_capture(capture.id)).status == "PARTIALLY_REFUNDED"
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await sim.refund_capture(capture.id, amount=Money(701), idempotency_key="r2")
    assert exc_info.value.has_issue("REFUND_AMOUNT_EXCEEDED")
    rest = await sim.refund_capture(capture.id, amount=None, idempotency_key="r3")
    assert rest.amount == Money(700)
    assert (await sim.get_capture(capture.id)).status == "REFUNDED"


async def test_payouts_accept_then_succeed_and_reject_reused_batch_ids(sim):
    item = PayoutItemRequest("seller@example.com", Money(300), "item-1")
    batch = await sim.create_payout(
        sender_batch_id="b1", items=[item], idempotency_key="p1", email_subject="Swarm"
    )
    assert batch.status == "PENDING"
    settled = await sim.get_payout(batch.batch_id)
    assert settled.status == "SUCCESS"
    assert settled.items[0].amount == Money(300)
    # Same idempotency key: same batch. New key with the same sender_batch_id: rejected.
    assert (
        await sim.create_payout(
            sender_batch_id="b1", items=[item], idempotency_key="p1", email_subject="Swarm"
        )
    ).batch_id == batch.batch_id
    with pytest.raises(PayPalValidationError):
        await sim.create_payout(
            sender_batch_id="b1", items=[item], idempotency_key="p2", email_subject="Swarm"
        )


async def test_invoice_lifecycle(sim):
    supplier = SimulatedPayPalClient("freshdairy", state=sim.state, clock=sim.clock)
    draft = InvoiceDraft(
        invoice_number="SW-1",
        invoice_date=date(2026, 10, 8),
        currency="SGD",
        recipient_email="platform@example.com",
        lines=[
            InvoiceLine("Milk 1L", Decimal(290), Money(205)),
            InvoiceLine("Eggs tray", Decimal(10), Money(890)),
        ],
    )
    invoice = await supplier.create_invoice(draft, idempotency_key="i1")
    assert invoice.status == "DRAFT"
    assert invoice.total == Money(59450 + 8900)
    await supplier.send_invoice(invoice.id, idempotency_key="s1")
    assert (await supplier.get_invoice(invoice.id)).status == "SENT"
    await supplier.record_invoice_payment(
        invoice.id,
        amount=Money(68350),
        payment_date=date(2026, 10, 9),
        method="PAYPAL",
        idempotency_key="pay1",
    )
    assert (await supplier.get_invoice(invoice.id)).is_paid
    with pytest.raises(PayPalUnprocessableError):
        await supplier.create_invoice(draft, idempotency_key="i2")  # duplicate number
    with pytest.raises(PayPalNotFoundError):
        await sim.get_invoice(invoice.id)  # other accounts cannot see it


async def test_webhook_signatures(sim):
    raw = b'{"id":"WH-1","event_type":"PAYMENT.CAPTURE.COMPLETED"}'
    headers = sim.sign_webhook(raw, "WH-ID")
    assert await sim.verify_webhook_signature(headers=headers, raw_body=raw, webhook_id="WH-ID")
    assert not await sim.verify_webhook_signature(
        headers=headers, raw_body=raw + b" ", webhook_id="WH-ID"
    )
    assert not await sim.verify_webhook_signature(headers=headers, raw_body=raw, webhook_id="OTHER")


async def test_fault_injection(sim):
    auth_id = await _hold(sim, 1000, "h1")
    sim.fail_next("authorizations.capture", PayPalServerError("PayPal is down", status_code=503))
    with pytest.raises(PayPalServerError):
        await sim.capture_authorization(
            auth_id, amount=Money(1), final_capture=True, idempotency_key="c"
        )
    await sim.capture_authorization(
        auth_id, amount=Money(1), final_capture=True, idempotency_key="c"
    )
