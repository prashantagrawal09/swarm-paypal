"""The PayPal gateway contract shared by the real and simulated clients.

The money engine only ever talks to `PayPalGateway`. Whether a call reaches the PayPal
sandbox (`PayPalClient`) or the in-memory simulator (`SimulatedPayPalClient`) depends on the
account's `paypal_mode`, and nothing above this layer needs to know which.

All result types keep the full PayPal response in `raw` so it can be stored in
`payments.raw` for audit and debugging.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from app.money.amount import Money

PayPalMode = Literal["REAL", "SIMULATED"]

# Statuses where PayPal considers an invoice settled. Payments recorded through the API
# (external payments) usually show up as MARKED_AS_PAID rather than PAID.
INVOICE_PAID_STATUSES = frozenset({"PAID", "MARKED_AS_PAID", "PAID_EXTERNAL"})

InvoicePaymentMethod = Literal[
    "BANK_TRANSFER",
    "CASH",
    "CHECK",
    "CREDIT_CARD",
    "DEBIT_CARD",
    "PAYPAL",
    "WIRE_TRANSFER",
    "OTHER",
]


# ---------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateOrderRequest:
    """An order with intent AUTHORIZE (Swarm never captures at order time).

    Exactly one way to pay must be chosen:
    - `save_payment_method=True`: first-time approval. The buyer approves in the browser and
      PayPal saves their wallet for future merchant-initiated orders (vault).
    - `vault_id=...`: a later order with the buyer not present, using the saved wallet.
    - neither: a plain buyer-approved order.
    """

    amount: Money
    reference_id: str
    description: str | None = None
    custom_id: str | None = None
    invoice_id: str | None = None
    save_payment_method: bool = False
    vault_id: str | None = None
    return_url: str | None = None
    cancel_url: str | None = None
    brand_name: str = "Swarm"

    def __post_init__(self) -> None:
        if not self.amount.is_positive:
            raise ValueError("Order amount must be positive")
        if self.save_payment_method and self.vault_id:
            raise ValueError("Choose either save_payment_method or vault_id, not both")
        if self.save_payment_method and not (self.return_url and self.cancel_url):
            raise ValueError("Saving a payment method needs return_url and cancel_url")


@dataclass(frozen=True)
class PayoutItemRequest:
    receiver_email: str
    amount: Money
    sender_item_id: str
    note: str | None = None


@dataclass(frozen=True)
class InvoiceLine:
    name: str
    quantity: Decimal
    unit_amount: Money
    description: str | None = None

    @property
    def total(self) -> Money:
        """Line total, rounded half-up to the minor unit (PayPal supports fractional qty)."""
        cents = (Decimal(self.unit_amount.cents) * self.quantity).quantize(Decimal(1))
        return Money(int(cents), self.unit_amount.currency)


@dataclass(frozen=True)
class InvoiceDraft:
    invoice_number: str
    invoice_date: date
    currency: str
    recipient_email: str
    lines: Sequence[InvoiceLine]
    recipient_business_name: str | None = None
    invoicer_email: str | None = None
    invoicer_business_name: str | None = None
    reference: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError("An invoice needs at least one line")
        if any(line.unit_amount.currency != self.currency for line in self.lines):
            raise ValueError("Every invoice line must use the invoice currency")

    @property
    def total(self) -> Money:
        total = Money.zero(self.currency)
        for line in self.lines:
            total += line.total
        return total


@dataclass(frozen=True)
class WebhookHeaders:
    """The PayPal transmission headers needed to verify a webhook delivery."""

    auth_algo: str
    cert_url: str
    transmission_id: str
    transmission_sig: str
    transmission_time: str

    @classmethod
    def from_mapping(cls, headers: Mapping[str, str]) -> WebhookHeaders:
        lower = {key.lower(): value for key, value in headers.items()}
        try:
            return cls(
                auth_algo=lower["paypal-auth-algo"],
                cert_url=lower["paypal-cert-url"],
                transmission_id=lower["paypal-transmission-id"],
                transmission_sig=lower["paypal-transmission-sig"],
                transmission_time=lower["paypal-transmission-time"],
            )
        except KeyError as exc:
            raise ValueError(f"Missing PayPal webhook header: {exc.args[0]}") from exc

    def to_mapping(self) -> dict[str, str]:
        return {
            "PAYPAL-AUTH-ALGO": self.auth_algo,
            "PAYPAL-CERT-URL": self.cert_url,
            "PAYPAL-TRANSMISSION-ID": self.transmission_id,
            "PAYPAL-TRANSMISSION-SIG": self.transmission_sig,
            "PAYPAL-TRANSMISSION-TIME": self.transmission_time,
        }


# ---------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VaultInfo:
    """The saved PayPal wallet ("vault") returned once a buyer approves saving it."""

    id: str | None
    status: str | None
    customer_id: str | None = None


@dataclass(frozen=True)
class Authorization:
    id: str
    status: str
    amount: Money
    create_time: datetime | None = None
    expiration_time: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class Order:
    id: str
    status: str
    approve_url: str | None = None
    payer_email: str | None = None
    vault: VaultInfo | None = None
    authorizations: tuple[Authorization, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def authorization(self) -> Authorization | None:
        return self.authorizations[0] if self.authorizations else None


@dataclass(frozen=True)
class Capture:
    id: str
    status: str
    amount: Money
    final_capture: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class Refund:
    id: str
    status: str
    amount: Money | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class PayoutItemResult:
    payout_item_id: str
    transaction_status: str | None
    receiver: str | None
    amount: Money | None
    sender_item_id: str | None = None
    transaction_id: str | None = None


@dataclass(frozen=True)
class PayoutBatch:
    batch_id: str
    status: str
    sender_batch_id: str | None = None
    items: tuple[PayoutItemResult, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class Invoice:
    id: str
    status: str
    invoice_number: str | None = None
    total: Money | None = None
    recipient_email: str | None = None
    lines: tuple[InvoiceLine, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_paid(self) -> bool:
        return self.status in INVOICE_PAID_STATUSES


# ---------------------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------------------


@runtime_checkable
class PayPalGateway(Protocol):
    """Every PayPal capability Swarm uses. Mutations take a stable `idempotency_key`,
    which becomes the `PayPal-Request-Id` header, so retries never double charge."""

    mode: PayPalMode
    label: str

    # Orders v2
    async def create_order(self, request: CreateOrderRequest, *, idempotency_key: str) -> Order: ...
    async def get_order(self, order_id: str) -> Order: ...
    async def authorize_order(self, order_id: str, *, idempotency_key: str) -> Order: ...

    # Payments v2
    async def get_authorization(self, authorization_id: str) -> Authorization: ...
    async def capture_authorization(
        self,
        authorization_id: str,
        *,
        amount: Money,
        final_capture: bool,
        idempotency_key: str,
        invoice_id: str | None = None,
        note_to_payer: str | None = None,
    ) -> Capture: ...
    async def void_authorization(
        self, authorization_id: str, *, idempotency_key: str
    ) -> Authorization | None: ...
    async def reauthorize_authorization(
        self, authorization_id: str, *, amount: Money, idempotency_key: str
    ) -> Authorization: ...
    async def get_capture(self, capture_id: str) -> Capture: ...
    async def refund_capture(
        self,
        capture_id: str,
        *,
        amount: Money | None,
        idempotency_key: str,
        note_to_payer: str | None = None,
    ) -> Refund: ...

    # Payouts v1
    async def create_payout(
        self,
        *,
        sender_batch_id: str,
        items: Sequence[PayoutItemRequest],
        idempotency_key: str,
        email_subject: str,
        email_message: str | None = None,
    ) -> PayoutBatch: ...
    async def get_payout(self, batch_id: str) -> PayoutBatch: ...

    # Invoicing v2
    async def create_invoice(self, draft: InvoiceDraft, *, idempotency_key: str) -> Invoice: ...
    async def send_invoice(
        self,
        invoice_id: str,
        *,
        idempotency_key: str,
        subject: str | None = None,
        note: str | None = None,
    ) -> None: ...
    async def get_invoice(self, invoice_id: str) -> Invoice: ...
    async def cancel_invoice(
        self, invoice_id: str, *, idempotency_key: str, note: str | None = None
    ) -> None: ...
    async def record_invoice_payment(
        self,
        invoice_id: str,
        *,
        amount: Money,
        payment_date: date,
        method: InvoicePaymentMethod,
        idempotency_key: str,
        note: str | None = None,
    ) -> str: ...

    # Webhooks v1
    async def verify_webhook_signature(
        self, *, headers: WebhookHeaders, raw_body: bytes, webhook_id: str
    ) -> bool: ...

    async def aclose(self) -> None: ...
