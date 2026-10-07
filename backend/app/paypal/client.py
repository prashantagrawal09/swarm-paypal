"""Real PayPal REST client (sandbox) implementing `PayPalGateway`.

- OAuth2 client-credentials tokens are cached until shortly before they expire, and
  refreshed once automatically if PayPal answers 401.
- Every mutation sends `PayPal-Request-Id` set to the caller's idempotency key, so a retry
  of the same step returns PayPal's original result instead of charging twice.
- Only idempotent requests (GETs and mutations with a request ID) are retried, and only on
  network errors, 409 PREVIOUS_REQUEST_IN_PROGRESS, 429 and 5xx.
- Failures are raised as typed `PayPalError`s carrying PayPal's debug ID and issue codes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import Any

import httpx

from app.money.amount import Money
from app.paypal import payloads
from app.paypal.credentials import PayPalCredentials
from app.paypal.errors import (
    PayPalAuthError,
    PayPalConfigError,
    PayPalError,
    PayPalTransportError,
    error_from_response,
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

logger = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
LIVE_BASE_URL = "https://api-m.paypal.com"

# Refresh tokens this many seconds before PayPal says they expire.
TOKEN_EXPIRY_MARGIN_SECONDS = 120


class PayPalClient:
    """Async client for one PayPal account (one REST app)."""

    mode: PayPalMode = "REAL"

    def __init__(
        self,
        credentials: PayPalCredentials,
        *,
        base_url: str = SANDBOX_BASE_URL,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        allow_live: bool = False,
    ) -> None:
        if base_url.rstrip("/") == LIVE_BASE_URL and not allow_live:
            raise PayPalConfigError("Swarm only talks to the PayPal sandbox", operation="init")
        self.credentials = credentials
        self.label = credentials.label
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http is None
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self.token_requests = 0
        self.last_debug_id: str | None = None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -----------------------------------------------------------------------------------
    # OAuth
    # -----------------------------------------------------------------------------------

    async def access_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if not force_refresh and self._token and self._monotonic() < self._token_expires_at:
                return self._token
            self.token_requests += 1
            try:
                response = await self._http.post(
                    f"{self.base_url}/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.credentials.client_id, self.credentials.client_secret),
                    headers={"Accept": "application/json"},
                )
            except httpx.TransportError as exc:
                raise PayPalTransportError(
                    f"Could not reach PayPal: {exc}", operation="oauth.token"
                ) from exc
            body = _json_or_none(response)
            if response.status_code != 200 or not isinstance(body, dict):
                error = error_from_response(response.status_code, body, operation="oauth.token")
                raise PayPalAuthError(
                    message=error.message,
                    status_code=error.status_code,
                    name=error.name,
                    debug_id=error.debug_id,
                    details=error.details,
                    operation="oauth.token",
                    raw=body,
                )
            self._token = str(body["access_token"])
            expires_in = float(body.get("expires_in", 0))
            self._token_expires_at = self._monotonic() + max(
                expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, 0
            )
            return self._token

    # -----------------------------------------------------------------------------------
    # Transport
    # -----------------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        json_body: Any = None,
        content: bytes | None = None,
        idempotency_key: str | None = None,
        prefer_representation: bool = True,
        safe_to_retry: bool = False,
    ) -> Any:
        """Send one API call with auth, idempotency and safe retries. Returns parsed JSON."""
        retry_allowed = method == "GET" or idempotency_key is not None or safe_to_retry
        refreshed_token = False
        attempt = 0
        while True:
            token = await self.access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            if idempotency_key:
                headers["PayPal-Request-Id"] = idempotency_key
            if prefer_representation:
                headers["Prefer"] = "return=representation"

            started = self._monotonic()
            error: PayPalError
            retry_after: float | None = None
            try:
                response = await self._http.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                    content=content,
                )
            except httpx.TransportError as exc:
                error = PayPalTransportError(f"Could not reach PayPal: {exc}", operation=operation)
            else:
                debug_id = response.headers.get("paypal-debug-id")
                self.last_debug_id = debug_id
                logger.info(
                    "paypal %s %s %s -> %s in %.0fms debug_id=%s",
                    self.label,
                    method,
                    path,
                    response.status_code,
                    (self._monotonic() - started) * 1000,
                    debug_id,
                )
                if response.status_code < 400:
                    return _json_or_none(response) or {}
                if response.status_code == 401 and not refreshed_token:
                    refreshed_token = True
                    await self.access_token(force_refresh=True)
                    continue
                error = error_from_response(
                    response.status_code, _json_or_none(response), operation=operation
                )
                if error.debug_id is None:
                    error.debug_id = debug_id
                retry_after = _retry_after_seconds(response)

            if not (retry_allowed and error.retryable) or attempt >= self._max_retries:
                raise error
            delay = retry_after if retry_after is not None else 0.5 * (2**attempt)
            logger.warning("Retrying %s after %s (attempt %d)", operation, error, attempt + 1)
            attempt += 1
            await self._sleep(delay)

    # -----------------------------------------------------------------------------------
    # Orders v2
    # -----------------------------------------------------------------------------------

    async def create_order(self, request: CreateOrderRequest, *, idempotency_key: str) -> Order:
        data = await self._request(
            "POST",
            "/v2/checkout/orders",
            operation="orders.create",
            json_body=payloads.order_body(request),
            idempotency_key=idempotency_key,
        )
        return payloads.parse_order(data)

    async def get_order(self, order_id: str) -> Order:
        data = await self._request("GET", f"/v2/checkout/orders/{order_id}", operation="orders.get")
        return payloads.parse_order(data)

    async def authorize_order(self, order_id: str, *, idempotency_key: str) -> Order:
        data = await self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            operation="orders.authorize",
            idempotency_key=idempotency_key,
        )
        return payloads.parse_order(data)

    # -----------------------------------------------------------------------------------
    # Payments v2
    # -----------------------------------------------------------------------------------

    async def get_authorization(self, authorization_id: str) -> Authorization:
        data = await self._request(
            "GET",
            f"/v2/payments/authorizations/{authorization_id}",
            operation="authorizations.get",
        )
        return payloads.parse_authorization(data)

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
        data = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            operation="authorizations.capture",
            json_body=payloads.capture_body(amount, final_capture, invoice_id, note_to_payer),
            idempotency_key=idempotency_key,
        )
        return payloads.parse_capture(data)

    async def void_authorization(
        self, authorization_id: str, *, idempotency_key: str
    ) -> Authorization | None:
        data = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            operation="authorizations.void",
            idempotency_key=idempotency_key,
        )
        return payloads.parse_authorization(data) if data.get("id") else None

    async def reauthorize_authorization(
        self, authorization_id: str, *, amount: Money, idempotency_key: str
    ) -> Authorization:
        data = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/reauthorize",
            operation="authorizations.reauthorize",
            json_body={"amount": amount.to_paypal()},
            idempotency_key=idempotency_key,
        )
        return payloads.parse_authorization(data)

    async def get_capture(self, capture_id: str) -> Capture:
        data = await self._request(
            "GET", f"/v2/payments/captures/{capture_id}", operation="captures.get"
        )
        return payloads.parse_capture(data)

    async def refund_capture(
        self,
        capture_id: str,
        *,
        amount: Money | None,
        idempotency_key: str,
        note_to_payer: str | None = None,
    ) -> Refund:
        data = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            operation="captures.refund",
            json_body=payloads.refund_body(amount, note_to_payer),
            idempotency_key=idempotency_key,
        )
        return payloads.parse_refund(data)

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
        if not items:
            raise ValueError("A payout batch needs at least one item")
        data = await self._request(
            "POST",
            "/v1/payments/payouts",
            operation="payouts.create",
            json_body=payloads.payout_body(sender_batch_id, items, email_subject, email_message),
            idempotency_key=idempotency_key,
            prefer_representation=False,
        )
        return payloads.parse_payout_batch(data)

    async def get_payout(self, batch_id: str) -> PayoutBatch:
        data = await self._request(
            "GET",
            f"/v1/payments/payouts/{batch_id}",
            operation="payouts.get",
            prefer_representation=False,
        )
        return payloads.parse_payout_batch(data)

    # -----------------------------------------------------------------------------------
    # Invoicing v2
    # -----------------------------------------------------------------------------------

    async def create_invoice(self, draft: InvoiceDraft, *, idempotency_key: str) -> Invoice:
        data = await self._request(
            "POST",
            "/v2/invoicing/invoices",
            operation="invoices.create",
            json_body=payloads.invoice_body(draft),
            idempotency_key=idempotency_key,
        )
        if data.get("id"):
            return payloads.parse_invoice(data)
        invoice_id = payloads.invoice_id_from_link(data)
        if not invoice_id:
            raise PayPalError("Invoice created but PayPal returned no ID", raw=data)
        return await self.get_invoice(invoice_id)

    async def send_invoice(
        self,
        invoice_id: str,
        *,
        idempotency_key: str,
        subject: str | None = None,
        note: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"send_to_recipient": True, "send_to_invoicer": False}
        if subject:
            body["subject"] = subject
        if note:
            body["note"] = note
        await self._request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            operation="invoices.send",
            json_body=body,
            idempotency_key=idempotency_key,
            prefer_representation=False,
        )

    async def get_invoice(self, invoice_id: str) -> Invoice:
        data = await self._request(
            "GET", f"/v2/invoicing/invoices/{invoice_id}", operation="invoices.get"
        )
        return payloads.parse_invoice(data)

    async def cancel_invoice(
        self, invoice_id: str, *, idempotency_key: str, note: str | None = None
    ) -> None:
        """POST /v2/invoicing/invoices/{id}/cancel (a sent invoice is withdrawn)."""
        body: dict[str, Any] = {"send_to_recipient": True, "send_to_invoicer": False}
        if note:
            body["note"] = note
        await self._request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/cancel",
            operation="invoices.cancel",
            json_body=body,
            idempotency_key=idempotency_key,
            prefer_representation=False,
        )

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
        data = await self._request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/payments",
            operation="invoices.payments",
            json_body=payloads.invoice_payment_body(amount, payment_date, method, note),
            idempotency_key=idempotency_key,
            prefer_representation=False,
        )
        return str(data.get("payment_id", ""))

    # -----------------------------------------------------------------------------------
    # Webhooks v1
    # -----------------------------------------------------------------------------------

    async def verify_webhook_signature(
        self, *, headers: WebhookHeaders, raw_body: bytes, webhook_id: str
    ) -> bool:
        data = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            operation="webhooks.verify",
            content=payloads.verify_webhook_body(headers, raw_body, webhook_id),
            prefer_representation=False,
            safe_to_retry=True,
        )
        return data.get("verification_status") == "SUCCESS"


def _json_or_none(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(float(value), 30.0)
    except ValueError:
        return None
