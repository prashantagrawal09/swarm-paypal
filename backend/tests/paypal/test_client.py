"""Real PayPal client against respx-mocked PayPal endpoints.

These pin the exact request shapes (verified against PayPal's OpenAPI specs) and the
client's behaviour around tokens, idempotency, retries and errors.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.money.amount import Money
from app.paypal.client import LIVE_BASE_URL, PayPalClient
from app.paypal.credentials import PayPalCredentials
from app.paypal.errors import (
    PayPalAuthError,
    PayPalConfigError,
    PayPalServerError,
    PayPalUnprocessableError,
)
from app.paypal.interface import (
    CreateOrderRequest,
    InvoiceDraft,
    InvoiceLine,
    PayoutItemRequest,
    WebhookHeaders,
)

AUTH_JSON = {
    "id": "0VF52814937998046",
    "status": "CREATED",
    "amount": {"currency_code": "SGD", "value": "10.00"},
    "create_time": "2026-10-07T01:00:00Z",
    "expiration_time": "2026-11-05T01:00:00Z",
}


def body(call) -> dict:
    return json.loads(call.request.content)


# ---------------------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------------------


async def test_token_is_cached_until_close_to_expiry(client, paypal_mock, fake_time):
    paypal_mock.get("/v2/payments/authorizations/A1").respond(200, json=AUTH_JSON)
    await client.get_authorization("A1")
    await client.get_authorization("A1")
    assert paypal_mock["token"].call_count == 1

    fake_time.now += 32400 - 60  # inside the refresh margin
    await client.get_authorization("A1")
    assert paypal_mock["token"].call_count == 2


async def test_token_request_uses_basic_auth_and_client_credentials(client, paypal_mock):
    await client.access_token()
    request = paypal_mock["token"].calls.last.request
    assert request.headers["authorization"].startswith("Basic ")
    assert request.content == b"grant_type=client_credentials"


async def test_bad_credentials_raise_auth_error(client, paypal_mock):
    paypal_mock["token"].respond(
        401, json={"error": "invalid_client", "error_description": "Client Authentication failed"}
    )
    with pytest.raises(PayPalAuthError) as exc_info:
        await client.access_token()
    assert exc_info.value.name == "invalid_client"


async def test_expired_token_is_refreshed_once_on_401(client, paypal_mock):
    route = paypal_mock.get("/v2/payments/authorizations/A1")
    route.side_effect = [
        httpx.Response(401, json={"error": "invalid_token"}),
        httpx.Response(200, json=AUTH_JSON),
    ]
    auth = await client.get_authorization("A1")
    assert auth.id == AUTH_JSON["id"]
    assert paypal_mock["token"].call_count == 2


def test_live_environment_is_refused():
    with pytest.raises(PayPalConfigError):
        PayPalClient(
            PayPalCredentials(client_id="cid", client_secret="secret"), base_url=LIVE_BASE_URL
        )


# ---------------------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------------------


async def test_vault_setup_order_shape_and_payer_action_link(client, paypal_mock):
    route = paypal_mock.post("/v2/checkout/orders").respond(
        200,
        json={
            "id": "5O190127TN364715T",
            "status": "PAYER_ACTION_REQUIRED",
            "links": [
                {"href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/5O1", "rel": "self"},
                {
                    "href": "https://www.sandbox.paypal.com/checkoutnow?token=5O1",
                    "rel": "payer-action",
                },
            ],
        },
    )
    order = await client.create_order(
        CreateOrderRequest(
            amount=Money(1000),
            reference_id="connect-cafe-mei",
            description="Swarm connect",
            save_payment_method=True,
            return_url="http://localhost:3000/connect/return",
            cancel_url="http://localhost:3000/connect/cancel",
        ),
        idempotency_key="connect-cafe-mei-1",
    )
    assert order.status == "PAYER_ACTION_REQUIRED"
    assert order.approve_url == "https://www.sandbox.paypal.com/checkoutnow?token=5O1"

    request = route.calls.last.request
    assert request.headers["PayPal-Request-Id"] == "connect-cafe-mei-1"
    assert request.headers["Prefer"] == "return=representation"
    sent = body(route.calls.last)
    assert sent["intent"] == "AUTHORIZE"
    assert sent["purchase_units"] == [
        {
            "reference_id": "connect-cafe-mei",
            "amount": {"currency_code": "SGD", "value": "10.00"},
            "description": "Swarm connect",
        }
    ]
    paypal = sent["payment_source"]["paypal"]
    assert paypal["attributes"]["vault"] == {
        "store_in_vault": "ON_SUCCESS",
        "usage_type": "MERCHANT",
    }
    assert paypal["experience_context"]["return_url"] == "http://localhost:3000/connect/return"
    assert paypal["experience_context"]["shipping_preference"] == "NO_SHIPPING"


async def test_authorize_returns_authorization_and_vault_id(client, paypal_mock):
    paypal_mock.post("/v2/checkout/orders/ORDER1/authorize").respond(
        201,
        json={
            "id": "ORDER1",
            "status": "COMPLETED",
            "payment_source": {
                "paypal": {
                    "email_address": "buyer@example.com",
                    "attributes": {
                        "vault": {"id": "nkq2y9g", "status": "VAULTED", "customer": {"id": "C1"}}
                    },
                }
            },
            "purchase_units": [{"payments": {"authorizations": [AUTH_JSON]}}],
        },
    )
    order = await client.authorize_order("ORDER1", idempotency_key="auth-1")
    assert order.vault is not None and order.vault.id == "nkq2y9g"
    assert order.vault.status == "VAULTED"
    assert order.payer_email == "buyer@example.com"
    assert order.authorization is not None
    assert order.authorization.amount == Money(1000)
    assert order.authorization.expiration_time is not None


async def test_vaulted_order_sends_only_vault_id(client, paypal_mock):
    route = paypal_mock.post("/v2/checkout/orders").respond(
        201,
        json={
            "id": "ORDER2",
            "status": "COMPLETED",
            "purchase_units": [{"payments": {"authorizations": [AUTH_JSON]}}],
        },
    )
    order = await client.create_order(
        CreateOrderRequest(amount=Money(2000), reference_id="go-1:cafe-mei", vault_id="nkq2y9g"),
        idempotency_key="hold-go-1-cafe-mei",
    )
    assert body(route.calls.last)["payment_source"] == {"paypal": {"vault_id": "nkq2y9g"}}
    assert order.authorization is not None


def test_order_request_validation():
    with pytest.raises(ValueError):
        CreateOrderRequest(amount=Money(0), reference_id="x")
    with pytest.raises(ValueError):
        CreateOrderRequest(amount=Money(100), reference_id="x", save_payment_method=True)
    with pytest.raises(ValueError):
        CreateOrderRequest(
            amount=Money(100),
            reference_id="x",
            vault_id="v",
            save_payment_method=True,
            return_url="a",
            cancel_url="b",
        )


# ---------------------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------------------


async def test_partial_capture_sends_amount_and_final_capture(client, paypal_mock):
    route = paypal_mock.post("/v2/payments/authorizations/A1/capture").respond(
        201,
        json={
            "id": "2GG279541U471931P",
            "status": "COMPLETED",
            "amount": {"currency_code": "SGD", "value": "6.00"},
            "final_capture": True,
        },
    )
    capture = await client.capture_authorization(
        "A1", amount=Money(600), final_capture=True, idempotency_key="cap-1", invoice_id="SW-1"
    )
    assert capture.amount == Money(600)
    assert capture.final_capture is True
    assert body(route.calls.last) == {
        "amount": {"currency_code": "SGD", "value": "6.00"},
        "final_capture": True,
        "invoice_id": "SW-1",
    }
    assert route.calls.last.request.headers["PayPal-Request-Id"] == "cap-1"


async def test_capture_above_authorization_is_a_typed_business_error(client, paypal_mock):
    paypal_mock.post("/v2/payments/authorizations/A1/capture").respond(
        422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "message": "The requested action could not be performed.",
            "debug_id": "f1ab2c3d",
            "details": [{"issue": "MAX_CAPTURE_AMOUNT_EXCEEDED", "description": "Too much"}],
        },
    )
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await client.capture_authorization(
            "A1", amount=Money(99999), final_capture=True, idempotency_key="cap-2"
        )
    error = exc_info.value
    assert error.has_issue("MAX_CAPTURE_AMOUNT_EXCEEDED")
    assert error.debug_id == "f1ab2c3d"
    assert error.operation == "authorizations.capture"


async def test_void_handles_204_and_representation(client, paypal_mock):
    route = paypal_mock.post("/v2/payments/authorizations/A1/void")
    route.respond(204)
    assert await client.void_authorization("A1", idempotency_key="void-1") is None
    route.respond(200, json={**AUTH_JSON, "status": "VOIDED"})
    voided = await client.void_authorization("A1", idempotency_key="void-1")
    assert voided is not None and voided.status == "VOIDED"
    assert route.calls.last.request.content == b""


async def test_reauthorize_sends_amount_and_maps_too_soon(client, paypal_mock):
    route = paypal_mock.post("/v2/payments/authorizations/A1/reauthorize").respond(
        422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "message": "...",
            "details": [{"issue": "REAUTHORIZATION_TOO_SOON"}],
        },
    )
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await client.reauthorize_authorization("A1", amount=Money(1000), idempotency_key="re-1")
    assert exc_info.value.has_issue("REAUTHORIZATION_TOO_SOON")
    assert body(route.calls.last) == {"amount": {"currency_code": "SGD", "value": "10.00"}}


async def test_refund_partial_and_full(client, paypal_mock):
    route = paypal_mock.post("/v2/payments/captures/C1/refund").respond(
        201,
        json={"id": "1JU08902781691411", "status": "COMPLETED"},
    )
    refund = await client.refund_capture("C1", amount=Money(200), idempotency_key="ref-1")
    assert refund.status == "COMPLETED"
    assert body(route.calls.last) == {"amount": {"currency_code": "SGD", "value": "2.00"}}
    await client.refund_capture("C1", amount=None, idempotency_key="ref-2")
    assert body(route.calls.last) == {}


# ---------------------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------------------


async def test_server_errors_are_retried_with_the_same_request_id(client, paypal_mock, fake_time):
    route = paypal_mock.post("/v2/payments/authorizations/A1/capture")
    route.side_effect = [
        httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE", "message": "try later"}),
        httpx.ConnectError("boom"),
        httpx.Response(
            201,
            json={
                "id": "C1",
                "status": "COMPLETED",
                "amount": {"currency_code": "SGD", "value": "1.00"},
            },
        ),
    ]
    capture = await client.capture_authorization(
        "A1", amount=Money(100), final_capture=False, idempotency_key="cap-retry"
    )
    assert capture.id == "C1"
    ids = {call.request.headers["PayPal-Request-Id"] for call in route.calls}
    assert ids == {"cap-retry"}
    assert fake_time.sleeps == [0.5, 1.0]


async def test_business_errors_are_not_retried(client, paypal_mock):
    route = paypal_mock.post("/v2/payments/captures/C1/refund").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "REFUND_AMOUNT_EXCEEDED"}]}
    )
    with pytest.raises(PayPalUnprocessableError):
        await client.refund_capture("C1", amount=Money(1), idempotency_key="ref-x")
    assert route.call_count == 1


async def test_retries_give_up_after_the_limit(client, paypal_mock, fake_time):
    route = paypal_mock.get("/v2/payments/captures/C1").respond(500, json={"name": "INTERNAL"})
    with pytest.raises(PayPalServerError):
        await client.get_capture("C1")
    assert route.call_count == 4
    assert len(fake_time.sleeps) == 3


# ---------------------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------------------


async def test_payout_body_uses_payouts_money_shape(client, paypal_mock):
    route = paypal_mock.post("/v1/payments/payouts").respond(
        201,
        json={
            "batch_header": {
                "payout_batch_id": "5UXD2E8A7EBQJ",
                "batch_status": "PENDING",
                "sender_batch_header": {"sender_batch_id": "swarm-go-1-freshdairy"},
            }
        },
    )
    batch = await client.create_payout(
        sender_batch_id="swarm-go-1-freshdairy",
        items=[
            PayoutItemRequest(
                receiver_email="supplier@example.com",
                amount=Money(58261),
                sender_item_id="go-1-freshdairy",
                note="Week 41 milk",
            )
        ],
        idempotency_key="payout-go-1",
        email_subject="Swarm payout",
    )
    assert batch.batch_id == "5UXD2E8A7EBQJ"
    assert batch.status == "PENDING"
    sent = body(route.calls.last)
    assert sent["sender_batch_header"] == {
        "sender_batch_id": "swarm-go-1-freshdairy",
        "recipient_type": "EMAIL",
        "email_subject": "Swarm payout",
    }
    assert sent["items"][0]["amount"] == {"currency": "SGD", "value": "582.61"}
    assert sent["items"][0]["receiver"] == "supplier@example.com"
    assert "Prefer" not in route.calls.last.request.headers


async def test_get_payout_parses_items(client, paypal_mock):
    paypal_mock.get("/v1/payments/payouts/B1").respond(
        200,
        json={
            "batch_header": {"payout_batch_id": "B1", "batch_status": "SUCCESS"},
            "items": [
                {
                    "payout_item_id": "PI1",
                    "transaction_id": "T1",
                    "transaction_status": "SUCCESS",
                    "payout_item": {
                        "receiver": "s@example.com",
                        "amount": {"currency": "SGD", "value": "3.00"},
                        "sender_item_id": "x",
                    },
                }
            ],
        },
    )
    batch = await client.get_payout("B1")
    assert batch.status == "SUCCESS"
    assert batch.items[0].amount == Money(300)
    assert batch.items[0].transaction_status == "SUCCESS"


# ---------------------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------------------


def _draft() -> InvoiceDraft:
    return InvoiceDraft(
        invoice_number="SW-GO1-FRESHDAIRY-1",
        invoice_date=date(2026, 10, 8),
        currency="SGD",
        recipient_email="platform@example.com",
        recipient_business_name="Swarm",
        invoicer_business_name="FreshDairy SG",
        lines=[InvoiceLine("Full cream milk 1L", Decimal(290), Money(205))],
    )


async def test_invoice_create_falls_back_to_get_when_only_a_link_comes_back(client, paypal_mock):
    create = paypal_mock.post("/v2/invoicing/invoices").respond(
        201,
        json={
            "rel": "self",
            "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-ABCD",
            "method": "GET",
        },
    )
    paypal_mock.get("/v2/invoicing/invoices/INV2-ABCD").respond(
        200,
        json={
            "id": "INV2-ABCD",
            "status": "DRAFT",
            "detail": {"invoice_number": "SW-GO1-FRESHDAIRY-1", "currency_code": "SGD"},
            "items": [
                {
                    "name": "Full cream milk 1L",
                    "quantity": "290",
                    "unit_amount": {"currency_code": "SGD", "value": "2.05"},
                }
            ],
            "amount": {"currency_code": "SGD", "value": "594.50"},
        },
    )
    invoice = await client.create_invoice(_draft(), idempotency_key="inv-1")
    assert invoice.id == "INV2-ABCD"
    assert invoice.total == Money(59450)
    assert invoice.lines[0].total == Money(59450)
    sent = body(create.calls.last)
    assert sent["detail"]["invoice_number"] == "SW-GO1-FRESHDAIRY-1"
    assert sent["items"][0] == {
        "name": "Full cream milk 1L",
        "quantity": "290",
        "unit_amount": {"currency_code": "SGD", "value": "2.05"},
        "unit_of_measure": "QUANTITY",
    }
    assert sent["primary_recipients"][0]["billing_info"]["email_address"] == "platform@example.com"


async def test_send_and_record_payment(client, paypal_mock):
    send = paypal_mock.post("/v2/invoicing/invoices/INV2-ABCD/send").respond(
        200,
        json={"href": "https://www.sandbox.paypal.com/invoice/p/#INV2-ABCD", "rel": "payer-view"},
    )
    pay = paypal_mock.post("/v2/invoicing/invoices/INV2-ABCD/payments").respond(
        200, json={"payment_id": "EXTR-86F38350LX4353815"}
    )
    await client.send_invoice("INV2-ABCD", idempotency_key="send-1", note="Week 41")
    assert body(send.calls.last) == {
        "send_to_recipient": True,
        "send_to_invoicer": False,
        "note": "Week 41",
    }
    payment_id = await client.record_invoice_payment(
        "INV2-ABCD",
        amount=Money(59450),
        payment_date=date(2026, 10, 9),
        method="PAYPAL",
        idempotency_key="invpay-1",
    )
    assert payment_id == "EXTR-86F38350LX4353815"
    assert body(pay.calls.last) == {
        "method": "PAYPAL",
        "payment_date": "2026-10-09",
        "amount": {"currency_code": "SGD", "value": "594.50"},
    }


# ---------------------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------------------


async def test_webhook_verification_passes_the_raw_event_through(client, paypal_mock):
    route = paypal_mock.post("/v1/notifications/verify-webhook-signature").respond(
        200, json={"verification_status": "SUCCESS"}
    )
    raw = b'{"id":"WH-1","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"amount":1.10}}'
    headers = WebhookHeaders("SHA256withRSA", "https://cert", "tx-1", "sig", "2026-10-07T01:00:00Z")
    assert await client.verify_webhook_signature(headers=headers, raw_body=raw, webhook_id="WH-ID")
    sent = route.calls.last.request.content
    assert sent.endswith(b'"webhook_event": ' + raw + b"}")
    envelope = json.loads(sent)
    assert envelope["webhook_id"] == "WH-ID"
    assert envelope["transmission_id"] == "tx-1"
    assert envelope["webhook_event"]["resource"]["amount"] == 1.10


async def test_webhook_verification_failure_is_false(client, paypal_mock):
    paypal_mock.post("/v1/notifications/verify-webhook-signature").respond(
        200, json={"verification_status": "FAILURE"}
    )
    headers = WebhookHeaders("SHA256withRSA", "https://cert", "tx-1", "sig", "t")
    assert not await client.verify_webhook_signature(
        headers=headers, raw_body=b"{}", webhook_id="W"
    )


def test_webhook_headers_parse_case_insensitively():
    headers = WebhookHeaders.from_mapping(
        {
            "paypal-auth-algo": "SHA256withRSA",
            "PAYPAL-CERT-URL": "https://cert",
            "Paypal-Transmission-Id": "tx",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "t",
        }
    )
    assert headers.transmission_id == "tx"
    with pytest.raises(ValueError):
        WebhookHeaders.from_mapping({"paypal-auth-algo": "x"})


async def test_cancel_invoice(client, paypal_mock):
    route = paypal_mock.post("/v2/invoicing/invoices/INV2-ABCD/cancel").respond(204)
    await client.cancel_invoice("INV2-ABCD", idempotency_key="cx-1", note="Wrong price")
    assert body(route.calls.last) == {
        "send_to_recipient": True,
        "send_to_invoicer": False,
        "note": "Wrong price",
    }
    assert route.calls.last.request.headers["PayPal-Request-Id"] == "cx-1"
