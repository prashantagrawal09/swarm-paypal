"""Money engine: the only code that moves money.

Agents and features ask the engine; the engine applies the rules, talks to PayPal through
the gateway that matches each account's mode (REAL sandbox or SIMULATED), records every
call in `payments`, writes balanced ledger entries and advances the state machines.

Crash safety and idempotency. Every PayPal mutation follows the same steps:
1. Derive a stable idempotency key from the business object (for example
   `capture:<shop order>:<authorization>`).
2. If a COMPLETED payment with that key exists, the step already happened: do nothing.
3. Otherwise write the payment as PENDING and commit, *then* call PayPal with the key as
   `PayPal-Request-Id`.
4. Commit the result, the state change and the ledger entries together.

A crash between steps 3 and 4 leaves a PENDING row; re-running the step sends the same
request ID, PayPal returns the original result, and nothing is charged twice.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import Clock, week_start
from app.db.enums import (
    ApprovalKind,
    ApprovalStatus,
    GroupOrderStatus,
    PaymentKind,
    PaymentStatus,
    PayPalModeEnum,
    ShopOrderStatus,
    SwapStatus,
)
from app.db.models import (
    ApprovalRequest,
    GroupOrder,
    GroupOrderLine,
    Payment,
    Shop,
    ShopOrder,
    SwapOffer,
)
from app.events import EventSink, NullEventSink
from app.money import ledger, pricing, rules
from app.money.amount import Money
from app.money.states import (
    COMMITTED_SHOP_ORDER_STATUSES,
    advance_group_order,
    advance_shop_order,
)
from app.paypal.accounts import GatewayRegistry
from app.paypal.errors import PayPalError
from app.paypal.interface import (
    Authorization,
    CreateOrderRequest,
    PayoutItemRequest,
    PayPalGateway,
)
from app.paypal.simulated import SimulatedPayPalClient

logger = logging.getLogger(__name__)

T = TypeVar("T")

SIM_EMAIL_DOMAIN = "sim.swarm.example"


class NeedsOwnerApproval(rules.RuleViolation):
    def __init__(self, approval_id: uuid.UUID, message: str) -> None:
        super().__init__("NEEDS_OWNER_APPROVAL", message)
        self.approval_id = approval_id


@dataclass
class StepOutcome:
    shop_order_id: uuid.UUID
    shop_code: str
    status: str
    amount_cents: int = 0
    detail: str = ""


@dataclass
class BatchResult:
    outcomes: list[StepOutcome] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


class MoneyEngine:
    def __init__(
        self,
        session: AsyncSession,
        gateways: GatewayRegistry,
        clock: Clock,
        events: EventSink | None = None,
    ) -> None:
        self.session = session
        self.gateways = gateways
        self.clock = clock
        self.events = events or NullEventSink()

    # ===================================================================================
    # Plumbing
    # ===================================================================================

    def _gateway(self, mode: PayPalModeEnum) -> PayPalGateway:
        return self.gateways.platform(mode.value)

    async def _payment_step(
        self,
        *,
        kind: PaymentKind,
        key: str,
        related_type: str,
        related_id: uuid.UUID,
        amount_cents: int,
        currency: str,
        mode: PayPalModeEnum,
        call: Callable[[], Awaitable[T]],
        account: str = "platform",
    ) -> tuple[Payment, T | None]:
        """Run one PayPal mutation with crash-safe idempotency (see module docstring).

        Returns the payment row and PayPal's result, or `None` as the result when the step
        had already completed earlier.
        """
        payment = await self.session.scalar(select(Payment).where(Payment.idempotency_key == key))
        if payment is not None and payment.status == PaymentStatus.COMPLETED:
            return payment, None
        if payment is None:
            payment = Payment(
                kind=kind,
                status=PaymentStatus.PENDING,
                paypal_mode=mode,
                account=account,
                related_type=related_type,
                related_id=related_id,
                amount_cents=amount_cents,
                currency=currency,
                idempotency_key=key,
                raw={},
            )
            self.session.add(payment)
            await self.session.commit()
        try:
            result = await call()
        except PayPalError as exc:
            payment.status = PaymentStatus.FAILED
            payment.error = str(exc)[:2000]
            payment.raw = {"error": exc.raw} if exc.raw is not None else {}
            await self.session.commit()
            raise
        payment.status = PaymentStatus.COMPLETED
        payment.paypal_id = _paypal_id(result)
        raw = getattr(result, "raw", None)
        payment.raw = raw if isinstance(raw, dict) else {}
        return payment, result

    async def _emit(self, kind: str, **payload: Any) -> None:
        await self.events.emit(kind, _jsonable(payload))

    async def _load_shop_order(self, shop_order_id: uuid.UUID) -> ShopOrder:
        shop_order = await self.session.scalar(
            select(ShopOrder)
            .where(ShopOrder.id == shop_order_id)
            .options(
                selectinload(ShopOrder.shop),
                selectinload(ShopOrder.lines).selectinload(GroupOrderLine.item),
                selectinload(ShopOrder.group_order).selectinload(GroupOrder.awarded_supplier),
            )
            .execution_options(populate_existing=True)
        )
        if shop_order is None:
            raise LookupError(f"Shop order {shop_order_id} not found")
        return shop_order

    async def _load_group_order(self, group_order_id: uuid.UUID) -> GroupOrder:
        group = await self.session.scalar(
            select(GroupOrder)
            .where(GroupOrder.id == group_order_id)
            .options(
                selectinload(GroupOrder.awarded_supplier),
                selectinload(GroupOrder.shop_orders).selectinload(ShopOrder.shop),
            )
            .execution_options(populate_existing=True)
        )
        if group is None:
            raise LookupError(f"Group order {group_order_id} not found")
        return group

    def _sim_ready(self, gateway: PayPalGateway, shop: Shop) -> None:
        if isinstance(gateway, SimulatedPayPalClient) and shop.vault_id:
            gateway.register_vault(shop.vault_id, shop.paypal_email or _sim_email(shop.code))

    # ===================================================================================
    # Spending limits
    # ===================================================================================

    async def committed_this_week(
        self, shop_id: uuid.UUID, week: Any, *, exclude_shop_order: uuid.UUID | None = None
    ) -> int:
        """What the shop has already committed for `week` (holds and net captures)."""
        rows = await self.session.execute(
            select(
                ShopOrder.status,
                ShopOrder.hold_amount_cents,
                ShopOrder.captured_amount_cents,
                ShopOrder.refunded_amount_cents,
                ShopOrder.id,
            )
            .join(GroupOrder, GroupOrder.id == ShopOrder.group_order_id)
            .where(ShopOrder.shop_id == shop_id, GroupOrder.week_start == week)
        )
        total = 0
        for status, hold, captured, refunded, shop_order_id in rows.all():
            if shop_order_id == exclude_shop_order or status not in COMMITTED_SHOP_ORDER_STATUSES:
                continue
            total += hold if status == ShopOrderStatus.AUTHORIZED else captured - refunded
        swaps = await self.session.scalars(
            select(SwapOffer).where(
                SwapOffer.to_shop_id == shop_id,
                SwapOffer.status.in_([SwapStatus.ACCEPTED, SwapStatus.PAID, SwapStatus.COMPLETED]),
            )
        )
        for swap in swaps:
            if week_start(swap.expires_at) == week:
                total += swap.price_cents
        return total

    async def _approved_extra(self, related_id: uuid.UUID) -> int:
        approval = await self.session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.related_id == related_id,
                ApprovalRequest.kind == ApprovalKind.OVER_LIMIT,
                ApprovalRequest.status == ApprovalStatus.APPROVED,
            )
            .order_by(ApprovalRequest.created_at.desc())
        )
        return int(approval.payload.get("over_by_cents", 0)) if approval else 0

    async def _ask_owner_over_limit(
        self, shop: Shop, related_id: uuid.UUID, check: rules.SpendCheck, what: str
    ) -> ApprovalRequest:
        existing = await self.session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.related_id == related_id,
                ApprovalRequest.kind == ApprovalKind.OVER_LIMIT,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        if existing:
            return existing
        over = Money(check.over_by_cents, shop.currency)
        limit = Money(check.limit_cents, shop.currency)
        approval = ApprovalRequest(
            shop_id=shop.id,
            kind=ApprovalKind.OVER_LIMIT,
            related_id=related_id,
            question=(
                f"{what} would take you {over} over your weekly limit of {limit}. "
                "Approve this once?"
            ),
            payload={
                "limit_cents": check.limit_cents,
                "committed_cents": check.committed_cents,
                "requested_cents": check.requested_cents,
                "over_by_cents": check.over_by_cents,
            },
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    # ===================================================================================
    # Holds (Wednesday)
    # ===================================================================================

    async def place_hold(self, shop_order_id: uuid.UUID) -> ShopOrder:
        """Authorize the shop's share of an awarded group order on its saved PayPal."""
        so = await self._load_shop_order(shop_order_id)
        if so.status == ShopOrderStatus.AUTHORIZED:
            return so
        if so.status == ShopOrderStatus.FAILED:
            so.status = advance_shop_order(so.status, ShopOrderStatus.PENDING)
        group, shop = so.group_order, so.shop
        if any(line.agreed_unit_price_cents is None for line in so.lines) or not so.lines:
            raise rules.RuleViolation("NOT_AWARDED", "Prices are not agreed for this order yet")

        hold = pricing.order_amount(
            [(line.qty_requested, line.agreed_unit_price_cents or 0) for line in so.lines],
            so.delivery_share_cents,
        )
        committed = await self.committed_this_week(
            shop.id, group.week_start, exclude_shop_order=so.id
        )
        check = rules.check_spend_limit(
            shop.weekly_spend_limit_cents, committed, hold, await self._approved_extra(so.id)
        )
        if not check.allowed:
            approval = await self._ask_owner_over_limit(
                shop, so.id, check, f"This week's {group.category.lower()} order"
            )
            so.failure_reason = approval.question
            so.hold_amount_cents = hold
            await self.session.commit()
            await self._emit(
                "approval_needed",
                shop=shop.code,
                shop_order_id=so.id,
                approval_id=approval.id,
                question=approval.question,
            )
            raise NeedsOwnerApproval(approval.id, approval.question)

        if not shop.vault_id:
            return await self._fail_hold(so, "PayPal is not connected for this shop yet")
        try:
            gateway = self._gateway(shop.paypal_mode)
        except PayPalError as exc:
            return await self._fail_hold(so, str(exc))
        self._sim_ready(gateway, shop)

        so.attempts += 1
        so.paypal_mode = shop.paypal_mode
        so.hold_amount_cents = hold
        key = f"hold:{so.id}:{so.attempts}"
        request = CreateOrderRequest(
            amount=Money(hold, group.currency),
            reference_id=f"so-{so.id.hex[:24]}",
            description=f"Swarm {group.category.lower()} order, week of {group.week_start}",
            custom_id=str(so.id),
            vault_id=shop.vault_id,
        )

        async def authorize() -> Authorization:
            return await _authorize_with_vault(gateway, request, key)

        try:
            payment, auth = await self._payment_step(
                kind=PaymentKind.AUTHORIZATION,
                key=key,
                related_type="shop_order",
                related_id=so.id,
                amount_cents=hold,
                currency=group.currency,
                mode=shop.paypal_mode,
                call=authorize,
            )
        except PayPalError as exc:
            return await self._fail_hold(so, _friendly(exc))

        now = self.clock.now()
        so.status = advance_shop_order(so.status, ShopOrderStatus.AUTHORIZED)
        so.authorization_id = auth.id if auth else payment.paypal_id
        so.authorized_at = so.original_authorized_at = now
        so.failure_reason = None
        await ledger.post(
            self.session,
            event="hold_placed",
            memo=f"Hold for {shop.name}, {group.category} week {group.week_start}",
            legs=ledger.hold_placed(shop.code, hold),
            currency=group.currency,
            booked_at=now,
            related_id=so.id,
        )
        await self.session.commit()
        await self._emit(
            "hold_placed",
            shop=shop.code,
            shop_order_id=so.id,
            amount_cents=hold,
            paypal_id=so.authorization_id,
            mode=shop.paypal_mode,
            category=group.category,
        )
        return so

    async def _fail_hold(self, so: ShopOrder, reason: str) -> ShopOrder:
        so.status = advance_shop_order(so.status, ShopOrderStatus.FAILED)
        so.failure_reason = reason
        await self.session.commit()
        await self._emit(
            "hold_failed",
            shop=so.shop.code,
            shop_order_id=so.id,
            reason=reason,
            mode=so.shop.paypal_mode,
        )
        return so

    async def place_holds(self, group_order_id: uuid.UUID) -> BatchResult:
        """Hold every shop's share. One shop failing never stops the others."""
        group = await self._load_group_order(group_order_id)
        result = BatchResult()
        for so in list(group.shop_orders):
            code = so.shop.code
            if so.status not in (ShopOrderStatus.PENDING, ShopOrderStatus.FAILED):
                continue
            try:
                done = await self.place_hold(so.id)
                result.outcomes.append(
                    StepOutcome(
                        so.id, code, done.status, done.hold_amount_cents, done.failure_reason or ""
                    )
                )
            except NeedsOwnerApproval as exc:
                result.outcomes.append(StepOutcome(so.id, code, "NEEDS_APPROVAL", 0, exc.message))
        group = await self._load_group_order(group_order_id)
        if group.status == GroupOrderStatus.AWARDED and any(
            so.status == ShopOrderStatus.AUTHORIZED for so in group.shop_orders
        ):
            group.status = advance_group_order(group.status, GroupOrderStatus.HELD)
            group.held_at = self.clock.now()
            await self.session.commit()
        return result

    # ===================================================================================
    # Captures (Thursday)
    # ===================================================================================

    async def capture_shop_order(self, shop_order_id: uuid.UUID) -> ShopOrder:
        """Charge for what actually arrived; the rest of the hold is released."""
        so = await self._load_shop_order(shop_order_id)
        if so.status != ShopOrderStatus.AUTHORIZED:
            return so
        group, shop = so.group_order, so.shop
        supplier = group.awarded_supplier
        if supplier is None:
            raise rules.RuleViolation("NOT_AWARDED", "Group order has no supplier")

        requested_grams = sum(line.qty_requested * line.item.unit_weight_grams for line in so.lines)
        delivered_grams = sum(_delivered(line) * line.item.unit_weight_grams for line in so.lines)
        share = pricing.delivered_share(so.delivery_share_cents, requested_grams, delivered_grams)
        amount = pricing.order_amount(
            [(_delivered(line), line.agreed_unit_price_cents or 0) for line in so.lines], share
        )
        rules.ensure_capture_within_hold(amount, so.hold_amount_cents)
        if amount == 0:
            return await self.void_shop_order(so.id, reason="Nothing was delivered")

        gateway = self._gateway(so.paypal_mode)
        self._sim_ready(gateway, shop)
        await self._refresh_hold_if_needed(so, gateway)
        auth_id = so.authorization_id
        assert auth_id is not None
        key = f"capture:{so.id}:{auth_id}"

        async def capture() -> Any:
            return await gateway.capture_authorization(
                auth_id,
                amount=Money(amount, group.currency),
                final_capture=True,
                idempotency_key=key,
                note_to_payer=f"Swarm {group.category.lower()} delivery, {group.week_start}",
            )

        try:
            payment, cap = await self._payment_step(
                kind=PaymentKind.CAPTURE,
                key=key,
                related_type="shop_order",
                related_id=so.id,
                amount_cents=amount,
                currency=group.currency,
                mode=so.paypal_mode,
                call=capture,
            )
        except PayPalError as exc:
            so.failure_reason = f"Capture failed: {_friendly(exc)}"
            await self.session.commit()
            await self._emit(
                "capture_failed", shop=shop.code, shop_order_id=so.id, reason=so.failure_reason
            )
            raise

        now = self.clock.now()
        so.status = advance_shop_order(so.status, ShopOrderStatus.CAPTURED)
        so.captured_amount_cents = amount
        so.capture_id = cap.id if cap else payment.paypal_id
        so.captured_at = now
        so.failure_reason = None
        memo = f"{shop.name} paid for {group.category} delivered by {supplier.name}"
        await ledger.post(
            self.session,
            event="hold_released",
            memo=f"Release hold for {shop.name}",
            legs=ledger.hold_released(shop.code, so.hold_amount_cents),
            currency=group.currency,
            booked_at=now,
            related_id=so.id,
        )
        await ledger.post(
            self.session,
            event="captured",
            memo=memo,
            legs=ledger.captured_for_supplier(shop.code, supplier.code, amount),
            currency=group.currency,
            booked_at=now,
            related_id=so.id,
        )
        await self.session.commit()
        partial = amount < so.hold_amount_cents
        await self._emit(
            "captured",
            shop=shop.code,
            shop_order_id=so.id,
            amount_cents=amount,
            hold_cents=so.hold_amount_cents,
            partial=partial,
            paypal_id=so.capture_id,
            mode=so.paypal_mode,
            category=group.category,
        )
        return so

    async def _refresh_hold_if_needed(self, so: ShopOrder, gateway: PayPalGateway) -> None:
        """Past the 3-day honor period: reauthorize (or re-hold after 29 days) first."""
        now = self.clock.now()
        assert so.authorized_at is not None and so.original_authorized_at is not None
        if not rules.needs_reauthorization(so.authorized_at, now):
            return
        old_id = so.authorization_id
        assert old_id is not None
        currency = so.group_order.currency
        if rules.can_reauthorize(so.original_authorized_at, now):
            key = f"reauth:{so.id}:{old_id}"

            async def reauthorize() -> Authorization:
                return await gateway.reauthorize_authorization(
                    old_id, amount=Money(so.hold_amount_cents, currency), idempotency_key=key
                )

            payment, auth = await self._payment_step(
                kind=PaymentKind.REAUTHORIZATION,
                key=key,
                related_type="shop_order",
                related_id=so.id,
                amount_cents=so.hold_amount_cents,
                currency=currency,
                mode=so.paypal_mode,
                call=reauthorize,
            )
            so.authorization_id = auth.id if auth else payment.paypal_id
        else:
            # Older than 29 days: the authorization is gone; place a fresh hold on the vault.
            if not so.shop.vault_id:
                raise rules.RuleViolation("HOLD_EXPIRED", "Hold expired and PayPal not connected")
            key = f"rehold:{so.id}:{old_id}"
            request = CreateOrderRequest(
                amount=Money(so.hold_amount_cents, currency),
                reference_id=f"so-{so.id.hex[:24]}",
                custom_id=str(so.id),
                vault_id=so.shop.vault_id,
            )

            async def rehold() -> Authorization:
                return await _authorize_with_vault(gateway, request, key)

            payment, auth = await self._payment_step(
                kind=PaymentKind.AUTHORIZATION,
                key=key,
                related_type="shop_order",
                related_id=so.id,
                amount_cents=so.hold_amount_cents,
                currency=currency,
                mode=so.paypal_mode,
                call=rehold,
            )
            so.authorization_id = auth.id if auth else payment.paypal_id
            so.original_authorized_at = now
        so.status = advance_shop_order(so.status, ShopOrderStatus.AUTHORIZED)
        so.authorized_at = now
        await self.session.commit()
        await self._emit(
            "hold_reauthorized",
            shop=so.shop.code,
            shop_order_id=so.id,
            amount_cents=so.hold_amount_cents,
            old_paypal_id=old_id,
            paypal_id=so.authorization_id,
            mode=so.paypal_mode,
        )

    async def capture_group_order(self, group_order_id: uuid.UUID) -> BatchResult:
        group = await self._load_group_order(group_order_id)
        result = BatchResult()
        for so in list(group.shop_orders):
            if so.status != ShopOrderStatus.AUTHORIZED:
                continue
            code = so.shop.code
            try:
                done = await self.capture_shop_order(so.id)
                result.outcomes.append(
                    StepOutcome(so.id, code, done.status, done.captured_amount_cents)
                )
            except (PayPalError, rules.RuleViolation) as exc:
                result.outcomes.append(StepOutcome(so.id, code, "CAPTURE_FAILED", 0, str(exc)))
        return result

    # ===================================================================================
    # Voids and cancellation
    # ===================================================================================

    async def void_shop_order(self, shop_order_id: uuid.UUID, *, reason: str) -> ShopOrder:
        so = await self._load_shop_order(shop_order_id)
        if so.status in (ShopOrderStatus.PENDING, ShopOrderStatus.FAILED):
            so.status = advance_shop_order(so.status, ShopOrderStatus.VOIDED)
            so.failure_reason = reason
            await self.session.commit()
            return so
        if so.status != ShopOrderStatus.AUTHORIZED:
            return so
        gateway = self._gateway(so.paypal_mode)
        auth_id = so.authorization_id
        assert auth_id is not None
        key = f"void:{auth_id}"

        async def void() -> Any:
            return await gateway.void_authorization(auth_id, idempotency_key=key)

        await self._payment_step(
            kind=PaymentKind.VOID,
            key=key,
            related_type="shop_order",
            related_id=so.id,
            amount_cents=so.hold_amount_cents,
            currency=so.group_order.currency,
            mode=so.paypal_mode,
            call=void,
        )
        now = self.clock.now()
        so.status = advance_shop_order(so.status, ShopOrderStatus.VOIDED)
        so.failure_reason = reason
        await ledger.post(
            self.session,
            event="hold_released",
            memo=f"Void hold for {so.shop.name}: {reason}",
            legs=ledger.hold_released(so.shop.code, so.hold_amount_cents),
            currency=so.group_order.currency,
            booked_at=now,
            related_id=so.id,
        )
        await self.session.commit()
        await self._emit(
            "hold_voided",
            shop=so.shop.code,
            shop_order_id=so.id,
            amount_cents=so.hold_amount_cents,
            paypal_id=auth_id,
            reason=reason,
            mode=so.paypal_mode,
        )
        return so

    async def cancel_group_order(self, group_order_id: uuid.UUID, *, reason: str) -> GroupOrder:
        """Cancel and release every hold."""
        group = await self._load_group_order(group_order_id)
        if group.status == GroupOrderStatus.CANCELLED:
            return group
        captured = [so for so in group.shop_orders if so.captured_amount_cents > 0]
        if captured:
            raise rules.RuleViolation("ALREADY_CAPTURED", "Money was already taken; refund instead")
        for so in list(group.shop_orders):
            await self.void_shop_order(so.id, reason=reason)
        group = await self._load_group_order(group_order_id)
        group.status = advance_group_order(group.status, GroupOrderStatus.CANCELLED)
        group.summary = {**group.summary, "cancel_reason": reason}
        await self.session.commit()
        await self._emit("group_order_cancelled", group_order_id=group.id, reason=reason)
        return group

    # ===================================================================================
    # Refunds (claims)
    # ===================================================================================

    async def refund_shop_order(
        self, shop_order_id: uuid.UUID, *, amount_cents: int, reason: str, refund_key: str
    ) -> Payment:
        """Refund part of what the shop paid. `refund_key` must be stable (for example the
        claim ID) so the same refund can never happen twice."""
        so = await self._load_shop_order(shop_order_id)
        supplier = so.group_order.awarded_supplier
        assert supplier is not None
        rules.ensure_refund_within_capture(
            amount_cents, so.captured_amount_cents, so.refunded_amount_cents
        )
        capture_id = so.capture_id
        assert capture_id is not None
        gateway = self._gateway(so.paypal_mode)
        currency = so.group_order.currency
        key = f"refund:{refund_key}"

        async def refund() -> Any:
            return await gateway.refund_capture(
                capture_id,
                amount=Money(amount_cents, currency),
                idempotency_key=key,
                note_to_payer=reason[:255],
            )

        payment, result = await self._payment_step(
            kind=PaymentKind.REFUND,
            key=key,
            related_type="shop_order",
            related_id=so.id,
            amount_cents=amount_cents,
            currency=currency,
            mode=so.paypal_mode,
            call=refund,
        )
        if result is None:
            return payment  # this refund already happened
        now = self.clock.now()
        so.refunded_amount_cents += amount_cents
        so.status = advance_shop_order(so.status, ShopOrderStatus.REFUNDED)
        await ledger.post(
            self.session,
            event="refunded",
            memo=f"Refund to {so.shop.name}: {reason}",
            legs=ledger.refunded_by_supplier(so.shop.code, supplier.code, amount_cents),
            currency=currency,
            booked_at=now,
            related_id=so.id,
        )
        await self.session.commit()
        await self._emit(
            "refunded",
            shop=so.shop.code,
            shop_order_id=so.id,
            amount_cents=amount_cents,
            paypal_id=payment.paypal_id,
            reason=reason,
            mode=so.paypal_mode,
        )
        return payment

    # ===================================================================================
    # Supplier payouts (settlement)
    # ===================================================================================

    async def supplier_amount_owed(self, group: GroupOrder) -> int:
        """Net captured for this group order minus what was already paid out (gross)."""
        captured = sum(
            so.captured_amount_cents - so.refunded_amount_cents for so in group.shop_orders
        )
        paid = sum(int(p.get("gross_cents", 0)) for p in group.summary.get("payouts", []))
        return captured - paid

    async def payout_supplier(
        self, group_order_id: uuid.UUID, *, withhold_cents: int = 0, reference: str = ""
    ) -> Payment | None:
        """Pay the supplier what it is owed for this group order, minus the platform fee.

        `withhold_cents` keeps money back while claims are open; a later call pays it.
        """
        group = await self._load_group_order(group_order_id)
        supplier = group.awarded_supplier
        if supplier is None:
            raise rules.RuleViolation("NOT_AWARDED", "Group order has no supplier")
        if group.status not in (GroupOrderStatus.DELIVERED, GroupOrderStatus.PARTIALLY_SETTLED):
            raise rules.RuleViolation("NOT_DELIVERED", f"Group order is {group.status}")
        owed = await self.supplier_amount_owed(group)
        gross = owed - withhold_cents
        if gross < 0:
            raise rules.RuleViolation("INVALID_WITHHOLD", "Cannot withhold more than is owed")
        sequence = len(group.summary.get("payouts", [])) + 1
        now = self.clock.now()
        payment: Payment | None = None
        if gross > 0:
            fee = pricing.platform_fee(gross, group.platform_fee_bps)
            net = gross - fee
            receiver = supplier.paypal_email or _sim_email(supplier.code)
            gateway = self._gateway(supplier.paypal_mode)
            key = f"payout:{group.id}:{sequence}"

            async def pay() -> Any:
                return await gateway.create_payout(
                    sender_batch_id=f"swarm-{group.id.hex}-{sequence}",
                    items=[
                        PayoutItemRequest(
                            receiver_email=receiver,
                            amount=Money(net, group.currency),
                            sender_item_id=f"go-{group.id.hex[:24]}-{sequence}",
                            note=f"Swarm {group.category.lower()} order, week of "
                            f"{group.week_start}. {reference}".strip(),
                        )
                    ],
                    idempotency_key=key,
                    email_subject=f"Swarm payout for week of {group.week_start}",
                )

            payment, _ = await self._payment_step(
                kind=PaymentKind.PAYOUT,
                key=key,
                related_type="group_order",
                related_id=group.id,
                amount_cents=net,
                currency=group.currency,
                mode=supplier.paypal_mode,
                call=pay,
            )
            await ledger.post(
                self.session,
                event="supplier_paid",
                memo=f"Payout to {supplier.name} ({group.category} {group.week_start})",
                legs=ledger.supplier_paid_out(supplier.code, gross, fee),
                currency=group.currency,
                booked_at=now,
                related_id=group.id,
            )
            payouts = [
                *group.summary.get("payouts", []),
                {
                    "sequence": sequence,
                    "gross_cents": gross,
                    "fee_cents": fee,
                    "net_cents": net,
                    "payment_id": str(payment.id),
                    "paypal_id": payment.paypal_id,
                },
            ]
            group.summary = {**group.summary, "payouts": payouts}

        for so in group.shop_orders:
            if so.status == ShopOrderStatus.CAPTURED:
                so.status = advance_shop_order(so.status, ShopOrderStatus.SETTLED)
        target = (
            GroupOrderStatus.PARTIALLY_SETTLED if withhold_cents > 0 else GroupOrderStatus.SETTLED
        )
        if group.status != target:
            group.status = advance_group_order(group.status, target)
        if target == GroupOrderStatus.SETTLED:
            group.settled_at = now
        await self.session.commit()
        if payment is not None:
            await self._emit(
                "supplier_paid",
                supplier=supplier.code,
                group_order_id=group.id,
                amount_cents=payment.amount_cents,
                gross_cents=gross,
                paypal_id=payment.paypal_id,
                mode=supplier.paypal_mode,
                withheld_cents=withhold_cents,
            )
        return payment

    # ===================================================================================
    # Shop-to-shop swaps (surplus and emergency)
    # ===================================================================================

    async def authorize_swap(self, swap_id: uuid.UUID) -> SwapOffer:
        """Hold the buyer's money for an accepted swap."""
        swap = await self.session.get(SwapOffer, swap_id, populate_existing=True)
        if swap is None or swap.to_shop_id is None:
            raise LookupError("Swap not found or has no buyer")
        if swap.authorization_id:
            return swap
        buyer = await self.session.get(Shop, swap.to_shop_id)
        assert buyer is not None
        week = week_start(swap.expires_at)
        committed = await self.committed_this_week(buyer.id, week)
        if swap.status == SwapStatus.ACCEPTED:
            committed -= swap.price_cents  # it already counts itself as accepted
        check = rules.check_spend_limit(
            buyer.weekly_spend_limit_cents,
            committed,
            swap.price_cents,
            await self._approved_extra(swap.id),
        )
        if not check.allowed:
            approval = await self._ask_owner_over_limit(buyer, swap.id, check, "This swap")
            await self.session.commit()
            raise NeedsOwnerApproval(approval.id, approval.question)
        if not buyer.vault_id:
            raise rules.RuleViolation("NOT_CONNECTED", "Buyer has not connected PayPal")
        gateway = self._gateway(buyer.paypal_mode)
        self._sim_ready(gateway, buyer)
        key = f"swap-hold:{swap.id}"
        request = CreateOrderRequest(
            amount=Money(swap.price_cents, swap.currency),
            reference_id=f"swap-{swap.id.hex[:24]}",
            description=f"Swarm {swap.kind.lower()} swap",
            custom_id=str(swap.id),
            vault_id=buyer.vault_id,
        )

        async def authorize() -> Authorization:
            return await _authorize_with_vault(gateway, request, key)

        payment, auth = await self._payment_step(
            kind=PaymentKind.AUTHORIZATION,
            key=key,
            related_type="swap",
            related_id=swap.id,
            amount_cents=swap.price_cents,
            currency=swap.currency,
            mode=buyer.paypal_mode,
            call=authorize,
        )
        swap.authorization_id = auth.id if auth else payment.paypal_id
        swap.details = {**swap.details, "buyer_mode": buyer.paypal_mode.value}
        await ledger.post(
            self.session,
            event="hold_placed",
            memo=f"Swap hold for {buyer.name}",
            legs=ledger.hold_placed(buyer.code, swap.price_cents),
            currency=swap.currency,
            booked_at=self.clock.now(),
            related_id=swap.id,
        )
        await self.session.commit()
        await self._emit(
            "hold_placed",
            shop=buyer.code,
            swap_id=swap.id,
            amount_cents=swap.price_cents,
            paypal_id=swap.authorization_id,
            mode=buyer.paypal_mode,
            category="SWAP",
        )
        return swap

    async def complete_swap(self, swap_id: uuid.UUID) -> SwapOffer:
        """Handover done: capture the buyer's hold and pay the seller (no platform fee)."""
        swap = await self.session.get(SwapOffer, swap_id, populate_existing=True)
        if swap is None or swap.to_shop_id is None or swap.authorization_id is None:
            raise LookupError("Swap not found or not authorized")
        if swap.status == SwapStatus.COMPLETED:
            return swap
        buyer = await self.session.get(Shop, swap.to_shop_id)
        seller = await self.session.get(Shop, swap.from_shop_id)
        assert buyer is not None and seller is not None
        now = self.clock.now()
        auth_id = swap.authorization_id
        charge_key = f"swap-capture:{swap.id}"
        buyer_gateway = self._gateway(buyer.paypal_mode)

        async def capture() -> Any:
            return await buyer_gateway.capture_authorization(
                auth_id,
                amount=Money(swap.price_cents, swap.currency),
                final_capture=True,
                idempotency_key=charge_key,
                note_to_payer="Swarm neighbour swap",
            )

        charge, result = await self._payment_step(
            kind=PaymentKind.SWAP_PAYMENT,
            key=charge_key,
            related_type="swap",
            related_id=swap.id,
            amount_cents=swap.price_cents,
            currency=swap.currency,
            mode=buyer.paypal_mode,
            call=capture,
        )
        if result is not None:
            await ledger.post(
                self.session,
                event="hold_released",
                memo=f"Release swap hold for {buyer.name}",
                legs=ledger.hold_released(buyer.code, swap.price_cents),
                currency=swap.currency,
                booked_at=now,
                related_id=swap.id,
            )
            await ledger.post(
                self.session,
                event="swap_captured",
                memo=f"{buyer.name} paid for surplus from {seller.name}",
                legs=ledger.swap_captured(buyer.code, seller.code, swap.price_cents),
                currency=swap.currency,
                booked_at=now,
                related_id=swap.id,
            )
        swap.payment_id = charge.id
        swap.status = SwapStatus.PAID
        await self.session.commit()

        payout_key = f"swap-payout:{swap.id}"
        seller_gateway = self._gateway(seller.paypal_mode)
        receiver = seller.paypal_email or _sim_email(seller.code)

        async def pay_seller() -> Any:
            return await seller_gateway.create_payout(
                sender_batch_id=f"swarm-swap-{swap.id.hex}",
                items=[
                    PayoutItemRequest(
                        receiver_email=receiver,
                        amount=Money(swap.price_cents, swap.currency),
                        sender_item_id=f"swap-{swap.id.hex[:24]}",
                        note="Swarm neighbour swap",
                    )
                ],
                idempotency_key=payout_key,
                email_subject="Swarm: a neighbour bought your surplus",
            )

        payout, paid = await self._payment_step(
            kind=PaymentKind.PAYOUT,
            key=payout_key,
            related_type="swap",
            related_id=swap.id,
            amount_cents=swap.price_cents,
            currency=swap.currency,
            mode=seller.paypal_mode,
            call=pay_seller,
        )
        if paid is not None:
            await ledger.post(
                self.session,
                event="swap_paid",
                memo=f"Payout to {seller.name} for surplus",
                legs=ledger.swap_paid_out(seller.code, swap.price_cents),
                currency=swap.currency,
                booked_at=now,
                related_id=swap.id,
            )
        swap.payout_id = payout.id
        swap.status = SwapStatus.COMPLETED
        await self.session.commit()
        await self._emit(
            "swap_completed",
            buyer=buyer.code,
            seller=seller.code,
            swap_id=swap.id,
            amount_cents=swap.price_cents,
            capture_paypal_id=charge.paypal_id,
            payout_paypal_id=payout.paypal_id,
        )
        return swap

    # ===================================================================================
    # Read helpers
    # ===================================================================================

    async def outstanding_holds_cents(self) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(ShopOrder.hold_amount_cents), 0)).where(
                ShopOrder.status == ShopOrderStatus.AUTHORIZED
            )
        )
        swaps = await self.session.scalar(
            select(func.coalesce(func.sum(SwapOffer.price_cents), 0)).where(
                SwapOffer.authorization_id.is_not(None),
                SwapOffer.status.in_([SwapStatus.ACCEPTED]),
            )
        )
        return int(total or 0) + int(swaps or 0)


# ---------------------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------------------


async def _authorize_with_vault(
    gateway: PayPalGateway, request: CreateOrderRequest, key: str
) -> Authorization:
    """Create a buyer-not-present order on the saved wallet and return its authorization.

    PayPal usually completes vaulted orders immediately; if not, authorize explicitly.
    """
    order = await gateway.create_order(request, idempotency_key=key)
    if order.authorization is None:
        order = await gateway.authorize_order(order.id, idempotency_key=f"{key}:authorize")
    if order.authorization is None:
        raise PayPalError(f"Order {order.id} ({order.status}) returned no authorization")
    return order.authorization


def _delivered(line: GroupOrderLine) -> int:
    return line.qty_requested if line.qty_delivered is None else line.qty_delivered


def _paypal_id(result: Any) -> str | None:
    for attribute in ("id", "batch_id"):
        value = getattr(result, attribute, None)
        if value:
            return str(value)
    return None


def _sim_email(code: str) -> str:
    return f"{code}@{SIM_EMAIL_DOMAIN}"


def _friendly(exc: PayPalError) -> str:
    if exc.issues:
        return f"PayPal said {', '.join(exc.issues)}"
    return exc.message


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value") and isinstance(getattr(value, "value", None), str):
        return value.value
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


__all__ = ["BatchResult", "MoneyEngine", "NeedsOwnerApproval", "StepOutcome"]
