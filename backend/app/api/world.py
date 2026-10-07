"""Read API for the web app: overview, shops, suppliers, group orders, payments, ledger.

Supplier floor prices are never exposed, here or anywhere else in the API.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CtxDep
from app.clock import week_start
from app.db.enums import ApprovalStatus, PaymentKind
from app.db.models import (
    ApprovalRequest,
    Claim,
    FlashDeal,
    GroupOrder,
    GroupOrderLine,
    Invoice,
    Item,
    LedgerEntry,
    Payment,
    Quote,
    Shop,
    ShopOrder,
    Supplier,
    SupplierItem,
    SwapOffer,
    TelegramChat,
)
from app.demo import controls
from app.features import group_buy, savings
from app.features.context import Ctx
from app.features.invoice_checker import OPEN_CLAIMS
from app.features.products import wording
from app.money import ledger, pricing

router = APIRouter(prefix="/api", tags=["world"])


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _week(ctx: Ctx, week: date | None) -> date:
    return week or week_start(ctx.now())


async def _shop_or_404(ctx: Ctx, code: str) -> Shop:
    try:
        return await ctx.shop(code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _supplier_or_404(ctx: Ctx, code: str) -> Supplier:
    try:
        return await ctx.supplier(code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def shop_card(shop: Shop) -> dict[str, Any]:
    return {
        "code": shop.code,
        "name": shop.name,
        "owner": shop.owner_name,
        "kind": shop.opening_hours.get("kind", ""),
        "address": shop.address,
        "lat": shop.latitude,
        "lng": shop.longitude,
        "mode": shop.paypal_mode.value,
        "connected": bool(shop.vault_id),
        "limit_cents": shop.weekly_spend_limit_cents,
        "hours": {k: v for k, v in shop.opening_hours.items() if k != "kind"},
    }


def payment_row(
    payment: Payment, shops: dict[uuid.UUID, Shop], suppliers: dict[uuid.UUID, Supplier]
) -> dict[str, Any]:
    shop = shops.get(payment.shop_id) if payment.shop_id else None
    supplier = suppliers.get(payment.supplier_id) if payment.supplier_id else None
    return {
        "id": str(payment.id),
        "kind": payment.kind.value,
        "status": payment.status.value,
        "mode": payment.paypal_mode.value,
        "amount_cents": payment.amount_cents,
        "currency": payment.currency,
        "paypal_id": payment.paypal_id,
        "related_type": payment.related_type,
        "related_id": str(payment.related_id),
        "shop": {"code": shop.code, "name": shop.name} if shop else None,
        "supplier": {"code": supplier.code, "name": supplier.name} if supplier else None,
        "error": payment.error,
        "at": _iso(payment.created_at),
    }


async def _lookups(ctx: Ctx) -> tuple[dict[uuid.UUID, Shop], dict[uuid.UUID, Supplier]]:
    shops = {s.id: s for s in await ctx.session.scalars(select(Shop))}
    suppliers = {s.id: s for s in await ctx.session.scalars(select(Supplier))}
    return shops, suppliers


# ---------------------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------------------


@router.get("/overview")
async def overview(ctx: CtxDep) -> dict[str, Any]:
    """Everything the live board header needs in one call."""
    return {**await controls.state(ctx), "stats": await savings.platform_summary(ctx)}


# ---------------------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------------------


@router.get("/shops")
async def shops(ctx: CtxDep) -> list[dict[str, Any]]:
    week = _week(ctx, None)
    orders = await ctx.session.execute(
        select(ShopOrder.shop_id, GroupOrder.category, ShopOrder.status)
        .join(GroupOrder, GroupOrder.id == ShopOrder.group_order_id)
        .where(GroupOrder.week_start == week)
    )
    by_shop: dict[uuid.UUID, list[dict[str, str]]] = {}
    for shop_id, category, status in orders.all():
        by_shop.setdefault(shop_id, []).append({"category": category.value, "status": status.value})
    pending = dict(
        (
            await ctx.session.execute(
                select(ApprovalRequest.shop_id, func.count())
                .where(ApprovalRequest.status == ApprovalStatus.PENDING)
                .group_by(ApprovalRequest.shop_id)
            )
        ).all()
    )
    rows = []
    for shop in await ctx.session.scalars(select(Shop).order_by(Shop.name)):
        report = await savings.shop_week(ctx, shop, week)
        rows.append(
            {
                **shop_card(shop),
                "committed_cents": await ctx.engine.committed_this_week(shop.id, week),
                "saved_week_cents": report.total_saved_cents,
                "orders": by_shop.get(shop.id, []),
                "pending_approvals": pending.get(shop.id, 0),
            }
        )
    return rows


@router.get("/shops/{code}")
async def shop_detail(code: str, ctx: CtxDep) -> dict[str, Any]:
    shop = await _shop_or_404(ctx, code)
    week = _week(ctx, None)
    report = await savings.shop_week(ctx, shop, week)
    approvals = await ctx.session.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.shop_id == shop.id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(10)
    )
    linked = await ctx.session.scalar(
        select(func.count()).select_from(TelegramChat).where(TelegramChat.shop_id == shop.id)
    )
    prefs = shop.preferences or {}
    return {
        **shop_card(shop),
        "committed_cents": await ctx.engine.committed_this_week(shop.id, week),
        "report": report.to_dict(),
        "saved_to_date_cents": await savings.shop_to_date(ctx, shop),
        "usual_weekly": prefs.get("usual_weekly", {}),
        "accepted_brands": prefs.get("accepted_brands", {}),
        "allow_substitutes": prefs.get("allow_substitutes", True),
        "telegram_linked": bool(linked) or shop.telegram_chat_id is not None,
        "approvals": [
            {
                "id": str(a.id),
                "kind": a.kind.value,
                "status": a.status.value,
                "question": a.question,
                "at": _iso(a.created_at),
            }
            for a in approvals
        ],
    }


@router.get("/shops/{code}/orders")
async def shop_orders(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    shop = await _shop_or_404(ctx, code)
    rows = await ctx.session.execute(
        select(GroupOrderLine, ShopOrder, GroupOrder, Item)
        .join(ShopOrder, ShopOrder.id == GroupOrderLine.shop_order_id)
        .join(GroupOrder, GroupOrder.id == ShopOrder.group_order_id)
        .join(Item, Item.id == GroupOrderLine.item_id)
        .where(GroupOrderLine.shop_id == shop.id)
        .options(selectinload(GroupOrder.awarded_supplier))
        .order_by(GroupOrder.week_start.desc(), GroupOrder.category, Item.name)
    )
    result = []
    for line, so, group, item in rows.all():
        delivered = line.qty_delivered
        price = line.agreed_unit_price_cents
        result.append(
            {
                "id": str(line.id),
                "week": str(group.week_start),
                "category": group.category.value,
                "supplier": group.awarded_supplier.name if group.awarded_supplier else None,
                "item": item.name,
                "brand": item.brand,
                "product": item.product_code,
                "unit": wording(item.product_code).unit,
                "qty_requested": line.qty_requested,
                "qty_delivered": delivered,
                "unit_price_cents": price,
                "alone_unit_price_cents": line.alone_unit_price_cents,
                "line_total_cents": (price or 0)
                * (delivered if delivered is not None else line.qty_requested),
                "order_status": so.status.value,
                "group_status": group.status.value,
                "hold_cents": so.hold_amount_cents,
                "captured_cents": so.captured_amount_cents,
                "refunded_cents": so.refunded_amount_cents,
                "delivery_share_cents": so.delivery_share_cents,
                "shop_order_id": str(so.id),
            }
        )
    return result


@router.get("/shops/{code}/payments")
async def shop_payments(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    shop = await _shop_or_404(ctx, code)
    shops, suppliers = await _lookups(ctx)
    rows = await ctx.session.scalars(
        select(Payment).where(Payment.shop_id == shop.id).order_by(Payment.created_at.desc())
    )
    return [payment_row(p, shops, suppliers) for p in rows]


@router.get("/shops/{code}/claims")
async def shop_claims(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    shop = await _shop_or_404(ctx, code)
    return [
        claim_row(c)
        for c in await ctx.session.scalars(
            select(Claim).where(Claim.shop_id == shop.id).order_by(Claim.created_at.desc())
        )
    ]


def claim_row(claim: Claim) -> dict[str, Any]:
    return {
        "id": str(claim.id),
        "type": claim.type.value,
        "qty": claim.qty_affected,
        "amount_cents": claim.amount_cents,
        "decision": claim.decision.value,
        "description": claim.description,
        "photo_url": claim.photo_url,
        "assessment": claim.ai_assessment,
        "note": claim.resolution_note,
        "at": _iso(claim.created_at),
        "shop_id": str(claim.shop_id),
    }


@router.get("/shops/{code}/swaps")
async def shop_swaps(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    shop = await _shop_or_404(ctx, code)
    shops, _ = await _lookups(ctx)
    rows = await ctx.session.scalars(
        select(SwapOffer)
        .where((SwapOffer.from_shop_id == shop.id) | (SwapOffer.to_shop_id == shop.id))
        .order_by(SwapOffer.created_at.desc())
    )
    return [swap_row(s, shops, shop.id) for s in rows]


def swap_row(
    swap: SwapOffer, shops: dict[uuid.UUID, Shop], me: uuid.UUID | None = None
) -> dict[str, Any]:
    seller = shops.get(swap.from_shop_id) if swap.from_shop_id else None
    buyer = shops.get(swap.to_shop_id) if swap.to_shop_id else None
    product = swap.details.get("product", "")
    return {
        "id": str(swap.id),
        "kind": swap.kind.value,
        "status": swap.status.value,
        "role": None if me is None else ("seller" if swap.from_shop_id == me else "buyer"),
        "seller": {"code": seller.code, "name": seller.name} if seller else None,
        "buyer": {"code": buyer.code, "name": buyer.name} if buyer else None,
        "product": product,
        "product_name": wording(product).name if product else "",
        "unit": wording(product).unit if product else "",
        "qty": swap.qty,
        "price_cents": swap.price_cents,
        "food_saved_grams": swap.food_saved_grams,
        "discount_pct": swap.details.get("discount_pct"),
        "seconds_to_sorted": swap.details.get("seconds_to_sorted"),
        "at": _iso(swap.created_at),
    }


@router.get("/swaps")
async def swaps(ctx: CtxDep, limit: int = 20) -> list[dict[str, Any]]:
    shops, _ = await _lookups(ctx)
    rows = await ctx.session.scalars(
        select(SwapOffer).order_by(SwapOffer.created_at.desc()).limit(limit)
    )
    return [swap_row(s, shops) for s in rows]


@router.get("/shops/{code}/report")
async def shop_report(code: str, ctx: CtxDep, week: date | None = None) -> dict[str, Any]:
    shop = await _shop_or_404(ctx, code)
    report = await savings.shop_week(ctx, shop, _week(ctx, week))
    return {
        **report.to_dict(),
        "text": savings.report_text(report, await savings.shop_to_date(ctx, shop)),
    }


@router.get("/products")
async def products(ctx: CtxDep) -> list[dict[str, Any]]:
    """Every product (brand variants grouped) with its SKUs and who sells them."""
    rows = await ctx.session.execute(
        select(Item, Supplier.code)
        .join(SupplierItem, SupplierItem.item_id == Item.id)
        .join(Supplier, Supplier.id == SupplierItem.supplier_id)
        .order_by(Item.category, Item.product_code, Item.brand)
    )
    grouped: dict[str, dict[str, Any]] = {}
    for item, supplier_code in rows.all():
        w = wording(item.product_code)
        entry = grouped.setdefault(
            item.product_code,
            {
                "product": item.product_code,
                "name": w.name,
                "unit": w.unit,
                "units": w.units,
                "category": item.category.value,
                "skus": [],
            },
        )
        entry["skus"].append(
            {"sku": item.sku, "brand": item.brand, "name": item.name, "supplier": supplier_code}
        )
    return list(grouped.values())


# ---------------------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------------------


def supplier_card(supplier: Supplier) -> dict[str, Any]:
    return {
        "code": supplier.code,
        "name": supplier.name,
        "mode": supplier.paypal_mode.value,
        "reliability": supplier.reliability_score,
        "delivery_fee_cents": supplier.delivery_fee_cents,
        "delivery_days": supplier.delivery_days,
        "tagline": supplier.profile.get("tagline", ""),
        "style": supplier.profile.get("style", ""),
        "platform_fee_bps": supplier.platform_fee_bps,
    }


@router.get("/suppliers")
async def suppliers(ctx: CtxDep) -> list[dict[str, Any]]:
    rows = []
    for supplier in await ctx.session.scalars(select(Supplier).order_by(Supplier.name)):
        awards = await ctx.session.scalar(
            select(func.count())
            .select_from(GroupOrder)
            .where(GroupOrder.awarded_supplier_id == supplier.id)
        )
        paid = await ctx.session.scalar(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.supplier_id == supplier.id, Payment.kind == PaymentKind.PAYOUT
            )
        )
        rows.append(
            {
                **supplier_card(supplier),
                "awards": int(awards or 0),
                "paid_out_cents": int(paid or 0),
            }
        )
    return rows


@router.get("/suppliers/{code}")
async def supplier_detail(code: str, ctx: CtxDep) -> dict[str, Any]:
    supplier = await _supplier_or_404(ctx, code)
    items = await ctx.session.scalars(
        select(SupplierItem)
        .where(SupplierItem.supplier_id == supplier.id)
        .options(selectinload(SupplierItem.item))
    )
    catalog = [
        {
            "sku": si.item.sku,
            "product": si.item.product_code,
            "name": si.item.name,
            "brand": si.item.brand,
            "category": si.item.category.value,
            "unit": wording(si.item.product_code).unit,
            "tiers": [
                {"min_qty": t.min_qty, "unit_price_cents": t.unit_price_cents}
                for t in pricing.parse_tiers(si.price_tiers)
            ],
            "stock": si.stock_limit,
        }
        for si in items
    ]
    return {
        **supplier_card(supplier),
        "catalog": sorted(catalog, key=lambda c: (c["category"], c["name"])),
    }


@router.get("/suppliers/{code}/quotes")
async def supplier_quotes(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    supplier = await _supplier_or_404(ctx, code)
    rows = await ctx.session.execute(
        select(Quote, GroupOrder)
        .join(GroupOrder, GroupOrder.id == Quote.group_order_id)
        .where(Quote.supplier_id == supplier.id)
        .order_by(GroupOrder.week_start.desc(), GroupOrder.category, Quote.round)
    )
    return [
        {
            "id": str(q.id),
            "week": str(g.week_start),
            "category": g.category.value,
            "round": q.round,
            "items_total_cents": q.total_cents,
            "delivery_fee_cents": q.delivery_fee_cents,
            "landed_total_cents": q.total_cents + q.delivery_fee_cents,
            "status": q.status.value,
            "message": q.message,
            "unit_prices": q.line_prices,
            "group_order_id": str(g.id),
        }
        for q, g in rows.all()
    ]


def invoice_row(invoice: Invoice, supplier: Supplier | None = None) -> dict[str, Any]:
    return {
        "id": str(invoice.id),
        "number": invoice.invoice_number,
        "revision": invoice.revision,
        "paypal_invoice_id": invoice.paypal_invoice_id,
        "total_cents": invoice.total_cents,
        "check_status": invoice.check_status.value,
        "report": invoice.check_report,
        "lines": invoice.line_items,
        "paypal_status": invoice.paypal_status,
        "mode": invoice.paypal_mode.value,
        "issued_via": invoice.issued_via,
        "paid": invoice.paid_payment_id is not None,
        "group_order_id": str(invoice.group_order_id),
        "supplier": {"code": supplier.code, "name": supplier.name} if supplier else None,
        "at": _iso(invoice.created_at),
    }


@router.get("/suppliers/{code}/invoices")
async def supplier_invoices(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    supplier = await _supplier_or_404(ctx, code)
    rows = await ctx.session.scalars(
        select(Invoice)
        .where(Invoice.supplier_id == supplier.id)
        .order_by(Invoice.created_at.desc())
    )
    return [invoice_row(i, supplier) for i in rows]


@router.get("/invoices")
async def invoices(ctx: CtxDep, limit: int = 20) -> list[dict[str, Any]]:
    _, suppliers_by_id = await _lookups(ctx)
    rows = await ctx.session.scalars(
        select(Invoice).order_by(Invoice.created_at.desc()).limit(limit)
    )
    return [invoice_row(i, suppliers_by_id.get(i.supplier_id)) for i in rows]


@router.get("/suppliers/{code}/payouts")
async def supplier_payouts(code: str, ctx: CtxDep) -> list[dict[str, Any]]:
    supplier = await _supplier_or_404(ctx, code)
    shops, suppliers_by_id = await _lookups(ctx)
    rows = await ctx.session.scalars(
        select(Payment)
        .where(Payment.supplier_id == supplier.id)
        .order_by(Payment.created_at.desc())
    )
    return [payment_row(p, shops, suppliers_by_id) for p in rows]


# ---------------------------------------------------------------------------------------
# Group orders, payments, ledger, flash deals
# ---------------------------------------------------------------------------------------


async def _ladder(ctx: Ctx, group: GroupOrder, pooled: dict[str, int]) -> list[dict[str, Any]]:
    offers, _ = await group_buy.supplier_offers(ctx.session, list(pooled))
    offer = next(
        (o for o in offers if group.awarded_supplier_id == o.supplier.id),
        offers[0] if offers else None,
    )
    prices = group.summary.get("unit_prices", {})
    ladder = []
    for product, qty in pooled.items():
        tiers = offer.tiers(product) if offer else []
        w = wording(product)
        ladder.append(
            {
                "product": product,
                "name": w.name,
                "unit": w.unit,
                "units": w.units,
                "qty": qty,
                "tiers": [
                    {"min_qty": t.min_qty, "unit_price_cents": t.unit_price_cents} for t in tiers
                ],
                "tier_price_cents": pricing.tier_unit_price(tiers, qty) if tiers and qty else None,
                "single_price_cents": tiers[0].unit_price_cents if tiers else None,
                "agreed_cents": prices.get(product),
                "supplier": offer.supplier.code if offer else None,
            }
        )
    return ladder


async def group_row(ctx: Ctx, group: GroupOrder, detail: bool = False) -> dict[str, Any]:
    pooled = group_buy.pooled_quantities(group)
    savings_rows = group_buy.savings_for_group(group)
    quotes = await ctx.session.execute(
        select(Quote, Supplier)
        .join(Supplier, Supplier.id == Quote.supplier_id)
        .where(Quote.group_order_id == group.id)
        .order_by(Quote.round, Supplier.code)
    )
    row: dict[str, Any] = {
        "id": str(group.id),
        "week": str(group.week_start),
        "category": group.category.value,
        "status": group.status.value,
        "rounds": group.negotiation_rounds,
        "supplier": (
            {"code": group.awarded_supplier.code, "name": group.awarded_supplier.name}
            if group.awarded_supplier
            else None
        ),
        "shops": len(group.shop_orders),
        "pooled": pooled,
        "pooled_text": ", ".join(
            f"{q} {wording(p).units if q != 1 else wording(p).unit} {wording(p).name}"
            for p, q in pooled.items()
        ),
        "list_landed_cents": group.summary.get("list_price_landed_cents"),
        "opening_landed_cents": group.summary.get("opening_best_landed_cents"),
        "final_landed_cents": group.summary.get("final_landed_cents"),
        "alone_cents": sum(s.alone_cents for s in savings_rows),
        "paid_cents": sum(s.paid_cents for s in savings_rows),
        "saved_cents": sum(s.saved_cents for s in savings_rows),
        "excluded": group.summary.get("excluded", []),
        "conversation_id": group.summary.get("conversation_id"),
        "delivery_fee_cents": group.delivery_fee_cents,
        "quotes": [
            {
                "supplier": s.code,
                "supplier_name": s.name,
                "round": q.round,
                "landed_cents": q.total_cents + q.delivery_fee_cents,
                "status": q.status.value,
            }
            for q, s in quotes.all()
        ],
        "ladder": await _ladder(ctx, group, pooled),
        "payouts": group.summary.get("payouts", []),
    }
    if detail:
        row["shop_orders"] = [
            {
                "shop": {
                    "code": so.shop.code,
                    "name": so.shop.name,
                    "mode": so.shop.paypal_mode.value,
                },
                "status": so.status.value,
                "hold_cents": so.hold_amount_cents,
                "captured_cents": so.captured_amount_cents,
                "refunded_cents": so.refunded_amount_cents,
                "delivery_share_cents": so.delivery_share_cents,
                "authorization_id": so.authorization_id,
                "capture_id": so.capture_id,
                "failure_reason": so.failure_reason,
                "lines": [
                    {
                        "item": ln.item.name,
                        "brand": ln.item.brand,
                        "product": ln.item.product_code,
                        "qty_requested": ln.qty_requested,
                        "qty_delivered": ln.qty_delivered,
                        "unit_price_cents": ln.agreed_unit_price_cents,
                    }
                    for ln in so.lines
                ],
            }
            for so in group.shop_orders
        ]
        _, suppliers_by_id = await _lookups(ctx)
        row["invoices"] = [
            invoice_row(i, suppliers_by_id.get(i.supplier_id))
            for i in await ctx.session.scalars(
                select(Invoice).where(Invoice.group_order_id == group.id).order_by(Invoice.revision)
            )
        ]
    return row


@router.get("/group-orders")
async def group_orders(ctx: CtxDep, week: date | None = None) -> list[dict[str, Any]]:
    ids = await ctx.session.scalars(
        select(GroupOrder.id)
        .where(GroupOrder.week_start == _week(ctx, week))
        .order_by(GroupOrder.category)
    )
    return [await group_row(ctx, await group_buy.load_group(ctx.session, gid)) for gid in list(ids)]


@router.get("/group-orders/{group_id}")
async def group_order(group_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    try:
        group = await group_buy.load_group(ctx.session, group_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Group order not found") from exc
    return await group_row(ctx, group, detail=True)


@router.get("/weeks")
async def weeks(ctx: CtxDep) -> list[str]:
    rows = await ctx.session.scalars(
        select(GroupOrder.week_start).distinct().order_by(GroupOrder.week_start.desc())
    )
    return [str(w) for w in rows]


@router.get("/payments")
async def payments(
    ctx: CtxDep, limit: int = Query(50, ge=1, le=500), mode: str | None = None
) -> list[dict[str, Any]]:
    shops_by_id, suppliers_by_id = await _lookups(ctx)
    query = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    if mode:
        query = query.where(Payment.paypal_mode == mode.upper())
    return [payment_row(p, shops_by_id, suppliers_by_id) for p in await ctx.session.scalars(query)]


@router.get("/ledger")
async def ledger_summary(ctx: CtxDep) -> dict[str, Any]:
    balances = await ledger.balances(ctx.session)
    groups: dict[str, dict[str, int]] = {"platform": {}, "suppliers": {}, "shops": {}}
    for account, value in sorted(balances.items()):
        if account.startswith("platform:"):
            groups["platform"][account] = value
        elif account.startswith("supplier:"):
            groups["suppliers"][account] = value
        else:
            groups["shops"][account] = value
    entries = await ctx.session.scalar(select(func.count()).select_from(LedgerEntry))
    return {
        "balances": groups,
        "invariant_gap_cents": await ledger.platform_invariant_gap(ctx.session),
        "unbalanced_transactions": len(await ledger.unbalanced_transactions(ctx.session)),
        "entries": int(entries or 0),
    }


@router.get("/flash-deals")
async def flash_deal_list(ctx: CtxDep) -> list[dict[str, Any]]:
    rows = await ctx.session.execute(
        select(FlashDeal, Supplier, Item)
        .join(Supplier, Supplier.id == FlashDeal.supplier_id)
        .join(Item, Item.id == FlashDeal.item_id)
        .order_by(FlashDeal.created_at.desc())
        .limit(20)
    )
    return [
        {
            "id": str(d.id),
            "supplier": {"code": s.code, "name": s.name},
            "item": i.name,
            "brand": i.brand,
            "unit": wording(i.product_code).unit,
            "qty": d.qty_available,
            "taken": d.taken_qty,
            "price_cents": d.price_cents,
            "list_price_cents": d.list_price_cents,
            "discount_pct": d.details.get("discount_pct"),
            "status": d.status.value,
            "expires_at": _iso(d.expires_at),
            "purchases": d.details.get("purchases", []),
        }
        for d, s, i in rows.all()
    ]


@router.get("/claims")
async def claim_list(ctx: CtxDep, open_only: bool = False) -> list[dict[str, Any]]:
    query = select(Claim).order_by(Claim.created_at.desc()).limit(50)
    if open_only:
        query = query.where(Claim.decision.in_(OPEN_CLAIMS))
    shops_by_id, _ = await _lookups(ctx)
    rows = []
    for claim in await ctx.session.scalars(query):
        shop = shops_by_id.get(claim.shop_id)
        rows.append(
            {**claim_row(claim), "shop": {"code": shop.code, "name": shop.name} if shop else None}
        )
    return rows
