"""SimulatedPayPalClient: an in-memory PayPal that follows PayPal's money rules.

Used for SIMULATED shops and suppliers, for tests and for the offline demo. It implements
the same `PayPalGateway` contract as the real client and is deliberately strict:

- capture total can never exceed the authorized amount (MAX_CAPTURE_AMOUNT_EXCEEDED),
- `final_capture=true` closes the authorization; nothing more can be captured,
- captured authorizations cannot be voided (PREVIOUSLY_CAPTURED),
- reauthorization only after the 3-day honor period (REAUTHORIZATION_TOO_SOON) and within
  29 days of the original authorization, up to 115% of the original amount,
- refunds can never exceed what was captured (REFUND_AMOUNT_EXCEEDED),
- replaying a mutation with the same idempotency key returns the original result.

Resources are stored in PayPal's JSON shape and read back through the same parsers as the
real client, so both clients produce identical result objects. Every ID starts with `SIM-`.
Issue codes match PayPal's where PayPal documents them; codes PayPal does not document are
marked "simulator-only" in docs/paypal-notes.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import secrets
import zlib
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

from app.clock import Clock, SystemClock
from app.money.amount import Money
from app.paypal import payloads
from app.paypal.errors import (
    PayPalError,
    PayPalIssue,
    PayPalNotFoundError,
    PayPalUnprocessableError,
    PayPalValidationError,
)
from app.paypal.interface import (
    Authorization,
    Capture,
    CreateOrderRequest,
    Invoice,
    InvoiceDraft,
    InvoicePaymentMethod,
    Order,
    PayoutBatch,
    PayoutItemRequest,
    PayPalMode,
    Refund,
    WebhookHeaders,
)

HONOR_PERIOD = timedelta(days=3)
AUTHORIZATION_VALIDITY = timedelta(days=29)
REAUTHORIZE_MAX_RATIO_BPS = 11_500  # 115%
SIM_AUTH_ALGO = "SIM-HMAC-SHA256"

T = TypeVar("T")


# ---------------------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------------------


@dataclass
class _Order:
    id: str
    request: CreateOrderRequest
    status: str
    created: datetime
    payer_email: str | None = None
    vault_id: str | None = None
    authorization_ids: list[str] = field(default_factory=list)


@dataclass
class _Authorization:
    id: str
    order_id: str
    amount: Money
    status: str
    created: datetime
    original_created: datetime
    captured_cents: int = 0
    superseded_by: str | None = None

    @property
    def expires(self) -> datetime:
        return self.original_created + AUTHORIZATION_VALIDITY


@dataclass
class _Capture:
    id: str
    authorization_id: str
    amount: Money
    status: str
    final_capture: bool
    created: datetime
    refunded_cents: int = 0


@dataclass
class _Invoice:
    id: str
    invoicer: str
    draft: InvoiceDraft
    status: str
    paid_cents: int = 0


@dataclass
class SimulatedPayPalState:
    """The shared "PayPal" behind every simulated account in one process."""

    webhook_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    orders: dict[str, _Order] = field(default_factory=dict)
    authorizations: dict[str, _Authorization] = field(default_factory=dict)
    captures: dict[str, _Capture] = field(default_factory=dict)
    refunds: dict[str, dict[str, Any]] = field(default_factory=dict)
    payouts: dict[str, dict[str, Any]] = field(default_factory=dict)
    invoices: dict[str, _Invoice] = field(default_factory=dict)
    vaults: dict[str, str] = field(default_factory=dict)  # vault_id -> payer email
    sender_batch_ids: set[str] = field(default_factory=set)
    invoice_numbers: set[tuple[str, str]] = field(default_factory=set)
    idempotency: dict[tuple[str, str, str], Any] = field(default_factory=dict)
    _counter: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def next_id(self, kind: str) -> str:
        return f"SIM-{kind}-{next(self._counter):06d}"


# ---------------------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------------------


class SimulatedPayPalClient:
    """Simulated PayPal account. Several clients can share one `SimulatedPayPalState`."""

    mode: PayPalMode = "SIMULATED"

    def __init__(
        self,
        label: str = "platform",
        *,
        state: SimulatedPayPalState | None = None,
        clock: Clock | None = None,
        auto_approve: bool = True,
        approval_base_url: str = "http://localhost:8000",
        default_payer_email: str = "buyer@sim.swarm.example",
    ) -> None:
        self.label = label
        self.state = state or SimulatedPayPalState()
        self.clock = clock or SystemClock()
        self.auto_approve = auto_approve
        self.approval_base_url = approval_base_url.rstrip("/")
        self.default_payer_email = default_payer_email
        self._faults: dict[str, deque[PayPalError]] = defaultdict(deque)

    async def aclose(self) -> None:
        return None

    # -- test and demo helpers ----------------------------------------------------------

    def fail_next(self, operation: str, error: PayPalError) -> None:
        """Make the next call of `operation` (for example "authorizations.capture") fail."""
        self._faults[operation].append(error)

    def approve_order(self, order_id: str, payer_email: str | None = None) -> None:
        """What the buyer does on PayPal's approval page."""
        order = self._order(order_id, "orders.approve")
        if order.status not in ("CREATED", "PAYER_ACTION_REQUIRED"):
            raise _unprocessable(
                "orders.approve", "ORDER_NOT_APPROVABLE", "Order is not awaiting approval"
            )
        order.status = "APPROVED"
        order.payer_email = payer_email or self.default_payer_email

    def sign_webhook(
        self, raw_body: bytes, webhook_id: str, *, transmission_id: str | None = None
    ) -> WebhookHeaders:
        """Produce headers a simulated webhook delivery would carry."""
        transmission_id = transmission_id or self.state.next_id("WHTX")
        transmission_time = self.clock.now().isoformat()
        return WebhookHeaders(
            auth_algo=SIM_AUTH_ALGO,
            cert_url="sim://swarm/webhook-cert",
            transmission_id=transmission_id,
            transmission_sig=self._webhook_signature(
                transmission_id, transmission_time, webhook_id, raw_body
            ),
            transmission_time=transmission_time,
        )

    # -- internals ------------------------------------------------------------------------

    def _check_fault(self, operation: str) -> None:
        if self._faults[operation]:
            raise self._faults[operation].popleft()

    def _idempotent(self, operation: str, key: str, action: Callable[[], T]) -> T:
        cache_key = (self.label, operation, key)
        if cache_key in self.state.idempotency:
            cached: T = self.state.idempotency[cache_key]
            return cached
        self._check_fault(operation)
        result = action()
        self.state.idempotency[cache_key] = result
        return result

    def _order(self, order_id: str, operation: str) -> _Order:
        order = self.state.orders.get(order_id)
        if order is None:
            raise _not_found(operation, order_id)
        return order

    def _auth(self, authorization_id: str, operation: str) -> _Authorization:
        auth = self.state.authorizations.get(authorization_id)
        if auth is None:
            raise _not_found(operation, authorization_id)
        return auth

    def _capture(self, capture_id: str, operation: str) -> _Capture:
        capture = self.state.captures.get(capture_id)
        if capture is None:
            raise _not_found(operation, capture_id)
        return capture

    def _invoice(self, invoice_id: str, operation: str) -> _Invoice:
        invoice = self.state.invoices.get(invoice_id)
        if invoice is None or invoice.invoicer != self.label:
            raise _not_found(operation, invoice_id)
        return invoice

    def _new_authorization(
        self, order: _Order, amount: Money, original_created: datetime | None = None
    ) -> _Authorization:
        now = self.clock.now()
        auth = _Authorization(
            id=self.state.next_id("AUTH"),
            order_id=order.id,
            amount=amount,
            status="CREATED",
            created=now,
            original_created=original_created or now,
        )
        self.state.authorizations[auth.id] = auth
        order.authorization_ids.append(auth.id)
        return auth

    def _webhook_signature(
        self, transmission_id: str, transmission_time: str, webhook_id: str, raw_body: bytes
    ) -> str:
        # Same message layout PayPal signs: id|time|webhook_id|crc32(body).
        message = f"{transmission_id}|{transmission_time}|{webhook_id}|{zlib.crc32(raw_body)}"
        digest = hmac.new(self.state.webhook_secret, message.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    # -- JSON views (PayPal's shape) ------------------------------------------------------

    def _auth_json(self, auth: _Authorization) -> dict[str, Any]:
        return {
            "id": auth.id,
            "status": auth.status,
            "amount": auth.amount.to_paypal(),
            "create_time": _iso(auth.created),
            "expiration_time": _iso(auth.expires),
            "links": [],
        }

    def _order_json(self, order: _Order) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": order.id,
            "intent": "AUTHORIZE",
            "status": order.status,
            "purchase_units": [
                {
                    "reference_id": order.request.reference_id,
                    "amount": order.request.amount.to_paypal(),
                    "payments": {
                        "authorizations": [
                            self._auth_json(self.state.authorizations[auth_id])
                            for auth_id in order.authorization_ids
                        ]
                    },
                }
            ],
            "links": [],
        }
        paypal: dict[str, Any] = {}
        if order.payer_email:
            paypal["email_address"] = order.payer_email
        if order.vault_id:
            paypal["attributes"] = {
                "vault": {
                    "id": order.vault_id,
                    "status": "VAULTED",
                    "customer": {"id": f"SIM-CUST-{order.vault_id[-6:]}"},
                }
            }
        if paypal:
            data["payment_source"] = {"paypal": paypal}
        if order.status in ("CREATED", "PAYER_ACTION_REQUIRED"):
            data["links"].append(
                {
                    "rel": "payer-action",
                    "href": f"{self.approval_base_url}/sim/approve/{order.id}",
                    "method": "GET",
                }
            )
        return data

    def _capture_json(self, capture: _Capture) -> dict[str, Any]:
        return {
            "id": capture.id,
            "status": capture.status,
            "amount": capture.amount.to_paypal(),
            "final_capture": capture.final_capture,
            "create_time": _iso(capture.created),
        }

    def _invoice_json(self, invoice: _Invoice) -> dict[str, Any]:
        data = payloads.invoice_body(invoice.draft)
        data["id"] = invoice.id
        data["status"] = invoice.status
        data["amount"] = invoice.draft.total.to_paypal()
        due = invoice.draft.total - Money(invoice.paid_cents, invoice.draft.currency)
        data["due_amount"] = due.to_paypal()
        return data

    # -----------------------------------------------------------------------------------
    # Orders v2
    # -----------------------------------------------------------------------------------

    async def create_order(self, request: CreateOrderRequest, *, idempotency_key: str) -> Order:
        def action() -> Order:
            if request.vault_id and request.vault_id not in self.state.vaults:
                raise _unprocessable(
                    "orders.create", "INVALID_VAULT_ID", "Saved payment method not found"
                )
            order = _Order(
                id=self.state.next_id("ORDER"),
                request=request,
                status="PAYER_ACTION_REQUIRED" if request.return_url else "CREATED",
                created=self.clock.now(),
            )
            self.state.orders[order.id] = order
            if request.vault_id:
                # Buyer not present: PayPal processes the saved wallet straight away.
                order.payer_email = self.state.vaults[request.vault_id]
                order.vault_id = request.vault_id
                self._new_authorization(order, request.amount)
                order.status = "COMPLETED"
            return payloads.parse_order(self._order_json(order))

        return self._idempotent("orders.create", idempotency_key, action)

    async def get_order(self, order_id: str) -> Order:
        self._check_fault("orders.get")
        return payloads.parse_order(self._order_json(self._order(order_id, "orders.get")))

    async def authorize_order(self, order_id: str, *, idempotency_key: str) -> Order:
        def action() -> Order:
            order = self._order(order_id, "orders.authorize")
            if order.status == "COMPLETED":
                raise _unprocessable(
                    "orders.authorize", "ORDER_ALREADY_AUTHORIZED", "Order already authorized"
                )
            if order.status != "APPROVED":
                if not self.auto_approve:
                    raise _unprocessable(
                        "orders.authorize", "ORDER_NOT_APPROVED", "Buyer has not approved"
                    )
                self.approve_order(order.id)
            self._new_authorization(order, order.request.amount)
            if order.request.save_payment_method:
                vault_id = self.state.next_id("VAULT")
                self.state.vaults[vault_id] = order.payer_email or self.default_payer_email
                order.vault_id = vault_id
            order.status = "COMPLETED"
            return payloads.parse_order(self._order_json(order))

        return self._idempotent("orders.authorize", idempotency_key, action)

    # -----------------------------------------------------------------------------------
    # Payments v2
    # -----------------------------------------------------------------------------------

    async def get_authorization(self, authorization_id: str) -> Authorization:
        self._check_fault("authorizations.get")
        auth = self._auth(authorization_id, "authorizations.get")
        return payloads.parse_authorization(self._auth_json(auth))

    async def capture_authorization(
        self,
        authorization_id: str,
        *,
        amount: Money,
        final_capture: bool,
        idempotency_key: str,
        invoice_id: str | None = None,
        note_to_payer: str | None = None,
    ) -> Capture:
        op = "authorizations.capture"

        def action() -> Capture:
            auth = self._auth(authorization_id, op)
            if auth.superseded_by:
                raise _unprocessable(
                    op, "AUTHORIZATION_SUPERSEDED", f"Capture {auth.superseded_by} instead"
                )
            if auth.status not in ("CREATED", "PARTIALLY_CAPTURED"):
                raise _unprocessable(op, "AUTHORIZATION_ALREADY_COMPLETED", auth.status)
            if self.clock.now() > auth.expires:
                raise _unprocessable(op, "AUTHORIZATION_EXPIRED", "Authorization has expired")
            if amount.currency != auth.amount.currency:
                raise _unprocessable(op, "CURRENCY_MISMATCH", "Capture currency differs")
            if not amount.is_positive:
                raise _validation(op, "INVALID_PARAMETER_VALUE", "Capture amount must be positive")
            if auth.captured_cents + amount.cents > auth.amount.cents:
                raise _unprocessable(
                    op, "MAX_CAPTURE_AMOUNT_EXCEEDED", "Capture exceeds the authorized amount"
                )
            capture = _Capture(
                id=self.state.next_id("CAPTURE"),
                authorization_id=auth.id,
                amount=amount,
                status="COMPLETED",
                final_capture=final_capture,
                created=self.clock.now(),
            )
            self.state.captures[capture.id] = capture
            auth.captured_cents += amount.cents
            fully = auth.captured_cents == auth.amount.cents
            auth.status = "CAPTURED" if final_capture or fully else "PARTIALLY_CAPTURED"
            return payloads.parse_capture(self._capture_json(capture))

        return self._idempotent(op, idempotency_key, action)

    async def void_authorization(
        self, authorization_id: str, *, idempotency_key: str
    ) -> Authorization | None:
        op = "authorizations.void"

        def action() -> Authorization | None:
            auth = self._auth(authorization_id, op)
            if auth.status == "CAPTURED":
                raise _unprocessable(op, "PREVIOUSLY_CAPTURED", "Authorization already captured")
            if auth.status == "VOIDED":
                raise _unprocessable(op, "PREVIOUSLY_VOIDED", "Authorization already voided")
            auth.status = "VOIDED"
            return payloads.parse_authorization(self._auth_json(auth))

        return self._idempotent(op, idempotency_key, action)

    async def reauthorize_authorization(
        self, authorization_id: str, *, amount: Money, idempotency_key: str
    ) -> Authorization:
        op = "authorizations.reauthorize"

        def action() -> Authorization:
            auth = self._auth(authorization_id, op)
            now = self.clock.now()
            if auth.status != "CREATED" or auth.superseded_by:
                raise _unprocessable(op, "AUTHORIZATION_ALREADY_COMPLETED", auth.status)
            if amount.currency != auth.amount.currency:
                raise _unprocessable(op, "AUTH_CURRENCY_MISMATCH", "Currency differs")
            if now - auth.original_created < HONOR_PERIOD:
                raise _unprocessable(
                    op, "REAUTHORIZATION_TOO_SOON", "Reauthorize after the 3-day honor period"
                )
            if now > auth.expires:
                raise _unprocessable(op, "AUTHORIZATION_EXPIRED", "Authorization has expired")
            if amount.cents * 10_000 > auth.amount.cents * REAUTHORIZE_MAX_RATIO_BPS:
                raise _unprocessable(
                    op, "REAUTHORIZATION_AMOUNT_EXCEEDED", "Above 115% of the original amount"
                )
            order = self.state.orders[auth.order_id]
            new_auth = self._new_authorization(
                order, amount, original_created=auth.original_created
            )
            auth.superseded_by = new_auth.id
            return payloads.parse_authorization(self._auth_json(new_auth))

        return self._idempotent(op, idempotency_key, action)

    async def get_capture(self, capture_id: str) -> Capture:
        self._check_fault("captures.get")
        return payloads.parse_capture(self._capture_json(self._capture(capture_id, "captures.get")))

    async def refund_capture(
        self,
        capture_id: str,
        *,
        amount: Money | None,
        idempotency_key: str,
        note_to_payer: str | None = None,
    ) -> Refund:
        op = "captures.refund"

        def action() -> Refund:
            capture = self._capture(capture_id, op)
            if capture.status not in ("COMPLETED", "PARTIALLY_REFUNDED"):
                raise _unprocessable(op, "CAPTURE_FULLY_REFUNDED", capture.status)
            remaining = capture.amount.cents - capture.refunded_cents
            refund_amount = amount or Money(remaining, capture.amount.currency)
            if refund_amount.currency != capture.amount.currency:
                raise _unprocessable(op, "CURRENCY_MISMATCH", "Refund currency differs")
            if not refund_amount.is_positive or refund_amount.cents > remaining:
                raise _unprocessable(
                    op, "REFUND_AMOUNT_EXCEEDED", "Refund exceeds the captured amount"
                )
            capture.refunded_cents += refund_amount.cents
            capture.status = (
                "REFUNDED"
                if capture.refunded_cents == capture.amount.cents
                else "PARTIALLY_REFUNDED"
            )
            refund: dict[str, Any] = {
                "id": self.state.next_id("REFUND"),
                "status": "COMPLETED",
                "amount": refund_amount.to_paypal(),
                "create_time": _iso(self.clock.now()),
            }
            self.state.refunds[refund["id"]] = refund
            return payloads.parse_refund(refund)

        return self._idempotent(op, idempotency_key, action)

    # -----------------------------------------------------------------------------------
    # Payouts v1
    # -----------------------------------------------------------------------------------

    async def create_payout(
        self,
        *,
        sender_batch_id: str,
        items: Sequence[PayoutItemRequest],
        idempotency_key: str,
        email_subject: str,
        email_message: str | None = None,
    ) -> PayoutBatch:
        op = "payouts.create"
        if not items:
            raise ValueError("A payout batch needs at least one item")

        def action() -> PayoutBatch:
            if sender_batch_id in self.state.sender_batch_ids:
                raise _validation(
                    op, "SENDER_BATCH_ID_ALREADY_USED", "Batch with this sender_batch_id exists"
                )
            if any(not item.amount.is_positive for item in items):
                raise _validation(op, "INVALID_AMOUNT", "Payout amounts must be positive")
            self.state.sender_batch_ids.add(sender_batch_id)
            batch_id = self.state.next_id("PAYOUT")
            total = Money.zero(items[0].amount.currency)
            for item in items:
                total += item.amount
            stored: dict[str, Any] = {
                "batch_header": {
                    "payout_batch_id": batch_id,
                    "batch_status": "SUCCESS",
                    "sender_batch_header": {
                        "sender_batch_id": sender_batch_id,
                        "email_subject": email_subject,
                    },
                    "amount": total.to_payouts(),
                    "time_created": _iso(self.clock.now()),
                },
                "items": [
                    {
                        "payout_item_id": self.state.next_id("PAYOUTITEM"),
                        "transaction_id": self.state.next_id("TXN"),
                        "transaction_status": "SUCCESS",
                        "payout_batch_id": batch_id,
                        "payout_item": {
                            "recipient_type": "EMAIL",
                            "receiver": item.receiver_email,
                            "amount": item.amount.to_payouts(),
                            "sender_item_id": item.sender_item_id,
                            "note": item.note,
                        },
                    }
                    for item in items
                ],
            }
            self.state.payouts[batch_id] = stored
            # Like PayPal, the create response only says the batch was accepted.
            accepted = {
                "batch_header": {
                    "payout_batch_id": batch_id,
                    "batch_status": "PENDING",
                    "sender_batch_header": stored["batch_header"]["sender_batch_header"],
                }
            }
            return payloads.parse_payout_batch(accepted)

        return self._idempotent(op, idempotency_key, action)

    async def get_payout(self, batch_id: str) -> PayoutBatch:
        self._check_fault("payouts.get")
        stored = self.state.payouts.get(batch_id)
        if stored is None:
            raise _not_found("payouts.get", batch_id)
        return payloads.parse_payout_batch(stored)

    # -----------------------------------------------------------------------------------
    # Invoicing v2
    # -----------------------------------------------------------------------------------

    async def create_invoice(self, draft: InvoiceDraft, *, idempotency_key: str) -> Invoice:
        op = "invoices.create"

        def action() -> Invoice:
            number_key = (self.label, draft.invoice_number)
            if number_key in self.state.invoice_numbers:
                raise _unprocessable(op, "DUPLICATE_INVOICE_NUMBER", draft.invoice_number)
            self.state.invoice_numbers.add(number_key)
            invoice = _Invoice(
                id=self.state.next_id("INV"), invoicer=self.label, draft=draft, status="DRAFT"
            )
            self.state.invoices[invoice.id] = invoice
            return payloads.parse_invoice(self._invoice_json(invoice))

        return self._idempotent(op, idempotency_key, action)

    async def send_invoice(
        self,
        invoice_id: str,
        *,
        idempotency_key: str,
        subject: str | None = None,
        note: str | None = None,
    ) -> None:
        op = "invoices.send"

        def action() -> None:
            invoice = self._invoice(invoice_id, op)
            if invoice.status != "DRAFT":
                raise _unprocessable(op, "INVALID_INVOICE_STATUS", f"Cannot send {invoice.status}")
            invoice.status = "SENT"

        self._idempotent(op, idempotency_key, action)

    async def get_invoice(self, invoice_id: str) -> Invoice:
        self._check_fault("invoices.get")
        return payloads.parse_invoice(self._invoice_json(self._invoice(invoice_id, "invoices.get")))

    async def record_invoice_payment(
        self,
        invoice_id: str,
        *,
        amount: Money,
        payment_date: date,
        method: InvoicePaymentMethod,
        idempotency_key: str,
        note: str | None = None,
    ) -> str:
        op = "invoices.payments"

        def action() -> str:
            invoice = self._invoice(invoice_id, op)
            if invoice.status not in ("SENT", "UNPAID", "PARTIALLY_PAID"):
                raise _unprocessable(op, "INVALID_INVOICE_STATUS", f"Cannot pay {invoice.status}")
            due = invoice.draft.total.cents - invoice.paid_cents
            if amount.currency != invoice.draft.currency or not 0 < amount.cents <= due:
                raise _unprocessable(op, "PAYMENT_AMOUNT_INVALID", "Payment exceeds amount due")
            invoice.paid_cents += amount.cents
            invoice.status = (
                "MARKED_AS_PAID"
                if invoice.paid_cents == invoice.draft.total.cents
                else "PARTIALLY_PAID"
            )
            return self.state.next_id("INVPAY")

        return self._idempotent(op, idempotency_key, action)

    # -----------------------------------------------------------------------------------
    # Webhooks v1
    # -----------------------------------------------------------------------------------

    async def verify_webhook_signature(
        self, *, headers: WebhookHeaders, raw_body: bytes, webhook_id: str
    ) -> bool:
        self._check_fault("webhooks.verify")
        if headers.auth_algo != SIM_AUTH_ALGO:
            return False
        expected = self._webhook_signature(
            headers.transmission_id, headers.transmission_time, webhook_id, raw_body
        )
        return hmac.compare_digest(expected, headers.transmission_sig)


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _debug_id() -> str:
    return f"SIM-DEBUG-{secrets.token_hex(6)}"


def _unprocessable(operation: str, issue: str, description: str) -> PayPalUnprocessableError:
    return PayPalUnprocessableError(
        message=(
            "The requested action could not be performed, semantically incorrect, "
            "or failed business validation."
        ),
        status_code=422,
        name="UNPROCESSABLE_ENTITY",
        debug_id=_debug_id(),
        details=[PayPalIssue(issue=issue, description=description)],
        operation=operation,
    )


def _validation(operation: str, issue: str, description: str) -> PayPalValidationError:
    return PayPalValidationError(
        message="Request is not well-formed, syntactically incorrect, or violates schema.",
        status_code=400,
        name="INVALID_REQUEST",
        debug_id=_debug_id(),
        details=[PayPalIssue(issue=issue, description=description)],
        operation=operation,
    )


def _not_found(operation: str, resource_id: str) -> PayPalNotFoundError:
    return PayPalNotFoundError(
        message=f"The specified resource does not exist: {resource_id}",
        status_code=404,
        name="RESOURCE_NOT_FOUND",
        debug_id=_debug_id(),
        details=[PayPalIssue(issue="INVALID_RESOURCE_ID", description=resource_id)],
        operation=operation,
    )
