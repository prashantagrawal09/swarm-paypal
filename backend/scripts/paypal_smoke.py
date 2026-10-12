"""PayPal sandbox smoke test: proves, step by step, every PayPal call Swarm depends on.

    python scripts/paypal_smoke.py              # real PayPal sandbox (credentials from .env)
    python scripts/paypal_smoke.py --simulated  # identical steps against the simulator

Steps: OAuth tokens, vault approval link (you approve in the browser once), authorize and
save PayPal, a hold without the buyer present, partial capture with final_capture, an
idempotent replay, void, reauthorize, partial refund, payout, invoice create/send/read/record
payment (through the PayPal Agent Toolkit) and webhook signature verification. It ends with
a PASS/FAIL table and writes a JSON report to backend/var/smoke-report.json.

The saved vault ID is kept in scripts/.smoke_state.json (git-ignored), so the browser
approval is only needed on the first run (or with --fresh-vault). The same file keeps one
hold aside so a run 3+ days later can prove a real reauthorization.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from app.clock import SwarmClock
from app.config import env_value, get_settings
from app.money.amount import Money
from app.paypal.accounts import (
    PLATFORM_PREFIX,
    credentials_for_prefix,
    missing_credential_keys,
)
from app.paypal.client import PayPalClient
from app.paypal.envfile import adopt_smoke_vault
from app.paypal.errors import PayPalError, PayPalUnprocessableError, PayPalValidationError
from app.paypal.interface import (
    Authorization,
    CreateOrderRequest,
    InvoiceDraft,
    InvoiceLine,
    Order,
    PayoutItemRequest,
    PayPalGateway,
    WebhookHeaders,
)
from app.paypal.simulated import SimulatedPayPalClient, SimulatedPayPalState
from app.paypal.toolkit import TOOLKIT_AVAILABLE, AgentToolkit
from app.paypal.webhooks import load_capture

BACKEND_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = BACKEND_DIR / "scripts" / ".smoke_state.json"
REPORT_PATH = BACKEND_DIR / "var" / "smoke-report.json"
HONOR_PERIOD = timedelta(days=3)
AUTH_VALIDITY = timedelta(days=29)
PAID_STATUSES = {"PAID", "MARKED_AS_PAID", "PAID_EXTERNAL"}

Status = Literal["PASS", "FAIL", "SKIP", "EXPECTED"]


class Skip(Exception):
    """Raised inside a step to mark it SKIP with a reason."""


class Expected(Exception):
    """Raised inside a step when PayPal rejected the call exactly as it should."""


@dataclass
class StepResult:
    number: int
    name: str
    status: Status
    detail: str
    ms: int


@dataclass
class SmokeConfig:
    simulated: bool
    platform_email: str | None
    payout_receiver: str | None
    webhook_id: str | None
    return_url: str
    cancel_url: str
    fresh_vault: bool = False
    approval_timeout: float = 600.0
    poll_interval: float = 3.0
    webhook_capture: Path | None = None
    currency: str = "SGD"


@dataclass
class SmokeContext:
    """Values handed from one step to the next."""

    run_id: str
    vault_id: str | None = None
    approval_order: Order | None = None
    first_hold: Authorization | None = None
    capture_hold: Authorization | None = None
    capture_id: str | None = None
    invoice_id: str | None = None
    invoice_total: Money | None = None
    ids: dict[str, str] = field(default_factory=dict)


class SmokeRun:
    def __init__(
        self,
        *,
        platform: PayPalGateway,
        supplier: PayPalGateway,
        toolkit: AgentToolkit | None,
        config: SmokeConfig,
        state: dict[str, Any],
        clock: SwarmClock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        out: Callable[[str], None] = print,
    ) -> None:
        self.platform = platform
        self.supplier = supplier
        self.toolkit = toolkit
        self.config = config
        self.state = state
        self.clock = clock
        self.sleep = sleep
        self.out = out
        self.results: list[StepResult] = []
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        self.ctx = SmokeContext(run_id=f"smoke-{stamp}-{secrets.token_hex(2)}")

    # -- plumbing -------------------------------------------------------------------------

    def key(self, name: str) -> str:
        return f"{self.ctx.run_id}-{name}"

    def money(self, cents: int) -> Money:
        return Money(cents, self.config.currency)

    def now(self) -> datetime:
        return self.clock.now() if self.clock else datetime.now(UTC)

    async def step(self, name: str, action: Callable[[], Awaitable[str]]) -> bool:
        number = len(self.results) + 1
        self.out(f"  [{number:>2}] {name} ...")
        started = time.monotonic()
        status: Status
        try:
            detail = await action()
            status = "PASS"
        except Skip as exc:
            status, detail = "SKIP", str(exc)
        except Expected as exc:
            status, detail = "EXPECTED", str(exc)
        except PayPalError as exc:
            status, detail = "FAIL", str(exc)
        except Exception as exc:
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        ms = int((time.monotonic() - started) * 1000)
        self.results.append(StepResult(number, name, status, detail, ms))
        self.out(f"       {status} {detail}")
        return status in ("PASS", "EXPECTED")

    def requires(self, value: object, what: str) -> None:
        if value is None:
            raise Skip(f"needs {what} from an earlier step")

    async def hold(self, cents: int, key: str) -> Authorization:
        """Place a hold on the saved PayPal wallet with the buyer not present."""
        self.requires(self.ctx.vault_id, "a saved vault ID")
        order = await self.platform.create_order(
            CreateOrderRequest(
                amount=self.money(cents),
                reference_id=key,
                description="Swarm smoke test hold",
                vault_id=self.ctx.vault_id,
            ),
            idempotency_key=self.key(f"{key}-order"),
        )
        if order.authorization is None:
            # PayPal may want an explicit authorize call for vaulted AUTHORIZE orders.
            order = await self.platform.authorize_order(
                order.id, idempotency_key=self.key(f"{key}-authorize")
            )
        if order.authorization is None:
            raise PayPalError(f"Order {order.id} ({order.status}) returned no authorization")
        self.ctx.ids[key] = order.authorization.id
        return order.authorization

    # -- steps ----------------------------------------------------------------------------

    async def oauth(self, gateway: PayPalGateway) -> str:
        if not isinstance(gateway, PayPalClient):
            return "simulated account, no OAuth needed"
        await gateway.access_token()
        await gateway.access_token()
        if gateway.token_requests != 1:
            raise PayPalError(f"Token was fetched {gateway.token_requests} times, expected 1")
        return f"token issued for {gateway.label}, cached (1 request for 2 uses)"

    async def vault_approval(self) -> str:
        saved = self.state.get("vault_id")
        if saved and not self.config.fresh_vault and not self.config.simulated:
            self.ctx.vault_id = saved
            raise Skip(f"reusing saved vault {saved} (run with --fresh-vault to approve again)")
        order = await self.platform.create_order(
            CreateOrderRequest(
                amount=self.money(1000),
                reference_id="smoke-connect",
                description="Swarm: connect your PayPal",
                save_payment_method=True,
                return_url=self.config.return_url,
                cancel_url=self.config.cancel_url,
            ),
            idempotency_key=self.key("connect-order"),
        )
        if not order.approve_url:
            raise PayPalError(f"Order {order.id} has no approval link (status {order.status})")
        self.ctx.approval_order = order
        if isinstance(self.platform, SimulatedPayPalClient):
            self.out(f"       approval link {order.approve_url} (simulated buyer approves)")
            self.platform.approve_order(order.id, "buyer@sim.swarm.example")
        else:
            self.out("")
            self.out("  " + "=" * 78)
            self.out("  ACTION NEEDED: open this link, log in as your SANDBOX PERSONAL (buyer)")
            self.out("  account, and approve. The script continues by itself once you approve.")
            self.out(f"  {order.approve_url}")
            self.out("  " + "=" * 78)
            self.out("")
        deadline = time.monotonic() + self.config.approval_timeout
        while True:
            current = await self.platform.get_order(order.id)
            if current.status in ("APPROVED", "COMPLETED"):
                return f"order {order.id} approved by buyer"
            if time.monotonic() > deadline:
                raise PayPalError(
                    f"Order {order.id} still {current.status} after "
                    f"{self.config.approval_timeout:.0f}s; approve the link and rerun"
                )
            await self.sleep(self.config.poll_interval)

    async def vault_authorize(self) -> str:
        if self.ctx.approval_order is None:
            if self.ctx.vault_id:
                raise Skip("vault already saved on an earlier run")
            raise Skip("needs the approved order from the previous step")
        order = await self.platform.authorize_order(
            self.ctx.approval_order.id, idempotency_key=self.key("connect-authorize")
        )
        if order.authorization is None:
            raise PayPalError(f"Authorize returned no authorization (status {order.status})")
        if order.vault is None or not order.vault.id:
            raise PayPalError(
                "Authorized, but PayPal returned no vault ID: enable Vault for the sandbox app "
                "(Apps & Credentials > app > Features > Accept payments > Advanced > Vault)"
            )
        self.ctx.vault_id = order.vault.id
        self.ctx.first_hold = order.authorization
        self.ctx.ids["vault"] = order.vault.id
        self.ctx.ids["connect_authorization"] = order.authorization.id
        if not self.config.simulated:
            self.state["vault_id"] = order.vault.id
            self.state["payer_email"] = order.payer_email
            self.state["vault_saved_at"] = self.now().isoformat()
        return (
            f"authorization {order.authorization.id} {order.authorization.amount}; "
            f"vault {order.vault.id} ({order.vault.status}) for {order.payer_email}"
        )

    async def hold_without_buyer(self) -> str:
        auth = await self.hold(2000, "hold")
        self.ctx.capture_hold = auth
        expires = f"{auth.expiration_time:%Y-%m-%d}" if auth.expiration_time else "?"
        return f"authorization {auth.id} {auth.amount} {auth.status}, expires {expires}"

    async def partial_capture(self) -> str:
        self.requires(self.ctx.capture_hold, "the hold")
        assert self.ctx.capture_hold is not None
        auth = self.ctx.capture_hold
        capture = await self.platform.capture_authorization(
            auth.id,
            amount=self.money(1500),
            final_capture=True,
            idempotency_key=self.key("capture"),
            invoice_id=self.key("capture"),
        )
        self.ctx.capture_id = capture.id
        self.ctx.ids["capture"] = capture.id
        after = await self.platform.get_authorization(auth.id)
        return (
            f"captured {capture.amount} of {auth.amount} (final_capture), capture {capture.id} "
            f"{capture.status}; authorization now {after.status}"
        )

    async def idempotent_replay(self) -> str:
        self.requires(self.ctx.capture_id, "the capture")
        assert self.ctx.capture_hold is not None
        replay = await self.platform.capture_authorization(
            self.ctx.capture_hold.id,
            amount=self.money(1500),
            final_capture=True,
            idempotency_key=self.key("capture"),
            invoice_id=self.key("capture"),
        )
        if replay.id != self.ctx.capture_id:
            raise PayPalError(f"Replay created a new capture {replay.id}: double charge!")
        return f"same PayPal-Request-Id returned the same capture {replay.id}, no double charge"

    async def void(self) -> str:
        auth = await self.hold(1200, "void-hold")
        voided = await self.platform.void_authorization(auth.id, idempotency_key=self.key("void"))
        status = (
            voided.status if voided else (await self.platform.get_authorization(auth.id)).status
        )
        if status != "VOIDED":
            raise PayPalError(f"Authorization {auth.id} is {status} after void")
        return f"authorization {auth.id} {auth.amount} -> VOIDED"

    async def reauthorize(self) -> str:
        if self.clock is not None:
            return await self._reauthorize_simulated()
        aged = self.state.get("aged_hold")
        if aged:
            created = datetime.fromisoformat(aged["created_at"])
            age = self.now() - created
            if age > AUTH_VALIDITY:
                self.state.pop("aged_hold", None)
                aged = None
            elif age >= HONOR_PERIOD:
                new_auth = await self.platform.reauthorize_authorization(
                    aged["authorization_id"],
                    amount=Money(aged["amount_cents"], self.config.currency),
                    idempotency_key=self.key("reauthorize-aged"),
                )
                await self.platform.void_authorization(
                    new_auth.id, idempotency_key=self.key("reauthorize-cleanup")
                )
                self.state.pop("aged_hold", None)
                self.ctx.ids["reauthorization"] = new_auth.id
                return (
                    f"hold {aged['authorization_id']} ({age.days} days old) reauthorized as "
                    f"{new_auth.id} {new_auth.amount}; then voided to clean up"
                )
        if aged:
            target_id = aged["authorization_id"]
            amount = Money(aged["amount_cents"], self.config.currency)
            ready = datetime.fromisoformat(aged["created_at"]) + HONOR_PERIOD
        else:
            auth = self.ctx.first_hold or await self.hold(500, "aged-hold")
            target_id, amount = auth.id, auth.amount
            created = auth.create_time or self.now()
            ready = created + HONOR_PERIOD
            self.state["aged_hold"] = {
                "authorization_id": auth.id,
                "amount_cents": auth.amount.cents,
                "created_at": created.isoformat(),
            }
        try:
            await self.platform.reauthorize_authorization(
                target_id, amount=amount, idempotency_key=self.key("reauthorize")
            )
        except PayPalUnprocessableError as exc:
            if exc.has_issue("REAUTHORIZATION_TOO_SOON"):
                raise Expected(
                    f"PayPal refused with REAUTHORIZATION_TOO_SOON (honor period). Hold "
                    f"{target_id} is saved; rerun after {ready:%Y-%m-%d %H:%M} UTC to "
                    f"reauthorize it for real"
                ) from exc
            raise
        return f"hold {target_id} reauthorized"

    async def _reauthorize_simulated(self) -> str:
        assert self.clock is not None
        auth = await self.hold(500, "aged-hold")
        try:
            await self.platform.reauthorize_authorization(
                auth.id, amount=auth.amount, idempotency_key=self.key("reauthorize-early")
            )
            raise PayPalError("Reauthorization inside the honor period should be refused")
        except PayPalUnprocessableError as exc:
            if not exc.has_issue("REAUTHORIZATION_TOO_SOON"):
                raise
        self.clock.advance(days=4)
        new_auth = await self.platform.reauthorize_authorization(
            auth.id, amount=auth.amount, idempotency_key=self.key("reauthorize")
        )
        self.ctx.ids["reauthorization"] = new_auth.id
        return (
            f"refused on day 0 (REAUTHORIZATION_TOO_SOON); after advancing the Swarm Clock 4 "
            f"days, {auth.id} reauthorized as {new_auth.id}"
        )

    async def refund(self) -> str:
        self.requires(self.ctx.capture_id, "the capture")
        assert self.ctx.capture_id is not None
        refund = await self.platform.refund_capture(
            self.ctx.capture_id,
            amount=self.money(500),
            idempotency_key=self.key("refund"),
            note_to_payer="Swarm smoke test partial refund",
        )
        self.ctx.ids["refund"] = refund.id
        capture = await self.platform.get_capture(self.ctx.capture_id)
        return f"refund {refund.id} {refund.status} S$5.00; capture now {capture.status}"

    async def payout(self) -> str:
        receiver = self.config.payout_receiver
        if not receiver:
            raise PayPalError("Set SMOKE_PAYOUT_RECEIVER or the supplier's _EMAIL in .env")
        batch = await self.platform.create_payout(
            sender_batch_id=self.key("payout"),
            items=[
                PayoutItemRequest(
                    receiver_email=receiver,
                    amount=self.money(300),
                    sender_item_id=self.key("payout-item"),
                    note="Swarm smoke test payout",
                )
            ],
            idempotency_key=self.key("payout"),
            email_subject="Swarm smoke test payout",
        )
        self.ctx.ids["payout_batch"] = batch.batch_id
        current = batch
        for _ in range(8):
            current = await self.platform.get_payout(batch.batch_id)
            if current.status in ("SUCCESS", "DENIED", "CANCELED"):
                break
            await self.sleep(self.config.poll_interval)
        if current.status in ("DENIED", "CANCELED"):
            raise PayPalError(f"Payout batch {batch.batch_id} ended {current.status}")
        item = current.items[0].transaction_status if current.items else "?"
        return f"batch {batch.batch_id} {current.status} (item {item}) S$3.00 -> {receiver}"

    def invoice_draft(self) -> InvoiceDraft:
        if not self.config.platform_email:
            raise PayPalError("Set PAYPAL_PLATFORM_EMAIL in .env (the invoice recipient)")
        return InvoiceDraft(
            invoice_number=f"SW-{self.ctx.run_id.upper()}"[:25],
            invoice_date=self.now().date(),
            currency=self.config.currency,
            recipient_email=self.config.platform_email,
            recipient_business_name="Swarm Platform",
            invoicer_business_name="FreshDairy SG",
            reference="Swarm smoke test",
            lines=[
                InvoiceLine("Full cream milk 1L", Decimal(3), self.money(205)),
                InvoiceLine("Eggs (tray of 30)", Decimal(1), self.money(890)),
            ],
        )

    async def invoice_create(self) -> str:
        draft = self.invoice_draft()
        self.ctx.invoice_total = draft.total
        if self.toolkit:
            invoice_id = await self.toolkit.create_invoice(draft)
            via = "Agent Toolkit create_invoice"
        else:
            invoice_id = (
                await self.supplier.create_invoice(draft, idempotency_key=self.key("invoice"))
            ).id
            via = "REST client" if not self.config.simulated else "simulated supplier"
        self.ctx.invoice_id = invoice_id
        self.ctx.ids["invoice"] = invoice_id
        return f"draft invoice {invoice_id} {draft.invoice_number} {draft.total} via {via}"

    async def invoice_send(self) -> str:
        self.requires(self.ctx.invoice_id, "the invoice")
        assert self.ctx.invoice_id is not None
        if self.toolkit:
            await self.toolkit.send_invoice(self.ctx.invoice_id, note="Swarm smoke test")
            via = "Agent Toolkit send_invoice"
        else:
            await self.supplier.send_invoice(
                self.ctx.invoice_id, idempotency_key=self.key("invoice-send")
            )
            via = "gateway"
        return f"invoice {self.ctx.invoice_id} sent to {self.config.platform_email} via {via}"

    async def invoice_read(self) -> str:
        self.requires(self.ctx.invoice_id, "the invoice")
        assert self.ctx.invoice_id is not None
        invoice = await self.supplier.get_invoice(self.ctx.invoice_id)
        if invoice.total != self.ctx.invoice_total:
            raise PayPalError(f"Invoice total {invoice.total} != {self.ctx.invoice_total}")
        lines = ", ".join(
            f"{line.quantity} x {line.name} @ {line.unit_amount}" for line in invoice.lines
        )
        return f"{invoice.status}, total {invoice.total}: {lines}"

    async def invoice_record_payment(self) -> str:
        self.requires(self.ctx.invoice_id, "the invoice")
        assert self.ctx.invoice_id is not None and self.ctx.invoice_total is not None
        method_used = "PAYPAL"
        for method in ("PAYPAL", "OTHER"):
            method_used = method
            try:
                if self.toolkit:
                    payment_id = await self.toolkit.record_payment(
                        self.ctx.invoice_id,
                        amount=self.ctx.invoice_total,
                        payment_date=self.now().date(),
                        method=method,
                        note="Paid by Swarm via PayPal Payouts (smoke test)",
                    )
                else:
                    payment_id = await self.supplier.record_invoice_payment(
                        self.ctx.invoice_id,
                        amount=self.ctx.invoice_total,
                        payment_date=self.now().date(),
                        method=method,
                        idempotency_key=self.key(f"invoice-pay-{method}"),
                        note="Paid by Swarm via PayPal Payouts (smoke test)",
                    )
                break
            except PayPalUnprocessableError:
                if method == "OTHER":
                    raise
        invoice = await self.supplier.get_invoice(self.ctx.invoice_id)
        if invoice.status not in PAID_STATUSES:
            raise PayPalError(f"Invoice is {invoice.status} after recording payment")
        return f"payment {payment_id} recorded (method {method_used}); invoice now {invoice.status}"

    async def webhook_forged(self) -> str:
        webhook_id = self.config.webhook_id
        if not webhook_id:
            raise Skip("set PAYPAL_WEBHOOK_ID (see docs/paypal-setup.md) to test verification")
        forged = WebhookHeaders(
            auth_algo="SHA256withRSA",
            cert_url="https://api.sandbox.paypal.com/v1/notifications/certs/CERT-360caa42-fca2a594-a5cafa77",
            transmission_id="00000000-0000-0000-0000-000000000000",
            transmission_sig="Zm9yZ2VkIHNpZ25hdHVyZQ==",
            transmission_time=self.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        raw = json.dumps({"id": "WH-FORGED", "event_type": "PAYMENT.CAPTURE.COMPLETED"}).encode()
        try:
            verified = await self.platform.verify_webhook_signature(
                headers=forged, raw_body=raw, webhook_id=webhook_id
            )
        except (PayPalValidationError, PayPalUnprocessableError) as exc:
            return f"forged delivery rejected by PayPal ({exc.name}, HTTP {exc.status_code})"
        if verified:
            raise PayPalError("A forged webhook was reported as verified!")
        return "forged delivery -> verification_status FAILURE (rejected)"

    async def webhook_genuine(self) -> str:
        webhook_id = self.config.webhook_id
        if isinstance(self.platform, SimulatedPayPalClient):
            raw = json.dumps({"id": "WH-SIM-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}).encode()
            headers = self.platform.sign_webhook(raw, webhook_id or "WH-SIM")
            ok = await self.platform.verify_webhook_signature(
                headers=headers, raw_body=raw, webhook_id=webhook_id or "WH-SIM"
            )
            if not ok:
                raise PayPalError("Simulated signed delivery failed verification")
            return "signed delivery -> verified"
        if not webhook_id:
            raise Skip("set PAYPAL_WEBHOOK_ID first")
        if not self.config.webhook_capture:
            raise Skip(
                "no captured delivery; run the backend behind a tunnel and pass "
                "--webhook-capture backend/var/webhooks/<event>.json (see docs/paypal-setup.md)"
            )
        headers, raw = load_capture(self.config.webhook_capture)
        if not await self.platform.verify_webhook_signature(
            headers=headers, raw_body=raw, webhook_id=webhook_id
        ):
            raise PayPalError("PayPal reported FAILURE for a captured delivery")
        return f"captured delivery {self.config.webhook_capture.name} -> SUCCESS"

    # -- orchestration --------------------------------------------------------------------

    async def run(self) -> list[StepResult]:
        await self.step("OAuth token + cache (platform)", lambda: self.oauth(self.platform))
        await self.step("OAuth token + cache (supplier)", lambda: self.oauth(self.supplier))
        await self.step("Vault: approval link, buyer approves", self.vault_approval)
        await self.step("Vault: authorize + save PayPal (vault ID)", self.vault_authorize)
        await self.step("Hold without buyer present (vault_id)", self.hold_without_buyer)
        await self.step("Partial capture S$15 of S$20 (final_capture)", self.partial_capture)
        await self.step("Idempotent replay of the capture", self.idempotent_replay)
        await self.step("Void a hold", self.void)
        await self.step("Reauthorize (honor period rules)", self.reauthorize)
        await self.step("Partial refund S$5", self.refund)
        await self.step("Payout S$3 (platform -> supplier)", self.payout)
        await self.step("Invoice create (supplier)", self.invoice_create)
        await self.step("Invoice send (supplier -> platform)", self.invoice_send)
        await self.step("Invoice read back, totals checked", self.invoice_read)
        await self.step("Invoice record payment", self.invoice_record_payment)
        await self.step("Webhook verify: forged delivery rejected", self.webhook_forged)
        await self.step("Webhook verify: genuine delivery accepted", self.webhook_genuine)
        return self.results


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def render_table(results: list[StepResult]) -> str:
    width = max(len(r.name) for r in results)
    lines = [f"{'#':>3}  {'Step':<{width}}  {'Result':<8}  {'Time':>7}", "-" * (width + 26)]
    for r in results:
        lines.append(f"{r.number:>3}  {r.name:<{width}}  {r.status:<8}  {r.ms:>5}ms")
    counts = {
        s: sum(1 for r in results if r.status == s) for s in ("PASS", "EXPECTED", "SKIP", "FAIL")
    }
    lines.append("-" * (width + 26))
    lines.append(
        f"PASS {counts['PASS']}  EXPECTED {counts['EXPECTED']}  SKIP {counts['SKIP']}  "
        f"FAIL {counts['FAIL']}"
    )
    return "\n".join(lines)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(BACKEND_DIR.parent))
    except ValueError:
        return str(path)


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        loaded: dict[str, Any] = json.loads(STATE_PATH.read_text())
        return loaded
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--simulated", action="store_true", help="use the simulated PayPal")
    parser.add_argument("--fresh-vault", action="store_true", help="approve a new vault")
    parser.add_argument("--approval-timeout", type=float, default=600.0)
    parser.add_argument("--webhook-capture", type=Path, help="captured webhook delivery JSON")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    supplier_prefix = env_value("SMOKE_SUPPLIER_PREFIX") or "PAYPAL_SUPPLIER_FRESHDAIRY"
    clock: SwarmClock | None = None
    toolkit: AgentToolkit | None = None
    platform: PayPalGateway
    supplier: PayPalGateway
    platform_email: str | None
    payout_receiver: str | None
    webhook_id: str | None

    if args.simulated:
        clock = SwarmClock(datetime.now(UTC))
        sim_state = SimulatedPayPalState()
        platform = SimulatedPayPalClient(
            "platform", state=sim_state, clock=clock, auto_approve=False
        )
        supplier = SimulatedPayPalClient("freshdairy", state=sim_state, clock=clock)
        platform_email = "platform@sim.swarm.example"
        payout_receiver = "freshdairy@sim.swarm.example"
        webhook_id = "WH-SIM"
        mode = "SIMULATED"
    else:
        if settings.paypal_env != "sandbox":
            print("Refusing to run: PAYPAL_ENV must be 'sandbox'.")
            return 2
        missing = missing_credential_keys(PLATFORM_PREFIX) + missing_credential_keys(
            supplier_prefix
        )
        if missing:
            print("Missing in .env: " + ", ".join(missing))
            print("Run `make paypal-setup` to add them (docs/paypal-setup.md shows where")
            print("each value is in the PayPal dashboard).")
            return 2
        platform_creds = credentials_for_prefix(PLATFORM_PREFIX, "platform")
        supplier_creds = credentials_for_prefix(supplier_prefix)
        assert platform_creds is not None and supplier_creds is not None
        platform = PayPalClient(platform_creds, base_url=settings.paypal_base_url)
        supplier = PayPalClient(supplier_creds, base_url=settings.paypal_base_url)
        if TOOLKIT_AVAILABLE:
            toolkit = AgentToolkit(supplier_creds)
        platform_email = settings.paypal_platform_email
        payout_receiver = env_value("SMOKE_PAYOUT_RECEIVER") or supplier_creds.email
        webhook_id = settings.paypal_webhook_id
        mode = "REAL sandbox"

    config = SmokeConfig(
        simulated=args.simulated,
        platform_email=platform_email,
        payout_receiver=payout_receiver,
        webhook_id=webhook_id,
        return_url=f"{settings.public_frontend_url}/connect/return",
        cancel_url=f"{settings.public_frontend_url}/connect/cancel",
        fresh_vault=args.fresh_vault,
        approval_timeout=args.approval_timeout,
        webhook_capture=args.webhook_capture,
        currency=settings.paypal_currency,
        poll_interval=0.0 if args.simulated else 3.0,
    )
    state = {} if args.simulated else load_state()
    print(f"\nSwarm PayPal smoke test ({mode}, {settings.paypal_currency})\n")
    run = SmokeRun(
        platform=platform,
        supplier=supplier,
        toolkit=toolkit,
        config=config,
        state=state,
        clock=clock,
    )
    try:
        results = await run.run()
    finally:
        await platform.aclose()
        await supplier.aclose()
        if not args.simulated:
            save_state(state)
            adopted = adopt_smoke_vault(state)
            if adopted:
                print(f"\nSaved the PayPal you approved to .env for {adopted}.")

    print("\n" + render_table(results))
    if run.ctx.ids:
        print("\nPayPal IDs (search these in the sandbox dashboard):")
        for name, value in run.ctx.ids.items():
            print(f"  {name:<22} {value}")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "mode": mode,
                "run_id": run.ctx.run_id,
                "finished_at": datetime.now(UTC).isoformat(),
                "results": [asdict(r) for r in results],
                "ids": run.ctx.ids,
            },
            indent=2,
        )
    )
    print(f"\nReport: {display_path(REPORT_PATH)}")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
