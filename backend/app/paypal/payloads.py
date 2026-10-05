"""Builders for PayPal request bodies and parsers for PayPal responses.

Field names here were checked against PayPal's published OpenAPI specs
(github.com/paypal/paypal-rest-api-specifications) and the developer docs; see
docs/paypal-notes.md. The real client, the simulated client and the Agent Toolkit adapter
all go through these functions, so there is exactly one place that knows PayPal's JSON shape.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.money.amount import Money
from app.paypal.interface import (
    Authorization,
    Capture,
    CreateOrderRequest,
    Invoice,
    InvoiceDraft,
    InvoiceLine,
    Order,
    PayoutBatch,
    PayoutItemRequest,
    PayoutItemResult,
    Refund,
    VaultInfo,
    WebhookHeaders,
)

# ---------------------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------------------


def order_body(request: CreateOrderRequest) -> dict[str, Any]:
    """POST /v2/checkout/orders with intent AUTHORIZE."""
    purchase_unit: dict[str, Any] = {
        "reference_id": request.reference_id,
        "amount": request.amount.to_paypal(),
    }
    for key in ("description", "custom_id", "invoice_id"):
        value = getattr(request, key)
        if value:
            purchase_unit[key] = value

    body: dict[str, Any] = {"intent": "AUTHORIZE", "purchase_units": [purchase_unit]}
    if request.vault_id:
        body["payment_source"] = {"paypal": {"vault_id": request.vault_id}}
    elif request.save_payment_method:
        body["payment_source"] = {
            "paypal": {
                "attributes": {"vault": {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT"}},
                "experience_context": {
                    "brand_name": request.brand_name,
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": request.return_url,
                    "cancel_url": request.cancel_url,
                },
            }
        }
    elif request.return_url and request.cancel_url:
        body["payment_source"] = {
            "paypal": {
                "experience_context": {
                    "brand_name": request.brand_name,
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": request.return_url,
                    "cancel_url": request.cancel_url,
                }
            }
        }
    return body


def capture_body(
    amount: Money, final_capture: bool, invoice_id: str | None, note_to_payer: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {"amount": amount.to_paypal(), "final_capture": final_capture}
    if invoice_id:
        body["invoice_id"] = invoice_id
    if note_to_payer:
        body["note_to_payer"] = note_to_payer
    return body


def refund_body(amount: Money | None, note_to_payer: str | None) -> dict[str, Any]:
    """An empty body refunds the full remaining amount."""
    body: dict[str, Any] = {}
    if amount is not None:
        body["amount"] = amount.to_paypal()
    if note_to_payer:
        body["note_to_payer"] = note_to_payer
    return body


def payout_body(
    sender_batch_id: str,
    items: Sequence[PayoutItemRequest],
    email_subject: str,
    email_message: str | None,
) -> dict[str, Any]:
    """POST /v1/payments/payouts. Note: Payouts money uses `currency`, not `currency_code`."""
    header: dict[str, Any] = {
        "sender_batch_id": sender_batch_id,
        "recipient_type": "EMAIL",
        "email_subject": email_subject,
    }
    if email_message:
        header["email_message"] = email_message
    return {
        "sender_batch_header": header,
        "items": [
            {
                "recipient_type": "EMAIL",
                "receiver": item.receiver_email,
                "amount": item.amount.to_payouts(),
                "sender_item_id": item.sender_item_id,
                "recipient_wallet": "PAYPAL",
                **({"note": item.note} if item.note else {}),
            }
            for item in items
        ],
    }


def invoice_line_body(line: InvoiceLine) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": line.name,
        "quantity": _decimal_str(line.quantity),
        "unit_amount": line.unit_amount.to_paypal(),
        "unit_of_measure": "QUANTITY",
    }
    if line.description:
        body["description"] = line.description
    return body


def invoice_body(draft: InvoiceDraft) -> dict[str, Any]:
    """POST /v2/invoicing/invoices (creates a DRAFT invoice)."""
    detail: dict[str, Any] = {
        "invoice_number": draft.invoice_number,
        "invoice_date": draft.invoice_date.isoformat(),
        "currency_code": draft.currency,
        "payment_term": {"term_type": "DUE_ON_RECEIPT"},
    }
    if draft.reference:
        detail["reference"] = draft.reference
    if draft.note:
        detail["note"] = draft.note

    invoicer: dict[str, Any] = {}
    if draft.invoicer_business_name:
        invoicer["business_name"] = draft.invoicer_business_name
    if draft.invoicer_email:
        invoicer["email_address"] = draft.invoicer_email

    billing_info: dict[str, Any] = {"email_address": draft.recipient_email}
    if draft.recipient_business_name:
        billing_info["business_name"] = draft.recipient_business_name

    body: dict[str, Any] = {
        "detail": detail,
        "primary_recipients": [{"billing_info": billing_info}],
        "items": [invoice_line_body(line) for line in draft.lines],
    }
    if invoicer:
        body["invoicer"] = invoicer
    return body


def invoice_payment_body(
    amount: Money, payment_date: date, method: str, note: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "method": method,
        "payment_date": payment_date.isoformat(),
        "amount": amount.to_paypal(),
    }
    if note:
        body["note"] = note
    return body


def verify_webhook_body(headers: WebhookHeaders, raw_body: bytes, webhook_id: str) -> bytes:
    """POST /v1/notifications/verify-webhook-signature.

    The event is spliced in as the exact bytes PayPal sent. Re-serialising parsed JSON can
    change number formatting or escaping, which makes PayPal report FAILURE for a genuine
    event, so the envelope is built by hand around the raw body.
    """
    envelope = {
        "auth_algo": headers.auth_algo,
        "cert_url": headers.cert_url,
        "transmission_id": headers.transmission_id,
        "transmission_sig": headers.transmission_sig,
        "transmission_time": headers.transmission_time,
        "webhook_id": webhook_id,
    }
    prefix = json.dumps(envelope)[:-1]  # drop the closing brace
    return prefix.encode() + b', "webhook_event": ' + raw_body.strip() + b"}"


# ---------------------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------------------


def parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def link_href(links: Any, *rels: str) -> str | None:
    for rel in rels:
        for link in links or []:
            if isinstance(link, dict) and link.get("rel") == rel:
                return str(link.get("href"))
    return None


def parse_authorization(data: dict[str, Any]) -> Authorization:
    return Authorization(
        id=data["id"],
        status=data.get("status", "UNKNOWN"),
        amount=Money.from_paypal_amount(data["amount"]),
        create_time=parse_time(data.get("create_time")),
        expiration_time=parse_time(data.get("expiration_time")),
        raw=data,
    )


def parse_order(data: dict[str, Any]) -> Order:
    paypal_source = (data.get("payment_source") or {}).get("paypal") or {}
    vault_data = (paypal_source.get("attributes") or {}).get("vault")
    vault = None
    if isinstance(vault_data, dict):
        vault = VaultInfo(
            id=vault_data.get("id"),
            status=vault_data.get("status"),
            customer_id=(vault_data.get("customer") or {}).get("id"),
        )
    authorizations: list[Authorization] = []
    for unit in data.get("purchase_units") or []:
        for auth in (unit.get("payments") or {}).get("authorizations") or []:
            authorizations.append(parse_authorization(auth))
    return Order(
        id=data["id"],
        status=data.get("status", "UNKNOWN"),
        approve_url=link_href(data.get("links"), "payer-action", "approve"),
        payer_email=paypal_source.get("email_address")
        or (data.get("payer") or {}).get("email_address"),
        vault=vault,
        authorizations=tuple(authorizations),
        raw=data,
    )


def parse_capture(data: dict[str, Any]) -> Capture:
    return Capture(
        id=data["id"],
        status=data.get("status", "UNKNOWN"),
        amount=Money.from_paypal_amount(data["amount"]),
        final_capture=data.get("final_capture"),
        raw=data,
    )


def parse_refund(data: dict[str, Any]) -> Refund:
    amount = data.get("amount")
    return Refund(
        id=data["id"],
        status=data.get("status", "UNKNOWN"),
        amount=Money.from_paypal_amount(amount) if amount else None,
        raw=data,
    )


def parse_payout_batch(data: dict[str, Any]) -> PayoutBatch:
    header = data.get("batch_header") or {}
    items = []
    for item in data.get("items") or []:
        detail = item.get("payout_item") or {}
        amount = detail.get("amount")
        items.append(
            PayoutItemResult(
                payout_item_id=item.get("payout_item_id", ""),
                transaction_status=item.get("transaction_status"),
                receiver=detail.get("receiver"),
                amount=Money.from_paypal_amount(amount) if amount else None,
                sender_item_id=detail.get("sender_item_id"),
                transaction_id=item.get("transaction_id"),
            )
        )
    return PayoutBatch(
        batch_id=header.get("payout_batch_id", ""),
        status=header.get("batch_status", "UNKNOWN"),
        sender_batch_id=(header.get("sender_batch_header") or {}).get("sender_batch_id"),
        items=tuple(items),
        raw=data,
    )


def parse_invoice(data: dict[str, Any]) -> Invoice:
    detail = data.get("detail") or {}
    currency = detail.get("currency_code") or (data.get("amount") or {}).get("currency_code")
    lines = []
    for item in data.get("items") or []:
        unit = item.get("unit_amount")
        if not unit:
            continue
        lines.append(
            InvoiceLine(
                name=item.get("name", ""),
                quantity=Decimal(str(item.get("quantity", "0"))),
                unit_amount=Money.from_paypal_amount(unit),
                description=item.get("description"),
            )
        )
    amount = data.get("amount")
    total = None
    total_currency = (amount or {}).get("currency_code") or currency
    if amount and amount.get("value") is not None and total_currency:
        total = Money.from_paypal(amount["value"], total_currency)
    recipients = data.get("primary_recipients") or []
    recipient_email = None
    if recipients:
        recipient_email = (recipients[0].get("billing_info") or {}).get("email_address")
    return Invoice(
        id=data["id"],
        status=data.get("status", "UNKNOWN"),
        invoice_number=detail.get("invoice_number"),
        total=total,
        recipient_email=recipient_email,
        lines=tuple(lines),
        raw=data,
    )


def invoice_id_from_link(data: dict[str, Any]) -> str | None:
    """Invoicing endpoints return a bare link (`{rel, href, method}`) unless asked for the
    full representation. Pull the invoice ID out of its href."""
    href = data.get("href") or link_href(data.get("links"), "self")
    if not href:
        return None
    return href.rstrip("/").rsplit("/", 1)[-1]


def _decimal_str(value: Decimal) -> str:
    return format(value.normalize(), "f")
