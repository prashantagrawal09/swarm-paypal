"""Invoice checker (F3): every supplier invoice is checked line by line before anyone pays.

1. After delivery the winning supplier's agent issues a PayPal invoice to the Swarm platform
   (through the PayPal Agent Toolkit for REAL suppliers, the simulator otherwise).
2. Code compares every line with what was agreed and what actually arrived: unit price,
   quantity, missing or extra lines, the delivery charge and the total.
3. Any mismatch rejects the invoice with a plain report ("Charged S$2.30/L, agreed S$2.05/L,
   290 L, overcharge S$72.50"); the supplier cancels it and issues a corrected revision.
4. An approved invoice is paid by PayPal Payout (minus the platform fee and anything held
   back for open claims), and the payment is recorded on the PayPal invoice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db.enums import (
    ClaimDecision,
    GroupOrderStatus,
    InvoiceCheckStatus,
    PayPalModeEnum,
    ShopOrderStatus,
)
from app.db.models import Claim, GroupOrder, Invoice, Payment, ShopOrder, Supplier
from app.features import group_buy
from app.features.context import Ctx
from app.features.products import wording
from app.money.amount import Money
from app.paypal.accounts import credentials_for_prefix
from app.paypal.client import PayPalClient
from app.paypal.errors import PayPalUnprocessableError
from app.paypal.interface import Invoice as PayPalInvoice
from app.paypal.interface import InvoiceDraft, InvoiceLine, InvoicePaymentMethod, PayPalGateway
from app.paypal.toolkit import TOOLKIT_AVAILABLE, AgentToolkit

DELIVERY_LINE = "Delivery to Tiong Bahru (shared drop)"
BILLED_STATUSES = (ShopOrderStatus.CAPTURED, ShopOrderStatus.SETTLED, ShopOrderStatus.REFUNDED)
OPEN_CLAIMS = (
    ClaimDecision.PENDING,
    ClaimDecision.ESCALATED_SUPPLIER,
    ClaimDecision.ESCALATED_OPERATOR,
)


# ---------------------------------------------------------------------------------------
# What the invoice should say
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedLine:
    product: str
    sku: str
    name: str
    qty: int
    unit_price_cents: int

    @property
    def total_cents(self) -> int:
        return self.qty * self.unit_price_cents


@dataclass
class Expected:
    lines: dict[str, ExpectedLine]
    delivery_cents: int

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines.values()) + self.delivery_cents


def expected_invoice(group: GroupOrder) -> Expected:
    """Agreed prices x delivered quantities, plus the delivery shares actually charged."""
    lines: dict[str, ExpectedLine] = {}
    items_charged = 0
    captured = 0
    for so in group.shop_orders:
        if so.status not in BILLED_STATUSES:
            continue
        captured += so.captured_amount_cents
        for line in so.lines:
            qty = line.qty_delivered or 0
            price = line.agreed_unit_price_cents or 0
            items_charged += qty * price
            product = line.item.product_code
            previous = lines.get(product)
            lines[product] = ExpectedLine(
                product,
                line.item.sku,
                f"{line.item.name} ({line.item.brand})",
                (previous.qty if previous else 0) + qty,
                price,
            )
    return Expected({p: line for p, line in lines.items() if line.qty}, captured - items_charged)


# ---------------------------------------------------------------------------------------
# The check (pure)
# ---------------------------------------------------------------------------------------


@dataclass
class CheckReport:
    approved: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    expected_total_cents: int = 0
    invoiced_total_cents: int = 0

    @property
    def overcharge_cents(self) -> int:
        return self.invoiced_total_cents - self.expected_total_cents

    def summary(self) -> str:
        if self.approved:
            return f"Matches the award and the delivery: {Money(self.expected_total_cents)}."
        return " ".join(issue["text"] for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "issues": self.issues,
            "expected_total_cents": self.expected_total_cents,
            "invoiced_total_cents": self.invoiced_total_cents,
            "overcharge_cents": self.overcharge_cents,
            "summary": self.summary(),
        }


def check(
    expected: Expected, invoice_lines: list[dict[str, Any]], invoiced_total: int
) -> CheckReport:
    report = CheckReport(
        True, expected_total_cents=expected.total_cents, invoiced_total_cents=invoiced_total
    )
    seen: set[str] = set()
    delivery_billed = 0
    for line in invoice_lines:
        if line.get("product") == "delivery":
            delivery_billed += line["total_cents"]
            continue
        product = line.get("product", "")
        want = expected.lines.get(product)
        if want is None:
            report.issues.append(
                {
                    "kind": "unexpected_line",
                    "product": product,
                    "text": f"{line['name']} was not part of this order.",
                }
            )
            continue
        seen.add(product)
        w = wording(product)
        if line["unit_price_cents"] != want.unit_price_cents:
            over = (line["unit_price_cents"] - want.unit_price_cents) * line["qty"]
            report.issues.append(
                {
                    "kind": "price",
                    "product": product,
                    "charged_cents": line["unit_price_cents"],
                    "agreed_cents": want.unit_price_cents,
                    "qty": line["qty"],
                    "difference_cents": over,
                    "text": (
                        f"{w.name.capitalize()}: charged "
                        f"{Money(line['unit_price_cents'])}/{w.unit}, "
                        f"agreed {Money(want.unit_price_cents)}/{w.unit}, "
                        f"{line['qty']} {w.units if line['qty'] != 1 else w.unit}, "
                        f"{'overcharge' if over > 0 else 'undercharge'} {Money(abs(over))}."
                    ),
                }
            )
        if line["qty"] != want.qty:
            report.issues.append(
                {
                    "kind": "quantity",
                    "product": product,
                    "billed": line["qty"],
                    "delivered": want.qty,
                    "text": f"{w.name.capitalize()}: billed {line['qty']}, {want.qty} delivered.",
                }
            )
    for product, want in expected.lines.items():
        if product not in seen:
            report.issues.append(
                {
                    "kind": "missing_line",
                    "product": product,
                    "text": f"{want.name} is missing from the invoice.",
                }
            )
    if delivery_billed != expected.delivery_cents:
        report.issues.append(
            {
                "kind": "delivery",
                "billed_cents": delivery_billed,
                "expected_cents": expected.delivery_cents,
                "text": (
                    f"Delivery billed {Money(delivery_billed)}, shops paid "
                    f"{Money(expected.delivery_cents)}."
                ),
            }
        )
    if invoiced_total != expected.total_cents and not report.issues:
        report.issues.append(
            {
                "kind": "total",
                "text": (
                    f"Total {Money(invoiced_total)} does not add up to "
                    f"{Money(expected.total_cents)}."
                ),
            }
        )
    report.approved = not report.issues
    return report


# ---------------------------------------------------------------------------------------
# Supplier billing: PayPal Agent Toolkit for REAL suppliers, the simulator otherwise
# ---------------------------------------------------------------------------------------


class SupplierBilling:
    def __init__(self, ctx: Ctx, supplier: Supplier) -> None:
        self.supplier = supplier
        self.toolkit: AgentToolkit | None = None
        self.gateway: PayPalGateway
        if supplier.paypal_mode == PayPalModeEnum.REAL:
            credentials = credentials_for_prefix(supplier.api_credentials_ref, supplier.code)
            self.gateway = ctx.runtime.registry.gateway(
                supplier.api_credentials_ref, "REAL", supplier.code
            )
            if TOOLKIT_AVAILABLE and credentials is not None:
                self.toolkit = AgentToolkit(credentials)
        else:
            self.gateway = ctx.runtime.registry.gateway(
                supplier.api_credentials_ref, "SIMULATED", supplier.code
            )

    @property
    def via(self) -> str:
        if self.toolkit:
            return "paypal-agent-toolkit"
        return "paypal-rest" if isinstance(self.gateway, PayPalClient) else "simulated"

    async def issue(self, draft: InvoiceDraft, key: str) -> PayPalInvoice:
        if self.toolkit:
            invoice_id = await self.toolkit.create_invoice(draft)
            await self.toolkit.send_invoice(
                invoice_id, note=draft.note or "Invoice from Swarm supplier"
            )
            return await self.toolkit.get_invoice(invoice_id)
        created = await self.gateway.create_invoice(draft, idempotency_key=f"{key}:create")
        await self.gateway.send_invoice(created.id, idempotency_key=f"{key}:send", note=draft.note)
        return await self.gateway.get_invoice(created.id)

    async def cancel(self, invoice_id: str, key: str, note: str) -> None:
        if self.toolkit:
            await self.toolkit.cancel_invoice(invoice_id, note=note)
        else:
            await self.gateway.cancel_invoice(invoice_id, idempotency_key=key, note=note)

    async def record_payment(
        self, invoice_id: str, amount: Money, key: str, note: str, today: date
    ) -> str:
        methods: tuple[InvoicePaymentMethod, ...] = ("PAYPAL", "OTHER")
        for method in methods:
            try:
                if self.toolkit:
                    return await self.toolkit.record_payment(
                        invoice_id,
                        amount=amount,
                        payment_date=today,
                        method=method,
                        note=note,
                    )
                return await self.gateway.record_invoice_payment(
                    invoice_id,
                    amount=amount,
                    payment_date=today,
                    method=method,
                    idempotency_key=f"{key}:{method}",
                    note=note,
                )
            except PayPalUnprocessableError:
                if method == "OTHER":
                    raise
        raise AssertionError("unreachable")


# ---------------------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------------------


def invoice_number(group: GroupOrder, revision: int) -> str:
    year, week, _ = group.week_start.isocalendar()
    return f"SW{year % 100:02d}W{week:02d}-{group.category.value[:3]}-R{revision}"


async def _group(ctx: Ctx, group_id: uuid.UUID) -> GroupOrder:
    return await group_buy.load_group(ctx.session, group_id)


async def issue(ctx: Ctx, group_id: uuid.UUID, *, markup: dict[str, int] | None = None) -> Invoice:
    """The supplier's agent bills the platform. `markup` (cents per unit, by product) is the
    demo's way to make a supplier overcharge."""
    group = await _group(ctx, group_id)
    supplier = group.awarded_supplier
    if supplier is None or group.status not in (
        GroupOrderStatus.DELIVERED,
        GroupOrderStatus.PARTIALLY_SETTLED,
    ):
        raise ValueError("Only delivered group orders are invoiced")
    expected = expected_invoice(group)
    revision = (
        int(
            await ctx.session.scalar(
                select(func.count()).select_from(Invoice).where(Invoice.group_order_id == group.id)
            )
            or 0
        )
        + 1
    )
    markup = markup or {}
    lines_json: list[dict[str, Any]] = []
    draft_lines: list[InvoiceLine] = []
    for product, line in expected.lines.items():
        price = line.unit_price_cents + markup.get(product, 0)
        lines_json.append(
            {
                "product": product,
                "sku": line.sku,
                "name": line.name,
                "qty": line.qty,
                "unit_price_cents": price,
                "total_cents": price * line.qty,
            }
        )
        draft_lines.append(
            InvoiceLine(
                line.name, Decimal(line.qty), Money(price, group.currency), description=line.sku
            )
        )
    if expected.delivery_cents:
        lines_json.append(
            {
                "product": "delivery",
                "sku": "DELIVERY",
                "name": DELIVERY_LINE,
                "qty": 1,
                "unit_price_cents": expected.delivery_cents,
                "total_cents": expected.delivery_cents,
            }
        )
        draft_lines.append(
            InvoiceLine(DELIVERY_LINE, Decimal(1), Money(expected.delivery_cents, group.currency))
        )
    number = invoice_number(group, revision)
    settings = get_settings()
    billing = SupplierBilling(ctx, supplier)
    draft = InvoiceDraft(
        invoice_number=number,
        invoice_date=ctx.now().date(),
        currency=group.currency,
        recipient_email=settings.paypal_platform_email or "platform@sim.swarm.example",
        recipient_business_name="Swarm (Tiong Bahru group buying)",
        invoicer_business_name=supplier.name,
        invoicer_email=supplier.paypal_email
        if supplier.paypal_mode == PayPalModeEnum.REAL
        else None,
        reference=f"{group.category.title()} group order, week of {group.week_start}",
        note=f"{group.category.title()} for {len(group.shop_orders)} Tiong Bahru shops.",
        lines=draft_lines,
    )
    remote = await billing.issue(draft, key=f"invoice:{group.id}:{revision}")
    total = sum(line["total_cents"] for line in lines_json)
    invoice = Invoice(
        supplier_id=supplier.id,
        group_order_id=group.id,
        paypal_invoice_id=remote.id,
        invoice_number=number,
        revision=revision,
        line_items=lines_json,
        total_cents=total,
        check_status=InvoiceCheckStatus.PENDING,
        paypal_mode=supplier.paypal_mode,
        paypal_status=remote.status,
        issued_via=billing.via,
        check_report={},
    )
    ctx.session.add(invoice)
    await ctx.session.commit()
    await ctx.bus.emit(
        "invoice_sent",
        {
            "supplier": supplier.code,
            "invoice_number": number,
            "amount_cents": total,
            "paypal_id": remote.id,
            "mode": supplier.paypal_mode.value,
            "via": billing.via,
        },
    )
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"invoice:{group.id}",
        from_agent=f"supplier:{supplier.code}",
        to_agent="coordinator:swarm",
        type="INVOICE",
        text=f"Invoice {number} for {Money(total)} sent through PayPal.",
        payload={
            "invoice_id": str(invoice.id),
            "paypal_invoice_id": remote.id,
            "total_cents": total,
            "via": billing.via,
            "revision": revision,
        },
    )
    return invoice


async def review(ctx: Ctx, invoice_id: uuid.UUID) -> Invoice:
    invoice = await ctx.session.get(Invoice, invoice_id, populate_existing=True)
    if invoice is None:
        raise LookupError("Invoice not found")
    group = await _group(ctx, invoice.group_order_id)
    report = check(expected_invoice(group), invoice.line_items, invoice.total_cents)
    invoice.check_report = report.to_dict()
    invoice.check_status = (
        InvoiceCheckStatus.APPROVED if report.approved else InvoiceCheckStatus.REJECTED
    )
    await ctx.session.commit()
    supplier_agent = (
        f"supplier:{group.awarded_supplier.code}" if group.awarded_supplier else "supplier"
    )
    await ctx.bus.emit(
        "invoice_checked",
        {
            "supplier": group.awarded_supplier.code if group.awarded_supplier else None,
            "invoice_number": invoice.invoice_number,
            "amount_cents": invoice.total_cents,
            "approved": report.approved,
            "overcharge_cents": report.overcharge_cents,
            "paypal_id": invoice.paypal_invoice_id,
            "mode": invoice.paypal_mode.value,
        },
    )
    if report.approved:
        text = f"Invoice {invoice.invoice_number} checked: {report.summary()} Paying now."
        kind = "INVOICE_APPROVED"
    else:
        text = (
            f"Invoice {invoice.invoice_number} rejected. {report.summary()} "
            "Please cancel it and send a corrected invoice."
        )
        kind = "INVOICE_REJECTED"
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"invoice:{group.id}",
        from_agent="coordinator:swarm",
        to_agent=supplier_agent,
        type=kind,
        text=text,
        payload={"invoice_id": str(invoice.id), "report": report.to_dict()},
    )
    return invoice


async def reissue(ctx: Ctx, invoice_id: uuid.UUID) -> Invoice:
    """The supplier withdraws a rejected invoice and bills the correct amounts."""
    old = await ctx.session.get(Invoice, invoice_id)
    if old is None or old.check_status != InvoiceCheckStatus.REJECTED:
        raise ValueError("Only rejected invoices are reissued")
    supplier = await ctx.session.get(Supplier, old.supplier_id)
    assert supplier is not None
    billing = SupplierBilling(ctx, supplier)
    if old.paypal_invoice_id:
        await billing.cancel(
            old.paypal_invoice_id, f"invoice-cancel:{old.id}", "Replaced by a corrected invoice"
        )
    old.paypal_status = "CANCELLED"
    await ctx.session.commit()
    await ctx.bus.emit(
        "invoice_cancelled",
        {
            "supplier": supplier.code,
            "invoice_number": old.invoice_number,
            "amount_cents": old.total_cents,
            "paypal_id": old.paypal_invoice_id,
            "mode": old.paypal_mode.value,
        },
    )
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"invoice:{old.group_order_id}",
        from_agent=f"supplier:{supplier.code}",
        to_agent="coordinator:swarm",
        type="INVOICE_CANCELLED",
        text=f"Sorry about that. {old.invoice_number} is cancelled; corrected invoice coming.",
    )
    return await issue(ctx, old.group_order_id)


async def open_claims_cents(ctx: Ctx, group_id: uuid.UUID) -> int:
    total = await ctx.session.scalar(
        select(func.coalesce(func.sum(Claim.amount_cents), 0))
        .join(ShopOrder, ShopOrder.id == Claim.shop_order_id)
        .where(ShopOrder.group_order_id == group_id, Claim.decision.in_(OPEN_CLAIMS))
    )
    return int(total or 0)


async def settle(ctx: Ctx, invoice_id: uuid.UUID) -> Payment | None:
    """Pay an approved invoice by Payout and record the payment on the PayPal invoice."""
    invoice = await ctx.session.get(Invoice, invoice_id, populate_existing=True)
    if invoice is None or invoice.check_status != InvoiceCheckStatus.APPROVED:
        raise ValueError("Only approved invoices are paid")
    if invoice.paid_payment_id:
        return await ctx.session.get(Payment, invoice.paid_payment_id)
    withhold = await open_claims_cents(ctx, invoice.group_order_id)
    payment = await ctx.engine.payout_supplier(
        invoice.group_order_id,
        withhold_cents=withhold,
        reference=f"Invoice {invoice.invoice_number}.",
    )
    supplier = await ctx.session.get(Supplier, invoice.supplier_id)
    assert supplier is not None
    if payment is not None and invoice.paypal_invoice_id:
        billing = SupplierBilling(ctx, supplier)
        await billing.record_payment(
            invoice.paypal_invoice_id,
            Money(invoice.total_cents - withhold),
            key=f"invoice-paid:{invoice.id}",
            note=f"Paid by PayPal Payouts ({Money(payment.amount_cents)} after the Swarm fee).",
            today=ctx.now().date(),
        )
        invoice.paypal_status = "MARKED_AS_PAID" if not withhold else "PARTIALLY_PAID"
    invoice.paid_payment_id = payment.id if payment else None
    await ctx.session.commit()
    if payment is not None:
        await ctx.bus.publish(
            ctx.session,
            conversation_id=f"invoice:{invoice.group_order_id}",
            from_agent="coordinator:swarm",
            to_agent=f"supplier:{supplier.code}",
            type="PAID",
            text=(
                f"Paid {Money(payment.amount_cents)} by PayPal Payout for {invoice.invoice_number}"
                + (
                    f", holding {Money(withhold)} until open claims are settled."
                    if withhold
                    else "."
                )
            ),
            payload={
                "payment_id": str(payment.id),
                "paypal_id": payment.paypal_id,
                "withheld_cents": withhold,
            },
        )
        await ctx.bus.publish(
            ctx.session,
            conversation_id=f"invoice:{invoice.group_order_id}",
            from_agent=f"supplier:{supplier.code}",
            to_agent="coordinator:swarm",
            type="PAYMENT_RECORDED",
            text=(
                f"Thanks, received. {invoice.invoice_number} marked as paid."
                if not withhold
                else f"Thanks, received. {invoice.invoice_number} recorded as partly paid "
                "until the claim is settled."
            ),
        )
    return payment


async def release_withheld(
    ctx: Ctx, group_id: uuid.UUID, *, refunded_cents: int = 0
) -> Payment | None:
    """Once a claim is decided, settle up with the supplier for what was held back for it.

    A refunded claim leaves nothing more to pay (that money went back to the shop, and
    `refunded_cents` says how much); a rejected one frees the whole amount. Whatever is still
    under an open claim stays held.
    """
    group = await _group(ctx, group_id)
    if group.status != GroupOrderStatus.PARTIALLY_SETTLED:
        return None
    owed = await ctx.engine.supplier_amount_owed(group)
    if owed < 0:  # refunded more than was held back: nothing to release
        return None
    still_held = min(await open_claims_cents(ctx, group_id), owed)
    payment = await ctx.engine.payout_supplier(
        group_id, withhold_cents=still_held, reference="Held back for a claim, now released."
    )
    invoice = await ctx.session.scalar(
        select(Invoice)
        .where(Invoice.group_order_id == group_id, Invoice.paid_payment_id.is_not(None))
        .order_by(Invoice.revision.desc())
    )
    supplier = group.awarded_supplier
    if supplier is None:
        return payment
    if payment is None:
        if refunded_cents:
            await ctx.bus.publish(
                ctx.session,
                conversation_id=f"invoice:{group_id}",
                from_agent="coordinator:swarm",
                to_agent=f"supplier:{supplier.code}",
                type="CLAIM_UPHELD",
                text=(
                    f"The claim was upheld: the {Money(refunded_cents)} held back went to the "
                    "shop as a PayPal refund instead. Nothing more is owed on this order."
                ),
                payload={"refunded_cents": refunded_cents, "withheld_cents": still_held},
            )
        return None
    released = owed - still_held
    if invoice is not None and invoice.paypal_invoice_id:
        await SupplierBilling(ctx, supplier).record_payment(
            invoice.paypal_invoice_id,
            Money(released),
            key=f"invoice-paid:{invoice.id}:{payment.id}",
            note=f"Released after a claim was settled ({Money(payment.amount_cents)} after the "
            "Swarm fee).",
            today=ctx.now().date(),
        )
        if not still_held:
            invoice.paypal_status = "MARKED_AS_PAID"
        await ctx.session.commit()
    await ctx.bus.publish(
        ctx.session,
        conversation_id=f"invoice:{group_id}",
        from_agent="coordinator:swarm",
        to_agent=f"supplier:{supplier.code}",
        type="PAID",
        text=(
            f"The claim was not upheld, so the {Money(released)} held back is yours: paid "
            f"{Money(payment.amount_cents)} by PayPal Payout."
        ),
        payload={
            "payment_id": str(payment.id),
            "paypal_id": payment.paypal_id,
            "withheld_cents": still_held,
        },
    )
    return payment


async def run_cycle(
    ctx: Ctx, group_id: uuid.UUID, *, markup: dict[str, int] | None = None
) -> list[Invoice]:
    """Issue, check, (reject and reissue), and pay. Returns every invoice revision."""
    invoices = [await review(ctx, (await issue(ctx, group_id, markup=markup)).id)]
    if invoices[-1].check_status == InvoiceCheckStatus.REJECTED:
        corrected = await reissue(ctx, invoices[-1].id)
        invoices.append(await review(ctx, corrected.id))
    if invoices[-1].check_status == InvoiceCheckStatus.APPROVED:
        await settle(ctx, invoices[-1].id)
    return invoices
